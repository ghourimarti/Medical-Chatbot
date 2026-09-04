"""PII redaction and metrics.

The redaction tests are the important ones. forbids raw query text in application
logs, and "we agreed not to log questions" is a convention — one `logger.info(f"q: {q}")`
away from a data-protection incident. These tests assert the PROCESSOR makes it
structurally impossible, so the guarantee survives a careless caller.
"""

from __future__ import annotations

import pytest
from medapi.observability.logging import (
    SENSITIVE_KEYS,
    fingerprint,
    redact_processor,
)
from medapi.observability.metrics import (
    REGISTRY,
    cache_events,
    record_answer,
    record_circuit,
    record_stage,
)
from prometheus_client import generate_latest

SENSITIVE_QUESTION = "I have chest pain and was diagnosed with cirrhosis last year"


def _process(**fields: object) -> dict[str, object]:
    return redact_processor(None, "info", dict(fields))


# PII redaction


@pytest.mark.parametrize("key", sorted(SENSITIVE_KEYS))
def test_every_sensitive_key_is_redacted(key: str) -> None:
    """Not just 'question' — any field that could carry health content."""
    out = _process(**{key: SENSITIVE_QUESTION})
    assert SENSITIVE_QUESTION not in str(out[key])
    assert "cirrhosis" not in str(out[key])
    assert str(out[key]).startswith("<redacted:")


def test_redaction_keeps_a_stable_fingerprint_for_correlation() -> None:
    """Debuggability is preserved: the same question yields the same hash, so 'is one
    query looping?' is answerable without ever storing the query."""
    a = _process(question=SENSITIVE_QUESTION)["question"]
    b = _process(question=SENSITIVE_QUESTION)["question"]
    c = _process(question="a completely different question")["question"]
    assert a == b and a != c


def test_length_is_retained_for_debugging() -> None:
    out = str(_process(question=SENSITIVE_QUESTION)["question"])
    assert f"{len(SENSITIVE_QUESTION)}chars" in out


def test_emails_and_ips_scrubbed_from_non_sensitive_fields() -> None:
    """Belt and braces: sensitive values sometimes arrive under innocuous keys."""
    out = _process(detail="contact patient@example.com from 203.0.113.9")
    assert "patient@example.com" not in str(out["detail"])
    assert "203.0.113.9" not in str(out["detail"])
    assert "<email>" in str(out["detail"]) and "<ip>" in str(out["detail"])


def test_api_keys_are_scrubbed() -> None:
    """A leaked provider key in a log is a credential-rotation incident."""
    out = _process(error="auth failed for gsk_abcdef1234567890abcdef")
    assert "gsk_abcdef1234567890abcdef" not in str(out["error"])
    assert "<groq-key>" in str(out["error"])


def test_safe_operational_fields_pass_through_untouched() -> None:
    """Redaction must not destroy the data that makes logs useful."""
    out = _process(kind="grounded", total_ms=1113, citations=4, model="llama-3.1-8b")
    assert out == {
        "kind": "grounded", "total_ms": 1113, "citations": 4, "model": "llama-3.1-8b"
    }


def test_fingerprint_is_short_and_stable() -> None:
    f = fingerprint(SENSITIVE_QUESTION)
    assert len(f) == 12
    assert f == fingerprint(SENSITIVE_QUESTION)
    assert SENSITIVE_QUESTION not in f


# metrics


def test_stage_metrics_are_recorded_per_stage() -> None:
    """Per-STAGE, not just per-endpoint: needed exactly this granularity to discover
    reranking was 85% of the retrieval path."""
    record_stage("embed", 104.0)
    record_stage("retrieve", 9.0)
    record_stage("rerank", 800.0)
    dump = generate_latest(REGISTRY).decode()
    assert 'medbot_stage_duration_seconds_count{stage="rerank"}' in dump
    assert 'stage="embed"' in dump


def test_none_timing_is_skipped_not_recorded_as_zero() -> None:
    """A skipped stage (e.g. reranker down) must not pollute the histogram with 0s —
    that would make a degraded request look like a fast one."""
    before = generate_latest(REGISTRY).decode()
    record_stage("condense", None)
    after = generate_latest(REGISTRY).decode()
    assert 'stage="condense"' not in after or before == after


def test_answer_and_cost_metrics() -> None:
    record_answer("grounded", 1113.0, cost_usd=0.0004)
    record_answer("no_answer", 300.0)
    dump = generate_latest(REGISTRY).decode()
    assert 'medbot_answers_total{kind="grounded"}' in dump
    assert 'medbot_answers_total{kind="no_answer"}' in dump
    assert "medbot_request_cost_usd" in dump


def test_cache_hit_rate_is_observable() -> None:
    """Hit rate is the cost lever — if it is not measured it cannot be tuned."""
    cache_events.labels(layer="response", result="hit").inc()
    cache_events.labels(layer="response", result="miss").inc()
    dump = generate_latest(REGISTRY).decode()
    assert 'layer="response",result="hit"' in dump


def test_circuit_state_is_numeric_for_alerting() -> None:
    """Gauges must be numeric so Prometheus can alert on them (D4b venue health)."""
    record_circuit("local", "open")
    record_circuit("groq", "closed")
    dump = generate_latest(REGISTRY).decode()
    assert 'medbot_venue_circuit_state{venue="local"} 2.0' in dump
    assert 'medbot_venue_circuit_state{venue="groq"} 0.0' in dump
