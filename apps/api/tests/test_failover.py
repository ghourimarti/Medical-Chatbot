"""S13: multi-venue failover, circuit breakers, and the streaming rule (D4, D4b, D21)."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Sequence

import pytest
from medapi.adapters.failover import CircuitBreaker, FailoverModel, VenueLeg
from medapi.venues import KNOWN_VENUES, build_failover_model, parse_chain

from medcore.config import Settings
from medcore.errors import AllProvidersDownError, ProviderError
from medcore.schema import Completion, Message


def _settings(**over: object) -> Settings:
    base: dict[str, object] = {"groq_api_key": "gsk_test"}
    base.update(over)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


class FakeVenue:
    """A venue that can be made to fail before, or partway through, a stream."""

    def __init__(
        self, name: str, *, fail: bool = False, fail_after_chunks: int | None = None
    ) -> None:
        self._name = name
        self._fail = fail
        self._fail_after = fail_after_chunks
        self.calls = 0

    @property
    def model_id(self) -> str:
        return f"{self._name}-model"

    async def complete(
        self, *, messages: Sequence[Message], max_tokens: int, temperature: float
    ) -> Completion:
        self.calls += 1
        if self._fail:
            raise ProviderError(f"{self._name} is down")
        return Completion(text=f"answer from {self._name}", model_id=self.model_id)

    async def stream(
        self, *, messages: Sequence[Message], max_tokens: int, temperature: float
    ) -> AsyncIterator[str]:
        self.calls += 1
        if self._fail:
            raise ProviderError(f"{self._name} is down")
        for i in range(3):
            if self._fail_after is not None and i >= self._fail_after:
                raise ProviderError(f"{self._name} died mid-stream")
            yield f"{self._name}-{i} "

    async def health(self) -> bool:
        return not self._fail


def _chain(*venues: FakeVenue, threshold: int = 3, cooldown: float = 30.0) -> FailoverModel:
    return FailoverModel(
        [
            VenueLeg(
                name=v.model_id.replace("-model", ""),
                model=v,
                breaker=CircuitBreaker(failure_threshold=threshold, cooldown_seconds=cooldown),
            )
            for v in venues
        ]
    )


# --- chain ordering -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_primary_is_used_when_healthy() -> None:
    primary, backup = FakeVenue("local"), FakeVenue("groq")
    result = await _chain(primary, backup).complete(
        messages=[Message(role="user", content="q")], max_tokens=10, temperature=0.0
    )
    assert result.text == "answer from local"
    assert backup.calls == 0, "backup must not be called when the primary succeeds"


@pytest.mark.asyncio
async def test_failover_to_next_venue() -> None:
    dead, backup = FakeVenue("local", fail=True), FakeVenue("groq")
    result = await _chain(dead, backup).complete(
        messages=[Message(role="user", content="q")], max_tokens=10, temperature=0.0
    )
    assert result.text == "answer from groq"


@pytest.mark.asyncio
async def test_all_venues_down_raises_degradable_error() -> None:
    """D21: with every leg dead the caller gets a typed, DEGRADABLE error so the ladder
    can fall through to cache-only mode rather than emitting a raw 500."""
    chain = _chain(FakeVenue("local", fail=True), FakeVenue("groq", fail=True))
    with pytest.raises(AllProvidersDownError) as exc:
        await chain.complete(
            messages=[Message(role="user", content="q")], max_tokens=10, temperature=0.0
        )
    assert exc.value.degradable
    assert "local" in str(exc.value) and "groq" in str(exc.value)


# --- circuit breaker ----------------------------------------------------------------


def test_breaker_opens_after_threshold() -> None:
    breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
    assert breaker.state == "closed"
    for _ in range(2):
        breaker.record_failure()
    assert breaker.allows_request(), "must not open before the threshold"
    breaker.record_failure()
    assert breaker.state == "open" and not breaker.allows_request()


def test_breaker_half_opens_after_cooldown() -> None:
    """Half-open lets exactly ONE probe through: releasing all traffic at once would
    re-overload the venue that just recovered."""
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.05)
    breaker.record_failure()
    assert breaker.state == "open"
    time.sleep(0.06)
    assert breaker.state == "half_open" and breaker.allows_request()


def test_success_resets_the_breaker() -> None:
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=60)
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    assert breaker.state == "closed", "a success must clear the consecutive-failure count"


@pytest.mark.asyncio
async def test_open_breaker_is_skipped_without_calling_the_venue() -> None:
    """The point of the breaker: stop paying a dead venue's timeout on every request.
    At 350 RPS with a 30s timeout that is thousands of requests queued on a known-dead leg."""
    dead, backup = FakeVenue("local", fail=True), FakeVenue("groq")
    chain = _chain(dead, backup, threshold=1)
    msg = [Message(role="user", content="q")]
    await chain.complete(messages=msg, max_tokens=10, temperature=0.0)  # opens the breaker
    calls_after_open = dead.calls
    await chain.complete(messages=msg, max_tokens=10, temperature=0.0)
    assert dead.calls == calls_after_open, "an open circuit must not call the venue at all"


# --- THE STREAMING RULE -------------------------------------------------------------


@pytest.mark.asyncio
async def test_streaming_fails_over_before_the_first_token() -> None:
    dead, backup = FakeVenue("local", fail=True), FakeVenue("groq")
    chunks = [
        c
        async for c in _chain(dead, backup).stream(
            messages=[Message(role="user", content="q")], max_tokens=10, temperature=0.0
        )
    ]
    assert "".join(chunks).startswith("groq-0")


@pytest.mark.asyncio
async def test_streaming_does_NOT_fail_over_after_the_first_token() -> None:
    """The subtle rule. Once tokens are rendered on the client, switching venues would
    produce a DIFFERENT continuation — the answer would visibly change mid-sentence. So a
    mid-stream failure is terminal and surfaces as an in-band error event (S4)."""
    dying, backup = FakeVenue("local", fail_after_chunks=2), FakeVenue("groq")
    chain = _chain(dying, backup)
    received: list[str] = []
    with pytest.raises(ProviderError):
        async for chunk in chain.stream(
            messages=[Message(role="user", content="q")], max_tokens=10, temperature=0.0
        ):
            received.append(chunk)
    assert received, "tokens emitted before the failure are kept"
    assert backup.calls == 0, "must NOT silently switch venues mid-stream"


# --- registry -----------------------------------------------------------------------


def test_parse_chain_preserves_order_and_dedupes() -> None:
    assert parse_chain("local, groq ,local") == ["local", "groq"]


def test_unknown_venue_is_rejected_at_config_time() -> None:
    with pytest.raises(ValueError, match="unknown venues"):
        parse_chain("local,teapot")


def test_unconfigured_venues_are_skipped_not_fatal() -> None:
    """RunPod/AWS can be named in the chain before their accounts exist."""
    model = build_failover_model(_settings(serving_chain="local,runpod,aws,groq"))
    assert model.venues == ["local", "groq"]  # runpod/aws have no URL yet


def test_empty_chain_fails_at_startup() -> None:
    """A service that boots with no way to answer would pass liveness and fail every
    request. Fail at startup instead (D17)."""
    with pytest.raises(ValueError, match="no usable venues"):
        build_failover_model(
            _settings(serving_chain="runpod,aws", vllm_runpod_url="", vllm_aws_url="")
        )


def test_all_known_venues_are_configurable() -> None:
    model = build_failover_model(
        _settings(
            serving_chain=",".join(KNOWN_VENUES),
            vllm_runpod_url="http://runpod.test/v1",
            vllm_aws_url="http://aws.test/v1",
        )
    )
    assert model.venues == list(KNOWN_VENUES)
    assert set(model.status()) == set(KNOWN_VENUES)
