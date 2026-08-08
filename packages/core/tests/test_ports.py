"""Ports are structural (Protocol) contracts. These tests prove a conforming adapter
satisfies the port by shape — no inheritance — and that mypy would accept it (the
`_accepts_*` functions are the compile-time half of the check)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence

from medcore.ports import EmbedderPort, ModelPort, RerankerPort, VectorStorePort
from medcore.schema import Completion, Message, RetrievedChunk


class FakeEmbedder:
    model_id = "fake"
    dimension = 1024

    async def embed_query(self, text: str) -> list[float]:
        return [0.0] * self.dimension

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.0] * self.dimension for _ in texts]


class FakeVectorStore:
    async def search(
        self,
        *,
        query_vector: Sequence[float],
        query_text: str,
        top_k: int,
        filters: Mapping[str, object] | None = None,
    ) -> list[RetrievedChunk]:
        return []

    async def upsert(self, chunks: Sequence[RetrievedChunk], *, collection: str) -> int:
        return len(list(chunks))

    async def health(self) -> bool:
        return True


class FakeReranker:
    async def rerank(
        self, *, query: str, chunks: Sequence[RetrievedChunk], top_k: int
    ) -> list[RetrievedChunk]:
        return list(chunks)[:top_k]


class FakeModel:
    model_id = "fake-llm"

    async def complete(
        self, *, messages: Sequence[Message], max_tokens: int, temperature: float
    ) -> Completion:
        return Completion(text="ok", model_id=self.model_id)

    async def stream(
        self, *, messages: Sequence[Message], max_tokens: int, temperature: float
    ) -> AsyncIterator[str]:
        yield "ok"

    async def health(self) -> bool:
        return True


# Compile-time structural checks (mypy enforces these signatures match the Protocols).
def _accepts_embedder(p: EmbedderPort) -> str:
    return p.model_id


def _accepts_store(p: VectorStorePort) -> None: ...
def _accepts_reranker(p: RerankerPort) -> None: ...
def _accepts_model(p: ModelPort) -> str:
    return p.model_id


def test_fakes_satisfy_ports_structurally() -> None:
    _accepts_embedder(FakeEmbedder())
    _accepts_store(FakeVectorStore())
    _accepts_reranker(FakeReranker())
    assert _accepts_model(FakeModel()) == "fake-llm"


def test_runtime_checkable_isinstance() -> None:
    assert isinstance(FakeEmbedder(), EmbedderPort)
    assert isinstance(FakeModel(), ModelPort)
