"""Circuit breaker + failover chain across serving venues (D4, D4b, D21).

THE STREAMING RULE — the non-obvious part of this design:

    Failover applies ONLY BEFORE THE FIRST TOKEN.

Non-streaming calls can be retried transparently; the caller never learns a leg failed.
Streaming cannot. Once the first token is on the wire the client has already rendered
text, and a second venue would produce a *different continuation* — the answer would
visibly change mid-sentence. So a mid-stream failure is terminal and surfaces as an error
event (S4's in-band error channel), while a failure before the first token falls through
to the next leg invisibly.

Why a circuit breaker at all: without one, every request pays the full timeout of a dead
venue before moving on. At 350 RPS with a 30s timeout that is 10,500 requests piled up on
a leg already known to be down. The breaker converts a slow failure into a fast one.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

from medcore.errors import AllProvidersDownError, ProviderError
from medcore.ports import ModelPort
from medcore.schema import Completion, Message

logger = logging.getLogger("medapi.failover")


@dataclass
class CircuitBreaker:
    """Per-venue breaker: closed -> open (after N failures) -> half-open (after cooldown).

    Half-open lets exactly ONE probe through. If a fully-open breaker released all traffic
    at once, recovery would immediately re-overload the venue that just came back.
    """

    failure_threshold: int = 3
    cooldown_seconds: float = 30.0
    _failures: int = field(default=0, init=False)
    _opened_at: float | None = field(default=None, init=False)

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        if time.monotonic() - self._opened_at >= self.cooldown_seconds:
            return "half_open"
        return "open"

    def allows_request(self) -> bool:
        return self.state != "open"

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold and self._opened_at is None:
            self._opened_at = time.monotonic()
            logger.warning("circuit opened after %s consecutive failures", self._failures)
        elif self.state == "half_open":
            # The probe failed: restart the cooldown rather than hammering the venue.
            self._opened_at = time.monotonic()


@dataclass(slots=True)
class VenueLeg:
    name: str
    model: ModelPort
    breaker: CircuitBreaker = field(default_factory=CircuitBreaker)


class FailoverModel:
    """ModelPort that walks an ordered chain of venues (D4b).

    Legs are independent FAILURE DOMAINS by design — local GPU, third-party cloud, AWS,
    hosted API. That is what makes this real outage protection, unlike two engines sharing
    one GPU pool (the correction recorded in D12).
    """

    def __init__(self, legs: Sequence[VenueLeg]) -> None:
        if not legs:
            raise ValueError("failover chain requires at least one venue")
        self._legs = list(legs)

    @property
    def model_id(self) -> str:
        return self._legs[0].model.model_id

    @property
    def venues(self) -> list[str]:
        return [leg.name for leg in self._legs]

    def status(self) -> dict[str, str]:
        return {leg.name: leg.breaker.state for leg in self._legs}

    async def complete(
        self, *, messages: Sequence[Message], max_tokens: int, temperature: float
    ) -> Completion:
        errors: list[str] = []
        for leg in self._legs:
            if not leg.breaker.allows_request():
                errors.append(f"{leg.name}: circuit open")
                continue
            try:
                result = await leg.model.complete(
                    messages=messages, max_tokens=max_tokens, temperature=temperature
                )
                leg.breaker.record_success()
                return result
            except ProviderError as e:
                leg.breaker.record_failure()
                errors.append(f"{leg.name}: {e.internal_message}")
                logger.warning("venue %s failed, trying next leg", leg.name)
        raise AllProvidersDownError("; ".join(errors))

    async def stream(
        self, *, messages: Sequence[Message], max_tokens: int, temperature: float
    ) -> AsyncIterator[str]:
        errors: list[str] = []
        for leg in self._legs:
            if not leg.breaker.allows_request():
                errors.append(f"{leg.name}: circuit open")
                continue
            started = False
            try:
                async for chunk in leg.model.stream(
                    messages=messages, max_tokens=max_tokens, temperature=temperature
                ):
                    if not started:
                        started = True
                        leg.breaker.record_success()
                    yield chunk
                return
            except ProviderError as e:
                if started:
                    # THE STREAMING RULE: tokens are already rendered on the client.
                    # Switching venues now would change the answer mid-sentence, so this
                    # failure is terminal and becomes an in-band error event (S4).
                    leg.breaker.record_failure()
                    logger.error("venue %s failed MID-STREAM; cannot fail over", leg.name)
                    raise
                leg.breaker.record_failure()
                errors.append(f"{leg.name}: {e.internal_message}")
                logger.warning("venue %s failed before first token; trying next", leg.name)
        raise AllProvidersDownError("; ".join(errors))

    async def health(self) -> bool:
        for leg in self._legs:
            if leg.breaker.allows_request() and await leg.model.health():
                return True
        return False
