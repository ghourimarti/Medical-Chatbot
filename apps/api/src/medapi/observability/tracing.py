"""OpenTelemetry tracing: per-request causal chains.

This sits alongside Prometheus because they answer different questions:

  * Prometheus aggregates: is the system healthy, what is p95 rerank latency?
  * OTel traces: why was this request slow, which stage, in what order, on which pod?
  * Langfuse: why was this answer bad, what prompt, what context, what cost?

A histogram can't tell you one slow request spent 800ms in rerank because the reranker pod
was cold. A trace can.

The PII split between the two sinks is the important part. OTel spans carry no raw query
text at all: only a fingerprint, durations, counts, scores and enum-ish outcomes. OTel data
flows to collectors, vendors and dashboards with broad read access. Langfuse may carry
prompt and completion content, because it's the one sanctioned store for that, access
controlled with 30-day retention.

Putting query text in a span attribute "just for debugging" is how a medical assistant
leaks patient questions to a third-party observability vendor.

On sampling: the SDK can only head-sample, deciding at span creation. Keeping 100% of
errors and slow requests is a tail decision and lives in the Collector's tail_sampling
processor (infra/observability/otel-collector.yaml). This module does the head half only.
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
    # Batch, never simple: a per-span network write puts collector latency directly on the
    # request path, and instrumentation shouldn't become a dependency of serving.
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
    """The only representation of a user question allowed in a span.

    Enough to answer "is this query looping or hitting cache?" across a trace, and
    irreversible: you can't recover the health question from the hash.
    """
    return fingerprint(question)
