"""Prometheus metrics.

RED per pipeline stage rather than per endpoint. A single `http_request_duration`
histogram tells you the system is slow but not whether the cause is embedding, retrieval,
reranking or the provider. That distinction is what showed reranking was 85% of the
retrieval path.

Cost is a first-class metric here: `medbot_request_cost_usd` makes "what does a query
cost?" a Grafana panel instead of a spreadsheet, and it's what the spend breaker alerts on.

Labels are bounded sets (stage, venue, kind, outcome). Never a user id, session id or
query; unbounded labels are how a metrics backend falls over.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry(auto_describe=True)

# Buckets sized around the latency targets, so the histogram resolves where the SLOs sit
# (retrieval p95 250ms, TTFT p95 2.0s) instead of Prometheus' generic defaults.
_STAGE_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_E2E_BUCKETS = (0.1, 0.25, 0.5, 0.8, 1.0, 2.0, 3.5, 5.0, 8.0, 12.0, 30.0)

stage_duration = Histogram(
    "medbot_stage_duration_seconds",
    "Pipeline stage latency",
    labelnames=("stage",),  # embed | retrieve | rerank | generate
    buckets=_STAGE_BUCKETS,
    registry=REGISTRY,
)

# These three carry `venue`. A failover chain serves the same endpoint from a local GPU
# and from a hosted API whose latency and price differ by an order of magnitude, so a
# combined histogram averages over whichever venues answered: the panel moves when the
# chain shifts rather than when performance does, and it can't say which venue is slow.
#
# `none` rather than an empty string for answers that generated nothing (refusals,
# degraded, cache hits), since an absent series and a zero are different claims.
request_duration = Histogram(
    "medbot_request_duration_seconds",
    "End-to-end query latency",
    labelnames=("outcome", "venue"),  # grounded|no_answer|refused|degraded|error x venue
    buckets=_E2E_BUCKETS,
    registry=REGISTRY,
)

ttft = Histogram(
    "medbot_ttft_seconds",
    "Time to first streamed token; the perceived-latency SLI",
    labelnames=("venue",),
    buckets=(0.05, 0.1, 0.25, 0.5, 0.8, 1.2, 2.0, 3.5, 6.0),
    registry=REGISTRY,
)

answers_total = Counter(
    "medbot_answers_total",
    "Answers by kind; the abstention and refusal rates are quality signals, not traffic",
    labelnames=("kind",),
    registry=REGISTRY,
)

errors_total = Counter(
    "medbot_errors_total",
    "Errors by type; `degradable` distinguishes handled degradation from real failure. "
    "`status` exists so SLOs can exclude 4xx: a 429 is quota enforcement working, and "
    "counting it against the availability budget lets abusive traffic page on-call for a "
    "system doing its job.",
    labelnames=("error_type", "degradable", "status"),
    registry=REGISTRY,
)

cache_events = Counter(
    "medbot_cache_events_total",
    "Cache hit/miss by layer; hit rate is the main cost lever, so it has to be visible",
    labelnames=("layer", "result"),  # response|embedding x hit|miss
    registry=REGISTRY,
)

tokens_total = Counter(
    "medbot_tokens_total",
    "Tokens consumed by direction and venue",
    labelnames=("direction", "venue"),  # prompt|completion
    registry=REGISTRY,
)

request_cost = Histogram(
    "medbot_request_cost_usd",
    "Per-request cost; makes the per-query cost target a dashboard, not a spreadsheet",
    labelnames=("venue",),
    buckets=(0.0001, 0.00025, 0.0005, 0.001, 0.0025, 0.005, 0.01, 0.05),
    registry=REGISTRY,
)

refusals_total = Counter(
    "medbot_refusals_total",
    "Guardrail refusals by category; the safety signal, not just the count",
    labelnames=("category",),  # emergency|self_harm|dosage|diagnosis|injection|...
    registry=REGISTRY,
)

no_answers_total = Counter(
    "medbot_no_answers_total",
    "Declines by which gate produced them; the two paths cost different money",
    labelnames=("path",),  # retrieval_gate (free) | model_abstained (full prompt)
    registry=REGISTRY,
)

degradations_total = Counter(
    "medbot_degradations_total",
    "Times the pipeline served a degraded answer rather than failing",
    labelnames=("component", "reason"),
    registry=REGISTRY,
)

venue_state = Gauge(
    "medbot_venue_circuit_state",
    "Serving-venue circuit breaker (0=closed, 1=half_open, 2=open); failover health",
    labelnames=("venue",),
    registry=REGISTRY,
)

dependency_state = Gauge(
    "medbot_dependency_circuit_state",
    "Infra dependency circuit breaker (0=closed, 2=open); Redis and Postgres",
    labelnames=("dependency",),
    registry=REGISTRY,
)

rate_limited_total = Counter(
    "medbot_rate_limited_total",
    "Requests rejected by quota, by scope",
    labelnames=("scope",),
    registry=REGISTRY,
)

_CIRCUIT_STATES = {"closed": 0, "half_open": 1, "open": 2}


def record_stage(stage: str, milliseconds: float | None) -> None:
    if milliseconds is not None:
        stage_duration.labels(stage=stage).observe(milliseconds / 1000.0)


def record_answer(
    kind: str,
    total_ms: float,
    cost_usd: float = 0.0,
    ttft_ms: float | None = None,
    refusal_category: str | None = None,
    no_answer_path: str | None = None,
    venue: str | None = None,
) -> None:
    answers_total.labels(kind=kind).inc()
    # Normalised once, so every observation below agrees on the label value.
    at = venue or "none"

    # Which safety rule fired, not just that one did. `answers_total{kind="refused"}`
    # can't tell an emergency from a dosage question, so a guardrail that quietly stopped
    # matching looks identical to one nobody triggered. That's how a broken self-harm rule
    # went unnoticed: every gerund phrasing fell through to retrieval, returned a
    # no_answer, and no counter moved.
    if refusal_category:
        refusals_total.labels(category=refusal_category).inc()

    # The two decline paths cost different money:
    #   retrieval_gate   nothing scored above threshold, the model was never called
    #   model_abstained  retrieval cleared the gate and the model read a full prompt to
    #                    say it had nothing (~1,000 prompt tokens for "I don't know")
    # Collapsed into one counter, a rising bill from adjacent-but-absent questions is
    # invisible.
    if no_answer_path:
        no_answers_total.labels(path=no_answer_path).inc()
    request_duration.labels(outcome=kind, venue=at).observe(total_ms / 1000.0)

    # Observe even when cost is 0. Local venues are free, so an `if cost_usd:` guard makes
    # the cost panel show "No data" instead of $0.
    request_cost.labels(venue=at).observe(cost_usd)

    # TTFT is the perceived-latency SLI. It was computed in the pipeline, carried on
    # Answer.timings and exported from here, but never actually observed, so the metric sat
    # at count 0. Streaming only: a non-streaming call has no first token to time, and
    # substituting total_ms would quietly redefine the SLI.
    if ttft_ms is not None:
        ttft.labels(venue=at).observe(ttft_ms / 1000.0)


def record_circuit(venue: str, state: str) -> None:
    venue_state.labels(venue=venue).set(_CIRCUIT_STATES.get(state, 0))


def record_dependency_circuit(dependency: str, *, is_open: bool) -> None:
    """Redis/Postgres breaker state.

    The breakers make an outage cheap (~0ms instead of a full timeout per call), which also
    removes the latency symptom an operator would have noticed. So the system degrades
    quietly and correctly, cache off and history dropped, with nothing in monitoring saying
    so unless this gauge exists.
    """
    dependency_state.labels(dependency=dependency).set(2 if is_open else 0)
