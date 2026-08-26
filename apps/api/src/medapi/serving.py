"""Cross-cutting request controls, shared by BOTH query endpoints (S10.6a).

WHY THIS MODULE EXISTS
----------------------
`query()` carried session handling, rate limiting, the kill switch, cache-aside, cost
attribution, metrics and history persistence inline — 194 lines of it. `query_stream()`
carried NONE of them, and the browser only ever calls the streaming endpoint. Measured
before the fix: 25 consecutive requests against a 20/min limit returned 25x 200 on
/query/stream while /query correctly returned 429 after the 20th.

So in practice the deployed system had no rate limiting, no kill switch, no spend
accounting, no caching and no history for real users. Every one of those is a documented
decision (D1, D9, D10, D18, D20, D21) that was simply absent from the path that matters.

The fix is EXTRACTION, not duplication. Copying the controls into the stream handler would
leave two copies to drift again — which is exactly how the first divergence happened (the
output dosage guardrail, S10.2b, had the identical shape). With one implementation, a
control added later cannot be added to one endpoint and forgotten in the other.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import Request, Response

from medapi.auth import bearer_token
from medapi.budget import SpendState
from medapi.conversations import Caller
from medapi.deps import Services
from medapi.observability import (
    cache_events,
    fingerprint,
    get_logger,
    rate_limited_total,
    record_answer,
    record_stage,
)
from medapi.pricing import cost_usd
from medcore.errors import QuotaExceededError
from medcore.schema import Answer, AnswerKind, DoneEvent

logger = get_logger("medapi.serving")

DEGRADED_TEXT = (
    "Answers are limited right now and I can't generate a new one. Please try again shortly."
)


@dataclass(slots=True)
class Preflight:
    """What the controls produced, threaded through to postflight."""

    session_id: UUID
    client_key: str | None
    log: Any
    # The authorised thread this turn belongs to, or None for the anonymous single-thread
    # path. Already ownership-checked by the time it lands here — nothing downstream
    # re-verifies it, so it must never be set from the request body directly.
    conversation_id: UUID | None = None


async def preflight(
    question: str,
    request: Request,
    svc: Services,
    conversation_id: UUID | None = None,
) -> Preflight:
    """Identity, authorisation and quota. Raises QuotaExceededError -> 429/7807, or
    ConversationNotFound -> 404 for a thread the caller does not own.

    Runs BEFORE any expensive work (D20): checking after retrieval would mean paying for
    the embedding and LLM call of a request we then reject, and the abuse case is exactly
    where cost control has to bite first. It also runs before the StreamingResponse exists,
    which is what lets an unauthorised thread be a real 404 instead of an in-band SSE error
    delivered once the status line already says 200.
    """
    session_id, _ = svc.sessions.resolve(request)

    # A fingerprint, never the question itself (D18) — enough to correlate repeats across
    # logs without ever storing a health question.
    log = logger.bind(session=str(session_id)[:8], q=fingerprint(question))

    # TWO independent keys (D18). The session bucket gives a well-behaved client a fair,
    # generous quota. The IP bucket is the enforcement one: a session id is just a cookie
    # the caller decides whether to send, so session-only limiting is opt-in and an abuser
    # opts out by dropping it. Measured in P5.2: 30 cookieless requests against a 20/min
    # limit produced ZERO 429s before the IP bucket existed.
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

    # Ownership of a caller-supplied thread is resolved HERE, in the one place both
    # endpoints pass through, and the authorised id is what travels onward. The request
    # body's value never reaches the writer: a thread is prompt context, so appending to
    # someone else's would be a write into their conversation, not merely a read of it.
    thread: UUID | None = None
    if conversation_id is not None and svc.conversations is not None:
        caller = Caller(
            session_id=session_id,
            user_id=await svc.conversations.resolve_user(
                bearer_token(request.headers.get("authorization"))
            ),
        )
        thread = await svc.conversations.resolve_thread(caller, conversation_id)

    return Preflight(
        session_id=session_id, client_key=client_key, log=log, conversation_id=thread
    )


def attach_session(response: Response, pre: Preflight, svc: Services) -> None:
    """Set the session cookie. Separate from preflight because a StreamingResponse is
    constructed AFTER the controls run — the 429 must be a real HTTP status, not an
    in-band SSE error delivered once bytes are already on the wire."""
    svc.sessions.attach(response, pre.session_id)


async def short_circuit(question: str, svc: Services, pre: Preflight) -> Answer | None:
    """A cached answer, or a degraded one when generation is disabled. None => generate.

    Cache-aside (D10) skips embedding, retrieval, reranking and generation — the single
    largest cost and latency lever in the system. A miss with generation disabled is
    DEGRADED, never an error (D20/D21): the kill switch and the daily spend breaker both
    arrive here.
    """
    cached = await svc.cache.get(question)
    if cached is not None:
        cache_events.labels(layer="response", result="hit").inc()
        record_answer(cached.kind.value, cached.timings.total_ms)
        pre.log.info("cache_hit", kind=cached.kind.value)
        return cached
    cache_events.labels(layer="response", result="miss").inc()

    if not await svc.kill_switch.llm_enabled() or (
        await svc.spend.state() is SpendState.EXCEEDED
    ):
        pre.log.warning("cache_only_mode", reason="kill_switch_or_spend_limit")
        degraded = Answer(kind=AnswerKind.DEGRADED, text=DEGRADED_TEXT)
        record_answer(degraded.kind.value, 0.0)
        return degraded

    return None


async def postflight(
    answer: Answer, *, question: str, svc: Services, pre: Preflight
) -> Answer:
    """Cost attribution, metrics, cache write, history persistence.

    Returns the answer with cost filled in, because the caller must serve the SAME object
    it accounted for — returning an un-costed answer while recording spend elsewhere is how
    a dashboard and an invoice end up disagreeing.
    """
    # Self-hosted venues price at $0/token by construction (their cost is GPU-hours,
    # tracked separately), so this measures hosted spend specifically.
    spent = cost_usd(answer.model_id or "", answer.usage)
    if spent:
        answer = answer.model_copy(
            update={"usage": answer.usage.model_copy(update={"cost_usd": spent})}
        )
        total = await svc.spend.record(spent)
        state = svc.spend.state_for(total)
        if state is not SpendState.OK:
            pre.log.warning("spend_alert", state=state.value, daily_total_usd=round(total, 4))

    # Instrumented at the STAGE boundary: the pipeline already returns timings, so metrics
    # are derived here rather than the pipeline importing Prometheus (D13).
    t = answer.timings
    for stage, ms in (
        ("embed", t.embed_ms),
        ("retrieve", t.retrieve_ms),
        ("rerank", t.rerank_ms),
        ("generate", t.generate_ms),
    ):
        record_stage(stage, ms)
    record_answer(answer.kind.value, t.total_ms, answer.usage.cost_usd)
    pre.log.info(
        "answered",
        kind=answer.kind.value,
        citations=len(answer.citations),
        total_ms=round(t.total_ms),
        rerank_ms=round(t.rerank_ms or 0),
        tokens=answer.usage.total_tokens,
        model=answer.model_id,
    )

    # Only GROUNDED answers are stored; Answer.is_cacheable refuses refusals, no-answers
    # and degraded responses (D10 safety rule, enforced by the type rather than this call).
    await svc.cache.set(question, answer)

    # Persistence is a SIDE EFFECT of answering, never a precondition (D21): a database
    # outage costs history, not availability.
    await svc.history.record_turn(
        pre.session_id,
        question=question,
        answer_text=answer.text,
        kind=answer.kind,
        model_id=answer.model_id,
        # Same hop count as the quota check. Deriving two different hashes for one client
        # behind a proxy would make abuse investigation and abuse enforcement disagree
        # about who the caller was.
        client_hash=pre.client_key,
        conversation_id=pre.conversation_id,
    )
    return answer


def answer_from_done(event: DoneEvent) -> Answer:
    """DoneEvent -> Answer so a streamed response can run the SAME postflight.

    Without this the streaming path would need its own accounting, which is precisely the
    duplication that produced the divergence this module exists to remove.
    """
    return Answer(
        kind=event.kind,
        text=event.text,
        citations=event.citations,
        model_id=event.model_id,
        usage=event.usage,
        timings=event.timings,
        refusal_category=event.refusal_category,
    )


def done_from_answer(answer: Answer) -> DoneEvent:
    """Answer -> DoneEvent so a cached or degraded response is delivered through the SAME
    SSE sequence as a generated one.

    The client then has exactly one code path: sources, then (maybe) tokens, then done. A
    cache hit that returned plain JSON instead would force every consumer to handle two
    response shapes for one endpoint, and the rarely-exercised branch is the one that rots.
    """
    return DoneEvent(
        kind=answer.kind,
        text=answer.text,
        citations=answer.citations,
        model_id=answer.model_id,
        usage=answer.usage,
        timings=answer.timings,
        refusal_category=answer.refusal_category,
    )
