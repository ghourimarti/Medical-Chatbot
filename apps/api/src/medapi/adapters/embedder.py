"""bge-large embedder, implementing EmbedderPort.

The model is CPU-bound and synchronous, so every call goes through asyncio.to_thread and
the event loop stays free. That is what lets one API pod hold thousands of concurrent
requests. Moving this behind the HTTP ml-service is a config change, not a rewrite.
"""

from __future__ import annotations

import os
import asyncio
from collections.abc import Sequence
from functools import cached_property

from sentence_transformers import SentenceTransformer

# bge models recommend a query-side instruction prefix for retrieval; documents get none.
_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def _device() -> str:
    """Where this encoder runs. `ML_DEVICE=cpu|cuda|auto`, default cpu.

    Mirrors medml.backends._device so the in-process fallback and the ml-service path
    cannot drift: a dev run that silently used a different device than production would
    make every latency number measured here meaningless.
    """
    choice = os.getenv("ML_DEVICE", "cpu").strip().lower()
    if choice != "auto":
        return choice
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:  # noqa: BLE001 - a probe must never stop startup
        return "cpu"


class BgeEmbedder:
    """EmbedderPort implementation backed by a local sentence-transformers model."""

    def __init__(self, model_id: str, dimension: int) -> None:
        self._model_id = model_id
        self._dimension = dimension

    @cached_property
    def _model(self) -> SentenceTransformer:
        model = SentenceTransformer(self._model_id, device=_device())
        # method renamed across sentence-transformers versions; support both.
        dim_fn = getattr(model, "get_embedding_dimension", None) or (
            model.get_sentence_embedding_dimension
        )
        got = dim_fn()
        if got != self._dimension:
            raise ValueError(
                f"{self._model_id} produces {got}-dim vectors but config expects "
                f"{self._dimension}. The Qdrant collection dimension is frozen; fix config."
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
