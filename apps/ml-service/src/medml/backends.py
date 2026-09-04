"""Model backends behind a seam, so torch and ONNX can be A/B'd by config.

DECISION GATE (D5): the bge query-instruction prefix is defined HERE and nowhere else.
bge retrieval models expect it on queries and NOT on documents; applying it inconsistently
between ingestion and query time degrades retrieval silently — the kind of bug that only
surfaces as a mediocre eval score with no error anywhere.
"""

from __future__ import annotations

import os
import time
from functools import cached_property
from typing import Protocol

# The one true definition. apps/api must never re-implement this.
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


class EmbeddingBackend(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def warmup(self) -> None: ...

    def encode(self, texts: list[str], *, is_query: bool) -> list[list[float]]: ...


class RerankBackend(Protocol):
    @property
    def model_id(self) -> str: ...

    def warmup(self) -> None: ...

    def score(self, query: str, passages: list[str]) -> list[float]: ...


def _device() -> str:
    """Where the encoders run. `ML_DEVICE=cpu|cuda|auto`, default cpu.

    This was hardcoded to "cpu" in both backends, which made the largest single component
    of TTFT untunable. Measured on the dev box: rerank p95 3.5s scoring 20 candidate pairs
    on CPU against a 0.8s TTFT target, so the pipeline spent multiples of its entire
    latency budget before the model could emit a first token.

    The default stays "cpu". On a single-GPU host the card is already holding the
    inference engine, and a cross-encoder that evicts KV cache trades one latency problem
    for another. "auto" picks cuda only when torch reports it available, so the same image
    runs on a CPU-only box unchanged.
    """
    choice = os.getenv("ML_DEVICE", "cpu").strip().lower()
    if choice != "auto":
        return choice
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:  # noqa: BLE001 - a probe must never stop the service booting
        return "cpu"


class TorchEmbeddingBackend:
    """sentence-transformers on CPU. The measured baseline (S3: ~140-225ms/query)."""

    def __init__(self, model_id: str, dimension: int) -> None:
        self._model_id = model_id
        self._dimension = dimension

    @cached_property
    def _model(self) -> object:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(self._model_id, device=_device())
        dim_fn = getattr(model, "get_embedding_dimension", None) or (
            model.get_sentence_embedding_dimension
        )
        got = dim_fn()
        if got != self._dimension:
            raise ValueError(
                f"{self._model_id} produces {got}-dim vectors, config expects {self._dimension}. "
                "The Qdrant collection dimension is frozen — fix config, do not mutate the index."
            )
        return model

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def dimension(self) -> int:
        return self._dimension

    def warmup(self) -> None:
        self.encode(["warmup"], is_query=True)

    def encode(self, texts: list[str], *, is_query: bool) -> list[list[float]]:
        prepared = [QUERY_INSTRUCTION + t for t in texts] if is_query else texts
        vecs = self._model.encode(  # type: ignore[attr-defined]
            prepared, normalize_embeddings=True, batch_size=32
        )
        return [v.tolist() for v in vecs]


class TorchRerankBackend:
    """Cross-encoder reranking. Scores (query, passage) pairs jointly, which is far more
    accurate than embedding cosine and is the main retrieval-quality lever."""

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
        self.score("warmup", ["warmup passage"])

    def score(self, query: str, passages: list[str]) -> list[float]:
        pairs = [(query, p) for p in passages]
        scores = self._model.predict(pairs)  # type: ignore[attr-defined]
        return [float(s) for s in scores]


class OnnxEmbeddingBackend:
    """ONNX Runtime embeddings via fastembed.

    Chosen over `optimum[onnxruntime]` because onnxruntime is already a dependency (it came
    in with fastembed for BM25) and fastembed serves the exact model we index with,
    `BAAI/bge-large-en-v1.5`. A second ONNX stack to reach the same runtime is bloat.

    ⚠ VECTOR COMPATIBILITY: query and document embeddings must come from the same model
    AND backend, or retrieval silently degrades. `scripts/compare_backends.py` measures the
    torch-vs-ONNX divergence; if it is not ~1.0 cosine, a re-index is mandatory.
    """

    def __init__(self, model_id: str, dimension: int) -> None:
        self._model_id = model_id
        self._dimension = dimension

    @cached_property
    def _model(self) -> object:
        from fastembed import TextEmbedding

        return TextEmbedding(model_name=self._model_id)

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def dimension(self) -> int:
        return self._dimension

    def warmup(self) -> None:
        self.encode(["warmup"], is_query=True)

    def encode(self, texts: list[str], *, is_query: bool) -> list[list[float]]:
        # fastembed applies bge's query instruction internally in query_embed(), so using
        # embed() for documents keeps the query/document asymmetry intact.
        model = self._model
        if is_query:
            vectors = [next(iter(model.query_embed(t))) for t in texts]  # type: ignore[attr-defined]
        else:
            vectors = list(model.embed(texts))  # type: ignore[attr-defined]
        return [v.tolist() for v in vectors]


class OnnxRerankBackend:
    """ONNX cross-encoder reranking via fastembed.

    Quantization is safer here than for embeddings. Reranking only needs score ordering
    preserved, whereas embeddings have to stay numerically compatible with vectors already
    written to the index.
    """

    def __init__(self, model_id: str) -> None:
        self._model_id = model_id

    @cached_property
    def _model(self) -> object:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        return TextCrossEncoder(model_name=self._model_id)

    @property
    def model_id(self) -> str:
        return self._model_id

    def warmup(self) -> None:
        self.score("warmup", ["warmup passage"])

    def score(self, query: str, passages: list[str]) -> list[float]:
        return [float(s) for s in self._model.rerank(query, passages)]  # type: ignore[attr-defined]


def build_embedding_backend(backend: str, model_id: str, dimension: int) -> EmbeddingBackend:
    if backend == "onnx":
        return OnnxEmbeddingBackend(model_id, dimension)
    return TorchEmbeddingBackend(model_id, dimension)


def build_rerank_backend(backend: str, model_id: str) -> RerankBackend:
    if backend == "onnx":
        return OnnxRerankBackend(model_id)
    return TorchRerankBackend(model_id)


def timed(fn: object) -> tuple[object, float]:  # pragma: no cover - helper
    t0 = time.perf_counter()
    result = fn()  # type: ignore[operator]
    return result, (time.perf_counter() - t0) * 1000
