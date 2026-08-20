"""HTTP surface.

S3: /healthz, /readyz, POST /api/v1/query (non-streaming).
S4: POST /api/v1/query/stream (SSE) + RFC 7807 errors + client-disconnect cancellation.
Rate limits arrive in S8, auth in S9, guardrails in S12.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from medapi.budget import SpendState
from medapi.deps import Services
from medapi.observability import (
    REGISTRY,
    cache_events,
    fingerprint,
    get_logger,
    rate_limited_total,
    record_answer,
    record_stage,
)
from medapi.pricing import cost_usd
from medcore.errors import MedbotError, ProblemDetail, QuotaExceededError
from medcore.schema import (
    Answer,
    AnswerKind,
    DoneEvent,
    ErrorEvent,
    QueryRequest,
    SourcesEvent,
    TokenEvent,
)

logger = get_logger("medapi.routes")
router = APIRouter()

# SSE headers. `X-Accel-Buffering: no` is not optional: without it an nginx/ALB in
# front will buffer the whole response and "streaming" silently becomes batch delivery.
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

_EVENT_NAMES = {SourcesEvent: "sources", TokenEvent: "token", DoneEvent: "done"}


def _services(request: Request) -> Services:
    return request.app.state.services  # type: ignore[no-any-return]


def _sse(event: str, payload: BaseModel) -> str:
    return f"event: {event}\ndata: {payload.model_dump_json()}\n\n"


@router.get("/metrics")
async def metrics() -> PlainTextResponse:
    """Prometheus scrape endpoint (D13). Deliberately unauthenticated in-cluster and
    excluded at the ingress — a NetworkPolicy restricts it to the scraper (S15)."""
    return PlainTextResponse(
        generate_latest(REGISTRY).decode(), media_type=CONTENT_TYPE_LATEST
    )


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the process is up. Never touches dependencies (K8s restarts on failure)."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    """Readiness means "this pod can answer a query", not "one dependency responded".

    P6.5.4: with ml-service scaled to zero the API reported READY while every single query
    returned 503, because readiness only consulted the vector store. Embedding is the FIRST
    step of retrieval — no vector, nothing to search — so an unreachable embedder is just
    as disqualifying as an unreachable index. Both are checked here, concurrently so a slow
    dependency cannot serialise the probe.

    Deliberately NOT checked: Redis and Postgres. Losing either degrades the service
    (cache bypass, history disabled) but it can still answer, and failing readiness would
    take the whole deployment out of service over a partial loss (D21).
    """
    services = _services(request)
    embedder_health = getattr(services.embedder, "health", None)
    store_ok, embedder_ok = await asyncio.gather(
        services.store.health(),
        embedder_health() if embedder_health else _always_true(),
    )
    ready = store_ok and embedder_ok
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "not_ready",
            "checks": {"vector_store": store_ok, "embedder": embedder_ok},
        },
    )


async def _always_true() -> bool:
    """In-process embedder: if the module is loaded, it is available."""
    return True


@router.post("/api/v1/query", response_model=Answer)
async def query(req: QueryRequest, request: Request, response: Response) -> Answer:
    svc = _services(request)
    session_id, _ = svc.sessions.resolve(request)
    svc.sessions.attach(response, session_id)

    # A fingerprint, never the question itself (D18). Enough to correlate repeats of the
    # same query across logs without ever storing a health question.
    log = logger.bind(session=str(session_id)[:8], q=fingerprint(req.question))

    # Quota BEFORE any expensive work (D20). Checking after retrieval would mean paying
    # for the embedding and LLM call of a request we then reject — the abuse case is
    # exactly where cost control must bite first. Raises QuotaExceededError -> 429/7807.
    #
    # TWO independent keys (D18). The session bucket gives a well-behaved client a fair,
    # generous quota. The IP bucket is the enforcement one: a session id is just a cookie
    # the caller decides whether to send, so session-only limiting is opt-in and an abuser
    # opts out by dropping the cookie. Measured in P5.2 before this was added — 30
    # cookieless requests against a 20/min limit produced ZERO 429s.
    buckets: list[tuple[str, str, int, int]] = [
        ("minute", str(session_id), svc.settings.rate_limit_per_minute, 60),
        ("day", str(session_id), svc.settings.rate_limit_per_day, 86_400),
    ]
    client_key = svc.sessions.client_hash(
        request, trusted_proxy_hops=svc.settings.trusted_proxy_hops
    )
    if client_key is not None:
        buckets += [
            ("ip_minute", client_key, svc.settings.rate_limit_ip_per_minute, 60),
            ("ip_day", client_key, svc.settings.rate_limit_ip_per_day, 86_400),
        ]
    for scope, key, limit, window in buckets:
        try:
            await svc.limiter.check(key, scope=scope, limit=limit, window_seconds=window)
        except QuotaExceededError:
            rate_limited_total.labels(scope=scope).inc()
            log.warning("rate_limited", scope=scope, limit=limit)
            raise

    # Cache-aside (D10). A hit skips embedding, retrieval, reranking, and generation —
    # the single largest cost and latency lever in the system.
    cached = await svc.cache.get(req.question)
    if cached is not None:
        cache_events.labels(layer="response", result="hit").inc()
        record_answer(cached.kind.value, cached.timings.total_ms)
        log.info("cache_hit", kind=cached.kind.value)
        return cached
    cache_events.labels(layer="response", result="miss").inc()

    # Cache miss + generation disabled => DEGRADED, never an error (D20/D21). Two paths
    # arrive here: an operator flipped the kill switch, or the daily spend breaker tripped.
    if not await svc.kill_switch.llm_enabled() or (
        await svc.spend.state() is SpendState.EXCEEDED
    ):
        log.warning("cache_only_mode", reason="kill_switch_or_spend_limit")
        degraded = Answer(
            kind=AnswerKind.DEGRADED,
            text=(
                "Answers are limited right now and I can't generate a new one. "
                "Please try again shortly."
            ),
        )
        record_answer(degraded.kind.value, 0.0)
        return degraded

    answer = await svc.pipeline.answer(req.question)

    # Cost attribution (D20). Self-hosted venues price at $0/token by construction — their
    # cost is GPU-hours, tracked separately — so this measures hosted spend specifically.
    spent = cost_usd(answer.model_id or "", answer.usage)
    if spent:
        answer = answer.model_copy(
            update={"usage": answer.usage.model_copy(update={"cost_usd": spent})}
        )
        total = await svc.spend.record(spent)
        state = svc.spend.state_for(total)
        if state is not SpendState.OK:
            log.warning("spend_alert", state=state.value, daily_total_usd=round(total, 4))

    # Instrument at the STAGE boundary: the pipeline already returns timings, so metrics
    # are derived here rather than the pipeline importing Prometheus (D13).
    t = answer.timings
    for stage, ms in (
        ("embed", t.embed_ms), ("retrieve", t.retrieve_ms),
        ("rerank", t.rerank_ms), ("generate", t.generate_ms),
    ):
        record_stage(stage, ms)
    record_answer(answer.kind.value, t.total_ms, answer.usage.cost_usd)
    log.info(
        "answered",
        kind=answer.kind.value,
        citations=len(answer.citations),
        total_ms=round(t.total_ms),
        rerank_ms=round(t.rerank_ms or 0),
        tokens=answer.usage.total_tokens,
        model=answer.model_id,
    )
    # Only GROUNDED answers are stored; Answer.is_cacheable refuses refusals, no-answers,
    # and degraded responses (D10 safety rule, enforced by the type, not by this call).
    await svc.cache.set(req.question, answer)

    # Persistence is a SIDE EFFECT of answering, never a precondition (D21): a database
    # outage costs history, not availability.
    await svc.history.record_turn(
        session_id,
        question=req.question,
        answer_text=answer.text,
        kind=answer.kind,
        model_id=answer.model_id,
        # Same hop count as the quota check above. Passing different values would derive
        # two different hashes for one client behind a proxy, so abuse investigation and
        # abuse enforcement would disagree about who the caller was.
        client_hash=client_key,
    )
    return answer


@router.get("/api/v1/session/history")
async def session_history(request: Request, response: Response) -> dict[str, object]:
    svc = _services(request)
    session_id, _ = svc.sessions.resolve(request)
    svc.sessions.attach(response, session_id)
    messages = await svc.history.load(session_id)
    return {
        "session_id": str(session_id),
        "enabled": svc.history.enabled,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
    }


@router.post("/api/v1/session/clear")
async def clear_session(request: Request, response: Response) -> dict[str, object]:
    """GDPR right-to-erasure (D18).

    Reports how many rows were actually removed rather than a bare 200 — a delete endpoint
    that claims success without proving removal passes review and fails an audit. Failures
    here deliberately propagate (as RFC 7807) instead of degrading silently.
    """
    svc = _services(request)
    session_id, _ = svc.sessions.resolve(request)
    svc.sessions.attach(response, session_id)
    deleted = await svc.history.clear(session_id)
    logger.info("session_cleared", session=str(session_id)[:8], deleted=deleted)
    return {"session_id": str(session_id), "deleted": deleted}


def _require_admin(request: Request) -> None:
    """Static API key for admin operations (D9).

    Deliberately NOT the anonymous session cookie: a kill switch reachable by any visitor
    is a denial-of-service button. Cognito OIDC replaces this in the cloud deployment; the
    shared key is the local/dev equivalent, and its absence fails CLOSED.
    """
    configured = _services(request).settings.admin_api_key
    if configured is None:
        raise QuotaExceededError("admin API disabled: ADMIN_API_KEY is not configured")
    presented = request.headers.get("x-admin-key", "")
    if not secrets.compare_digest(presented, configured.get_secret_value()):
        raise QuotaExceededError("invalid admin key")


@router.get("/admin/status")
async def admin_status(request: Request) -> dict[str, object]:
    """Operational snapshot: what is live, what is tripped, what has been spent today."""
    _require_admin(request)
    svc = _services(request)
    total = await svc.spend.total_today()
    return {
        "llm_enabled": await svc.kill_switch.llm_enabled(),
        "spend_today_usd": round(total, 4),
        "spend_limit_usd": svc.settings.daily_spend_limit_usd,
        "spend_state": svc.spend.state_for(total).value,
        "serving_chain": svc.model.venues,
        "circuits": svc.model.status(),
        "collection_alias": svc.settings.qdrant_collection,
        "cache_namespace": svc.settings.cache_namespace,
    }


@router.post("/admin/kill-switch")
async def admin_kill_switch(request: Request, enabled: bool, reason: str = "") -> dict[str, object]:
    """Flip generation on/off AT RUNTIME (D20).

    No redeploy: a cost incident happens at 3am, and if stopping it requires a CI pipeline
    the bleeding continues for twenty minutes. The ENV setting remains a floor — if
    LLM_ENABLED=false was shipped, this cannot turn generation back on.
    """
    _require_admin(request)
    svc = _services(request)
    effective = await svc.kill_switch.set_enabled(enabled, reason=reason)
    logger.warning("kill_switch_changed", requested=enabled, effective=effective, reason=reason)
    return {"requested": enabled, "effective_llm_enabled": effective, "reason": reason}


@router.post("/api/v1/query/stream")
async def query_stream(req: QueryRequest, request: Request) -> StreamingResponse:
    pipeline = _services(request).pipeline

    async def event_source() -> AsyncIterator[str]:
        try:
            async for event in pipeline.stream_answer(req.question):
                yield _sse(_EVENT_NAMES[type(event)], event)
        except asyncio.CancelledError:
            # Client disconnected. Propagating closes the provider stream, which stops
            # token spend for an answer nobody will read (D20). Never swallow this.
            logger.info("client disconnected mid-stream; provider stream aborted")
            raise
        except MedbotError as exc:
            logger.warning("domain error mid-stream: %s", exc.internal_message)
            yield _sse("error", ErrorEvent(problem=exc.to_problem().model_dump(exclude_none=True)))
        except Exception:
            # Bytes are already on the wire, so the HTTP status can no longer change:
            # the error must be delivered in-band, still without leaking internals.
            logger.exception("unhandled error mid-stream")
            problem = ProblemDetail(
                type="https://p5-medical-chatbot/problems/internal-error",
                title="Internal Server Error",
                status=500,
                detail="An unexpected error occurred while generating the answer.",
            )
            yield _sse("error", ErrorEvent(problem=problem.model_dump(exclude_none=True)))

    return StreamingResponse(event_source(), media_type="text/event-stream", headers=SSE_HEADERS)
