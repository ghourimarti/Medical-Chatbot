"""Circuit breaker and failover chain across serving venues.

The important rule here: failover only applies before the first token.

Non-streaming calls retry transparently and the caller never learns a leg failed.
Streaming can't do that. Once the first token is on the wire the client has rendered text,
and a second venue produces a different continuation, so the answer would visibly change
mid-sentence. A mid-stream failure is therefore terminal and surfaces as an in-band error
event, while a failure before the first token falls through to the next leg invisibly.

The breaker is there because otherwise every request pays the full timeout of a dead venue
before moving on. At 350 RPS with a 30s timeout that's 10,500 requests piled onto a leg
already known to be down. It turns a slow failure into a fast one.
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
    """Publish every leg's breaker state after any transition.

    All of them, not just the one that moved. `medbot_venue_circuit_state` is a gauge, and
    writing it only for the venue that was touched leaves the others reporting a stale
    value forever, so the dashboard shows a leg as closed long after it stopped being tried.
    """
    try:
        for leg in legs:
            record_circuit(leg.name, leg.breaker.state)
    except Exception:  # noqa: BLE001
        logger.debug("circuit metric failed", exc_info=True)


class FailoverModel:
    """ModelPort that walks an ordered chain of venues.

    The legs are independent failure domains: local GPU, third-party cloud, AWS, hosted
    API. That independence is what makes this real outage protection, as opposed to two
    engines sharing a single GPU pool.
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
                # Token accounting goes here rather than in postflight, because this is
                # the only place that knows both the usage and which venue produced it. A
                # postflight recorder could only label them "unknown", and unattributed
                # tokens can't answer what the metric is for: local serving vs paid.
                _record_tokens(leg.name, result.usage)
                _publish_states(self._legs)
                # Stamp the leg here. The sub-model knows its own venue, but only this
                # loop knows which chain leg was taken, and the leg is the identity the
                # chain is configured in.
                return result.model_copy(update={"venue": leg.name})
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
        on_usage: Callable[[Usage], None] | None = None,
    ) -> AsyncIterator[str]:
        """`on_venue(venue_name, model_id)` fires once, when a leg produces its first token.

        Without it the streaming path has no way to learn which leg served. The pipeline
        falls back to `self._model.model_id`, and FailoverModel.model_id returns the first
        configured leg regardless of who answered. With SGLang stopped, Groq served and
        every streamed answer still reported Qwen: response body, stored transcript and
        Langfuse alike.

        That matters more than a cosmetic mislabel. Failover is verified by asking which
        model_id came back, and the browser uses the streaming path, so the one path real
        users take was the one that couldn't answer the question, with cost attribution
        crediting a hosted answer to the free local engine.

        A callback rather than a `last_venue` attribute, because an attribute is shared
        mutable state and two concurrent streams would overwrite each other. A closure
        belongs to one request.
        """
        errors: list[str] = []
        for leg in self._legs:
            if not leg.breaker.allows_request():
                errors.append(f"{leg.name}: circuit open")
                continue
            started = False

            def _usage(u: Usage, _leg: VenueLeg = leg) -> None:
                # Attributed to the leg that streamed it, which is the point of the venue
                # label: local tokens are free, hosted tokens are an invoice.
                _record_tokens(_leg.name, u)
                # ...and hand it to the caller too. This used to stop at Prometheus, so a
                # streamed answer had tokens in the metric and zeros everywhere else:
                # DoneEvent.usage defaulted empty, so the stored turn and the Langfuse
                # trace both recorded a free answer. Per-answer cost attribution was blank
                # for exactly the requests real users make.
                if on_usage is not None:
                    on_usage(u)

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
                            # First token means this leg has committed to the answer. We
                            # can't fail over past this point, so it's the venue for the
                            # whole response.
                            on_venue(leg.name, leg.model.model_id)
                    yield chunk
                return
            except ProviderError as e:
                if started:
                    # Tokens are already rendered on the client. Switching venues now
                    # would change the answer mid-sentence, so this failure is terminal
                    # and becomes an in-band error event.
                    leg.breaker.record_failure()
                    _publish_states(self._legs)
                    logger.error("venue %s failed mid-stream; cannot fail over", leg.name)
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
