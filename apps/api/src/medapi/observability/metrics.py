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

refusals_total = Counter(
    "medbot_refusals_total",
    "Guardrail refusals BY CATEGORY - the safety signal, not just the count",
    labelnames=("category",),  # emergency|self_harm|dosage|diagnosis|injection|...
    registry=REGISTRY,
)

no_answers_total = Counter(
    "medbot_no_answers_total",
    "Declines by WHICH gate produced them - the two paths cost different money",
    labelnames=("path",),  # retrieval_gate (free) | model_abstained (full prompt)
    registry=REGISTRY,
)

degradations_total = Counter(
    "medbot_degradations_total",
    "Times the pipeline silently served a WORSE answer rather than failing",
    labelnames=("component", "reason"),
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


def record_answer(
    kind: str,
    total_ms: float,
    cost_usd: float = 0.0,
    ttft_ms: float | None = None,
    refusal_category: str | None = None,
    no_answer_path: str | None = None,
) -> None:
    answers_total.labels(kind=kind).inc()

    # WHICH safety rule fired, not merely that one did. `answers_total{kind="refused"}`
    # cannot tell an emergency from a dosage question, so a guardrail that silently
    # stopped matching would look identical to one nobody triggered - which is exactly
    # how the self-harm rule shipped broken (I7.1): every gerund phrasing fell through to
    # retrieval and returned a no_answer, and no counter moved to say so.
    if refusal_category:
        refusals_total.labels(category=refusal_category).inc()

    # The two decline paths cost different money and mean different things:
    #   retrieval_gate   nothing scored above threshold; the model was never called
    #   model_abstained  retrieval cleared the gate, the model read a full prompt and
    #                    said it had nothing - ~1,000 prompt tokens to say "I don't know"
    # Collapsed into one counter, a rising bill from adjacent-but-absent questions is
    # invisible.
    if no_answer_path:
        no_answers_total.labels(path=no_answer_path).inc()
    request_duration.labels(outcome=kind).observe(total_ms / 1000.0)

    # ALWAYS observed, including 0.0. The old `if cost_usd:` guard skipped every
    # self-hosted request, because a local venue costs $0 by construction — so the one
    # configuration this project actually runs recorded NO cost samples at all, and the
    # "cost/request" panel read "No data" rather than the true and useful "$0.000000".
    # Absent and zero are different answers; a spend dashboard must not confuse them.
    request_cost.observe(cost_usd)

    # TTFT is the perceived-latency SLI and the headline NFR (p50 0.8s / p95 2.0s). It was
    # computed in the pipeline, carried on Answer.timings, exported from this module — and
    # never observed, so the metric existed with count 0 and the NFR was unmeasurable.
    # Streaming only: on a non-streaming call there is no "first token" to time, and
    # feeding total_ms in as a substitute would quietly redefine the SLI.
    if ttft_ms is not None:
        ttft.observe(ttft_ms / 1000.0)


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
