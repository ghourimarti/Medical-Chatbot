"""FastAPI application factory + lifespan (D7).

Lifespan builds the service singletons once, warms the embedder, and ensures the Qdrant
collection exists at the configured dimension — so a misconfiguration fails startup (and
the readiness probe), not the first user request.
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
    # JSON to stdout with PII redaction (D13/D18). Console renderer locally for
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
    # Verify, never create (P6.3.5). Creating the collection here would take the name
    # reserved for the D11 alias and turn a missing corpus into an empty one.
    await services.store.verify_collection()
    # Warm the in-process embedder so the first request isn't slow. When ml-service is
    # configured the model lives there and warms in ITS lifespan — nothing to do here.
    warmup = getattr(services.embedder, "warmup", None)
    if warmup is not None:
        await asyncio.to_thread(warmup)
    # Schema + partitions. A partitioned table with no matching partition REJECTS inserts,
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
            # D21: history is optional, answering is not. Log loudly, serve anyway.
            logger.exception("database init failed; continuing WITHOUT history")

    app.state.services = services
    logger.info("medapi ready: collection=%s dim=%s", settings.qdrant_collection,
                settings.embedding_dim)
    try:
        yield
    finally:
        # Drain buffered spans/events so the last requests before a rollout are
        # not lost — the ones most likely to explain why you are rolling back.
        flush_llm_traces()
        await services.store.close()
        if services.engine is not None:
            await services.engine.dispose()


def _settings_for_tracing() -> Any:
    """Settings at import time. get_settings() is lru_cached, so this is the same object
    lifespan will use — no second read, no chance of the two disagreeing."""
    return get_settings()


def create_app() -> FastAPI:
    app = FastAPI(title="P5 Medical RAG API", version="0.1.0", lifespan=lifespan)
    # Tracing is wired HERE, not in lifespan, and the difference is not cosmetic.
    #
    # FastAPIInstrumentor adds ASGI middleware, and Starlette freezes its middleware stack
    # when the application starts. `lifespan` runs AFTER that point, so instrumenting from
    # inside it silently does nothing: no HTTP request span is ever created.
    #
    # The failure was invisible because the EXPLICIT stage spans still worked. Jaeger
    # showed traces containing a lone `embed` or a lone `rerank` — orphans with no parent
    # request — which reads like a sampling artefact rather than missing instrumentation.
    # A partial trace is worse than no trace: it looks like data.
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
