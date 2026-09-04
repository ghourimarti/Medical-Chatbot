"""Typed, fail-fast configuration.

A missing or malformed setting raises at construction, so the process refuses to start
instead of booting and dying on the first request.

Nothing outside this module reads os.environ.
"""

from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# bge-large-en-v1.5 => 1024 dims. Baked into the Qdrant collection schema and every stored
# vector, so changing it means a new collection and a full re-embed. Literal rather than
# int to make that hard to do by accident.
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

    # Serving venues. All of them speak the same OpenAI-compatible protocol, so one
    # adapter covers every leg; only base_url, model id and key differ.
    #
    # Ordered preference list: the first reachable leg answers, and a leg with an empty URL
    # is skipped, so the chain can name venues whose accounts do not exist yet. Entries are
    # `venue` or `venue-engine`, e.g. local-vllm,local-sglang,openai,groq. A bare venue
    # falls back to SERVING_ENGINE.
    #
    # Order matters: legs are only outage protection if they fail independently.
    # local-vllm -> local-sglang covers an engine crash or an OOM regression, but both legs
    # share a GPU and a box. Keep a hosted leg last.
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

    # SGLang endpoints for the same three GPU venues. `serving_engine` was originally an
    # either/or selector; the chain now takes `venue-engine` entries, which is what makes
    # vLLM-then-SGLang engine failover expressible.
    #
    # Local default tracks SGLANG_LOCAL_PORT in .env.example (5010), not the 1111 in
    # docs/benchmarks/vllm-vs-sglang.md. The ports were renumbered after that run (vLLM
    # moved 1110 -> 5009 at the same time) and the doc still shows the old ones.
    # runpod/aws stay empty; an unconfigured venue is skipped, not an error.
    sglang_local_url: str = "http://localhost:5010/v1"
    sglang_local_model: str = "Qwen/Qwen2.5-7B-Instruct-AWQ"
    sglang_runpod_url: str = ""
    sglang_runpod_model: str = "Qwen/Qwen2.5-7B-Instruct-AWQ"
    sglang_aws_url: str = ""
    sglang_aws_model: str = "Qwen/Qwen2.5-7B-Instruct-AWQ"

    groq_base_url: str = "https://api.groq.com/openai/v1"

    # --- LLM providers. Self-hosted is primary; hosted legs are the outage cover. ---
    groq_api_key: SecretStr
    # Groq dropped the whole Llama family from this account in 2026-08; both
    # llama-3.1-8b-instant and llama-3.3-70b-versatile return 404 now. Pinning model ids
    # makes that survivable but can't prevent it, which is part of why the self-hosted
    # venue is worth having: those weights are a file we hold.
    #
    # Replacements picked by measurement. qwen/qwen3.6-27b also works, but emits <think>
    # preambles that corrupt structured output.
    groq_default_model: str = "openai/gpt-oss-20b"
    groq_escalation_model: str = "openai/gpt-oss-120b"
    # OpenAI is a real chain venue. It used to be config nothing read: you could set
    # OPENAI_API_KEY, see it sitting in .env, and never have it serve a token.
    openai_api_key: SecretStr | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_fallback_model: str = "gpt-4o-mini"
    groq_timeout: float = 10.0

    # --- Embeddings ---
    embedding_model_id: str = "BAAI/bge-large-en-v1.5"
    embedding_dim: Literal[1024] = EMBEDDING_DIM
    reranker_model_id: str = "BAAI/bge-reranker-base"
    rerank_timeout: float = 2.0
    # Empty runs the models in-process (dev/tests); set calls apps/ml-service over HTTP,
    # so CPU work scales on its own deployment.
    ml_service_url: str = ""
    embed_timeout: float = 5.0
    # torch is the reference implementation; onnx is what actually meets the 250ms
    # retrieval budget. Trimming candidates alone doesn't get there.
    ml_backend: Literal["torch", "onnx"] = "torch"
    # Rerank backend, separate from the embedding one; empty inherits ml_backend.
    #
    # Separable because the risk isn't symmetric. Swapping the embedding backend changes
    # the vectors, which have to stay numerically compatible with everything already in
    # the index, so that flip is an index migration. Reranking only has to preserve score
    # order, so a faster runtime there costs nothing.
    #
    # Worth setting: rerank was ~1.5s of a ~2.3s TTFT on CPU, the largest single term.
    ml_rerank_backend: Literal["", "torch", "onnx"] = ""

    # --- Retrieval ---
    retrieval_top_k: int = Field(default=20, ge=1, le=100)
    rerank_top_k: int = Field(default=4, ge=1, le=20)
    # Applies to the sigmoid-normalized cross-encoder score (0..1) once reranking is on.
    # Dense cosine and cross-encoder logits are different scales; the sigmoid in
    # adapters/reranker.py is what lets one threshold cover both.
    no_answer_threshold: float = Field(default=0.30, ge=0.0, le=1.0)
    # Budget for the follow-up rewrite. A standalone question is one sentence, so this is
    # a ceiling for a model that ignores the instruction and starts answering, not a
    # target. Condense runs before retrieval, so every token here lands on TTFT.
    #
    # 256 rather than 64 because a reasoning model spends this same budget on its
    # reasoning and returns an empty string if the cap is small. 64 was fine for
    # Qwen2.5-7B and quietly stopped being fine when the serving chain changed.
    condense_max_tokens: int = Field(default=256, ge=16, le=512)
    hybrid_search: bool = True  # dense + BM25, server-side RRF fusion

    # --- Vector store ---
    qdrant_url: str = "http://localhost:5002"
    # The app queries an alias, never a collection name. Ingestion builds a new collection
    # and repoints the alias atomically, so readers never see a half-ingested corpus.
    #
    # Alias is `gale_live`; ingestion creates `gale_live_v1`, `gale_live_v2`... The names
    # have to differ anyway, since Qdrant won't let an alias and a collection share one.
    qdrant_collection: str = "gale_live"
    chunk_size: int = Field(default=500, ge=100, le=4000)
    chunk_overlap: int = Field(default=50, ge=0, le=1000)

    # --- Ingestion queue ---
    sqs_queue_url: str = ""
    aws_endpoint_url: str = ""  # set for LocalStack; empty = real AWS
    aws_region: str = "us-east-1"
    worker_poll_seconds: int = Field(default=20, ge=1, le=20)  # SQS long-poll maximum
    worker_visibility_timeout: int = Field(default=900, ge=30)
    worker_max_receives: int = Field(default=3, ge=1)  # then -> DLQ

    # --- Primary database. Empty disables history/session persistence; the app still
    # answers, it just doesn't remember. ---
    database_url: str = ""
    db_pool_size: int = 10
    db_max_overflow: int = 20
    history_retention_days: int = Field(default=30, ge=1, le=3650)
    history_max_turns: int = Field(default=20, ge=1, le=100)

    # --- Sessions. The dev default keeps local runs frictionless; the validator below
    # refuses it outside `local`. A random per-process secret would invalidate every
    # session on restart and give each replica its own. ---
    session_secret: SecretStr = SecretStr(DEV_SESSION_SECRET)
    secure_cookies: bool = False  # True everywhere TLS terminates (dev/staging/prod)

    # --- Cache + quotas. Empty REDIS_URL turns caching off and drops rate limiting back
    # to per-replica in-process counters: weaker, but never absent. ---
    redis_url: str = ""
    # Bounded pool that waits. The default pool raises as soon as every connection is
    # checked out, which turns a 2ms cache lookup into a storm of MaxConnectionsError under
    # burst; at 1500 RPS that took the process down. Bounded so we can't exhaust Redis's
    # client limit or our own fds, waiting so a burst costs a few ms of queueing instead of
    # a failure. Sized well above steady-state so it binds on pathology, not normal load.
    redis_max_connections: int = Field(default=128, ge=1)
    redis_pool_timeout: float = Field(default=2.0, gt=0)
    # Without a socket timeout a wedged Redis holds every connection until TCP gives up,
    # so the pool drains and the fail-open path never gets a chance to run. That is how
    # "Redis is slow" turns into "the API is down".
    redis_socket_timeout: float = Field(default=2.0, gt=0)
    # Low threshold: Redis failures aren't transient the way a network blip is, and each
    # extra attempt costs a full socket timeout on a request that is already late. Short
    # cooldown because recovery measured ~5s, and probing early costs one slow request
    # while probing late costs a needlessly cold cache.
    redis_circuit_failure_threshold: int = Field(default=5, ge=1)
    redis_circuit_cooldown_seconds: float = Field(default=10.0, gt=0)
    # Lower than Redis on purpose. A breaker should open after roughly one request's worth
    # of failures, so the threshold has to be counted in requests, not calls. Redis is hit
    # ~10x per request, so 5 opens partway through the first. Postgres is hit twice
    # (history load, history write), so 5 would need ~3 requests: measured, requests 1-5
    # took ~9s and only the 6th dropped back to 5s.
    postgres_circuit_failure_threshold: int = Field(default=2, ge=1)
    postgres_circuit_cooldown_seconds: float = Field(default=15.0, gt=0)
    cache_ttl_seconds: int = Field(default=86_400, ge=60)
    embedding_cache_ttl_seconds: int = Field(default=604_800, ge=60)
    # Semantic cache: measured and declined. These two knobs are all that is left of it,
    # kept so the decision stays visible in config instead of vanishing. There is no
    # SemanticCache class and nothing else reads them.
    #
    # Numbers in docs/SEMANTIC_CACHE.md. At 0.97 it is safe but inert: 0 false hits over
    # 23,005 golden pairs, but it catches 1 paraphrase in 12, and exact-match caching
    # already covers verbatim repeats. A useful catch rate needs ~0.92, which sits 0.007
    # above a known dangerous pair ("maximum daily dose" vs "minimum daily dose", 0.9133).
    # That margin is thinner than the sampling error on the danger estimate.
    semantic_cache_enabled: bool = False
    semantic_cache_threshold: float = Field(default=0.97, ge=0.90, le=1.0)
    rate_limit_per_minute: int = Field(default=20, ge=1)
    rate_limit_per_day: int = Field(default=200, ge=1)
    # Per-IP ceiling. Session-only limiting is bypassable: the session id comes from a
    # cookie the client chooses to send, so dropping it mints a fresh bucket every request.
    # Measured: 30 cookieless requests against a 20/min limit produced zero 429s.
    #
    # Much higher than the session limit, because carrier-grade NAT, universities and
    # corporate proxies put thousands of real users behind one address. Sized to throttle
    # scripted abuse without cutting off a campus.
    rate_limit_ip_per_minute: int = Field(default=300, ge=1)
    rate_limit_ip_per_day: int = Field(default=20_000, ge=1)
    # How many reverse proxies we operate in front of the API. 0 means direct exposure and
    # X-Forwarded-For is ignored entirely, since it is client-supplied. Behind an ALB set 1,
    # ALB + CloudFront set 2. Wrong in either direction hurts: too low collapses every user
    # into the proxy's bucket, too high trusts a header the client wrote.
    trusted_proxy_hops: int = Field(default=0, ge=0, le=4)

    # --- Cost controls / kill switch ---
    llm_enabled: bool = True  # static floor for the kill switch; false can't be undone at runtime
    cache_only_mode: bool = False
    # Daily ceiling; 0 disables the breaker. The default is sized for development (this
    # deployment runs ~$2/day), not for the full-load target.
    daily_spend_limit_usd: float = Field(default=5.0, ge=0.0)
    spend_soft_alert_ratio: float = Field(default=0.5, gt=0.0, le=1.0)
    admin_api_key: SecretStr | None = None  # required to flip the kill switch

    # --- Accounts, all optional. With no JWKS URL accounts are off and the anonymous
    # product works as before, so anonymous chat never waits on an identity provider.
    clerk_jwks_url: str | None = None
    # Checked when set: a validly-signed token from another Clerk instance is still not a
    # token for this application.
    clerk_issuer: str | None = None
    clerk_audience: str | None = None
    llm_max_input_tokens: int = 3000
    llm_max_output_tokens: int = 512

    # --- Tracing. Separate from the Prometheus metrics: metrics answer "is the system
    # healthy", traces answer "why was this request slow".
    #
    # The PII asymmetry is load-bearing. OTel spans carry no query text, because they fan
    # out to collectors and vendors. Langfuse is the only sanctioned store for prompt and
    # completion content: access-controlled, 30-day retention. ---
    otel_enabled: bool = False
    otel_endpoint: str = ""  # e.g. http://otel-collector:4318
    otel_service_name: str = "medbot-api"
    # Head sampling only. Keeping 100% of errors and slow requests is a tail decision,
    # made in the Collector's tail_sampling processor; the SDK can't do it. At full load
    # 100% sampling would make tracing its own cost centre.
    otel_sample_ratio: float = Field(default=0.05, ge=0.0, le=1.0)

    langfuse_public_key: str = ""
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "http://localhost:5015"

    # --- Cache invalidation is version-key composition: bump a version and old entries go
    # cold. Nothing anywhere writes a manual purge. ---
    prompt_version: str = "v1"
    corpus_version: str = "v1"
    index_version: str = "v1"

    @property
    def cache_namespace(self) -> str:
        """Composite key prefix, so every cached value is scoped by the configuration that
        produced it and a prompt or re-index bump can't serve a stale answer.

        Two things belong in here that are easy to leave out, both found the same way:

        `qdrant_collection`, because without it, pointing the service at a different and
        empty collection still returned fully cited answers. Relying on an operator to bump
        `index_version` by hand is a convention, and forgetting it is silent.

        Every model that could serve, not just the default one. Naming a single venue's
        model meant swapping VLLM_LOCAL_MODEL kept serving the previous model's answers
        under the new model's name, and switching engines reused each other's cache.

        Hashed because the full list is long and these keys get read by hand in redis-cli.
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
        """Fail on renamed env vars instead of ignoring them.

        `extra="ignore"` is right in general, but it makes a renamed setting fail silently:
        SERVING_PRIMARY=local looks like it selects the GPU venue and does nothing, so the
        symptom ("my vLLM box is idle") shows up a long way from the cause.
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
        """Local dev stays frictionless; every other environment supplies real values."""
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
            # An empty REDIS_URL is fine locally but degrades silently: caching off, rate
            # limiting back to per-replica counters. With N replicas the effective quota is
            # N x the configured one and hit rate collapses to ~1/N, which only shows up
            # under real traffic.
            if not self.redis_url:
                raise ValueError(
                    f"REDIS_URL must be set in environment={self.environment!r} "
                    "(without it quotas are per-replica and caching is disabled)"
                )
            # Same silent-degradation shape as REDIS_URL. An empty DATABASE_URL disables
            # history and the service still answers, so nothing looks wrong, but Postgres
            # is the only system of record here: no history, no audit trail, and no way to
            # honour a deletion request.
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
    """Cached accessor. Called once at startup so a bad config fails the readiness probe
    rather than the first user request."""
    return Settings()  # type: ignore[call-arg]  # values come from env/.env
