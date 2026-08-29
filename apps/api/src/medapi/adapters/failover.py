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

import inspect
import logging
import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field

from medapi.observability.metrics import record_circuit, tokens_total
from medcore.errors import AllProvidersDownError, ProviderError
from medcore.ports import ModelPort
from medcore.schema import Completion, Message, Usage

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



def _record_tokens(venue: str, usage: Usage) -> None:
    """Publish token counts per direction and venue. Never raises: a metrics failure must
    not turn a successful generation into an error."""
    try:
        if usage.prompt_tokens:
            tokens_total.labels(direction="prompt", venue=venue).inc(usage.prompt_tokens)
        if usage.completion_tokens:
            tokens_total.labels(direction="completion", venue=venue).inc(
                usage.completion_tokens
            )
    except Exception:  # noqa: BLE001 - observability must never fail a request
        logger.debug("token metric failed", exc_info=True)


def _publish_states(legs: Sequence[VenueLeg]) -> None:
    """Publish EVERY leg's breaker state after any transition.

    All legs, not just the one that moved: `medbot_venue_circuit_state` is a Gauge, and a
    gauge that is only written when a venue is touched leaves the untouched ones reporting
    a stale value forever. The dashboard would then show a leg as closed long after it
    stopped being tried.
    """
    try:
        for leg in legs:
            record_circuit(leg.name, leg.breaker.state)
    except Exception:  # noqa: BLE001
        logger.debug("circuit metric failed", exc_info=True)


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
                # Token accounting belongs HERE, not in postflight: this is the only place
                # that knows BOTH the usage and which venue produced it. Answer carries no
                # venue, so a postflight recorder could only label them "unknown" — and a
                # token count you cannot attribute to a venue cannot answer the question
                # the metric exists for ("what is local serving vs what are we paying for").
                _record_tokens(leg.name, result.usage)
                _publish_states(self._legs)
                return result
            except ProviderError as e:
                leg.breaker.record_failure()
                _publish_states(self._legs)
                errors.append(f"{leg.name}: {e.internal_message}")
                logger.warning("venue %s failed, trying next leg", leg.name)
        _publish_states(self._legs)
        raise AllProvidersDownError("; ".join(errors))

    async def stream(
        self,
        *,
        messages: Sequence[Message],
        max_tokens: int,
        temperature: float,
        on_venue: Callable[[str, str], None] | None = None,
    ) -> AsyncIterator[str]:
        """`on_venue(venue_name, model_id)` fires once, when a leg produces its first token.

        S20.12: without it the streaming path had NO WAY to learn which leg served. The
        pipeline fell back to `self._model.model_id`, and FailoverModel.model_id returns
        `self._legs[0].model.model_id` - the FIRST CONFIGURED leg, whoever actually
        answered. So with SGLang stopped, Groq served and every streamed answer still
        reported Qwen: in the response body, in the stored transcript, and in Langfuse.

        That is worse than a cosmetic mislabel. The whole failover design is verified by
        asking "which model_id came back?", and the browser uses the streaming path - so
        the one path real users take was the one that could not answer that question, and
        cost attribution silently credited a hosted answer to the free local engine.

        A CALLBACK rather than a `last_venue` attribute: attributes are shared mutable
        state and two concurrent streams would overwrite each other's answer. A closure
        belongs to exactly one request.
        """
        errors: list[str] = []
        for leg in self._legs:
            if not leg.breaker.allows_request():
                errors.append(f"{leg.name}: circuit open")
                continue
            started = False

            def _usage(u: Usage, _leg: VenueLeg = leg) -> None:
                # Attributed to the leg that STREAMED it, which is the whole point of the
                # venue label: local tokens are free, hosted tokens are an invoice.
                _record_tokens(_leg.name, u)

            stream_kwargs: dict[str, object] = {}
            if "on_usage" in inspect.signature(leg.model.stream).parameters:
                stream_kwargs["on_usage"] = _usage
            try:
                async for chunk in leg.model.stream(
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    **stream_kwargs,  # type: ignore[arg-type]
                ):
                    if not started:
                        started = True
                        leg.breaker.record_success()
                        _publish_states(self._legs)
                        if on_venue is not None:
                            # First token = this leg committed to the answer. The
                            # STREAMING RULE below makes it final: we can no longer fail
                            # over, so this is the venue for the whole response.
                            on_venue(leg.name, leg.model.model_id)
                    yield chunk
                return
            except ProviderError as e:
                if started:
                    # THE STREAMING RULE: tokens are already rendered on the client.
                    # Switching venues now would change the answer mid-sentence, so this
                    # failure is terminal and becomes an in-band error event (S4).
                    leg.breaker.record_failure()
                    _publish_states(self._legs)
                    logger.error("venue %s failed MID-STREAM; cannot fail over", leg.name)
                    raise
                leg.breaker.record_failure()
                _publish_states(self._legs)
                errors.append(f"{leg.name}: {e.internal_message}")
                logger.warning("venue %s failed before first token; trying next", leg.name)
        raise AllProvidersDownError("; ".join(errors))

    async def health(self) -> bool:
        for leg in self._legs:
            if leg.breaker.allows_request() and await leg.model.health():
                return True
        return False
