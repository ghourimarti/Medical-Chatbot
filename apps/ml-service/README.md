# ml-service — CPU inference (embeddings + reranking)

Serves `BAAI/bge-large-en-v1.5` embeddings (1024-dim) and `BAAI/bge-reranker-base`
cross-encoder scores over HTTP, so the API tier stays pure-async I/O (D7) and CPU work
scales on its own deployment (D22).

## Why this exists
S3 measured **223 ms** for a single in-process query embedding against a **250 ms** retrieval
p95 budget — embedding alone was consuming the entire budget while competing with the API
for CPU. Extraction fixes the *topology*; the backend seam in `backends.py` is where the
*performance* problem gets fixed next.

## Endpoints
| Method | Path | Notes |
|---|---|---|
| POST | `/embed` | `{texts: [...], is_query: bool}` → 1024-dim vectors. **Batched** (cap 512). |
| POST | `/rerank` | `{query, passages, top_k}` → indices + scores, sorted desc |
| GET | `/healthz` | liveness |
| GET | `/readyz` | 503 until both models are warm — the probe never lies about readiness |

**The `is_query` flag is load-bearing.** bge retrieval models expect an instruction prefix on
queries and none on documents. `QUERY_INSTRUCTION` is defined once, in `backends.py`; if the
API ever re-implements it, ingestion and query-time drift apart and retrieval quality degrades
with no error anywhere.

## Measured latency (RTX 3060 host, CPU-only, torch backend, warm)
| Operation | Cold | Warm |
|---|---:|---:|
| `/embed` — 1 query | 369 ms | **118–169 ms** |
| `/rerank` — 20 passages → top 4 | — | **154–178 ms** |

### ⚠ Retrieval budget status
```
embed ~120 ms  +  Qdrant search ~20 ms  +  rerank ~155 ms  ≈  295 ms
NFR (Phase 1): retrieval p95 ≤ 250 ms                        ✗ OVER by ~45 ms
```
This is a **measured** gap, not a predicted one. Options, in order of preference:
1. **ONNX int8 backends** (typ. 2–4× on CPU) → projected ~110 ms total. The `EmbeddingBackend`
   / `RerankBackend` protocols exist precisely so this drops in without touching routes.
2. Rerank fewer candidates (20 → 10) — cheap, costs some recall; measure in S6.
3. Move ml-service to the GPU pool (isolated from vLLM) — S15 GPU node group.
4. Re-negotiate the NFR — only with evidence that the others are insufficient.

Decision deferred to **S6**, where the retrieval path changes anyway and the eval harness can
measure the quality cost of option 2 rather than guessing.

## Run
```bash
uv run uvicorn medml.main:app --port 5006        # local
docker compose up -d ml-service                   # containerized
curl -s localhost:5006/readyz
curl -s -X POST localhost:5006/embed -H 'content-type: application/json' \
     --data-binary '{"texts":["What is cirrhosis?"],"is_query":true}' | head -c 200
```

## Wiring
`ML_SERVICE_URL` empty → the API runs models in-process (tests, single-process dev).
Set → the API uses `HttpEmbedder`/`HttpReranker`. The port abstraction means neither the
pipeline nor its tests can tell the difference.
