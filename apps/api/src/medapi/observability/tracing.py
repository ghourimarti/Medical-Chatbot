"""OpenTelemetry tracing — per-request causal chains (D13).

WHY THIS EXISTS ALONGSIDE PROMETHEUS. They answer different questions and neither
substitutes for the other:

  * Prometheus (S11) aggregates: "is the system healthy? what is p95 rerank latency?"
  * OTel traces: "why was THIS request slow? which stage, in what order, on which pod?"
  * Langfuse (llm_trace.py): "why was THIS answer bad? what prompt, what context, what cost?"

A histogram cannot tell you that one slow request spent 800ms in rerank because the
reranker pod was cold. A trace can.

PII POLICY — the two sinks are deliberately different, and this asymmetry is the point:

  * OTel spans carry **NO raw query text, ever**. Only a fingerprint (stable hash),
    durations, counts, scores, and enum-ish outcomes. OTel data flows to collectors,
    vendors, and dashboards with broad read access; health questions are sensitive
    (D18), so they must not be there.
  * Langfuse MAY carry prompt/completion content, because D18 designates it the ONE
    sanctioned store for that data — access-controlled, 30-day retention.

Putting query text in a span attribute "just for debugging" is how a medical assistant
leaks patient questions into a third-party observability vendor.

SAMPLING. The SDK can only HEAD-sample (decide at span creation). "Keep 100% of errors
and slow requests" is a TAIL decision and is impossible here — it lives in the Collector's
tail_sampling processor (see infra/observability/otel-collector.yaml). Claiming the SDK
does tail sampling would be wrong; this module does the head half only.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from medapi.observability.logging import fingerprint

_TRACER: Any = None
_ENABLED = False


def configure_tracing(
    *,
    enabled: bool,
    endpoint: str,
    service_name: str,
    environment: str,
    sample_ratio: float,
) -> None:
    """Idempotent. A no-op when disabled so local dev needs no collector running."""
    global _TRACER, _ENABLED
    if not enabled or not endpoint:
        _ENABLED = False
        return
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    resource = Resource.create(
        {"service.name": service_name, "deployment.environment": environment}
    )
    provider = TracerProvider(
        resource=resource,
        # ParentBased, not bare ratio: once a trace is sampled it must stay sampled across
        # every service it touches, or you collect disconnected fragments that cannot be
        # reassembled into the causal chain the trace exists to show.
        sampler=ParentBased(root=TraceIdRatioBased(sample_ratio)),
    )
    # Batch, never simple: a per-span network write would put collector latency directly
    # on the request path — instrumentation must not become a dependency of serving.
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")))
    trace.set_tracer_provider(provider)
    _TRACER = trace.get_tracer("medbot.pipeline")
    _ENABLED = True


def instrument_app(app: Any) -> None:
    """Auto-instrument the HTTP layer so pipeline spans nest under a request span."""
    if not _ENABLED:
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz,metrics")


@contextmanager
def stage_span(name: str, **attributes: Any) -> Iterator[Any]:
    """Span for one pipeline stage. Attributes MUST be PII-free (see module docstring).

    Silently degrades to a no-op when tracing is off, so call sites need no conditionals
    and the pipeline never depends on the observability stack being up.
    """
    if not _ENABLED or _TRACER is None:
        yield None
        return
    with _TRACER.start_as_current_span(name) as span:
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)
        yield span


def set_attrs(span: Any, **attributes: Any) -> None:
    """Attach outcome attributes after a stage completes. No-op if span is None."""
    if span is None:
        return
    for key, value in attributes.items():
        if value is not None:
            span.set_attribute(key, value)


def question_fingerprint(question: str) -> str:
    """The ONLY representation of a user question allowed in a span.

    Enough to answer "is this same query looping / hitting cache?" across a trace,
    while being irreversible — you cannot recover the health question from the hash.
    """
    return fingerprint(question)
