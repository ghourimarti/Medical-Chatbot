"""Throttled logging.

Measured: at 1500 RPS the Redis fallback path wrote 2.3 MB of identical tracebacks in
seconds. Log formatting is synchronous and CPU-bound, so the error handler competed with
the request path for the resources needed to recover — the reporting amplified the outage.
"""

from __future__ import annotations

import logging

from medapi.logthrottle import ThrottledLogger


def test_first_call_is_emitted(caplog) -> None:  # type: ignore[no-untyped-def]
    t = ThrottledLogger(interval_seconds=60.0)
    with caplog.at_level(logging.WARNING, logger="medapi.throttled"):
        t.warning("k", "redis exploded")
    assert "redis exploded" in caplog.text


def test_burst_collapses_to_one_record(caplog) -> None:  # type: ignore[no-untyped-def]
    """The property that matters: 10k failing requests must not produce 10k log records."""
    t = ThrottledLogger(interval_seconds=60.0)
    with caplog.at_level(logging.WARNING, logger="medapi.throttled"):
        for _ in range(10_000):
            t.warning("k", "redis exploded")
    assert len(caplog.records) == 1


def test_suppressed_count_is_reported_on_the_next_emission(caplog) -> None:  # type: ignore[no-untyped-def]
    """During an incident the RATE is the useful signal; 9,999 stack traces are not."""
    t = ThrottledLogger(interval_seconds=0.0)  # every call is past the interval
    with caplog.at_level(logging.WARNING, logger="medapi.throttled"):
        t.warning("k", "boom")
    t._interval = 3600.0  # freeze: subsequent calls are suppressed
    for _ in range(500):
        t.warning("k", "boom")
    t._interval = 0.0  # allow the next emission
    with caplog.at_level(logging.WARNING, logger="medapi.throttled"):
        t.warning("k", "boom")
    assert "+500 suppressed" in caplog.text


def test_distinct_keys_do_not_suppress_each_other(caplog) -> None:  # type: ignore[no-untyped-def]
    """A Redis failure must not mask a simultaneous Postgres failure."""
    t = ThrottledLogger(interval_seconds=60.0)
    with caplog.at_level(logging.WARNING, logger="medapi.throttled"):
        t.warning("redis", "redis down")
        t.warning("postgres", "postgres down")
        t.warning("redis", "redis down")
    assert len(caplog.records) == 2
