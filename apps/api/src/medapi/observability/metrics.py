"""Prometheus metrics (D13, D20).

RED (Rate, Errors, Duration) per PIPELINE STAGE, not just per endpoint. A single
`http_request_duration` histogram tells you the system is slow; it cannot tell you whether
the cause is embedding, retrieval, reranking, or the provider. S6 needed exactly that
distinction to discover reranking was 85% of the retrieval path — a per-endpoint metric
would have left that invisible.

Cost is a first-class metric, not an afterthought (D20): `medbot_request_cost_usd` makes
"what does a query cost?" a Grafana panel rather than a spreadsheet exercise, and it is
what the spend breaker in S18 will alert on.

Cardinality discipline: labels are bounded sets (stage, venue, kind, outcome). Never a
user id, session id, or query — unbounded labels are how a metrics backend falls over.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry(auto_describe=True)

# Buckets chosen around the Phase-1 NFRs so the histogram resolves where the SLOs sit
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

request_duration = Histogram(
    "medbot_request_duration_seconds",
    "End-to-end query latency",
    labelnames=("outcome",),  # grounded | no_answer | refused | degraded | error
    buckets=_E2E_BUCKETS,
    registry=REGISTRY,
)

ttft = Histogram(
    "medbot_ttft_seconds",
    "Time to first streamed token — the perceived-latency SLI (NFR p50 0.8s / p95 2.0s)",
    buckets=(0.05, 0.1, 0.25, 0.5, 0.8, 1.2, 2.0, 3.5, 6.0),
    registry=REGISTRY,
)

answers_total = Counter(
    "medbot_answers_total",
    "Answers by kind — the abstention/refusal rate is a QUALITY signal, not just traffic",
    labelnames=("kind",),
    registry=REGISTRY,
)

errors_total = Counter(
    "medbot_errors_total",
    "Errors by type; `degradable` distinguishes handled degradation from real failure. "
    "`status` exists so SLOs can exclude 4xx: a 429 is quota enforcement working, and "
    "counting it against the availability budget would let abusive traffic page the "
    "on-call engineer for a system behaving exactly as designed (P5.5).",
    labelnames=("error_type", "degradable", "status"),
    registry=REGISTRY,
)

cache_events = Counter(
    "medbot_cache_events_total",
    "Cache hit/miss by layer — hit rate is the D10 cost lever, so it must be observable",
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
    "Per-request cost — makes the ≤$0.001/query NFR a dashboard, not a spreadsheet",
    buckets=(0.0001, 0.00025, 0.0005, 0.001, 0.0025, 0.005, 0.01, 0.05),
    registry=REGISTRY,
)

venue_state = Gauge(
    "medbot_venue_circuit_state",
    "Serving-venue circuit breaker (0=closed, 1=half_open, 2=open) — D4b failover health",
    labelnames=("venue",),
    registry=REGISTRY,
)

dependency_state = Gauge(
    "medbot_dependency_circuit_state",
    "Infra dependency circuit breaker (0=closed, 2=open) — Redis, Postgres (P5.5)",
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


def record_answer(kind: str, total_ms: float, cost_usd: float = 0.0) -> None:
    answers_total.labels(kind=kind).inc()
    request_duration.labels(outcome=kind).observe(total_ms / 1000.0)
    if cost_usd:
        request_cost.observe(cost_usd)


def record_circuit(venue: str, state: str) -> None:
    venue_state.labels(venue=venue).set(_CIRCUIT_STATES.get(state, 0))


def record_dependency_circuit(dependency: str, *, is_open: bool) -> None:
    """Redis/Postgres breaker state (P5.5).

    Without this, the P5.3 and P5.4 fixes are invisible: the breakers make an outage cheap
    (~0ms instead of a full timeout per call), which is exactly what removes the latency
    symptom an operator would otherwise notice. The system degrades quietly and correctly —
    cache off, history dropped — and nothing in monitoring says so. A fix that hides its own
    failure signal needs to publish one.
    """
    dependency_state.labels(dependency=dependency).set(2 if is_open else 0)
