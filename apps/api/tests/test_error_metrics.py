"""Error metrics feed the availability SLO.

Two defects this pins down:

  1. `medbot_errors_total` was DECLARED and exported but never incremented anywhere, while
     the error-budget burn alert summed it. An alert wired to a metric nobody emits is
     worse than no alert — it occupies the slot a working one would fill and reports
     healthy forever.

  2. Once wired, every domain error counted, including 429s. Quota enforcement is the
     system working; letting it burn the availability budget means abusive traffic can
     page the on-call engineer for correct behaviour.
"""

from __future__ import annotations

import pytest
from medapi.observability.metrics import errors_total

from medcore.errors import (
    AllProvidersDownError,
    QuotaExceededError,
    RetrievalError,
)


def _value(error_type: str, degradable: str, status: str) -> float:
    return (
        errors_total.labels(
            error_type=error_type, degradable=degradable, status=status
        )._value.get()
    )


class TestErrorClassification:
    """The SLO expression is `degradable="false" AND status=~"5.."`. These assert that the
    labels actually produced put each error on the correct side of that filter."""

    def test_quota_is_4xx_so_it_cannot_burn_the_availability_budget(self) -> None:
        assert QuotaExceededError.status == 429
        assert not str(QuotaExceededError.status).startswith("5")

    def test_retrieval_failure_is_5xx_and_does_burn_budget(self) -> None:
        assert RetrievalError.status == 503
        assert str(RetrievalError.status).startswith("5")

    def test_all_providers_down_is_5xx(self) -> None:
        assert AllProvidersDownError.status == 503

    def test_slugs_are_stable_public_identifiers(self) -> None:
        """Alerts group by slug, so renaming a class must not silently break a rule."""
        assert RetrievalError.slug == "retrieval-unavailable"
        assert AllProvidersDownError.slug == "service-degraded"
        assert QuotaExceededError.slug == "quota-exceeded"


@pytest.mark.asyncio
async def test_handler_increments_with_all_three_labels() -> None:
    from fastapi import Request
    from medapi.errors import medbot_error_handler

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/query",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 1234),
    }
    before = _value("retrieval-unavailable", "true", "503")
    resp = await medbot_error_handler(Request(scope), RetrievalError("index empty"))
    assert resp.status_code == 503
    after = _value("retrieval-unavailable", "true", "503")
    assert after == before + 1, "the SLO's input metric must actually be emitted"


@pytest.mark.asyncio
async def test_unhandled_errors_are_counted_as_bugs() -> None:
    from fastapi import Request
    from medapi.errors import unhandled_error_handler

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/query",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 1234),
    }
    before = _value("unhandled", "false", "500")
    resp = await unhandled_error_handler(Request(scope), RuntimeError("boom"))
    assert resp.status_code == 500
    assert _value("unhandled", "false", "500") == before + 1
