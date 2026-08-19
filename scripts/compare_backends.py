"""Compare torch vs ONNX model backends: latency AND numerical compatibility (S5.9).

Latency alone is not enough to justify a backend swap. Query embeddings must remain
compatible with the document vectors ALREADY WRITTEN to the index — if ONNX produces
materially different vectors, retrieval degrades silently and the only fix is a full
re-index. So this measures both, and states plainly which one the result implies.

    uv run python scripts/compare_backends.py
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "ml-service" / "src"))

from medml.backends import (  # noqa: E402
    OnnxEmbeddingBackend,
    OnnxRerankBackend,
    TorchEmbeddingBackend,
    TorchRerankBackend,
)

MODEL = "BAAI/bge-large-en-v1.5"
RERANKER = "BAAI/bge-reranker-base"
DIM = 1024

QUERIES = [
    "What is an abscess?",
    "What is cirrhosis of the liver?",
    "What causes chickenpox?",
    "What is dementia?",
    "What is celiac disease?",
]
# ~500-char passages, matching real corpus chunk size — reranker cost scales with length,
# so short synthetic strings would understate it (the S5-vs-S6 discrepancy).
PASSAGES = [
    (
        "Cirrhosis is a chronic, degenerative disease in which normal liver cells are "
        "damaged and are then replaced by scar tissue. The condition develops slowly over "
        "many years and may be caused by alcohol abuse, viral hepatitis, or fatty liver "
        "disease. Symptoms often do not appear until significant damage has occurred, at "
        "which point patients may experience jaundice, fatigue, and fluid accumulation."
    )
    for _ in range(20)
]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def bench_embed(backend: object, label: str) -> tuple[float, list[list[float]]]:
    backend.warmup()  # type: ignore[attr-defined]
    times: list[float] = []
    vectors: list[list[float]] = []
    for q in QUERIES:
        t0 = time.perf_counter()
        vec = backend.encode([q], is_query=True)[0]  # type: ignore[attr-defined]
        times.append((time.perf_counter() - t0) * 1000)
        vectors.append(vec)
    print(f"  {label:6s} embed  {statistics.fmean(times):7.1f} ms/query  dim={len(vectors[0])}")
    return statistics.fmean(times), vectors


def bench_rerank(backend: object, label: str, k: int) -> tuple[float, list[float]]:
    backend.warmup()  # type: ignore[attr-defined]
    times: list[float] = []
    scores: list[float] = []
    for q in QUERIES[:3]:
        t0 = time.perf_counter()
        scores = backend.score(q, PASSAGES[:k])  # type: ignore[attr-defined]
        times.append((time.perf_counter() - t0) * 1000)
    print(f"  {label:6s} rerank {statistics.fmean(times):7.1f} ms  (k={k})")
    return statistics.fmean(times), scores


def main() -> None:
    print("=== EMBEDDING ===")
    torch_ms, torch_vecs = bench_embed(TorchEmbeddingBackend(MODEL, DIM), "torch")
    onnx_ms, onnx_vecs = bench_embed(OnnxEmbeddingBackend(MODEL, DIM), "onnx")

    sims = [cosine(a, b) for a, b in zip(torch_vecs, onnx_vecs, strict=True)]
    mean_sim = statistics.fmean(sims)
    print(f"\n  speedup: {torch_ms / onnx_ms:.2f}x")
    print(f"  torch-vs-onnx cosine similarity: min={min(sims):.6f} mean={mean_sim:.6f}")
    if mean_sim >= 0.9999:
        print("  => VECTORS COMPATIBLE: existing index can be reused, no re-index needed.")
    elif mean_sim >= 0.99:
        print("  => NEAR-COMPATIBLE: measure retrieval quality before reusing the index.")
    else:
        print("  => INCOMPATIBLE: a full re-index with this backend is MANDATORY.")

    print("\n=== RERANKING ===")
    for k in (20, 10):
        t_ms, t_scores = bench_rerank(TorchRerankBackend(RERANKER), "torch", k)
        o_ms, o_scores = bench_rerank(OnnxRerankBackend(RERANKER), "onnx", k)
        print(f"  speedup: {t_ms / o_ms:.2f}x")
        # Only the ORDER matters for reranking, so compare rankings, not raw scores.
        t_order = sorted(range(len(t_scores)), key=lambda i: t_scores[i], reverse=True)
        o_order = sorted(range(len(o_scores)), key=lambda i: o_scores[i], reverse=True)
        print(f"  top-4 ranking identical: {t_order[:4] == o_order[:4]}\n")

    print("=== RETRIEVAL PATH (embed + qdrant + rerank) vs NFR p95 <= 250 ms ===")
    qdrant_ms = 10.0  # measured on the 7,080-chunk hybrid collection
    onnx_rr_20, _ = bench_rerank(OnnxRerankBackend(RERANKER), "onnx", 20)
    per_candidate = onnx_rr_20 / 20
    for k in (20, 15, 10, 5):
        total = onnx_ms + qdrant_ms + per_candidate * k
        print(f"  onnx k={k:2d}: {onnx_ms:5.0f} + {qdrant_ms:4.0f} + {per_candidate * k:6.0f}"
              f" = {total:6.0f} ms  {'OK' if total <= 250 else 'OVER'}")


if __name__ == "__main__":
    main()
