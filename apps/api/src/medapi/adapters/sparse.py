"""BM25 sparse encoding for hybrid retrieval (D3).

Dense embeddings match *meaning*; BM25 matches *exact terms*. Medical text is full of
proper nouns, drug names, and acronyms where exact match matters and semantic similarity
misleads ("hepatitis B" vs "hepatitis C" are near-identical in embedding space). Hybrid
retrieval covers both failure modes; that is the whole point of D3.

Uses Qdrant's own fastembed BM25 rather than a hand-rolled implementation: IDF estimation,
stemming, and document-length normalization are exactly the kind of details where a
from-scratch BM25 is subtly wrong and nobody notices until retrieval quality is bad.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import cached_property

from qdrant_client import models

BM25_MODEL_ID = "Qdrant/bm25"


class Bm25Encoder:
    """Produces Qdrant SparseVector objects for documents and queries."""

    def __init__(self, model_id: str = BM25_MODEL_ID) -> None:
        self._model_id = model_id

    @cached_property
    def _model(self) -> object:
        from fastembed import SparseTextEmbedding

        return SparseTextEmbedding(model_name=self._model_id)

    @property
    def model_id(self) -> str:
        return self._model_id

    def warmup(self) -> None:
        self.encode_query("warmup")

    def encode_documents(self, texts: Sequence[str]) -> list[models.SparseVector]:
        embeddings = self._model.embed(list(texts))  # type: ignore[attr-defined]
        return [
            models.SparseVector(indices=e.indices.tolist(), values=e.values.tolist())
            for e in embeddings
        ]

    def encode_query(self, text: str) -> models.SparseVector:
        # query_embed applies query-side IDF weighting, which differs from document-side.
        emb = next(iter(self._model.query_embed(text)))  # type: ignore[attr-defined]
        return models.SparseVector(indices=emb.indices.tolist(), values=emb.values.tolist())
