"""FastAPI application factory and lifespan.

Lifespan builds the service singletons once, warms the embedder, and checks the Qdrant
collection exists at the configured dimension, so a misconfiguration fails startup and the
readiness probe rather than the first user request.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from sqlalchemy import text

from medapi.conversations import router as conversations_router
from medapi.db.partitions import ensure_future_partitions
from medapi.db.schema_sql import INITIAL_DDL
from medapi.deps import build_services
from medapi.errors import register_error_handlers
from medapi.observability import configure_logging
from medapi.observability.llm_trace import configure_llm_tracing
from medapi.observability.llm_trace import flush as flush_llm_traces
from medapi.observability.tracing import configure_tracing, instrument_app
from medapi.routes import router
from medcore.config import get_settings

logger = logging.getLogger("medapi")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    # JSON to stdout with PII redaction. Console renderer locally for
    # readability; structured everywhere a log aggregator will consume it.
    configure_logging(settings.log_level, json_output=settings.environment != "local")
    # Tracing is already configured in create_app() — it has to be, because ASGI
    # instrumentation must be attached before the middleware stack freezes. Repeating it
    # here would be harmless (configure_tracing is idempotent) but misleading: it would
    # suggest this is where tracing starts.
    configure_llm_tracing(
        public_key=settings.langfuse_public_key,
        secret_key=(
            settings.langfuse_secret_key.get_secret_value()
            if settings.langfuse_secret_key
            else ""
        ),
        host=settings.langfuse_host,
        environment=settings.environment,
    )
    services = build_services(settings)
    # Verify, never create. Creating the collection here would take the name reserved for
    # the alias and turn a missing corpus into an empty one.
    await services.store.verify_collection()
    # Warm the in-process embedder so the first request isn't slow. When ml-service is
    # configured the model lives there and warms in ITS lifespan — nothing to do here.
    warmup = getattr(services.embedder, "warmup", None)
    if warmup is not None:
        await asyncio.to_thread(warmup)
    # The BM25 encoder too. Its model is a cached_property that fastembed downloads on
    # first use, so without this the first real user query pays the download - and if the
    # network is briefly unavailable at that instant, that user's request is the one that
    # fails. Warming here moves the cost to startup, where a failure is loud and
    # nobody is waiting on an answer.
    sparse = getattr(services, "sparse", None)
    sparse_warmup = getattr(sparse, "warmup", None)
    if sparse_warmup is not None:
        try:
            await asyncio.to_thread(sparse_warmup)
            logger.info("sparse (BM25) encoder warm")
        except Exception:
            # Retrieval degrades to dense-only rather than refusing to boot: a missing
            # sparse half costs recall, not availability.
            logger.exception("sparse warmup failed; retrieval will be DENSE-ONLY")
    # Schema and partitions. A partitioned table with no matching partition rejects inserts,
    # so tomorrow's partitions are created at every boot as well as by the scheduled job
    # (S9). Cheap insurance against a 00:00:00 write outage.
    if services.engine is not None:
        try:
            async with services.engine.begin() as conn:
                for ddl in INITIAL_DDL:
                    await conn.execute(text(ddl))
                await ensure_future_partitions(conn, days_ahead=7)
            logger.info("database ready: schema + 8 days of partitions")
        except Exception:
            # History is optional, answering is not. Log loudly, serve anyway.
            logger.exception("database init failed; continuing WITHOUT history")

    app.state.services = services
    logger.info("medapi ready: collection=%s dim=%s", settings.qdrant_collection,
                settings.embedding_dim)
    try:
        yield
    finally:
        # Drain buffered spans and events so the last requests before a rollout survive.
        # Those are the ones most likely to explain why you're rolling back.
        flush_llm_traces()
        await services.store.close()
        if services.engine is not None:
            await services.engine.dispose()


def _settings_for_tracing() -> Any:
    """Settings at import time. get_settings() is lru_cached, so this is the same object
    lifespan uses: no second read, no chance of the two disagreeing."""
    return get_settings()


def create_app() -> FastAPI:
    app = FastAPI(title="P5 Medical RAG API", version="0.1.0", lifespan=lifespan)
    # Tracing is wired here rather than in lifespan, and that matters.
    #
    # FastAPIInstrumentor adds ASGI middleware, and Starlette freezes its middleware stack
    # when the application starts. `lifespan` runs after that point, so instrumenting from
    # inside it does nothing at all: no HTTP request span is ever created.
    #
    # It was invisible because the explicit stage spans still worked. Jaeger showed traces
    # containing a lone `embed` or `rerank` with no parent request, which reads like a
    # sampling artefact rather than missing instrumentation.
    configure_tracing(
        enabled=_settings_for_tracing().otel_enabled,
        endpoint=_settings_for_tracing().otel_endpoint,
        service_name=_settings_for_tracing().otel_service_name,
        environment=_settings_for_tracing().environment,
        sample_ratio=_settings_for_tracing().otel_sample_ratio,
    )
    instrument_app(app)
    register_error_handlers(app)  # RFC 7807 for every failure path (D18)
    app.include_router(router)
    app.include_router(conversations_router)
    return app


app = create_app()
