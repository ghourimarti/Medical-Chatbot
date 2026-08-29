"""Typed, fail-fast configuration (Decision 17).

demo/ reads `os.environ.get("GROQ_API_KEY")` at import time. Missing key => `None` =>
the app boots "successfully" and dies on the first user request. Here, a missing or
malformed setting raises at construction: the process refuses to start. Deploy-time
error, not 3 a.m. pager.

Nothing outside this module may read os.environ.
"""

from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# DECISION GATE B (locked, D5 v2.1): bge-large-en-v1.5 => 1024 dims.
# This constant is baked into the Qdrant collection schema and every stored vector.
# Changing it = new collection + full re-embed. It is the most expensive-to-reverse
# constant in the repo, which is why it is a Literal, not an int.
EMBEDDING_DIM: Literal[1024] = 1024

Environment = Literal["local", "dev", "staging", "prod"]

# Recognisable on sight, and rejected outside `local` by Settings._reject_dev_secrets.
DEV_SESSION_SECRET = "dev-only-insecure-session-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    environment: Environment = "local"
    log_level: str = "INFO"

    # --- Serving venues (D4b). Every venue speaks the SAME OpenAI-compatible protocol, so
    # one adapter serves all of them; only base_url, model id and key differ. ---
    # An ORDERED PREFERENCE LIST. The first reachable leg answers; the rest are tried in
    # order; a leg whose URL is empty is skipped, so the chain can name venues whose
    # accounts do not exist yet.
    #
    # Each entry is `venue` or `venue-engine`:
    #     local-vllm,local-sglang,openai,groq
    # A bare GPU venue (`local`) uses SERVING_ENGINE as its engine, which is what keeps
    # older chains working unchanged.
    #
    # WHY A LIST AND NOT PRIORITY NUMBERS: numbers put identity and order in two places
    # that can disagree, and inserting a leg means renumbering the rest. The list is the
    # order, so there is nothing to keep in sync.
    #
    # WHAT THE ORDER SHOULD RESPECT: legs are only outage protection when they fail
    # INDEPENDENTLY. local-vllm -> local-sglang covers an ENGINE fault (a crash, an OOM
    # regression, a bad build) but not a dead GPU or a dead box — both legs share those.
    # Independence starts at the hosted legs, so keep at least one of them last.
    serving_chain: str = "groq,openai"
    # Default engine for a chain entry that does not name one.
    serving_engine: Literal["vllm", "sglang"] = "sglang"
    circuit_failure_threshold: int = Field(default=3, ge=1)
    circuit_cooldown_seconds: float = Field(default=30.0, ge=1.0)

    vllm_local_url: str = "http://localhost:5009/v1"
    vllm_local_model: str = "Qwen/Qwen2.5-7B-Instruct-AWQ"
    vllm_runpod_url: str = ""
    vllm_runpod_model: str = "Qwen/Qwen2.5-7B-Instruct-AWQ"
    vllm_aws_url: str = ""
    vllm_aws_model: str = "Qwen/Qwen2.5-7B-Instruct-AWQ"

    # SGLang endpoints for the same three GPU venues.
    #
    # S13.7 made `serving_engine` an either/or SELECTOR: you could run vLLM or SGLang,
    # never "vLLM, and if the engine faults, SGLang". D12 v2.1 had actually asked for the
    # second thing — SGLang as ENGINE-LEVEL failover — so the chain now accepts
    # `venue-engine` entries and `local-vllm,local-sglang` is expressible.
    #
    # The failure-domain caveat still holds and is why the ORDER matters: those two legs
    # share a GPU and a box, so the pair survives an engine crash or an OOM regression and
    # nothing else. It is not outage protection. Keep a hosted leg last for that.
    #
    # Local default tracks SGLANG_LOCAL_PORT in .env.example (5010), NOT the 1111 in
    # docs/benchmarks/vllm-vs-sglang.md — the ports were renumbered after S14 (vLLM moved
    # 1110 -> 5009 at the same time) and the benchmark doc still shows the old run.
    # runpod/aws stay empty: an unconfigured venue is SKIPPED, never an error.
    sglang_local_url: str = "http://localhost:5010/v1"
    sglang_local_model: str = "Qwen/Qwen2.5-7B-Instruct-AWQ"
    sglang_runpod_url: str = ""
    sglang_runpod_model: str = "Qwen/Qwen2.5-7B-Instruct-AWQ"
    sglang_aws_url: str = ""
    sglang_aws_model: str = "Qwen/Qwen2.5-7B-Instruct-AWQ"

    groq_base_url: str = "https://api.groq.com/openai/v1"

    # --- LLM providers (D4: self-host primary lands in S13; hosted is the outage leg) ---
    groq_api_key: SecretStr
    # MODEL DEPRECATION (S19, 2026-08). Groq removed the entire Llama family from this
    # account: llama-3.1-8b-instant and llama-3.3-70b-versatile both return 404
    # ("does not exist or you do not have access"). They worked in S6.10.
    #
    # This is the failure mode that pinning model IDs makes MANAGEABLE but cannot
    # prevent: with a hosted API the vendor can retire the pin underneath you. The
    # self-hosted vLLM venue (D4b `local`) has no such exposure — its weights are a
    # file we hold — which is a real argument for the multi-venue design beyond
    # outage protection.
    #
    # Replacements chosen by measurement, not availability: qwen/qwen3.6-27b also
    # works but emits <think> reasoning preambles that corrupt structured output.
    groq_default_model: str = "openai/gpt-oss-20b"
    groq_escalation_model: str = "openai/gpt-oss-120b"
    # OpenAI is a real chain venue, not just a spare key. Before this it was config that
    # NOTHING read (the same dead-config shape as serving_engine in S13.7 and
    # semantic_cache_enabled in S19.4): you could set OPENAI_API_KEY, see it in .env, and
    # never have it serve a single token.
    openai_api_key: SecretStr | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_fallback_model: str = "gpt-4o-mini"
    groq_timeout: float = 10.0

    # --- Embeddings (D5) ---
    embedding_model_id: str = "BAAI/bge-large-en-v1.5"
    embedding_dim: Literal[1024] = EMBEDDING_DIM
    reranker_model_id: str = "BAAI/bge-reranker-base"
    rerank_timeout: float = 2.0
    # Empty => run the models in-process (dev/tests). Set => call apps/ml-service over
    # HTTP, so CPU work scales on its own deployment (D22). One config line switches it.
    ml_service_url: str = ""
    embed_timeout: float = 5.0
    # torch = reference implementation; onnx = ONNX Runtime (S5.9), required to meet the
    # 250ms retrieval NFR — measured: candidate reduction alone cannot get there.
    ml_backend: Literal["torch", "onnx"] = "torch"

    # --- Retrieval (D3) ---
    retrieval_top_k: int = Field(default=20, ge=1, le=100)
    rerank_top_k: int = Field(default=4, ge=1, le=20)
    # Threshold applies to the SIGMOID-normalized cross-encoder score (0..1) once reranking
    # is on. Dense cosine and cross-encoder logits are different scales — the sigmoid in
    # adapters/reranker.py is what makes one threshold meaningful for both.
    no_answer_threshold: float = Field(default=0.30, ge=0.0, le=1.0)
    # Budget for the follow-up rewrite. A standalone question is a SENTENCE, so this is
    # a ceiling on a model that ignores the instruction and starts answering instead -
    # not a target. Small on purpose: condense runs before retrieval, so every token
    # here is added directly to time-to-first-token.
    condense_max_tokens: int = Field(default=64, ge=16, le=256)
    hybrid_search: bool = True  # dense + BM25 with server-side RRF fusion (D3)

    # --- Vector store (D2, D11) ---
    qdrant_url: str = "http://localhost:5002"
    # The app queries an ALIAS, never a collection name. Ingestion builds a new collection
    # and repoints the alias atomically, so readers never see a half-ingested corpus.
    #
    # NAMING: the alias is `gale_live`; ingestion creates `gale_live_v1`, `gale_live_v2`...
    # A distinct alias name is not cosmetic — Qdrant forbids an alias and a collection
    # sharing a name, and `gale_live` reads unambiguously as "whatever is currently live".
    qdrant_collection: str = "gale_live"
    chunk_size: int = Field(default=500, ge=100, le=4000)
    chunk_overlap: int = Field(default=50, ge=0, le=1000)

    # --- Ingestion queue (D11) ---
    sqs_queue_url: str = ""
    aws_endpoint_url: str = ""  # set for LocalStack; empty = real AWS
    aws_region: str = "us-east-1"
    worker_poll_seconds: int = Field(default=20, ge=1, le=20)  # SQS long-poll maximum
    worker_visibility_timeout: int = Field(default=900, ge=30)
    worker_max_receives: int = Field(default=3, ge=1)  # then -> DLQ

    # --- Primary database (D1). Empty => history/session persistence disabled, the app
    # still answers (D21 degradation: chat works, it just doesn't remember). ---
    database_url: str = ""
    db_pool_size: int = 10
    db_max_overflow: int = 20
    history_retention_days: int = Field(default=30, ge=1, le=3650)  # GDPR (D18)
    history_max_turns: int = Field(default=20, ge=1, le=100)

    # --- Sessions (D9). The dev default keeps local runs and tests frictionless; the
    # validator below makes it IMPOSSIBLE to ship to prod. demo/ used os.urandom(24),
    # which invalidated every session on restart and on every added replica. ---
    session_secret: SecretStr = SecretStr(DEV_SESSION_SECRET)
    secure_cookies: bool = False  # True everywhere TLS terminates (dev/staging/prod)

    # --- Cache + quotas (D10, D20). Empty REDIS_URL => caching off, rate limiting falls
    # back to per-replica in-process counters (weaker, but never absent). ---
    redis_url: str = ""
    # Connection-pool shape (P5.2). The default pool errors immediately once every
    # connection is checked out, which under burst turns a 2ms cache lookup into a storm of
    # MaxConnectionsError — measured at 1500 RPS, where it took the process down. A BOUNDED
    # pool with a WAIT is the correct shape: bounded so we cannot exhaust Redis's own
    # client limit or our file descriptors, waiting so a burst becomes a few milliseconds
    # of queueing instead of a failure. Sized well above steady-state concurrency because
    # the pool should bind on pathology, not on normal traffic.
    redis_max_connections: int = Field(default=128, ge=1)
    redis_pool_timeout: float = Field(default=2.0, gt=0)
    # Without a socket timeout a wedged Redis holds every connection until TCP gives up
    # (minutes), so the pool drains and the fail-open path never runs. This is what makes
    # "Redis is slow" degrade into "the API is down".
    redis_socket_timeout: float = Field(default=2.0, gt=0)
    # Circuit breaker (P5.3). Threshold is low because Redis failures are not transient in
    # the way a network blip is — if it is down, it is down, and every additional attempt
    # costs a full socket timeout on a request that is already late. Cooldown is short
    # because the recovery measurement was ~5s and the cost of probing early is one slow
    # request, while the cost of probing late is a needlessly cold cache.
    redis_circuit_failure_threshold: int = Field(default=5, ge=1)
    redis_circuit_cooldown_seconds: float = Field(default=10.0, gt=0)
    # Postgres gets a LOWER threshold than Redis, and the reason is the general rule for
    # sizing a breaker: the threshold must be measured in REQUESTS, not in calls.
    #
    # A breaker's job is to stop the second slow request, so it should open after roughly
    # one request's worth of failures. Redis is called ~10x per request, so 5 opens partway
    # through the first one. Postgres is called TWICE (history load, history write), so the
    # same 5 needs ~3 requests — measured in P5.5: requests 1-5 took ~9s and only the 6th
    # and 7th dropped to the normal 5s. Copying Redis's number onto a dependency with a
    # different call rate silently produced a breaker that barely engaged.
    postgres_circuit_failure_threshold: int = Field(default=2, ge=1)
    postgres_circuit_cooldown_seconds: float = Field(default=15.0, gt=0)
    cache_ttl_seconds: int = Field(default=86_400, ge=60)
    embedding_cache_ttl_seconds: int = Field(default=604_800, ge=60)
    # D10 semantic cache: measured in S19.4 and DECLINED. These two knobs are the whole of
    # it — there is no SemanticCache class, and nothing else reads them. Kept so the
    # decision stays visible in config rather than silently vanishing.
    #
    # Measured (docs/SEMANTIC_CACHE.md): at 0.97 it is safe but inert — 0 false hits across
    # 23,005 golden pairs and 15 adversarial pairs, but it catches only 1 paraphrase in 12,
    # and exact-match caching already handles verbatim repeats. Reaching a useful catch
    # rate needs ~0.92, which sits 0.007 above a KNOWN dangerous pair ("maximum daily dose"
    # vs "minimum daily dose", 0.9133). The margin is thinner than the sampling error on
    # the danger estimate. D10's premise was also wrong: "aspirin dose adult" vs "child"
    # measures 0.8235, not "closer than 0.95".
    semantic_cache_enabled: bool = False
    semantic_cache_threshold: float = Field(default=0.97, ge=0.90, le=1.0)
    rate_limit_per_minute: int = Field(default=20, ge=1)
    rate_limit_per_day: int = Field(default=200, ge=1)
    # Per-IP ceiling (D18). Session-only limiting is BYPASSABLE: the session id comes from a
    # cookie the client chooses to send, so dropping it mints a fresh quota bucket on every
    # request. Measured in P5.2 — 30 cookieless requests against a 20/min limit produced
    # zero 429s. The IP bucket is the one an abuser cannot opt out of.
    #
    # It is deliberately MUCH higher than the session limit because carrier-grade NAT,
    # universities, and corporate proxies put thousands of legitimate users behind one
    # address; sized to throttle scripted abuse without cutting off a whole campus.
    rate_limit_ip_per_minute: int = Field(default=300, ge=1)
    rate_limit_ip_per_day: int = Field(default=20_000, ge=1)
    # Number of reverse proxies WE operate in front of the API. 0 = direct exposure, and
    # X-Forwarded-For is ignored entirely (it is client-supplied and spoofable). Behind an
    # ALB set 1; ALB + CloudFront set 2. Getting this wrong in either direction is a real
    # outage: too low collapses every user into the proxy's bucket, too high trusts a
    # header the client wrote.
    trusted_proxy_hops: int = Field(default=0, ge=0, le=4)

    # --- Cost controls / kill switch (D20) ---
    llm_enabled: bool = True  # static floor for the kill switch; false can't be undone at runtime
    cache_only_mode: bool = False
    # Daily ceiling. At the Phase-1 full-load target ($25k/mo) this is ~$830/day; the
    # portfolio deployment runs at ~$2/day, so the default is a safety net sized for
    # development, not production. 0 disables the breaker.
    daily_spend_limit_usd: float = Field(default=5.0, ge=0.0)
    spend_soft_alert_ratio: float = Field(default=0.5, gt=0.0, le=1.0)
    admin_api_key: SecretStr | None = None  # required to flip the kill switch

    # --- Accounts (D24, S20b). ALL OPTIONAL: with no JWKS URL, accounts are simply off and
    # the anonymous product works exactly as before. That is the D24 sequencing promise —
    # anonymous chat never waits on an identity provider being configured.
    clerk_jwks_url: str | None = None
    # Checked when set: a validly-signed token from a DIFFERENT Clerk instance is still not
    # a token for this application.
    clerk_issuer: str | None = None
    clerk_audience: str | None = None
    llm_max_input_tokens: int = 3000
    llm_max_output_tokens: int = 512

    # --- Tracing (D13, S15.6). Distinct from the Prometheus metrics of S11: metrics
    # answer "is the system healthy", traces answer "why was THIS request slow/bad".
    #
    # PII asymmetry is deliberate and load-bearing: OTel spans carry NO query text (they
    # fan out to collectors and vendors), while Langfuse is the ONE sanctioned store for
    # prompt/completion content (D18) — access-controlled, 30-day retention. ---
    otel_enabled: bool = False
    otel_endpoint: str = ""  # e.g. http://otel-collector:4318
    otel_service_name: str = "medbot-api"
    # HEAD sampling only. Keeping 100% of errors/slow requests is a TAIL decision and is
    # made in the Collector (tail_sampling processor), not here — the SDK cannot do it.
    # 4.5M queries/day at 100% would make tracing its own cost centre (D13).
    otel_sample_ratio: float = Field(default=0.05, ge=0.0, le=1.0)

    langfuse_public_key: str = ""
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "http://localhost:5015"

    # --- DECISION GATE C (locked, D10): cache invalidation is version-key composition.
    # Bump a version => old entries go cold. No code ever writes a manual purge. ---
    prompt_version: str = "v1"
    corpus_version: str = "v1"
    index_version: str = "v1"

    @property
    def cache_namespace(self) -> str:
        """Composite key prefix. Every cached value is scoped by the exact configuration
        that produced it, so a prompt or re-index bump can never serve a stale answer.

        `qdrant_collection` is part of the key (P5.5). It was not, and the gap was found by
        accident: pointing the service at a DIFFERENT, EMPTY collection still returned fully
        cited answers, because the cache key never mentioned which index produced them.

        The composition relied on an operator remembering to bump `index_version` whenever
        the collection changed. That is a convention, and the failure mode when it is
        forgotten is silent and wrong — answers served from an index the service is no
        longer using, with citations pointing into it. Including the collection name makes
        the invalidation automatic: change where you read from, and the cache follows.

        S19.5: the model component was `groq_default_model` — ONE venue's model, named
        unconditionally, even when Groq was last in the chain and never served a request.
        Two consequences, both silent:

          * changing VLLM_LOCAL_MODEL or SGLANG_LOCAL_MODEL did NOT change the key, so a
            model swap kept serving answers generated by the PREVIOUS model, with the new
            model's name on the response;
          * switching ENGINE=vllm <-> sglang reused each other's cached answers.

        That is the identical defect this docstring already describes for
        `qdrant_collection`, one line below the warning: the key did not mention what
        actually produced the answer. Now every model that COULD serve is folded in, so
        changing any of them invalidates automatically. Hashed because the full list is
        long and keys are read by humans in redis-cli.
        """
        candidates = "|".join((
            self.serving_chain,
            self.serving_engine,
            self.vllm_local_model,
            self.sglang_local_model,
            self.groq_default_model,
            self.openai_fallback_model,
        ))
        digest = hashlib.sha256(candidates.encode()).hexdigest()[:12]
        return (
            f"medbot:p{self.prompt_version}:c{self.corpus_version}"
            f":i{self.index_version}:q{self.qdrant_collection}"
            f":m{digest}"
        )

    @model_validator(mode="after")
    def _reject_retired_serving_vars(self) -> Self:
        """Fail on env vars that were renamed, instead of ignoring them (P6.4.3).

        `extra="ignore"` is right for the general case — the process should not care about
        unrelated environment — but it makes a RENAMED setting fail silently, which is the
        worst kind: SERVING_PRIMARY=local looks like it selects the GPU venue and does
        nothing at all, so the symptom is "my vLLM box is idle", far from the cause.
        Found when the in-cluster pod showed SERVING_PRIMARY unset while .env.example still
        advertised it. Retired names get a loud error naming their replacement.
        """
        retired = {
            "SERVING_PRIMARY": "SERVING_CHAIN",
            "SERVING_FALLBACK_CHAIN": "SERVING_CHAIN",
        }
        found = [f"{old} -> {new}" for old, new in retired.items() if os.environ.get(old)]
        if found:
            raise ValueError(
                "retired serving env var(s) set and would be silently ignored: "
                + "; ".join(found)
                + ". Use a single ordered SERVING_CHAIN (e.g. 'local,runpod,aws,groq')."
            )
        return self

    @model_validator(mode="after")
    def _reject_dev_secrets_outside_local(self) -> Self:
        """A default secret that works everywhere is a default secret that reaches prod.
        Local dev stays frictionless; any other environment must supply a real value."""
        if self.environment != "local":
            if self.session_secret.get_secret_value() == DEV_SESSION_SECRET:
                raise ValueError(
                    f"SESSION_SECRET must be set in environment={self.environment!r} "
                    "(the development default is refused outside 'local')"
                )
            if not self.secure_cookies:
                raise ValueError(
                    f"SECURE_COOKIES must be true in environment={self.environment!r}"
                )
            # Found in P5.2. An empty REDIS_URL is a legitimate local convenience, but it
            # degrades SILENTLY: caching turns off and rate limiting falls back to
            # per-replica in-process counters. With N replicas that means the effective
            # quota is N x the configured one and the cache hit rate collapses to ~1/N —
            # a capacity and abuse problem that shows up only under production traffic,
            # which is exactly when nobody is reading startup logs.
            if not self.redis_url:
                raise ValueError(
                    f"REDIS_URL must be set in environment={self.environment!r} "
                    "(without it quotas are per-replica and caching is disabled)"
                )
            # Found in P5.4, and the same silent-degradation class as REDIS_URL above —
            # which is the point: fixing one instance of a pattern and not auditing for
            # the others leaves the bug in place under a different name.
            #
            # An empty DATABASE_URL disables history entirely and the service still answers
            # perfectly, so nothing looks wrong. But Postgres is this system's only SYSTEM
            # OF RECORD: without it there is no chat history, no audit trail, and no
            # deletion capability for a GDPR request (D1, D9). For a medical assistant that
            # is a compliance failure that presents as a working service.
            if not self.database_url:
                raise ValueError(
                    f"DATABASE_URL must be set in environment={self.environment!r} "
                    "(without it there is no history, no audit trail, and no GDPR deletion)"
                )
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "prod"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor. Call once at process start (FastAPI lifespan) so a bad config
    fails the readiness probe rather than the first request."""
    return Settings()  # type: ignore[call-arg]  # values come from env/.env
