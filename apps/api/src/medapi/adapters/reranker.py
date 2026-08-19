"""In-process cross-encoder reranker (D3). Implements RerankerPort.

Mirrors BgeEmbedder: used when ML_SERVICE_URL is unset (tests, single-process dev), so the
pipeline ALWAYS has a reranker. Without this, test runs would silently measure a
non-reranked pipeline — i.e. measure the thing we are trying to improve, unimproved.

SCORE SCALE (the subtle part): a cross-encoder emits raw logits (~-10..+10), while dense
retrieval emits cosine similarity (0..1). The no-answer threshold compares one number, so
logits are squashed through a sigmoid to a comparable 0..1 probability. Skipping this makes
the threshold silently meaningless after reranking.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from functools import cached_property

from medcore.schema import RetrievedChunk


def sigmoid(x: float) -> float:
    """Cross-encoder logit -> 0..1 probability, comparable with cosine scores."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)  # numerically stable for large negative logits
    return e / (1.0 + e)


class BgeReranker:
    """RerankerPort backed by a local sentence-transformers CrossEncoder."""

    def __init__(self, model_id: str) -> None:
        self._model_id = model_id

    @cached_property
    def _model(self) -> object:
        from sentence_transformers import CrossEncoder

        return CrossEncoder(self._model_id, device="cpu")

    @property
    def model_id(self) -> str:
        return self._model_id

    def warmup(self) -> None:
        self._score("warmup", ["warmup passage"])

    def _score(self, query: str, passages: list[str]) -> list[float]:
        pairs = [(query, p) for p in passages]
        return [float(s) for s in self._model.predict(pairs)]  # type: ignore[attr-defined]

    async def rerank(
        self, *, query: str, chunks: Sequence[RetrievedChunk], top_k: int
    ) -> list[RetrievedChunk]:
        items = list(chunks)
        if not items:
            return []
        # CPU-bound: never on the event loop (D7).
        raw = await asyncio.to_thread(self._score, query, [c.text for c in items])
        scored = [
            c.model_copy(update={"rerank_score": sigmoid(s)})
            for c, s in zip(items, raw, strict=True)
        ]
        scored.sort(key=lambda c: c.rerank_score or 0.0, reverse=True)
        return scored[:top_k]
