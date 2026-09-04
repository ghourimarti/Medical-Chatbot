"""Venue error diagnosability.

The defect: `ProviderError(f"{self.venue}: {e}")` logged `local: ` — an empty message —
because httpx's transport exceptions carry an empty `str()`. During the run the logs
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


# serving_engine actually selects an engine


def _settings(**overrides: object):
    from medcore.config import Settings

    base = {
        "groq_api_key": "gsk_test_key_not_real",
        "serving_chain": "local,groq",
    }
    return Settings(**{**base, **overrides})  # type: ignore[arg-type]


def test_serving_engine_selects_the_gpu_endpoint() -> None:
    """The whole point of. `serving_engine` was declared in Settings and read
    NOWHERE — `vllm_local_url` was hardcoded, so SERVING_ENGINE=sglang served vLLM."""
    from medapi.venues import ChainLeg, _venue_config

    bare = ChainLeg("local", None)
    vllm = _settings(serving_engine="vllm")
    sglang = _settings(serving_engine="sglang")
    assert _venue_config(vllm, bare)[0] == vllm.vllm_local_url
    assert _venue_config(sglang, bare)[0] == sglang.sglang_local_url
    assert _venue_config(vllm, bare)[0] != _venue_config(sglang, bare)[0]


def test_an_explicit_engine_beats_the_default() -> None:
    """`local-sglang` must mean SGLang even when SERVING_ENGINE says vllm — otherwise the
    per-leg engine is decoration."""
    from medapi.venues import ChainLeg, _venue_config

    cfg = _settings(serving_engine="vllm")
    assert _venue_config(cfg, ChainLeg("local", "sglang"))[0] == cfg.sglang_local_url
    assert _venue_config(cfg, ChainLeg("local", "vllm"))[0] == cfg.vllm_local_url


def test_groq_ignores_the_engine_setting() -> None:
    """Groq is a hosted API — there is no engine of ours to choose."""
    from medapi.venues import ChainLeg, _venue_config

    for engine in ("vllm", "sglang"):
        url, _, key = _venue_config(_settings(serving_engine=engine), ChainLeg("groq", None))
        assert url.startswith("https://api.groq.com")
        assert key


def test_sglang_is_not_a_venue_name() -> None:
    """SGLang is an ENGINE, never a venue of its own.

    It is now reachable as a chain leg (`local-sglang`) because v2.1 asked for
    engine-level failover, but the failure-domain caveat is unchanged and is why the
    spelling matters: `local-vllm -> local-sglang` share a GPU and a box, so that pair
    covers an engine fault and nothing else. A bare `sglang` would imply a venue — an
    independent place to fail — which does not exist.
    """
    import pytest
    from medapi.venues import KNOWN_VENUES, parse_chain

    assert "sglang" not in KNOWN_VENUES
    with pytest.raises(ValueError, match="unknown venue"):
        parse_chain("local,sglang")

    # ...but as an ENGINE of a real venue it is legitimate.
    assert [leg.label for leg in parse_chain("local-sglang")] == ["local-sglang"]


def test_missing_engine_url_is_a_loud_skip_not_a_silent_downgrade(caplog) -> None:  # type: ignore[no-untyped-def]
    """Asking for self-hosted SGLang and silently receiving Groq is the failure this
    warning exists to prevent."""
    import logging

    from medapi.venues import build_failover_model

    settings = _settings(serving_engine="sglang", sglang_local_url="")
    with caplog.at_level(logging.WARNING, logger="medapi.venues"):
        model = build_failover_model(settings)
    assert model.venues == ["groq"]
    # The warning must name the ENGINE. "not configured" alone would leave the operator
    # believing they were served self-hosted SGLang when they were served a hosted API.
    warned = " ".join(r.getMessage() for r in caplog.records)
    assert "sglang" in warned and "SKIPPED" in warned
