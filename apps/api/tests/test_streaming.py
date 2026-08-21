"""S4: SSE streaming, cancellation, and RFC 7807 error envelopes."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence

import pytest
from medapi.pipeline.rag import RagPipeline

from medcore.config import Settings
from medcore.errors import ProviderError, RetrievalError
from medcore.schema import (
    AnswerKind,
    Completion,
    DoneEvent,
    Message,
    RetrievedChunk,
    SourcesEvent,
    TokenEvent,
)


def _settings() -> Settings:
    return Settings(_env_file=None, groq_api_key="gsk_test")  # type: ignore[call-arg]


class StubEmbedder:
    model_id, dimension = "stub", 1024

    async def embed_query(self, text: str) -> list[float]:
        return [0.1] * self.dimension

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.1] * self.dimension for _ in texts]


class StubStore:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self._chunks = chunks

    async def search(
        self, *, query_vector: Sequence[float], query_text: str, top_k: int,
        filters: Mapping[str, object] | None = None,
    ) -> list[RetrievedChunk]:
        return self._chunks[:top_k]

    async def upsert(self, chunks: Sequence[RetrievedChunk], *, collection: str) -> int:
        return 0

    async def health(self) -> bool:
        return True


class StreamingStubModel:
    """Records whether its stream was closed early — that is how we prove cancellation
    propagates to the provider (and therefore that token spend stops)."""

    model_id = "stub-llm"

    def __init__(self, deltas: list[str], *, hang: bool = False) -> None:
        self._deltas = deltas
        self._hang = hang
        self.cancelled = False
        self.emitted = 0

    async def complete(
        self, *, messages: Sequence[Message], max_tokens: int, temperature: float
    ) -> Completion:
        return Completion(text="".join(self._deltas), model_id=self.model_id)

    async def stream(
        self, *, messages: Sequence[Message], max_tokens: int, temperature: float
    ) -> AsyncIterator[str]:
        try:
            for d in self._deltas:
                self.emitted += 1
                yield d
            if self._hang:
                await asyncio.sleep(30)  # simulate a long generation
        except GeneratorExit:
            self.cancelled = True
            raise
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    async def health(self) -> bool:
        return True


def _chunk(score: float) -> RetrievedChunk:
    return RetrievedChunk(
        id="c1", text="Cirrhosis is a chronic degenerative liver disease.",
        source="Gale", page=42, dense_score=score,
    )


def _pipeline(model: StreamingStubModel, score: float = 0.9) -> RagPipeline:
    return RagPipeline(
        settings=_settings(), embedder=StubEmbedder(),
        store=StubStore([_chunk(score)]), model=model,
    )


@pytest.mark.asyncio
async def test_event_order_sources_then_tokens_then_done() -> None:
    """Citations must arrive BEFORE tokens so a client can paint sources while the
    answer is still being written."""
    pipe = _pipeline(StreamingStubModel(["Cirrhosis ", "is ", "scarring [1]."]))
    events = [e async for e in pipe.stream_answer("What is cirrhosis?")]

    assert isinstance(events[0], SourcesEvent)
    assert events[0].citations, "sources event must carry citations"
    assert all(isinstance(e, TokenEvent) for e in events[1:-1])
    assert isinstance(events[-1], DoneEvent)
    assert events[-1].kind is AnswerKind.GROUNDED
    assert events[-1].text == "Cirrhosis is scarring [1]."


@pytest.mark.asyncio
async def test_ttft_is_measured_on_first_token() -> None:
    pipe = _pipeline(StreamingStubModel(["a", "b", "c"]))
    events = [e async for e in pipe.stream_answer("q?")]
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.timings.ttft_ms is not None and done.timings.ttft_ms >= 0
    assert done.timings.total_ms >= done.timings.ttft_ms


@pytest.mark.asyncio
async def test_no_answer_path_streams_empty_sources_and_done() -> None:
    """Below the retrieval threshold: no tokens, no citations, honest don't-know."""
    pipe = _pipeline(StreamingStubModel(["unused"]), score=0.01)
    events = [e async for e in pipe.stream_answer("What is West Nile virus?")]

    assert isinstance(events[0], SourcesEvent) and events[0].citations == []
    assert not any(isinstance(e, TokenEvent) for e in events)
    assert isinstance(events[-1], DoneEvent) and events[-1].kind is AnswerKind.NO_ANSWER


@pytest.mark.asyncio
async def test_model_abstention_streams_as_no_answer() -> None:
    abstain = ["I don't have reliable information ", "on that in my reference material."]
    pipe = _pipeline(StreamingStubModel(abstain))
    events = [e async for e in pipe.stream_answer("How does CRISPR work?")]
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.kind is AnswerKind.NO_ANSWER
    assert done.citations == []


@pytest.mark.asyncio
async def test_early_consumer_exit_cancels_provider_stream() -> None:
    """D20: a client that disconnects mid-answer must abort the provider call, or we
    pay for tokens nobody reads."""
    model = StreamingStubModel(["a", "b", "c"], hang=True)
    pipe = _pipeline(model)

    gen = pipe.stream_answer("q?")
    await gen.__anext__()  # sources
    await gen.__anext__()  # first token
    await gen.aclose()  # simulate client disconnect

    assert model.cancelled, "provider stream must be closed when the consumer goes away"
    assert model.emitted < 3, "generation must stop early, not run to completion"


def test_problem_detail_hides_internals_and_maps_status() -> None:
    """RFC 7807: safe detail out, internal message stays in logs (D18)."""
    secret = "psycopg2: password=hunter2 host=10.0.0.5"
    problem = RetrievalError(secret).to_problem(instance="/api/v1/query/stream")
    assert secret not in problem.detail
    assert problem.status == 503
    assert problem.type.endswith("/retrieval-unavailable")
    assert ProviderError().to_problem().status == 502


# ---------------------------------------------------------------------------
# S10.2 — refusal categories reach the client, and the OUTPUT guardrail covers
# the streaming path. These are the tests whose absence hid a real safety hole:
# every previous safety assertion ran against answer(), the path a browser never
# takes, so stream_answer() shipped with no output-side dosage net at all.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streaming_output_guardrail_blocks_a_dosage_instruction() -> None:
    """THE REGRESSION TEST for the S10.2b defect.

    A model that starts emitting a dose must be cut off mid-stream: the dose must never
    reach the client, generation must stop (we do not pay for the rest), and the terminal
    event must be a categorised refusal.
    """
    model = StreamingStubModel(["Take ", "500mg ", "twice daily."])
    pipe = _pipeline(model)

    events = [e async for e in pipe.stream_answer("How is this treated?")]
    done = events[-1]
    streamed = "".join(e.text for e in events if isinstance(e, TokenEvent))

    assert isinstance(done, DoneEvent)
    assert done.kind is AnswerKind.REFUSED
    assert done.refusal_category == "dosage"
    assert "500mg" not in streamed, "the dose reached the client"
    assert "500mg" not in done.text, "the dose survived in the terminal event"
    assert not done.citations, "a refusal must not cite"
    assert model.emitted < 3, "generation continued after the block — still paying"


@pytest.mark.asyncio
async def test_streaming_input_refusal_carries_its_category() -> None:
    """An emergency and a dosage refusal must be distinguishable by the client, so
    "contact emergency services now" can be rendered differently from "ask a pharmacist"."""
    pipe = _pipeline(StreamingStubModel(["never used"]))
    events = [
        e async for e in pipe.stream_answer("I'm having chest pain and my left arm is numb")
    ]
    done = events[-1]

    assert isinstance(done, DoneEvent)
    assert done.kind is AnswerKind.REFUSED
    assert done.refusal_category == "emergency"


@pytest.mark.asyncio
async def test_grounded_stream_carries_no_refusal_category() -> None:
    """No false positives: a normal cited answer must not be tagged with a safety category."""
    pipe = _pipeline(StreamingStubModel(["Cirrhosis ", "is ", "scarring [1]."]))
    events = [e async for e in pipe.stream_answer("What is cirrhosis?")]
    done = events[-1]

    assert isinstance(done, DoneEvent)
    assert done.kind is AnswerKind.GROUNDED
    assert done.refusal_category is None
