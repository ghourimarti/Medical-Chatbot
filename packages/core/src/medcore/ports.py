"""Port protocols: the layer that keeps vendor choices reversible.

Swapping Qdrant for pgvector, vLLM for SGLang or a hosted leg, or one embedding model for
another stays a config change because the pipeline depends on these protocols and never on
an SDK type.

Structural (Protocol) rather than nominal (ABC), so an adapter satisfies a port by shape
and no vendor class has to inherit from our code.
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
    """`search` takes both a vector and the raw text, so hybrid dense+sparse retrieval is
    expressible without changing this signature. A vector-only port would force an
    interface change on the slice it exists to protect."""

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
    """The seam that makes vLLM, SGLang and the hosted legs interchangeable."""

    @property
    def model_id(self) -> str: ...

    async def complete(
        self, *, messages: Sequence[Message], max_tokens: int, temperature: float
    ) -> Completion: ...

    def stream(
        self, *, messages: Sequence[Message], max_tokens: int, temperature: float
    ) -> AsyncIterator[str]: ...

    async def health(self) -> bool: ...
