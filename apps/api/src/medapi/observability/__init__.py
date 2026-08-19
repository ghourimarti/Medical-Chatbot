"""Observability (D13): structured logs, RED metrics, and traces.

Ordering principle used throughout: instrument at the STAGE boundary, not inside the
stage. The pipeline stages already return timings (S3/S6); this package turns those into
metrics and log fields without the pipeline importing Prometheus or structlog. Business
logic stays free of observability plumbing, and observability stays swappable (D13's
"OTel is vendor-neutral, that's why it's first").
"""

from medapi.observability.logging import configure_logging, fingerprint, get_logger
from medapi.observability.metrics import (
    REGISTRY,
    cache_events,
    errors_total,
    rate_limited_total,
    record_answer,
    record_circuit,
    record_stage,
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
    "tokens_total",
    "ttft",
]
