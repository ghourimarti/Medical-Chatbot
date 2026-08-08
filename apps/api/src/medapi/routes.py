"""HTTP surface. S3: /healthz (liveness), /readyz (dependency readiness), POST /query.
Streaming (/query/stream), RFC 7807 handlers, and rate limits arrive in S4/S8/S12."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from medapi.deps import Services
from medcore.schema import Answer, QueryRequest

router = APIRouter()


def _services(request: Request) -> Services:
    return request.app.state.services  # type: ignore[no-any-return]


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the process is up. Never touches dependencies (K8s restarts on failure)."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    """Readiness: only serve traffic when the vector store is reachable (D21)."""
    store_ok = await _services(request).store.health()
    status = "ready" if store_ok else "not_ready"
    return JSONResponse(
        status_code=200 if store_ok else 503,
        content={"status": status, "checks": {"vector_store": store_ok}},
    )


@router.post("/api/v1/query", response_model=Answer)
async def query(req: QueryRequest, request: Request) -> Answer:
    return await _services(request).pipeline.answer(req.question)
