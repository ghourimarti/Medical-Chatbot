"""Structured logs, RED metrics and traces.

Instrument at the stage boundary, not inside the stage. The pipeline stages already return
timings; this package turns those into metrics and log fields without the pipeline ever
importing Prometheus or structlog. Business logic stays free of plumbing, and the backend
stays swappable.
"""

from medapi.observability.logging import configure_logging, fingerprint, get_logger
from medapi.observability.metrics import (
    REGISTRY,
    cache_events,
    degradations_total,
    errors_total,
    no_answers_total,
    rate_limited_total,
    record_answer,
    record_circuit,
    record_stage,
    refusals_total,
    tokens_total,
    ttft,
)

__all__ = [
    "REGISTRY",
    "cache_events",
    "configure_logging",
    "errors_total",
    "fingerprint",
    "get_logger",
    "rate_limited_total",
    "record_answer",
    "record_circuit",
    "record_stage",
    "degradations_total",
    "no_answers_total",
    "refusals_total",
    "tokens_total",
    "ttft",
]
