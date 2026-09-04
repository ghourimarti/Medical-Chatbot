"""In-process cross-encoder reranker, implementing RerankerPort.

Mirrors BgeEmbedder and is used when ML_SERVICE_URL is unset (tests, single-process dev),
so the pipeline always has a reranker. Without it, test runs would quietly measure a
non-reranked pipeline.

Watch the score scale. A cross-encoder emits raw logits (~-10..+10) while dense retrieval
emits cosine similarity (0..1), and the no-answer threshold compares a single number, so
the logits go through a sigmoid to land on a comparable 0..1. Skip that and the threshold
means nothing once reranking is on.
"""

from __future__ import annotations

import os
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


class BgeReranker:
    """RerankerPort backed by a local sentence-transformers CrossEncoder."""

    def __init__(self, model_id: str) -> None:
        self._model_id = model_id

    @cached_property
    def _model(self) -> object:
        from sentence_transformers import CrossEncoder

        return CrossEncoder(self._model_id, device=_device())

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
        # CPU-bound, so never on the event loop.
        raw = await asyncio.to_thread(self._score, query, [c.text for c in items])
        scored = [
            c.model_copy(update={"rerank_score": sigmoid(s)})
            for c, s in zip(items, raw, strict=True)
        ]
        scored.sort(key=lambda c: c.rerank_score or 0.0, reverse=True)
        return scored[:top_k]
