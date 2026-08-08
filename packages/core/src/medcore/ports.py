"""Port protocols — the reversibility layer.

Every "Reversibility: Easy" claim in the Decision Log is cashed here. D2 (Qdrant ->
pgvector flip-down), D4/D12 (vLLM <-> SGLang <-> hosted), D5 (embedding swap) are all
config flips *because* the pipeline depends on these protocols, never on an SDK type.

Structural (Protocol), not nominal (ABC): an adapter satisfies a port by shape, so no
vendor class ever has to inherit from our code.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Protocol, runtime_checkable

from medcore.schema import Completion, Message, RetrievedChunk


@runtime_checkable
class EmbedderPort(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    async def embed_query(self, text: str) -> list[float]: ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...


@runtime_checkable
class VectorStorePort(Protocol):
    """`search` takes BOTH a vector and the raw text: hybrid dense+sparse retrieval (D3)
    must be expressible without ever changing this signature. A vector-only port would
    force an interface change on the very slice it exists to protect."""

    async def search(
        self,
        *,
        query_vector: Sequence[float],
        query_text: str,
        top_k: int,
        filters: Mapping[str, object] | None = None,
    ) -> list[RetrievedChunk]: ...

    async def upsert(self, chunks: Sequence[RetrievedChunk], *, collection: str) -> int: ...

    async def health(self) -> bool: ...


@runtime_checkable
class RerankerPort(Protocol):
    async def rerank(
        self, *, query: str, chunks: Sequence[RetrievedChunk], top_k: int
    ) -> list[RetrievedChunk]: ...


@runtime_checkable
class ModelPort(Protocol):
    """The seam behind which vLLM (primary), SGLang (engine failover), and the hosted
    outage leg are interchangeable (D4, D12)."""

    @property
    def model_id(self) -> str: ...

    async def complete(
        self, *, messages: Sequence[Message], max_tokens: int, temperature: float
    ) -> Completion: ...

    def stream(
        self, *, messages: Sequence[Message], max_tokens: int, temperature: float
    ) -> AsyncIterator[str]: ...

    async def health(self) -> bool: ...
