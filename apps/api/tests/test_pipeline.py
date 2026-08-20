"""Unit tests: the LCEL pipeline with mocked ports (no network, no Qdrant, no Groq)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence

import pytest
from medapi.pipeline.context import build_context
from medapi.pipeline.rag import RagPipeline

from medcore.config import Settings
from medcore.errors import RetrievalError
from medcore.schema import AnswerKind, Completion, Message, RetrievedChunk


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
        return len(list(chunks))

    async def health(self) -> bool:
        return True


class StubModel:
    model_id = "stub-llm"

    def __init__(self, text: str = "Cirrhosis is scarring of the liver [1].") -> None:
        self._text = text

    async def complete(
        self, *, messages: Sequence[Message], max_tokens: int, temperature: float
    ) -> Completion:
        return Completion(text=self._text, model_id=self.model_id)

    async def stream(
        self, *, messages: Sequence[Message], max_tokens: int, temperature: float
    ) -> AsyncIterator[str]:
        yield "x"

    async def health(self) -> bool:
        return True


def _chunk(score: float) -> RetrievedChunk:
    return RetrievedChunk(
        id="c1", text="Cirrhosis is a chronic degenerative liver disease.",
        source="Gale", page=42, dense_score=score,
    )


@pytest.mark.asyncio
async def test_grounded_answer_when_retrieval_is_confident() -> None:
    pipe = RagPipeline(
        settings=_settings(), embedder=StubEmbedder(),
        store=StubStore([_chunk(0.9)]), model=StubModel(),
    )
    ans = await pipe.answer("What is cirrhosis?")
    assert ans.kind is AnswerKind.GROUNDED
    assert ans.citations and ans.citations[0].chunk_id == "c1"
    assert ans.model_id == "stub-llm"


@pytest.mark.asyncio
async def test_no_answer_when_below_threshold() -> None:
    """D3: below the confidence floor, abstain — never generate ungrounded (the demo's
    ooc-010 West Nile confabulation is exactly what this prevents)."""
    pipe = RagPipeline(
        settings=_settings(), embedder=StubEmbedder(),
        store=StubStore([_chunk(0.05)]), model=StubModel(),
    )
    ans = await pipe.answer("What is West Nile virus?")
    assert ans.kind is AnswerKind.NO_ANSWER
    assert not ans.citations


@pytest.mark.asyncio
async def test_model_abstention_is_relabeled_not_grounded() -> None:
    """Retrieval cleared the coarse threshold but the model said it doesn't know: the answer
    must be NO_ANSWER without citations, never a 'grounded' answer whose text is a don't-know.
    This is the CRISPR case the S3 live test surfaced."""
    abstain = "I don't have reliable information on that in my reference material."
    pipe = RagPipeline(
        settings=_settings(), embedder=StubEmbedder(),
        store=StubStore([_chunk(0.6)]), model=StubModel(abstain),
    )
    ans = await pipe.answer("How does CRISPR work?")
    assert ans.kind is AnswerKind.NO_ANSWER
    assert not ans.citations


@pytest.mark.asyncio
async def test_empty_store_is_a_FAULT_not_an_abstention() -> None:
    """P5.3. This previously returned NO_ANSWER, and that was the most dangerous bug here.

    A vector search over a populated collection always returns its nearest neighbours,
    however irrelevant — so zero candidates cannot mean "the corpus has no match". It means
    the index is empty, missing, or the alias resolves to nothing.

    Reporting that as "I don't have reliable information on that in my reference material"
    makes a broken index look like a truthful answer: every request 200s, no alert fires,
    and every user is confidently misinformed. It must be a typed, retryable 503.
    """
    pipe = RagPipeline(
        settings=_settings(), embedder=StubEmbedder(), store=StubStore([]), model=StubModel()
    )
    with pytest.raises(RetrievalError):
        await pipe.answer("anything")


@pytest.mark.asyncio
async def test_low_scoring_chunks_ARE_a_genuine_abstention() -> None:
    """The other half of the split: retrieval worked, nothing cleared the floor. That is a
    correct no-answer and must NOT become an error."""
    weak = _chunk(0.01)
    pipe = RagPipeline(
        settings=_settings(), embedder=StubEmbedder(), store=StubStore([weak]), model=StubModel()
    )
    ans = await pipe.answer("anything")
    assert ans.kind is AnswerKind.NO_ANSWER
    assert not ans.citations


def test_build_context_numbers_and_budgets() -> None:
    chunks = [_chunk(0.9), _chunk(0.8)]
    ctx, cites = build_context(chunks, max_input_tokens=3000)
    assert "[1]" in ctx and "[2]" in ctx
    assert len(cites) == 2
    tiny, tiny_cites = build_context(chunks, max_input_tokens=5)
    assert len(tiny_cites) == 1  # budget drops the second chunk
