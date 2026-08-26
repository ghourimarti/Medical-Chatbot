"""Composition root. Singletons are built ONCE at startup and stored on app state, not
rebuilt per request (demo calls create_qa_chain() on every request — the bug this kills).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from medapi.adapters.embedder import BgeEmbedder
from medapi.adapters.failover import FailoverModel
from medapi.adapters.ml_client import HttpEmbedder, HttpReranker
from medapi.adapters.reranker import BgeReranker
from medapi.adapters.sparse import Bm25Encoder
from medapi.adapters.vector_store import QdrantVectorStore
from medapi.auth import AuthVerifier, build_verifier
from medapi.budget import KillSwitch, SpendTracker
from medapi.cache import EmbeddingCache, ResponseCache
from medapi.conversations import ConversationService
from medapi.db.engine import build_engine, build_session_factory
from medapi.history import HistoryService
from medapi.pipeline.rag import RagPipeline
from medapi.ratelimit import RateLimiter
from medapi.redis_guard import GuardedRedis
from medapi.session import SessionManager
from medapi.venues import build_failover_model
from medcore.config import Settings
from medcore.ports import EmbedderPort, RerankerPort


@dataclass(slots=True)
class Services:
    settings: Settings
    embedder: EmbedderPort
    store: QdrantVectorStore
    model: FailoverModel
    pipeline: RagPipeline
    history: HistoryService
    sessions: SessionManager
    cache: ResponseCache
    embedding_cache: EmbeddingCache
    limiter: RateLimiter
    spend: SpendTracker
    kill_switch: KillSwitch
    conversations: ConversationService | None = None
    verifier: AuthVerifier | None = None
    reranker: RerankerPort | None = None
    engine: AsyncEngine | None = None
    redis: Any | None = None


def build_services(settings: Settings) -> Services:
    # The port makes topology a config choice: HTTP service in deployment, in-process
    # for tests and single-process dev. Neither the pipeline nor its tests can tell.
    embedder: EmbedderPort
    reranker: RerankerPort | None = None
    if settings.ml_service_url:
        embedder = HttpEmbedder(
            settings.ml_service_url,
            settings.embedding_model_id,
            settings.embedding_dim,
            settings.embed_timeout,
        )
        reranker = HttpReranker(
            settings.ml_service_url, settings.reranker_model_id, settings.rerank_timeout
        )
    else:
        embedder = BgeEmbedder(settings.embedding_model_id, settings.embedding_dim)
        # In-process reranker so the pipeline ALWAYS reranks (D3). Without this, dev and
        # test runs would silently measure a non-reranked pipeline.
        reranker = BgeReranker(settings.reranker_model_id)
    sparse = Bm25Encoder() if settings.hybrid_search else None
    store = QdrantVectorStore(
        url=settings.qdrant_url,
        collection=settings.qdrant_collection,
        dimension=settings.embedding_dim,
    )
    # Multi-venue failover chain (D4b). GroqModel is gone: Groq is now simply one venue
    # in the chain, served by the same OpenAI-compatible adapter as vLLM and SGLang.
    model = build_failover_model(settings)
    pipeline = RagPipeline(
        settings=settings,
        embedder=embedder,
        store=store,
        model=model,
        reranker=reranker,
        sparse=sparse,
    )
    # No DATABASE_URL => history disabled, app still answers (D21). The same code path
    # serves local dev and a Postgres outage, so the fallback is exercised constantly.
    engine: AsyncEngine | None = None
    factory = None
    if settings.database_url:
        engine = build_engine(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
        )
        factory = build_session_factory(engine)
    # Redis is optional: caching off, rate limiting degrades to per-replica counters (D10).
    redis_client: Any | None = None
    if settings.redis_url:
        from redis.asyncio import BlockingConnectionPool, Redis

        # BlockingConnectionPool, not the default: when all connections are busy the
        # default raises MaxConnectionsError instantly, so a traffic burst becomes an error
        # storm rather than a queue. Blocking makes callers wait up to `timeout` for a free
        # connection — a burst costs milliseconds of latency instead of failed requests.
        # Measured in P5.2: the default pool produced 78% failures at 1500 RPS.
        # Wrapped in a circuit breaker (P5.3). Fail-open is per-call, and one request makes
        # ~10 Redis calls; with Redis DOWN each paid the full socket timeout, which took
        # measured latency from 2.0s to 20.4s. The breaker remembers, so an outage costs
        # ~0ms per call instead of 2s.
        redis_client = GuardedRedis(
            Redis(
                connection_pool=BlockingConnectionPool.from_url(
                    settings.redis_url,
                    max_connections=settings.redis_max_connections,
                    timeout=settings.redis_pool_timeout,
                    socket_timeout=settings.redis_socket_timeout,
                    socket_connect_timeout=settings.redis_socket_timeout,
                    health_check_interval=30,
                    decode_responses=False,
                )
            ),
            failure_threshold=settings.redis_circuit_failure_threshold,
            cooldown_seconds=settings.redis_circuit_cooldown_seconds,
        )

    verifier = build_verifier(settings)

    return Services(
        settings=settings,
        embedder=embedder,
        store=store,
        model=model,
        pipeline=pipeline,
        cache=ResponseCache(
            redis_client, settings.cache_namespace, settings.cache_ttl_seconds
        ),
        embedding_cache=EmbeddingCache(
            redis_client, settings.cache_namespace, settings.embedding_cache_ttl_seconds
        ),
        limiter=RateLimiter(redis_client, settings.cache_namespace),
        spend=SpendTracker(
            redis_client,
            settings.cache_namespace,
            daily_limit_usd=settings.daily_spend_limit_usd,
            soft_alert_ratio=settings.spend_soft_alert_ratio,
        ),
        kill_switch=KillSwitch(
            redis_client, settings.cache_namespace, env_enabled=settings.llm_enabled
        ),
        redis=redis_client,
        history=HistoryService(
            factory,
            max_turns=settings.history_max_turns,
            failure_threshold=settings.postgres_circuit_failure_threshold,
            cooldown_seconds=settings.postgres_circuit_cooldown_seconds,
        ),
        sessions=SessionManager(
            settings.session_secret.get_secret_value(),
            secure_cookies=settings.secure_cookies,
        ),
        reranker=reranker,
        engine=engine,
        # Accounts are OPTIONAL infrastructure: with no JWKS URL the verifier rejects any
        # token presented, and with no database the service reports itself disabled. Either
        # way the anonymous product is unaffected (D24 sequencing).
        #
        # ONE verifier, shared. Building it twice gave the readiness check and the request
        # path separate PyJWKClient instances, so each JWKS fetch happened twice and a key
        # rotation cost two cache misses instead of one. Worse, they could disagree: an
        # operator swapping one for a test would leave the other on the old config.
        verifier=verifier,
        conversations=ConversationService(factory, verifier),
    )
