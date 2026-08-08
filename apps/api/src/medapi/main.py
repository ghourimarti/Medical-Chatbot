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

from fastapi import FastAPI

from medapi.deps import build_services
from medapi.routes import router
from medcore.config import get_settings

logger = logging.getLogger("medapi")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    services = build_services(settings)
    await services.store.ensure_collection()
    # Warm the embedding model off the event loop so the first request isn't slow.
    await asyncio.to_thread(services.embedder.warmup)
    app.state.services = services
    logger.info("medapi ready: collection=%s dim=%s", settings.qdrant_collection,
                settings.embedding_dim)
    try:
        yield
    finally:
        await services.store.close()


def create_app() -> FastAPI:
    app = FastAPI(title="P5 Medical RAG API", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
