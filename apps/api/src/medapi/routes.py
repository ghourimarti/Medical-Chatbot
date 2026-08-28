"""HTTP surface.

S3: /healthz, /readyz, POST /api/v1/query (non-streaming).
S4: POST /api/v1/query/stream (SSE) + RFC 7807 errors + client-disconnect cancellation.
Rate limits arrive in S8, auth in S9, guardrails in S12.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import AsyncIterator, Awaitable

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from medapi.auth import jwks_reachable
from medapi.deps import Services
from medapi.observability import (
    REGISTRY,
    get_logger,
)
from medapi.serving import (
    answer_from_done,
    attach_session,
    done_from_answer,
    postflight,
    preflight,
    short_circuit,
)
from medcore.errors import MedbotError, ProblemDetail, QuotaExceededError
from medcore.schema import (
    Answer,
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
    store_ok, embedder_ok = await _readiness_checks(_services(request))
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


# A probe must always answer faster than the orchestrator is willing to wait. Kubernetes
# defaults readinessProbe.timeoutSeconds to 1, so a check with no deadline of its own does
# not "run long" - it is recorded as a FAILURE, and the pod leaves the load balancer.
_READINESS_TIMEOUT = 2.0

# How long a pod may coast on its last successful check while a dependency is merely slow.
# Slow and absent look identical to a single timed-out call, but they demand opposite
# verdicts, and this window is what separates them: a blip is ridden out, a real outage
# still flips the pod NotReady once the window lapses.
_READINESS_GRACE = 30.0

_last_ready_ok: float | None = None


async def _bounded(coro: Awaitable[bool]) -> bool | None:
    """True/False if the dependency answered, None if it did not answer in time.

    None is a third state on purpose. Collapsing "did not answer" into False is what makes
    a slow dependency indistinguishable from a broken one.
    """
    try:
        return await asyncio.wait_for(coro, timeout=_READINESS_TIMEOUT)
    except TimeoutError:
        return None
    except Exception:
        return False


async def _readiness_checks(services: Services) -> tuple[bool, bool]:
    """Single source of truth for "can this pod answer", shared by /readyz and the public
    status page. Two endpoints computing readiness independently WILL drift, and a status
    page that reports healthy while the probe fails is worse than no status page.

    P6.5.4: with ml-service scaled to zero the API reported READY while every query failed,
    because readiness only consulted the vector store. Both are checked now.

    INFRA-3: and then the opposite failure. Immediately after a 7,080-chunk ingest, Qdrant
    was optimising into its segments and `get_collection` blocked past 20s - while the pod
    happily served a grounded query with citations throughout. Unbounded checks turn a
    dependency's slow spell into a self-inflicted outage, and they do it to every replica
    at once, right after a re-index: exactly the D11 alias swap this design exists to make
    seamless. So each check is bounded, and a timeout falls back to the last good result
    within _READINESS_GRACE rather than immediately declaring the pod unfit.
    """
    global _last_ready_ok

    embedder_health = getattr(services.embedder, "health", None)
    store_res, embedder_res = await asyncio.gather(
        _bounded(services.store.health()),
        _bounded(embedder_health() if embedder_health else _always_true()),
    )

    now = time.monotonic()
    if store_res is True and embedder_res is True:
        _last_ready_ok = now
        return True, True

    # An outright False is a definite answer - no grace, the pod really cannot serve.
    if store_res is False or embedder_res is False:
        return bool(store_res), bool(embedder_res)

    # Only timeouts remain. Coast on the last known-good result if it is still fresh.
    if _last_ready_ok is not None and (now - _last_ready_ok) <= _READINESS_GRACE:
        logger.warning(
            "readiness check timed out; coasting on last good result",
            extra={
                "store": store_res,
                "embedder": embedder_res,
                "age_s": round(now - _last_ready_ok, 1),
            },
        )
        return True, True

    return store_res is True, embedder_res is True


@router.get("/api/v1/status")
async def public_status(request: Request) -> dict[str, object]:
    """PUBLIC operational status (S10.2c) — deliberately a different endpoint from
    /admin/status, which is key-gated because it exposes spend, circuit state and the
    serving chain. Those are operator facts; leaking them tells an attacker which
    provider to target and how much budget is left to burn.

    What a visitor legitimately needs: can it answer right now, is generation degraded,
    and which corpus/index version produced the answers they are reading.
    """
    svc = _services(request)
    store_ok, embedder_ok = await _readiness_checks(svc)
    generation_enabled = await svc.kill_switch.llm_enabled()
    if not (store_ok and embedder_ok):
        status = "unavailable"
    elif not generation_enabled:
        status = "degraded"
    else:
        status = "ok"
    return {
        "status": status,
        "checks": {"vector_store": store_ok, "embedder": embedder_ok},
        "generation_enabled": generation_enabled,
        "corpus": {
            "version": svc.settings.corpus_version,
            "index_version": svc.settings.index_version,
        },
    }


@router.post("/api/v1/query", response_model=Answer)
async def query(req: QueryRequest, request: Request, response: Response) -> Answer:
    """Non-streaming answer.

    The cross-cutting controls live in medapi.serving so this path and the streaming path
    cannot diverge (S10.6a). They used to live inline here — 194 lines of them — while the
    streaming endpoint had none.
    """
    svc = _services(request)
    pre = await preflight(req.question, request, svc, req.conversation_id)
    attach_session(response, pre, svc)

    short = await short_circuit(req.question, svc, pre)
    if short is not None:
        return short

    # Prior turns, so a follow-up like "what causes it?" can be condensed into a
    # standalone question before retrieval. Loaded AFTER short_circuit: a cache hit must
    # not pay for a database read it will not use.
    history = await svc.history.load(pre.session_id)
    answer = await svc.pipeline.answer(req.question, history)
    return await postflight(answer, question=req.question, svc=svc, pre=pre)


@router.get("/api/v1/session/history")
async def session_history(request: Request, response: Response) -> dict[str, object]:
    svc = _services(request)
    session_id, is_new = svc.sessions.resolve(request)

    # A READ MUST NOT MINT A SESSION.
    #
    # This endpoint used to resolve-and-attach unconditionally, which meant a first-time
    # visitor loading the page raced their own first question: both requests arrive without
    # a cookie, both mint a session, and whichever Set-Cookie lands last silently orphans
    # the other session. The symptom was history that intermittently failed to appear —
    # caught only because a browser test failed roughly one run in two.
    #
    # A visitor with no session has no history by definition, so there is nothing to mint
    # a session FOR. Only a write (a query) establishes one.
    if is_new:
        return {"session_id": None, "enabled": svc.history.enabled, "messages": []}

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
        # Accounts health is reported HERE and deliberately not in /readyz or the public
        # status page. A JWKS outage stops new sign-ins from being verified; it does not
        # stop the pod answering questions. Failing readiness on it would take the whole
        # anonymous product down over a dependency the anonymous product never uses
        # (D21, D24) — and an autoscaler would then cycle healthy pods during the outage.
        "accounts": await _accounts_status(svc),
    }


async def _accounts_status(svc: Services) -> dict[str, object]:
    verifier = svc.verifier
    enabled = bool(verifier is not None and getattr(verifier, "enabled", False))
    status: dict[str, object] = {
        "enabled": enabled,
        "storage": bool(svc.conversations is not None and svc.conversations.enabled),
    }
    url = getattr(svc.settings, "clerk_jwks_url", None)
    if enabled and url:
        # Probed only for the operator view, never on the request path: verification uses
        # the cached JWKS, so a reachability check per request would add a network hop to
        # every signed-in call for information the request does not need.
        status["jwks_reachable"] = await jwks_reachable(url)
    return status


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
    """Streaming answer — the endpoint a browser actually uses.

    S10.6a: this handler previously carried NONE of the cross-cutting controls that
    query() carried. No rate limiting, no kill switch, no cache, no spend accounting, no
    history, no session. Measured before the fix: 25 consecutive requests against a 20/min
    limit returned 25x 200 here while /api/v1/query correctly 429'd after the 20th. In
    other words the deployed rate limit could be bypassed by using the default endpoint.

    ORDER MATTERS. The controls run BEFORE the StreamingResponse is constructed, so a
    quota rejection is a real HTTP 429 with an RFC 7807 body. Once the response has begun
    the status line is already 200 and the only way left to report a failure is in-band —
    which a client has to special-case.
    """
    svc = _services(request)
    pre = await preflight(req.question, request, svc, req.conversation_id)
    short = await short_circuit(req.question, svc, pre)
    # Loaded here rather than inside event_source(): a database read must not happen
    # after the response has started streaming, where a failure could no longer be
    # turned into a clean HTTP status. Skipped entirely on a cache hit.
    history = [] if short is not None else await svc.history.load(pre.session_id)

    async def event_source() -> AsyncIterator[str]:
        # A cached or degraded answer is delivered through the SAME event sequence as a
        # generated one, so the client keeps exactly one code path.
        if short is not None:
            yield _sse("sources", SourcesEvent(citations=short.citations))
            yield _sse("done", done_from_answer(short))
            return

        terminal: DoneEvent | None = None
        try:
            async for event in svc.pipeline.stream_answer(req.question, history):
                if isinstance(event, DoneEvent):
                    terminal = event
                yield _sse(_EVENT_NAMES[type(event)], event)
        except asyncio.CancelledError:
            # Client disconnected. Propagating closes the provider stream, which stops
            # token spend for an answer nobody will read (D20). Never swallow this.
            logger.info("client disconnected mid-stream; provider stream aborted")
            raise
        except MedbotError as exc:
            logger.warning("domain error mid-stream: %s", exc.internal_message)
            yield _sse("error", ErrorEvent(problem=exc.to_problem().model_dump(exclude_none=True)))
            return
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
            return

        if terminal is not None:
            # Accounting runs after the final byte. A cancelled stream deliberately skips
            # it: a partial generation has no usage figures to attribute, and inventing
            # them would corrupt the spend ledger. That gap is bounded now that rate
            # limiting applies to this endpoint, and it is recorded rather than hidden.
            await postflight(
                answer_from_done(terminal), question=req.question, svc=svc, pre=pre
            )

    response = StreamingResponse(
        event_source(), media_type="text/event-stream", headers=SSE_HEADERS
    )
    attach_session(response, pre, svc)
    return response
