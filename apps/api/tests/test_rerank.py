"""reranking, score normalization, hybrid wiring, and graceful degradation."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

import pytest
from medapi.adapters.reranker import sigmoid
from medapi.pipeline.rag import RagPipeline

from medcore.config import Settings
from medcore.errors import RerankerError
from medcore.schema import AnswerKind, Completion, Message, RetrievedChunk


def _settings(**over: object) -> Settings:
    base: dict[str, object] = {"groq_api_key": "gsk_test"}
    base.update(over)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


class StubEmbedder:
    model_id, dimension = "stub", 1024

    async def embed_query(self, text: str) -> list[float]:
        return [0.1] * self.dimension

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.1] * self.dimension for _ in texts]


class RecordingStore:
    """Records how it was called so we can assert the hybrid path is actually used."""

    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self._chunks = chunks
        self.last_kwargs: dict[str, object] = {}

    async def search(self, **kwargs: object) -> list[RetrievedChunk]:
        self.last_kwargs = kwargs
        return self._chunks[: int(kwargs.get("top_k", 10))]  # type: ignore[arg-type]

    async def upsert(self, chunks: Sequence[RetrievedChunk], *, collection: str) -> int:
        return 0

    async def health(self) -> bool:
        return True


class StubModel:
    model_id = "stub-llm"

    async def complete(
        self, *, messages: Sequence[Message], max_tokens: int, temperature: float
    ) -> Completion:
        return Completion(text="Answer grounded in context [1].", model_id=self.model_id)

    async def stream(
        self, *, messages: Sequence[Message], max_tokens: int, temperature: float
    ) -> AsyncIterator[str]:
        yield "x"

    async def health(self) -> bool:
        return True


class StubReranker:
    """Reverses the input order, so a test can prove reranking actually happened."""

    def __init__(self, fail: bool = False) -> None:
        self._fail = fail

    async def rerank(
        self, *, query: str, chunks: Sequence[RetrievedChunk], top_k: int
    ) -> list[RetrievedChunk]:
        if self._fail:
            raise RerankerError("reranker down")
        reversed_chunks = list(reversed(list(chunks)))
        return [
            c.model_copy(update={"rerank_score": 0.9 - 0.1 * i})
            for i, c in enumerate(reversed_chunks)
        ][:top_k]


class StubSparse:
    class _Vec:
        indices = [1, 2, 3]
        values = [0.5, 0.4, 0.3]

    def encode_query(self, text: str) -> object:
        return self._Vec()


def _chunks(n: int) -> list[RetrievedChunk]:
    return [
        RetrievedChunk(id=f"c{i}", text=f"passage {i}", source="Gale", page=i, dense_score=0.6)
        for i in range(n)
    ]


# score normalization


def test_sigmoid_maps_logits_into_zero_one() -> None:
    """Cross-encoder logits (~-10..+10) must become 0..1 so ONE threshold is meaningful
    for both dense cosine and rerank scores."""
    assert sigmoid(0.0) == pytest.approx(0.5)
    assert 0.0 < sigmoid(-12.0) < 0.01
    assert 0.99 < sigmoid(12.0) < 1.0
    assert sigmoid(-1000.0) >= 0.0  # numerically stable, no overflow


def test_sigmoid_is_monotonic() -> None:
    vals = [sigmoid(x) for x in (-5.0, -1.0, 0.0, 1.0, 5.0)]
    assert vals == sorted(vals)


# pipeline behaviour


@pytest.mark.asyncio
async def test_rerank_stage_reorders_candidates() -> None:
    store = RecordingStore(_chunks(5))
    pipe = RagPipeline(
        settings=_settings(rerank_top_k=3),
        embedder=StubEmbedder(), store=store, model=StubModel(), reranker=StubReranker(),
    )
    ans, contexts = await pipe.answer_verbose("q?")
    assert ans.kind is AnswerKind.GROUNDED
    # StubReranker reverses: highest-ranked should be the LAST retrieved chunk.
    assert contexts[0] == "passage 4"
    assert len(contexts) == 3  # rerank_top_k applied


@pytest.mark.asyncio
async def test_reranker_failure_degrades_instead_of_erroring() -> None:
    """a reranker outage costs quality, never availability."""
    store = RecordingStore(_chunks(5))
    pipe = RagPipeline(
        settings=_settings(), embedder=StubEmbedder(), store=store,
        model=StubModel(), reranker=StubReranker(fail=True),
    )
    ans = await pipe.answer("q?")
    assert ans.kind is AnswerKind.GROUNDED  # still answers
    assert ans.citations  # fusion order served


@pytest.mark.asyncio
async def test_hybrid_search_passes_sparse_vector() -> None:
    store = RecordingStore(_chunks(3))
    pipe = RagPipeline(
        settings=_settings(), embedder=StubEmbedder(), store=store,
        model=StubModel(), reranker=StubReranker(), sparse=StubSparse(),
    )
    await pipe.answer("what is cirrhosis?")
    assert "sparse_vector" in store.last_kwargs, "hybrid path must send a sparse vector"


@pytest.mark.asyncio
async def test_dense_only_when_sparse_encoder_absent() -> None:
    store = RecordingStore(_chunks(3))
    pipe = RagPipeline(
        settings=_settings(), embedder=StubEmbedder(), store=store,
        model=StubModel(), reranker=StubReranker(),
    )
    await pipe.answer("q?")
    assert "sparse_vector" not in store.last_kwargs


@pytest.mark.asyncio
async def test_total_ms_includes_every_stage() -> None:
    """Regression guard: total_ms once omitted rerank_ms and under-reported a 1113ms
    request as 354ms. A latency metric that hides the most expensive stage is worse than
    none, because it looks authoritative."""
    store = RecordingStore(_chunks(5))
    pipe = RagPipeline(
        settings=_settings(), embedder=StubEmbedder(), store=store,
        model=StubModel(), reranker=StubReranker(),
    )
    ans = await pipe.answer("q?")
    t = ans.timings
    stage_sum = (
        (t.embed_ms or 0) + (t.retrieve_ms or 0) + (t.rerank_ms or 0) + (t.generate_ms or 0)
    )
    assert t.total_ms == pytest.approx(stage_sum, rel=1e-6)
    assert t.rerank_ms is not None, "rerank stage must be timed"


@pytest.mark.asyncio
async def test_threshold_applies_to_normalized_rerank_score() -> None:
    """After reranking, effective_score is the sigmoid-normalized rerank score. A high
    threshold must therefore trigger the no-answer path."""
    store = RecordingStore(_chunks(3))
    pipe = RagPipeline(
        settings=_settings(no_answer_threshold=0.95),
        embedder=StubEmbedder(), store=store, model=StubModel(), reranker=StubReranker(),
    )
    ans = await pipe.answer("q?")
    assert ans.kind is AnswerKind.NO_ANSWER
