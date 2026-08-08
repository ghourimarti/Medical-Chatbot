"""bge-large embedder (D5). Implements EmbedderPort.

The model is CPU-bound and synchronous. Every call runs in a worker thread via
asyncio.to_thread so the async event loop is never blocked (D7) — the discipline that
lets one API pod hold thousands of concurrent requests. In S5 this moves behind an HTTP
ml-service; the port keeps that a config change, not a rewrite.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from functools import cached_property

from sentence_transformers import SentenceTransformer

# bge models recommend a query-side instruction prefix for retrieval; documents get none.
_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class BgeEmbedder:
    """EmbedderPort implementation backed by a local sentence-transformers model."""

    def __init__(self, model_id: str, dimension: int) -> None:
        self._model_id = model_id
        self._dimension = dimension

    @cached_property
    def _model(self) -> SentenceTransformer:
        model = SentenceTransformer(self._model_id, device="cpu")
        # method renamed across sentence-transformers versions; support both.
        dim_fn = getattr(model, "get_embedding_dimension", None) or (
            model.get_sentence_embedding_dimension
        )
        got = dim_fn()
        if got != self._dimension:
            raise ValueError(
                f"{self._model_id} produces {got}-dim vectors but config expects "
                f"{self._dimension}. The Qdrant collection dimension is frozen — fix config."
            )
        return model

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def dimension(self) -> int:
        return self._dimension

    def warmup(self) -> None:
        """Force model load eagerly (called from lifespan) so the first request isn't slow."""
        _ = self._model

    async def embed_query(self, text: str) -> list[float]:
        return await asyncio.to_thread(self._encode_one, _QUERY_PREFIX + text)

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await asyncio.to_thread(self._encode_many, list(texts))

    def _encode_one(self, text: str) -> list[float]:
        vec = self._model.encode(text, normalize_embeddings=True)
        return vec.tolist()  # type: ignore[no-any-return]

    def _encode_many(self, texts: list[str]) -> list[list[float]]:
        vecs = self._model.encode(texts, normalize_embeddings=True, batch_size=32)
        return [v.tolist() for v in vecs]
