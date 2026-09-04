"""A streamed answer must name the venue that actually served it.

Reported from the UI: with SGLang stopped, Groq produced the answer while Langfuse, the
stored transcript and the response body all still said Qwen.

Cause: the streaming path took `model_id` from `self._model.model_id`, and
`FailoverModel.model_id` returns `self._legs[0].model.model_id` — the FIRST CONFIGURED
leg, whoever answered. The non-streaming path was always right because it uses
`completion.model_id` from the leg that responded.

Why that is worse than a mislabel: the whole failover design is verified by asking "which
model_id came back?", and the BROWSER USES THE STREAMING PATH. So the one path real users
take was the one that could not answer the question the design exists to answer — and cost
attribution credited hosted answers to the free local engine.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from medapi.adapters.failover import FailoverModel, VenueLeg

from medcore.errors import ProviderError
from medcore.schema import Completion, Message


class _Venue:
    def __init__(self, model_id: str, *, dead: bool = False) -> None:
        self.model_id = model_id
        self._dead = dead

    async def complete(self, **_: Any) -> Completion:
        if self._dead:
            raise ProviderError(f"{self.model_id} is down")
        return Completion(text="ok", model_id=self.model_id)

    async def stream(self, **_: Any) -> AsyncIterator[str]:
        if self._dead:
            raise ProviderError(f"{self.model_id} is down")
        for chunk in ("Emphysema ", "is ", "a ", "lung ", "disease."):
            yield chunk

    async def health(self) -> bool:
        return not self._dead


def _chain(primary_dead: bool) -> FailoverModel:
    return FailoverModel([
        VenueLeg(name="local-sglang", model=_Venue("Qwen/Qwen2.5-7B-Instruct-AWQ",
                                                   dead=primary_dead)),
        VenueLeg(name="groq", model=_Venue("openai/gpt-oss-20b")),
    ])


@pytest.mark.asyncio
async def test_stream_reports_the_FALLBACK_venue_when_the_primary_is_down() -> None:
    """THE regression: stop SGLang, and the stream must say Groq — not Qwen."""
    seen: list[tuple[str, str]] = []
    model = _chain(primary_dead=True)

    chunks = [c async for c in model.stream(
        messages=[Message(role="user", content="q")], max_tokens=64, temperature=0.0,
        on_venue=lambda venue, mid: seen.append((venue, mid)),
    )]

    assert chunks, "no tokens produced"
    assert seen == [("groq", "openai/gpt-oss-20b")], (
        f"streaming reported the wrong venue: {seen}"
    )
    # And the misleading property that caused this is still the FIRST leg — which is why
    # the pipeline must not use it.
    assert model.model_id == "Qwen/Qwen2.5-7B-Instruct-AWQ"


@pytest.mark.asyncio
async def test_stream_reports_the_primary_when_it_is_healthy() -> None:
    seen: list[tuple[str, str]] = []
    model = _chain(primary_dead=False)
    async for _ in model.stream(
        messages=[Message(role="user", content="q")], max_tokens=64, temperature=0.0,
        on_venue=lambda venue, mid: seen.append((venue, mid)),
    ):
        pass
    assert seen == [("local-sglang", "Qwen/Qwen2.5-7B-Instruct-AWQ")]


@pytest.mark.asyncio
async def test_on_venue_fires_exactly_once() -> None:
    """It marks the COMMITMENT to a leg, not every token. The streaming rule makes the first
    token final — failover after that would change the answer mid-sentence."""
    seen: list[tuple[str, str]] = []
    model = _chain(primary_dead=False)
    async for _ in model.stream(
        messages=[Message(role="user", content="q")], max_tokens=64, temperature=0.0,
        on_venue=lambda venue, mid: seen.append((venue, mid)),
    ):
        pass
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_stream_works_without_the_callback() -> None:
    """on_venue is optional: a caller that does not care must not break."""
    model = _chain(primary_dead=True)
    chunks = [c async for c in model.stream(
        messages=[Message(role="user", content="q")], max_tokens=64, temperature=0.0,
    )]
    assert "".join(chunks).startswith("Emphysema")


@pytest.mark.asyncio
async def test_streamed_tokens_are_metered_against_the_serving_venue() -> None:
    """Measured before the fix:

        streamed query    medbot_tokens_total 2784 -> 2784   delta 0
        non-stream query  medbot_tokens_total 2784 -> 3972   delta 1188

    The browser streams, so token accounting and cost/request were blind to the only path
    real users take, and every 'answered' log line read tokens=0.

    An OpenAI-compatible server reports usage on a stream ONLY if asked, via
    stream_options.include_usage. Nobody asked.
    """
    from medapi.observability import REGISTRY

    from medcore.schema import Usage

    class _UsageVenue:
        model_id = "openai/gpt-oss-20b"

        async def complete(self, **_: Any) -> Completion:  # pragma: no cover
            raise NotImplementedError

        async def stream(
            self, *, on_usage: Any = None, **_: Any
        ) -> AsyncIterator[str]:
            yield "Anaemia "
            yield "is low haemoglobin."
            if on_usage is not None:
                on_usage(Usage(prompt_tokens=900, completion_tokens=40))

        async def health(self) -> bool:
            return True

    def value(**labels: str) -> float:
        return REGISTRY.get_sample_value("medbot_tokens_total", labels) or 0.0

    before = value(direction="prompt", venue="groq")
    model = FailoverModel([VenueLeg(name="groq", model=_UsageVenue())])
    async for _ in model.stream(
        messages=[Message(role="user", content="q")], max_tokens=64, temperature=0.0
    ):
        pass

    assert value(direction="prompt", venue="groq") == before + 900
    assert value(direction="completion", venue="groq") >= 40


@pytest.mark.asyncio
async def test_a_server_that_ignores_stream_options_still_streams() -> None:
    """Not every OpenAI-compatible server implements include_usage. One that ignores it
    must simply never report usage — degrading to the old behaviour, not breaking."""
    model = _chain(primary_dead=False)
    chunks = [c async for c in model.stream(
        messages=[Message(role="user", content="q")], max_tokens=64, temperature=0.0,
    )]
    assert "".join(chunks).startswith("Emphysema")
