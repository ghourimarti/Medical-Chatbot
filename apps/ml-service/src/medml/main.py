"""ml-service: FastAPI app, routes, and lifespan.

Models are warmed at startup (D7/D21): lazy loading would make the first user wait ~10s
and would let the readiness probe lie about being ready.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from medcore.config import get_settings
from medml.backends import build_embedding_backend, build_rerank_backend
from medml.schema import (
    EmbedRequest,
    EmbedResponse,
    RerankRequest,
    RerankResponse,
    ScoredPassage,
)

logger = logging.getLogger("medml")
router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    ready = bool(getattr(request.app.state, "warm", False))
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "warming"},
    )


@router.post("/embed", response_model=EmbedResponse)
async def embed(req: EmbedRequest, request: Request) -> EmbedResponse:
    backend = request.app.state.embedder
    t0 = time.perf_counter()
    # to_thread: the model is synchronous CPU work and must never run on the event loop.
    vectors = await asyncio.to_thread(backend.encode, req.texts, is_query=req.is_query)
    return EmbedResponse(
        vectors=vectors,
        model_id=backend.model_id,
        dimension=backend.dimension,
        duration_ms=(time.perf_counter() - t0) * 1000,
    )


@router.post("/rerank", response_model=RerankResponse)
async def rerank(req: RerankRequest, request: Request) -> RerankResponse:
    backend = request.app.state.reranker
    t0 = time.perf_counter()
    scores = await asyncio.to_thread(backend.score, req.query, req.passages)
    ranked = sorted(
        (ScoredPassage(index=i, score=s) for i, s in enumerate(scores)),
        key=lambda r: r.score,
        reverse=True,
    )
    if req.top_k is not None:
        ranked = ranked[: req.top_k]
    return RerankResponse(
        results=ranked,
        model_id=backend.model_id,
        duration_ms=(time.perf_counter() - t0) * 1000,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    app.state.embedder = build_embedding_backend(
        settings.ml_backend, settings.embedding_model_id, settings.embedding_dim
    )
    rerank_backend = settings.ml_rerank_backend or settings.ml_backend
    app.state.reranker = build_rerank_backend(rerank_backend, settings.reranker_model_id)
    app.state.warm = False
    logger.info("warming models (embed_backend=%s rerank_backend=%s embed=%s rerank=%s)",
                settings.ml_backend, rerank_backend,
                settings.embedding_model_id, settings.reranker_model_id)
    await asyncio.to_thread(app.state.embedder.warmup)
    await asyncio.to_thread(app.state.reranker.warmup)
    app.state.warm = True
    logger.info("ml-service ready: dim=%s", settings.embedding_dim)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="P5 ML Service", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()


def run() -> None:  # pragma: no cover - entrypoint
    import os

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("ML_SERVICE_PORT", "8001")))  # noqa: S104
