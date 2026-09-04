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

import contextlib
import time
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
    llm_trace,
    rate_limited_total,
    record_answer,
    record_stage,
)
from medapi.pipeline.rag import is_context_dependent
from medapi.pricing import cost_usd
from medcore.errors import QuotaExceededError
from medcore.prompts import load_prompt
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
    # A FOLLOW-UP IS NEVER SERVED FROM CACHE (D10/INFRA-5).
    #
    # The cache key is a hash of the question text, namespaced by prompt/corpus/index/model
    # version — and by nothing about the conversation. So "What causes it?" produced ONE key
    # for every thread on the system. Asked after pneumonia in one conversation and after
    # cirrhosis in another, the second reader was served the first reader's answer, with
    # confident citations to the wrong condition. Proven with `cache_hit: true` returning a
    # coccydynia answer to a thread that had only ever discussed pneumonia.
    #
    # This module's own docstring states the stakes: a wrong cache hit is a patient-safety
    # bug, not a stale page.
    #
    # WHY NOT CONDENSE FIRST AND KEY ON THE RESULT. That is the better long-term answer -
    # "What causes pneumonia?" is genuinely shareable and would RAISE the hit rate. But it
    # puts an LLM call ahead of every cache lookup, which is precisely the cost the cache
    # exists to avoid, and it restructures the request path. Declining to cache the one
    # category that is currently WRONG is smaller, safe, and loses almost nothing: a
    # standalone question - the overwhelming majority - still takes the fast path
    # untouched.
    if is_context_dependent(question):
        cache_events.labels(layer="response", result="skip").inc()
        return None

    t0 = time.perf_counter()
    cached = await svc.cache.get(question)
    if cached is not None:
        cache_events.labels(layer="response", result="hit").inc()
        # THIS request's duration, not the one it avoided.
        #
        # It used to pass `cached.timings.total_ms` - the ORIGINAL generation time, replayed
        # on every hit. So a 40ms cache hit was recorded into the latency histogram as an
        # 11-second request, and the effect compounded: the more traffic the cache served,
        # the WORSE p95 looked. The single largest latency lever in the system reported
        # itself as a regression, and request p95 was inflated by answers that were never
        # generated.
        #
        # The replayed stage timings stay ON THE ANSWER (they describe how that content was
        # produced, which is useful) - they simply must not be re-observed as if this
        # request had done the work.
        elapsed_ms = (time.perf_counter() - t0) * 1000
        # venue="cache", NOT the venue that originally generated this answer, and not the
        # same "none" refusals use. Crediting the original venue would let sub-millisecond
        # cache reads pull down that venue's latency percentiles and make it look faster
        # than it serves. Reusing "none" would blend a cheap success into the bucket that
        # means "nothing was generated". A cache hit is its own kind of answer, so it gets
        # its own label, and per-venue latency stays a statement about venues.
        record_answer(cached.kind.value, elapsed_ms, venue="cache")
        pre.log.info(
            "cache_hit", kind=cached.kind.value, elapsed_ms=round(elapsed_ms, 1)
        )
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
        # condense FIRST because it runs first, and because it was MISSING: rag.py computes
        # condense_ms and sums it into total_ms, but this loop never recorded it. Grafana's
        # stage-latency panel renders `by (stage)`, so it silently omitted the slowest
        # stage at p95 (Jaeger: 4254ms) and the visible stages summed to less than the
        # total with no gap to explain it.
        ("condense", t.condense_ms),
        ("embed", t.embed_ms),
        ("retrieve", t.retrieve_ms),
        ("rerank", t.rerank_ms),
        ("generate", t.generate_ms),
    ):
        record_stage(stage, ms)
    # ttft_ms is None on the non-streaming path, which is exactly right: there is no
    # first token to time, and record_answer skips the observation rather than
    # substituting total_ms and silently redefining the SLI.
    # no_answer_path is derived from whether a prompt was actually spent: the retrieval
    # gate declines before the model, so prompt_tokens is 0; a model abstention has read
    # a full context to reach the same word. Same kind, very different bill.
    no_answer_path = None
    if answer.kind is AnswerKind.NO_ANSWER:
        no_answer_path = (
            "model_abstained" if answer.usage.prompt_tokens else "retrieval_gate"
        )
    record_answer(
        answer.kind.value,
        t.total_ms,
        answer.usage.cost_usd,
        t.ttft_ms,
        refusal_category=answer.refusal_category,
        no_answer_path=no_answer_path,
        venue=answer.venue,
    )
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

    # D13/D18: the LLM-shaped record. This call is what makes Langfuse show anything at
    # all - the module was fully written, configured and enabled, and had NO CALLER, so
    # every container reported healthy while the trace list stayed empty (INFRA-4).
    #
    # It sits in postflight so the streaming path gets it too: answer_from_done() exists
    # precisely so both paths run this one function, and tracing only the non-streaming
    # branch would under-report exactly the requests users actually make.
    #
    # Never awaited and never allowed to raise: trace_answer swallows its own errors, and
    # observability must not be able to fail a medical answer.
    _trace_to_langfuse(answer, question=question, pre=pre)

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



def _trace_to_langfuse(answer: Answer, *, question: str, pre: Preflight) -> None:
    """Assemble the Langfuse payload. Separate from postflight so the accounting path
    stays readable and so a change here cannot disturb cost or history."""
    if not llm_trace.is_enabled():
        return
    try:
        prompt = load_prompt("answer")
        version, sha = prompt.version, prompt.sha256
    except Exception:  # noqa: BLE001 - a missing prompt file must not lose the trace
        version, sha = "unknown", ""

    # trace_answer already swallows its own errors; this is the second layer, and it is
    # not redundant. postflight runs AFTER the answer is final, so anything that escapes
    # here converts a delivered medical answer into a 500 - the tracer would take down the
    # exact request it exists to explain.
    with contextlib.suppress(Exception):  # observability must never fail an answer
        _emit(answer, question=question, version=version, sha=sha)


def _emit(answer: Answer, *, question: str, version: str, sha: str) -> None:
    llm_trace.trace_answer(
        question=question,
        answer_text=answer.text,
        kind=answer.kind.value,
        prompt_version=version,
        prompt_sha=sha,
        model_id=answer.model_id,
        # Citation snippets, not the full retrieved chunks: Answer does not carry the raw
        # context, and widening the response contract to feed a tracer would be the wrong
        # trade. Enough to see WHICH passages grounded the answer, which is the question
        # a faithfulness regression actually asks.
        contexts=[c.snippet for c in answer.citations],
        prompt_tokens=answer.usage.prompt_tokens,
        completion_tokens=answer.usage.completion_tokens,
        cost_usd=answer.usage.cost_usd or 0.0,
        timings={
            "embed_ms": answer.timings.embed_ms,
            "retrieve_ms": answer.timings.retrieve_ms,
            "rerank_ms": answer.timings.rerank_ms,
            "generate_ms": answer.timings.generate_ms,
            "total_ms": answer.timings.total_ms,
        },
        cache_hit=answer.cache_hit,
        # trace_answer has always accepted a venue and _emit never passed one, so every
        # Langfuse trace recorded venue=None - the one field that separates self-hosted
        # from paid spend, missing from the store whose job is per-answer cost attribution.
        # Answer.venue only started carrying it once the chain leg reached the response
        # contract; before that there was nothing here to pass.
        venue=answer.venue,
    )


async def record_short_circuit(
    answer: Answer, *, question: str, svc: Services, pre: Preflight
) -> None:
    """Persist a turn that never reached postflight (INFRA-5).

    A cache hit returns from `short_circuit` BEFORE postflight runs, and postflight is the
    only caller of `record_turn`. So every answer the cache served was invisible: absent
    from the session transcript, and — because the conversation link is written with the
    row — absent from the conversation it was asked in. A thread could be created, asked a
    previously-seen question, and stay permanently empty. Reported as "the conversation
    saves but will not reload", which is exactly what it looked like from outside.

    Measured, not inferred: 634 rows before a cached ask, 634 after.

    Only the history write is repeated here. `short_circuit` already records the answer
    metric and the cache-hit counter, and re-recording spend would bill a request that
    cost nothing — the bug this deliberately does not create while fixing the other one.
    """
    await svc.history.record_turn(
        pre.session_id,
        question=question,
        answer_text=answer.text,
        kind=answer.kind,
        model_id=answer.model_id,
        client_hash=pre.client_key,
        conversation_id=pre.conversation_id,
    )


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
        # Carry the venue across the conversion or the streaming path loses it here, one
        # step before postflight - which would leave Langfuse recording venue=None for
        # exactly the requests the browser makes, i.e. all the real ones.
        venue=event.venue,
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
        # The reverse trip, so a cached or degraded answer reports the venue that
        # originally produced it rather than an empty field.
        venue=answer.venue,
    )
