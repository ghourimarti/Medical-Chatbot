"""Venue error diagnosability (P5.2 finding #4).

The defect: `ProviderError(f"{self.venue}: {e}")` logged `local: ` — an empty message —
because httpx's transport exceptions carry an empty `str()`. During the P5.2 run the logs
could not distinguish "nothing is listening" from "the request timed out" from "the server
hung up mid-response". Every one of those has a different operator response.

These tests pin the property that the TYPE always survives, since that is the part httpx
guarantees is informative.
"""

from __future__ import annotations

import httpx
import pytest
from medapi.adapters.openai_compat import _describe


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectError(""),
        httpx.ReadTimeout(""),
        httpx.RemoteProtocolError(""),
        httpx.ConnectTimeout(""),
        httpx.ReadError(""),
    ],
)
def test_empty_message_exceptions_still_name_their_type(exc: Exception) -> None:
    """This is the exact regression: these are the classes that stringify to ''."""
    out = _describe(exc)
    assert type(exc).__name__ in out
    assert out.strip() not in ("", ":")
    assert "no message" in out


def test_message_is_kept_when_present() -> None:
    out = _describe(httpx.ConnectError("connection refused"))
    assert "ConnectError" in out
    assert "connection refused" in out


def test_status_error_carries_status_and_body() -> None:
    """The provider's own body is the most useful line available — SGLang, for instance,
    reports exact token counts on a 400, which turns a mystery into an arithmetic check."""
    request = httpx.Request("POST", "http://localhost:5010/v1/chat/completions")
    response = httpx.Response(
        400,
        request=request,
        json={
            "message": (
                "The input (14032 tokens) is longer than the "
                "model's context length (8192 tokens)."
            )
        },
    )
    out = _describe(httpx.HTTPStatusError("", request=request, response=response))
    assert "status=400" in out
    assert "14032 tokens" in out


def test_body_is_truncated_and_single_line() -> None:
    """A huge or multi-line body must not turn one log record into a wall of text — that is
    the same amplification failure that motivated the throttled logger."""
    request = httpx.Request("POST", "http://x/v1/chat/completions")
    response = httpx.Response(500, request=request, text="line1\nline2\n" + ("x" * 5000))
    out = _describe(httpx.HTTPStatusError("", request=request, response=response))
    assert "\n" not in out
    assert len(out) < 400
