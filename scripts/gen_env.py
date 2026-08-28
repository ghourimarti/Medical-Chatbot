"""Generate .env and .env.example from ONE spec, so they cannot drift apart.

Why a generator instead of two hand-maintained files: they had already drifted. `.env`
still carried NEXT_PUBLIC_API_URL (removed from the example in S10.14 because nothing
reads it) and was missing 13 keys the example documents, including every SGLANG_* name.
Two files edited by hand always end up describing two different systems.

Two rules this enforces mechanically:

  1. ONE BOXED SECTION PER SERVICE. Everything Postgres needs — port, database, user,
     password — sits together under one header, so configuring a service means reading
     one block rather than hunting the file.

  2. COMMENTS GO ABOVE THEIR VARIABLE, NEVER TRAILING. `PORT=5001  # boots first` is a
     trap: python-dotenv strips that trailing comment, a plain shell `source` strips it,
     and anything else keeps it. This repo has already been bitten once (empty values
     taking the comment as their value). Above-the-line comments are unambiguous to every
     reader.

Usage:
    python scripts/gen_env.py --check        # fail if .env.example is stale (CI-safe)
    python scripts/gen_env.py --write        # rewrite .env.example
    python scripts/gen_env.py --write-env    # rewrite .env, PRESERVING existing values
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# (KEY, example_value, comment_lines)  — comment lines are emitted ABOVE the key.
Var = tuple[str, str, tuple[str, ...]]
Section = tuple[str, str, tuple[Var, ...]]  # (title, subtitle, vars)

TIERS: list[tuple[str, list[Section]]] = [
    ("APPLICATION", [
        ("RUNTIME", "process-wide behaviour", (
            ("ENVIRONMENT", "local", (
                "local | dev | staging | prod.",
                "Outside `local` the config REFUSES to start without a real SESSION_SECRET,",
                "SECURE_COOKIES=true, REDIS_URL and DATABASE_URL. A default that works",
                "everywhere is a default that reaches production.",
            )),
            ("LOG_LEVEL", "INFO", ("DEBUG | INFO | WARNING | ERROR",)),
        )),
        ("API — FastAPI backend", "http://localhost:5007/docs", (
            ("API_PORT", "5007", ("Host port. The container always listens on 8000.",)),
            ("SESSION_SECRET", "dev-only-insecure-session-secret-change-me", (
                "SECRET. Signs the anonymous session cookie.",
                "The dev value is REJECTED outside local. demo/ used os.urandom(24), which",
                "invalidated every session on restart and on every added replica.",
            )),
            ("SECURE_COOKIES", "false", (
                "true wherever TLS terminates. Forced true outside",
                "local.",
            )),
            ("ADMIN_API_KEY", "", (
                "SECRET. Guards /admin/*. Empty = admin endpoints are unavailable, which is",
                "the safe default: an unset key must not mean an open door.",
            )),
            ("TRUSTED_PROXY_HOPS", "0", (
                "Proxy hops to trust in X-Forwarded-For. 0 = trust none.",
                "Set this WRONG and per-IP rate limits are defeated by a forged header.",
            )),
        )),
        ("WEB — Next.js frontend", "http://localhost:5008", (
            ("WEB_PORT", "5008", ("Host port; the container listens on 3000.",)),
            ("API_BASE_URL", "http://localhost:5007", (
                "SERVER-SIDE ONLY. The browser never dials the API directly — it talks to",
                "this origin and the BFF proxy forwards server-side (D23). A NEXT_PUBLIC_*",
                "equivalent would be inlined into the browser bundle and imply otherwise.",
            )),
            ("UPSTREAM_TIMEOUT_MS", "120000", (
                "Generation can legitimately take tens of seconds.",
                "INLINED AT BUILD TIME: changing it needs a rebuild, not a restart.",
            )),
        )),
        ("ML-SERVICE — embeddings + reranking", "http://localhost:5006/readyz", (
            ("ML_SERVICE_PORT", "5006", (
                "Must be up BEFORE the API: readiness checks it",
                "(P6.5.4).",
            )),
            ("ML_SERVICE_URL", "http://ml-service:8001", (
                "EMPTY = run the models in-process (tests, single-process dev).",
                "SET = the API calls this service over HTTP so CPU work scales separately (D22).",
                "One line switches the topology.",
            )),
            ("ML_BACKEND", "torch", (
                "torch = reference implementation. onnx = ONNX Runtime (S5.9), needed to meet",
                "the 250ms retrieval NFR — measured: fewer candidates alone cannot get there.",
            )),
            ("EMBEDDING_MODEL_ID", "BAAI/bge-large-en-v1.5", (
                "1024-dim. The dimension is FROZEN — see the note",
                "below.",
            )),
            ("RERANKER_MODEL_ID", "BAAI/bge-reranker-base", (
                "Cross-encoder. Dominates query latency",
                "(S5.9).",
            )),
            ("EMBED_TIMEOUT", "8.0", (
                "Seconds. Was 5.0 against a measured p95 of 2.35s, which looks like",
                "ample headroom until several queries arrive at once: ml-service runs",
                "bge-large on CPU, so concurrency serialises and the 5s budget was",
                "exceeded under a burst - a 503, because without a vector there is",
                "nothing to retrieve.",
            )),
            ("RERANK_TIMEOUT", "4.0", (
                "Seconds. On timeout the pipeline DEGRADES (skips rerank), never fails.",
                "MEASURED, not guessed: this was 2.0 while the reranker's own p95 was",
                "2.425s. A timeout BELOW the p95 of the thing it guards makes the",
                "degraded path the NORMAL path - the cross-encoder was being skipped on",
                "well over 5% of queries, silently serving fusion order instead of",
                "reranked order, with every dashboard green.",
                "The real fix is a GPU reranker; this only stops the fallback firing",
                "as routine behaviour. Re-derive it from",
                "medbot_stage_duration_seconds if the hardware changes.",
            )),
        )),
        ("RETRIEVAL — hybrid search + no-answer floor (D3)", "", (
            ("HYBRID_SEARCH", "true", (
                "Dense + BM25 sparse, fused server-side by RRF in",
                "Qdrant.",
            )),
            ("RETRIEVAL_TOP_K", "20", ("Candidates fetched per branch, before reranking.",)),
            ("RERANK_TOP_K", "4", ("Passages kept for the context window after reranking.",)),
            ("NO_ANSWER_THRESHOLD", "0.30", (
                "Applies to the SIGMOID-NORMALISED cross-encoder score (0..1).",
                "Dense cosine and cross-encoder logits are different scales; the sigmoid in",
                "adapters/reranker.py is what makes ONE threshold meaningful for both.",
                "Below this the answer is an honest 'I don't have reliable information'.",
            )),
        )),
    ]),
    ("INFERENCE", [
        ("SERVING CHAIN — ordered failover preference (D4b)", "first reachable leg answers", (
            ("SERVING_CHAIN", "local-sglang,groq", (
                "AN ORDERED PREFERENCE LIST. Comma-separated, tried left to right; a leg with",
                "no URL or key is SKIPPED, so you can name venues before their accounts exist.",
                "",
                "  Entry form:  venue  |  venue-engine",
                "  Venues:      local, runpod, aws  (your GPUs)  ·  groq, openai  (hosted)",
                "  Engines:     vllm, sglang        (GPU venues only)",
                "",
                "  Examples:",
                "    local-sglang,groq               THE DEFAULT: SGLang, hosted safety net",
                "    local-vllm,groq                 vLLM instead",
                "    local-vllm,local-sglang,groq    both engines - a REHEARSAL, not steady",
                "                                    state: one GPU is one failure domain",
                "    groq                            hosted only (no GPU needed)",
                "",
                "WHY A LIST AND NOT PRIORITY NUMBERS: numbers split identity from order into",
                "two places that can disagree, and inserting a leg means renumbering the rest.",
                "",
                "WHAT THE ORDER SHOULD RESPECT: legs only protect you when they fail",
                "INDEPENDENTLY. local-vllm -> local-sglang covers an ENGINE fault (crash, OOM,",
                "a bad build) but NOT a dead GPU or a dead box — both legs share those.",
                "Independence begins at the hosted legs, so keep one of them last.",
            )),
            ("SERVING_ENGINE", "sglang", (
                "Default engine for a chain entry that does NOT name one (`local` -> this).",
                "Ignored by hosted venues: there is no engine of ours to choose.",
                "Kept in step with the Makefile's ENGINE default on purpose: this value is",
                "what applies when the stack is started WITHOUT `make` (a bare",
                "`docker compose up`, or a container restart), and a disagreement there is",
                "how a chain ends up naming an engine that is not running - every request",
                "then pays a connect timeout on a dead leg before failing over.",
            )),
            ("CIRCUIT_FAILURE_THRESHOLD", "3", ("Consecutive failures before a leg is skipped.",)),
            ("CIRCUIT_COOLDOWN_SECONDS", "30", (
                "How long a tripped leg stays skipped before a",
                "retry.",
            )),
        )),
        ("vLLM — self-hosted engine (local GPU)", "http://localhost:5009/v1", (
            ("VLLM_LOCAL_PORT", "5009", ("Host port; the container listens on 8000.",)),
            ("VLLM_LOCAL_URL", "http://localhost:5009/v1", (
                "MUST match VLLM_LOCAL_PORT. In-container the API uses http://vllm:8000/v1.",
            )),
            ("VLLM_LOCAL_MODEL", "Qwen/Qwen2.5-7B-Instruct-AWQ", (
                "AWQ INT4 — fits a 12GB card. CHANGE IT HERE and nowhere else: this one",
                "value is both the engine's --model argument AND the model name the API",
                "puts in every OpenAI-compatible request.",
                "RESTART BOTH SIDES, or they disagree:",
                "    make down && make up-vllm",
                "Restarting only the engine leaves the API asking for a model that is no",
                "longer loaded -> 404 -> the leg fails -> failover to the HOSTED venue.",
                "You then think you are benchmarking a self-hosted engine while paying",
                "for every token. `make which-engine` and inspect_stack.py both check",
                "that the two agree.",
                "Bigger model = more VRAM: a 12GB card fits ~7B at INT4, not FP16.",
            )),
            ("VLLM_GPU_MEMORY_UTILIZATION", "0.80", (
                "Headroom for the KV cache at 8k context on",
                "12GB.",
            )),
            ("VLLM_MAX_MODEL_LEN", "8192", ("Context length. Trades against batch size.",)),
            ("VLLM_RUNPOD_URL", "", ("Empty = venue skipped (Track D.2).",)),
            ("VLLM_RUNPOD_MODEL", "Qwen/Qwen2.5-7B-Instruct-AWQ", ()),
            ("VLLM_AWS_URL", "", ("Empty = venue skipped (Track D.1, needs G-instance quota).",)),
            ("VLLM_AWS_MODEL", "Qwen/Qwen2.5-7B-Instruct-AWQ", ()),
        )),
        ("SGLang — second engine, same weights", "http://localhost:5010/v1", (
            ("SGLANG_LOCAL_PORT", "5010", ("Host port; the container listens on 30000.",)),
            ("SGLANG_LOCAL_URL", "http://localhost:5010/v1", ("MUST match SGLANG_LOCAL_PORT.",)),
            ("SGLANG_LOCAL_MODEL", "Qwen/Qwen2.5-7B-Instruct-AWQ", (
                "Same weights as vLLM — one download, one cache volume.",
                "Same rule as VLLM_LOCAL_MODEL: change it here, then restart BOTH the",
                "engine and the API (`make down && make up-sglang`). Keeping the two",
                "engines on the SAME model is what makes a failover comparison mean",
                "anything — different weights would compare models, not engines.",
            )),
            ("SGLANG_MEM_FRACTION", "0.45", (
                "Deliberately lower than vLLM's 0.80: if BOTH engines run on one card they",
                "cannot each claim 80% of it. Running the pair is a failover rehearsal.",
            )),
            ("SGLANG_MAX_MODEL_LEN", "8192", ()),
            ("SGLANG_RUNPOD_URL", "", ()),
            ("SGLANG_RUNPOD_MODEL", "Qwen/Qwen2.5-7B-Instruct-AWQ", ()),
            ("SGLANG_AWS_URL", "", ()),
            ("SGLANG_AWS_MODEL", "Qwen/Qwen2.5-7B-Instruct-AWQ", ()),
        )),
        ("GROQ — hosted venue (the outage leg + escalation tier)", "", (
            ("GROQ_API_KEY", "gsk_...", ("SECRET. THE ONLY REQUIRED VALUE in this file.",)),
            ("GROQ_BASE_URL", "https://api.groq.com/openai/v1", ()),
            ("GROQ_DEFAULT_MODEL", "openai/gpt-oss-20b", (
                "MODEL DEPRECATION IS REAL (S19/S6.12): Groq retired the whole Llama family on",
                "this account — llama-3.1-8b-instant and llama-3.3-70b-versatile both 404 now,",
                "and both worked in S6. A hosted vendor can retire your pinned model underneath",
                "you; a self-hosted engine cannot, because its weights are a file we hold.",
            )),
            ("GROQ_ESCALATION_MODEL", "openai/gpt-oss-120b", (
                "Bigger model for low-confidence",
                "answers.",
            )),
            ("GROQ_TIMEOUT", "10.0", ("Seconds.",)),
        )),
        ("OPENAI — optional hosted venue", "", (
            ("OPENAI_API_KEY", "", (
                "SECRET. Empty = the `openai` chain leg is SKIPPED, never a",
                "runtime 401.",
            )),
            ("OPENAI_BASE_URL", "https://api.openai.com/v1", ()),
            ("OPENAI_FALLBACK_MODEL", "gpt-4o-mini", ()),
        )),
        ("HUGGING FACE — model weight downloads", "", (
            ("HF_TOKEN", "", (
                "SECRET, optional but strongly recommended. Unauthenticated Hub pulls are",
                "throttled to ~0.4 MB/s (S3b blocker #2), and huggingface_hub does NOT resume",
                "across restarts — so a slow pull must still be one uninterrupted run.",
            )),
        )),
    ]),
    ("DATA", [
        ("POSTGRES — system of record (D1)", "localhost:5001 · pgAdmin / psql", (
            ("POSTGRES_PORT", "5001", ("Host port; the container listens on 5432.",)),
            ("POSTGRES_DB", "medbot", ("Application database: sessions, chat history, audit.",)),
            ("POSTGRES_USER", "medbot", ()),
            ("POSTGRES_PASSWORD", "medbot", ("SECRET (local dev value).",)),
            ("LANGFUSE_POSTGRES_DB", "langfuse", (
                "Langfuse's database on the SAME server — one container, one backup story.",
                "Created by infra/postgres/init/ on FIRST boot only (empty volume).",
            )),
            ("DATABASE_URL", "postgresql+asyncpg://medbot:medbot@postgres:5432/medbot", (
                "What the API actually connects with. `postgres` is the compose service name;",
                "use localhost:5001 when running the API on the host.",
                "EMPTY = history/session persistence disabled and the app still answers (D21) —",
                "which is why it is REQUIRED outside local: silent degradation is the hazard.",
            )),
            ("DB_POOL_SIZE", "10", ()),
            ("DB_MAX_OVERFLOW", "20", ()),
            ("HISTORY_RETENTION_DAYS", "30", ("GDPR (D18). Enforced by dropping day partitions.",)),
            ("HISTORY_MAX_TURNS", "20", ()),
            ("POSTGRES_CIRCUIT_FAILURE_THRESHOLD", "3", (
                "Losing Postgres DEGRADES the service (history off) rather than stopping it,",
                "so the breaker exists to stop hammering a dead database, not to fail requests.",
            )),
            ("POSTGRES_CIRCUIT_COOLDOWN_SECONDS", "30", ()),
        )),
        ("QDRANT — vector store (D2, D11)", "http://localhost:5002/dashboard", (
            ("QDRANT_HTTP_PORT", "5002", ("REST + dashboard; container listens on 6333.",)),
            ("QDRANT_GRPC_PORT", "5003", ("Container listens on 6334.",)),
            ("QDRANT_URL", "http://qdrant:6333", (
                "Use http://localhost:5002 when running the API on the",
                "host.",
            )),
            ("QDRANT_COLLECTION", "gale_live", (
                "This is an ALIAS, not a collection (D11). Ingestion builds gale_live_v1,",
                "gale_live_v2 ... and repoints the alias ATOMICALLY on success, so readers",
                "never see a half-ingested corpus and rollback is one alias operation.",
                "The API only ever VERIFIES it — creating it here would take the name the",
                "alias needs and permanently break the swap (P6.3.5).",
            )),
            ("CHUNK_SIZE", "500", ()),
            ("CHUNK_OVERLAP", "50", ()),
        )),
        ("REDIS — cache + quotas (D10, D20)", "localhost:5004 · RedisInsight", (
            ("REDIS_PORT", "5004", ("Container listens on 6379.",)),
            ("REDIS_URL", "redis://redis:6379/0", (
                "EMPTY = caching off AND rate limiting falls back to PER-REPLICA in-process",
                "counters, so the effective limit becomes N x the configured one. Required",
                "outside local for exactly that reason (P5.2.9).",
            )),
            ("REDIS_MAXMEMORY", "256mb", ()),
            ("CACHE_TTL_SECONDS", "86400", (
                "Response cache entries. Version keys invalidate; TTL only",
                "bounds growth.",
            )),
            ("EMBEDDING_CACHE_TTL_SECONDS", "604800", (
                "Embeddings are deterministic for a given model, so they",
                "live longer.",
            )),
            ("SEMANTIC_CACHE_ENABLED", "false", (
                "OFF, and measured (S19.4 / docs/SEMANTIC_CACHE.md). The premise was tested and",
                "REFUTED: across 23,005 golden pairs the max similarity was 0.8541 — nothing",
                "reached the safe 0.95 threshold, so a safe setting is inert, while a useful",
                "one leaves 0.007 of margin against clinically different questions.",
            )),
            ("SEMANTIC_CACHE_THRESHOLD", "0.97", (
                "Only meaningful if the flag above is ever turned",
                "on.",
            )),
            ("REDIS_SOCKET_TIMEOUT", "2.0", (
                "Seconds. Redis is a cache: waiting on it must never",
                "dominate a request.",
            )),
            ("REDIS_POOL_TIMEOUT", "2.0", (
                "Seconds to wait for a pooled connection before",
                "giving up.",
            )),
            ("REDIS_CIRCUIT_FAILURE_THRESHOLD", "3", (
                "Redis loss is fail-OPEN: bypass the cache, keep",
                "answering.",
            )),
            ("REDIS_CIRCUIT_COOLDOWN_SECONDS", "30", ()),
            ("REDIS_MAX_CONNECTIONS", "128", (
                "BOUNDED pool with a WAIT. The default pool errors the moment every connection",
                "is checked out, which under burst turned a 2ms cache lookup into a storm of",
                "MaxConnectionsError and took the process down at 1500 RPS (P5.2.6).",
            )),
        )),
        ("LOCALSTACK — SQS for the ingestion worker (D11)", "http://localhost:5005", (
            ("LOCALSTACK_PORT", "5005", ()),
            ("AWS_ENDPOINT_URL", "http://localstack:4566", ("EMPTY = talk to real AWS instead.",)),
            ("AWS_REGION", "us-east-1", ()),
            ("AWS_ACCESS_KEY_ID", "test", (
                "[infra] boto3 reads this straight from the environment, so no Settings",
                "field names it and no grep finds it. LocalStack accepts anything; real",
                "AWS does not.",
            )),
            ("AWS_SECRET_ACCESS_KEY", "test", ("[infra] SECRET. Read by boto3, same as above.",)),
            ("SQS_QUEUE_URL", "", (
                "Empty = the worker has no queue and exits rather than",
                "idling.",
            )),
            ("WORKER_POLL_SECONDS", "20", ("SQS long-poll maximum.",)),
            ("WORKER_VISIBILITY_TIMEOUT", "900", ()),
            ("WORKER_MAX_RECEIVES", "3", ("Then the message goes to the DLQ.",)),
        )),
    ]),
    ("OBSERVABILITY", [
        ("OTEL COLLECTOR — traces in, tail-sampled, out to Jaeger", "localhost:5011 / 5012", (
            ("OTEL_ENABLED", "true", (
                "false = the app still creates spans and simply does not",
                "export them.",
            )),
            ("OTEL_HTTP_PORT", "5011", ("OTLP/HTTP; container listens on 4318.",)),
            ("OTEL_GRPC_PORT", "5012", ("OTLP/gRPC; container listens on 4317.",)),
            ("OTEL_ENDPOINT", "http://otel-collector:4318", ()),
            ("OTEL_SERVICE_NAME", "medbot-api", ("Stamped on every span.",)),
            ("OTEL_SAMPLE_RATIO", "1.0", (
                "SDK HEAD sampling. Keep this at 1.0: the Collector does TAIL sampling, and",
                "it can only decide about traces it actually receives.",
                "",
                "MEASURED at 0.05: Jaeger showed a 'trace' containing ONE span (rerank,",
                "1205ms) with no parent HTTP span. Head sampling does not give you 5% of",
                "whole traces — it drops individual spans and leaves ORPHAN FRAGMENTS, so",
                "the collector's 'keep 100% of errors and slow requests' policy silently",
                "cannot apply to what never arrived.",
                "",
                "Send everything, let the Collector decide. That is the entire point of",
                "putting tail_sampling in otel-collector.yaml.",
            )),
        )),
        ("JAEGER — distributed trace UI", "http://localhost:5023", (
            ("JAEGER_UI_PORT", "5023", (
                "Where a slow request is diagnosed: the span tree across",
                "HTTP -> embed -> retrieve -> rerank -> generate.",
                "Complements Langfuse rather than duplicating it — Langfuse answers what the",
                "model saw and what it cost, Jaeger answers where the time went.",
            )),
        )),
        ("PROMETHEUS — metrics + alert rules", "http://localhost:5013/targets", (
            ("PROMETHEUS_PORT", "5013", ("No auth locally.",)),
        )),
        ("OPEN WEBUI — chat straight at the engines", "http://localhost:5024", (
            ("OPEN_WEBUI_PORT", "5024", (
                "A ChatGPT-style UI wired to vLLM and SGLang, with a model picker to switch",
                "between them on the same prompt.",
                "",
                "This is the UNGUARDED path, on purpose: no retrieval, no citations, no",
                "medical guardrails. It answers 'is the engine generating sensible text',",
                "which curl cannot. The product UI on :5008 is the guarded one.",
            )),
        )),
        ("GRAFANA — dashboards", "http://localhost:5014", (
            ("GRAFANA_PORT", "5014", ()),
            ("GRAFANA_ADMIN_USER", "admin", ()),
            ("GRAFANA_ADMIN_PASSWORD", "admin", ("SECRET (local dev value).",)),
            ("GRAFANA_ANONYMOUS", "true", (
                "true = open the dashboards with NO login. Anonymous is Viewer, never Admin,",
                "so a stray click cannot edit a provisioned dashboard. Local-only convenience.",
            )),
        )),
        ("LANGFUSE — LLM traces (prompts, completions, cost)", "http://localhost:5015", (
            ("LANGFUSE_WEB_PORT", "5015", ()),
            ("LANGFUSE_PUBLIC_KEY", "pk-lf-medbot-local", (
                "The API sends traces with these. They are also what Langfuse is BOOTSTRAPPED",
                "with below, which is what makes tracing work with no manual key copying.",
            )),
            ("LANGFUSE_SECRET_KEY", "sk-lf-medbot-local", ("SECRET.",)),
            ("LANGFUSE_HOST", "http://langfuse:3000", (
                "Use http://localhost:5015 from the",
                "host.",
            )),
            ("LANGFUSE_INIT_ORG_ID", "medbot-local", (
                "HEADLESS BOOTSTRAP. Langfuse creates the org, project and user, and PINS the",
                "API keys to the values above, on first boot of an EMPTY database.",
                "A warm start ignores these, so changing a key needs `make downv` to take.",
            )),
            ("LANGFUSE_INIT_ORG_NAME", "Medbot Local", ()),
            ("LANGFUSE_INIT_PROJECT_ID", "medbot", ()),
            ("LANGFUSE_INIT_PROJECT_NAME", "Medical RAG Chatbot", ()),
            ("LANGFUSE_INIT_USER_EMAIL", "admin@medbot.local", (
                "Log in with this if you want the",
                "UI.",
            )),
            ("LANGFUSE_INIT_USER_NAME", "Medbot Admin", ()),
            ("LANGFUSE_INIT_USER_PASSWORD", "medbot-admin-1234", ("SECRET (local dev value).",)),
            ("LANGFUSE_NEXTAUTH_SECRET", "langfuse-dev-secret-change-me", ("SECRET.",)),
            ("LANGFUSE_SALT", "langfuse-dev-salt-change-me", ("SECRET.",)),
            ("LANGFUSE_ENCRYPTION_KEY", "0" * 64, (
                "SECRET. Required by Langfuse v3: exactly 64 hex chars (32 bytes).",
                "Generate: openssl rand -hex 32",
            )),
            # v3 splits ingestion from serving, so Langfuse needs its own columnar store
            # and blob store. These back the trace pipeline, not the app.
            ("LANGFUSE_CLICKHOUSE_PASSWORD", "clickhouse", ("SECRET (local dev value).",)),
            ("LANGFUSE_MINIO_ROOT_USER", "minioadmin", ()),
            ("LANGFUSE_MINIO_ROOT_PASSWORD", "minioadmin", ("SECRET (local dev value).",)),
            ("LANGFUSE_MINIO_CONSOLE_PORT", "5025", ("MinIO console UI.",)),
        )),
        ("REDISINSIGHT — Redis GUI, databases pre-registered", "http://localhost:5022", (
            ("REDISINSIGHT_PORT", "5022", ()),
            ("REDISINSIGHT_DATABASES", "medbot-cache|redis|6379", (
                "name|host|port, comma-separated for more than one. A seeder registers these",
                "on startup so nothing is added by hand. Idempotent: it checks before adding.",
                "Langfuse v2 uses Postgres only and so has no Redis to register here.",
            )),
        )),
    ]),
    ("COST, SAFETY AND AUTH", [
        ("COST CONTROLS + KILL SWITCH (D20)", "", (
            ("LLM_ENABLED", "true", (
                "false = COST KILL SWITCH: serve cache/degraded, make no",
                "provider calls.",
            )),
            ("CACHE_ONLY_MODE", "false", (
                "true = degraded mode. The spend breaker flips this",
                "automatically.",
            )),
            ("LLM_MAX_INPUT_TOKENS", "3000", ()),
            ("LLM_MAX_OUTPUT_TOKENS", "512", ()),
            ("DAILY_SPEND_LIMIT_USD", "5.0", (
                "Hard breaker: at 100% the service flips to",
                "CACHE_ONLY_MODE.",
            )),
            ("SPEND_SOFT_ALERT_RATIO", "0.5", (
                "Fraction of the daily limit that raises a",
                "warning.",
            )),
        )),
        ("RATE LIMITS - per session and per IP (D20)",
         "a 429 is enforcement working, not an outage", (
            ("RATE_LIMIT_PER_MINUTE", "20", ("Per anonymous session.",)),
            ("RATE_LIMIT_PER_DAY", "200", ("Per anonymous session.",)),
            ("RATE_LIMIT_IP_PER_MINUTE", "60", (
                "Per IP, so rotating session cookies does not multiply the allowance.",
                "Only trustworthy if TRUSTED_PROXY_HOPS is set correctly.",
            )),
            ("RATE_LIMIT_IP_PER_DAY", "1000", ()),
        )),
        ("CACHE INVALIDATION — version-key composition (D10)", "", (
            ("PROMPT_VERSION", "v1", ("Bump to invalidate; never purge by hand.",)),
            ("CORPUS_VERSION", "v1", ("Bump after a re-ingest.",)),
            ("INDEX_VERSION", "v1", ("Bump after an embedding-model change.",)),
        )),
        ("CLERK — optional user auth (D24)", "", (
            ("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "", (
                "All EMPTY = Clerk genuinely off: no provider, no Clerk JavaScript loaded, no",
                "sign-in button, and the backend uses DisabledVerifier. Conversations still",
                "work, owned by the anonymous session instead of a user.",
            )),
            ("CLERK_SECRET_KEY", "", ("SECRET.",)),
            ("CLERK_JWKS_URL", "", (
                "Empty = auth fails CLOSED for presented tokens, never a",
                "silent downgrade.",
            )),
            ("CLERK_ISSUER", "", ()),
            ("CLERK_AUDIENCE", "", ()),
        )),
    ]),
]

HEADER = """# ============================================================================
#  P5 Medical RAG Chatbot - environment
# ============================================================================
#
#  GENERATED FILE. Edit scripts/gen_env.py and re-run it; hand edits to layout
#  are overwritten. VALUES are preserved when regenerating .env.
#
#  Layout rules, both enforced by the generator:
#    1. One boxed section per SERVICE - everything that service needs is together.
#    2. Comments sit ABOVE their variable, never trailing. `PORT=5001  # note` is
#       parsed differently by python-dotenv, a shell `source`, and everything else;
#       this repo has already been bitten by it once.
#
#  Host ports are grouped by tier: data 5001-5005, app 5006-5008,
#  inference 5009-5010, observability 5011-5023. Only HOST ports are remapped -
#  container ports stay standard, which is why an in-network URL says
#  `postgres:5432` while a host URL says `localhost:5001`.
#
#  See every URL:            make urls
#  See URLs + credentials:   make service_ls
# ============================================================================
"""

BOX = 74


def render(values: dict[str, str] | None = None) -> str:
    """Render the file. `values` overrides example values (used to preserve .env)."""
    out: list[str] = [HEADER]
    for tier_name, sections in TIERS:
        out.append("")
        out.append("# " + "#" * BOX)
        out.append(f"# ##  {tier_name}".ljust(BOX) + "##")
        out.append("# " + "#" * BOX)
        for title, subtitle, variables in sections:
            out.append("")
            # Border is "# +" + BOX dashes + "+"  = BOX + 4 chars.
            # Content is "# | " + text + padding + "|", so the pad target is BOX + 3.
            out.append("# +" + "-" * BOX + "+")
            out.append(f"# | {title}".ljust(BOX + 3) + "|")
            if subtitle:
                out.append(f"# | {subtitle}".ljust(BOX + 3) + "|")
            out.append("# +" + "-" * BOX + "+")
            for key, example, comments in variables:
                for line in comments:
                    out.append(f"# {line}".rstrip())
                if values is None:
                    value = example
                else:
                    value = values.get(key, example)
                    if not value and key in FILL_IF_EMPTY:
                        value = example
                out.append(f"{key}={value}")
    out.append("")
    return "\n".join(out)


# Keys where an EMPTY existing value must NOT win over the spec default.
#
# `--write-env` preserves what is already in .env, which is right for anything the operator
# supplies. It is wrong for local BOOTSTRAP identifiers: the Langfuse keys are not secrets
# you obtain from anywhere, they are arbitrary strings that must simply MATCH on both sides
# (the container is initialised with them, the API sends them). Preserving a blank left
# tracing silently off while every container reported healthy — the failure this whole
# section exists to prevent.
#
# Deliberately NOT here: OPENAI_API_KEY, VLLM_RUNPOD_URL and friends, where empty carries
# real meaning ("skip this leg") and filling it in would fabricate configuration.
FILL_IF_EMPTY = {
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_INIT_ORG_ID",
    "LANGFUSE_INIT_PROJECT_ID",
    "LANGFUSE_INIT_USER_EMAIL",
    "LANGFUSE_INIT_USER_PASSWORD",
    "LANGFUSE_NEXTAUTH_SECRET",
    "LANGFUSE_SALT",
    "LANGFUSE_ENCRYPTION_KEY",
    "LANGFUSE_CLICKHOUSE_PASSWORD",
    "LANGFUSE_MINIO_ROOT_USER",
    "LANGFUSE_MINIO_ROOT_PASSWORD",
    "SESSION_SECRET",
    # An empty OTEL_ENDPOINT means spans are created and exported NOWHERE. Jaeger then
    # shows an empty trace list forever while every container reports healthy — the
    # failure mode Jaeger was added to remove, reproduced one layer down.
    "OTEL_ENDPOINT",
}


def parse_values(path: Path) -> dict[str, str]:
    """Existing KEY=VALUE pairs, with trailing comments stripped the dotenv way."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"^\s*([A-Z][A-Z0-9_]*)\s*=(.*)$", line)
        if not match:
            continue
        key, raw = match.group(1), match.group(2).strip()
        if raw and not raw.startswith(('"', "'")):
            cut = raw.find(" #")
            if cut != -1:
                raw = raw[:cut].rstrip()
        values[key] = raw
    return values


def missing_from_spec() -> list[str]:
    """Settings fields the spec does not document.

    This exists because generating the file WITHOUT it silently dropped 16 live settings
    (rate limits, cache TTLs, circuit breakers) on the first run — they simply vanished
    from .env and fell back to code defaults, which is a change nobody asked for and
    nothing would have reported. A generator that can quietly delete configuration is
    worse than the two hand-edited files it replaced.
    """
    try:
        from medcore.config import Settings
    except Exception:  # noqa: BLE001 - the check is best-effort outside the venv
        return []
    documented = {k for _, sections in TIERS for _, _, v in sections for k, _, _ in v}
    # EMBEDDING_DIM is deliberately absent: it is Literal[1024] and cannot be set from an
    # env string at all (it broke 18 tests when it was). Changing the dimension means a new
    # collection and a full re-embed, not an edit here.
    exempt = {"EMBEDDING_DIM"}
    return sorted({f.upper() for f in Settings.model_fields} - documented - exempt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="rewrite .env.example")
    parser.add_argument("--write-env", action="store_true", help="rewrite .env, keeping values")
    parser.add_argument("--check", action="store_true", help="fail if .env.example is stale")
    args = parser.parse_args()

    example_path = REPO / ".env.example"
    env_path = REPO / ".env"
    example = render()

    gaps = missing_from_spec()
    if gaps:
        print(f"SPEC GAP: {len(gaps)} Settings field(s) undocumented: {', '.join(gaps)}",
              file=sys.stderr)
        print("Add them to TIERS in this file; regenerating without them DELETES them "
              "from .env.", file=sys.stderr)
        return 1

    if args.check:
        current = example_path.read_text(encoding="utf-8") if example_path.is_file() else ""
        if current != example:
            print("STALE: .env.example does not match scripts/gen_env.py", file=sys.stderr)
            print("Run: python scripts/gen_env.py --write", file=sys.stderr)
            return 1
        print(".env.example is up to date")
        return 0

    if args.write:
        example_path.write_text(example, encoding="utf-8")
        print(f"wrote {example_path}")

    if args.write_env:
        existing = parse_values(env_path)
        # A key the spec no longer lists is DROPPED on purpose: that is how
        # NEXT_PUBLIC_API_URL (read by nothing) stops travelling forward.
        known = {k for _, sections in TIERS for _, _, v in sections for k, _, _ in v}
        dropped = sorted(set(existing) - known)
        if env_path.is_file():
            backup = env_path.parent / ".env.bak"
            backup.write_text(env_path.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"backup -> {backup}")
        env_path.write_text(render(existing), encoding="utf-8")
        print(f"wrote {env_path} (values preserved)")
        if dropped:
            print(f"dropped {len(dropped)} key(s) nothing reads: {', '.join(dropped)}")

    if not (args.write or args.write_env):
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
