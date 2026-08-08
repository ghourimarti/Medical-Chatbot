# medapi — query service (S3 thin slice)

FastAPI + a self-authored LCEL RAG pipeline over Qdrant (1024-dim, bge-large) with Groq
as the generator. This is the S3 walking skeleton: dense retrieval, non-streaming, no
rerank/cache/auth yet — those arrive in later steps.

## Architecture (S3)
```
POST /api/v1/query
   └─ RagPipeline (LCEL: self-authored runnables)
        embed ──► retrieve ──► no-answer gate ──► build_context ──► generate
        (bge)     (Qdrant)      (D3 threshold)     (cited, budgeted)   (Groq, ModelPort)
```
Adapters (`adapters/`) implement the `medcore` ports — swappable per D2/D4/D5/D12.
Vendor SDKs live here, never in `medcore`.

## Run locally
```bash
docker compose up -d qdrant                    # vector store on :1104
uv run medapi-reindex --limit 1500             # embed a corpus subset at 1024d
uv run uvicorn medapi.main:app --port 1107     # boot the API
curl -s localhost:1107/readyz
curl -s -X POST localhost:1107/api/v1/query \
     -H 'content-type: application/json' \
     -d '{"question":"What is an abscess?","stream":false}' | jq
```

## Endpoints
| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | Liveness — process up (never touches deps) |
| GET | `/readyz` | Readiness — 503 until Qdrant reachable (D21) |
| POST | `/api/v1/query` | Grounded, cited answer (or typed no-answer) |

## Tests
```bash
uv run pytest apps/api/tests/test_pipeline.py                 # unit (mocked ports)
RUN_QDRANT_TESTS=1 uv run pytest apps/api/tests/test_integration.py  # needs Qdrant
```

## What's deliberately deferred
Streaming + cancellation (S4) · embed/rerank as a separate CPU service (S5) · hybrid +
reranker + eval delta (S6) · sessions/history (S7) · caching + quotas (S8) · durable
ingestion with alias-swap (S9) · self-hosted vLLM/SGLang serving (S13).
