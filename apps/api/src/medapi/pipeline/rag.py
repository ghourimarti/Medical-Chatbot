"""The RAG query pipeline as an LCEL chain of SELF-AUTHORED runnables (D6 v2.1).

Every stage is a plain async function wrapped as a RunnableLambda; they compose with `|`.
LCEL supplies composition/streaming/batching plumbing — never hidden business logic. No
prebuilt chain (RetrievalQA, create_retrieval_chain) is used or importable (ruff-banned):
that opacity is exactly what let demo's k=1 ship unexamined.

S3 pipeline: embed -> retrieve -> (no-answer gate) -> build_context -> generate.
Reranking/hybrid (S6), streaming (S4), and caching (S8) slot in as added stages later.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from langchain_core.runnables import Runnable, RunnableLambda

from medapi.guardrails import (
    _MESSAGES,
    RefusalCategory,
    classify_input,
    contains_dosage_instruction,
)
from medapi.observability.metrics import degradations_total
from medapi.observability.tracing import question_fingerprint, set_attrs, stage_span
from medapi.pipeline.context import build_context
from medcore.config import Settings
from medcore.errors import RerankerError, RetrievalError
from medcore.ports import EmbedderPort, ModelPort, RerankerPort, VectorStorePort
from medcore.prompts import load_prompt
from medcore.schema import (
    Answer,
    AnswerKind,
    Citation,
    DoneEvent,
    Message,
    RetrievedChunk,
    SourcesEvent,
    StageTimings,
    TokenEvent,
    Usage,
)

logger = logging.getLogger("medapi.pipeline")


class SparseEncoder(Protocol):
    """Minimal structural contract for BM25 encoding — keeps the pipeline free of any
    fastembed/qdrant import (the medcore no-vendor-SDK rule, applied one layer out)."""

    def encode_query(self, text: str) -> object: ...


NO_ANSWER_TEXT = "I don't have reliable information on that in my reference material."

# The model is instructed to emit NO_ANSWER_TEXT when the context is insufficient. When it
# does, the answer is NOT grounded even though retrieval cleared the (coarse, dense-only)
# threshold — so we relabel it NO_ANSWER and drop the (irrelevant) citations. S6's hybrid
# retrieval + reranker + tuned threshold makes the retrieval-side gate do more of this work.
_ABSTENTION_MARKERS = (
    "don't have reliable information",
    "do not have reliable information",
    "reference material",
)


def _is_abstention(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in _ABSTENTION_MARKERS)


@dataclass(slots=True)
class PipelineState:
    """State threaded through the LCEL stages. Immutable-ish: stages return updated copies."""

    question: str
    # Prior turns, oldest-first. Empty for a first question and for any caller that
    # does not thread history - the pipeline stays usable standalone.
    history: list[Message] = field(default_factory=list)
    # What RETRIEVAL searches for. Usually identical to `question`; for a follow-up it
    # is the condensed standalone form. Kept separate on purpose: the user must be
    # shown, and the model must answer, the question they actually TYPED - not our
    # rewrite of it.
    search_question: str = ""
    query_vector: list[float] = field(default_factory=list)
    chunks: list[RetrievedChunk] = field(default_factory=list)
    context: str = ""
    citations: list[Citation] = field(default_factory=list)
    answer: Answer | None = None
    timings: StageTimings = field(default_factory=StageTimings)



_ANAPHORA_RE = re.compile(
    r"\b(it|its|that|this|those|these|they|them|their|he|she|him|her|"
    r"the (condition|disease|drug|treatment|illness|infection|one))\b",
    re.IGNORECASE,
)


_PRONOUN_RE = re.compile(
    r"\b(it|its|they|them|their|those|these|this|that|he|she|him|her)\b",
    re.IGNORECASE,
)

_CONTINUATION_RE = re.compile(
    r"^(and|or|but|also|what about|how about|then)\b",
    re.IGNORECASE,
)


def is_followup(question: str) -> bool:
    """Loose test, used to decide whether to ATTEMPT a condense rewrite.

    Two signals, both cheap: the question REFERS to something (anaphora), or is too short
    to name a subject at all ("why?"). Deliberately over-eager — a false positive costs one
    small rewrite that returns the question unchanged.
    """
    if len(question.split()) <= 3:
        return True
    return bool(_ANAPHORA_RE.search(question))


def is_context_dependent(question: str) -> bool:
    """Strict test, used to decide whether the question is SAFE TO CACHE (D10/INFRA-5).

    Deliberately NOT the same predicate as `is_followup`, and the difference is the point.
    The two have opposite cost asymmetries:

      condense — a false positive wastes one cheap rewrite. Over-eager is correct.
      cache    — a false positive permanently disables caching for that question shape.

    `is_followup` treats anything of three words or fewer as dependent, which is right for
    condense and catastrophic here: "What is cirrhosis?" IS three words. Reusing it would
    have switched off the response cache for the single most common question shape in the
    product — a large, silent cost increase that no test would have flagged as a failure.
    Caught by a test asserting the fast path SURVIVES, which is why that test exists.

    So this asks the narrower question: does the text point at something outside itself?
    Anaphora does. A one- or two-word fragment ("why?", "and then?") does too, having no
    room to name a subject. "What is cirrhosis?" names its subject and is cacheable.
    """
    if len(question.split()) <= 2:
        return True
    # A CONTINUATION opener ("and the treatment?", "what about children?") carries the
    # subject forward from the previous turn without using a pronoun, so the pronoun test
    # alone misses it.
    if _CONTINUATION_RE.match(question.strip()):
        return True
    # PRONOUNS ONLY — not the looser `the (condition|treatment|...)` alternation that
    # `is_followup` uses. That alternation matches "Describe the treatment options for
    # pneumonia", which names its own subject and is perfectly safe to cache; treating it
    # as thread-bound would lose the hit on a very ordinary phrasing for no correctness
    # gain. Anything that reaches here and still refers outward does so with a pronoun.
    return bool(_PRONOUN_RE.search(question))

class RagPipeline:
    def __init__(
        self,
        *,
        settings: Settings,
        embedder: EmbedderPort,
        store: VectorStorePort,
        model: ModelPort,
        reranker: RerankerPort | None = None,
        sparse: SparseEncoder | None = None,
    ) -> None:
        self._s = settings
        self._embedder = embedder
        self._store = store
        self._model = model
        self._reranker = reranker
        self._sparse = sparse
        self._system_prompt = load_prompt("system", settings.prompt_version)
        self._answer_prompt = load_prompt("answer", settings.prompt_version)
        self._condense_prompt = load_prompt("condense", settings.prompt_version)
        # Self-authored stages, composed with LCEL. Each is inspectable and unit-testable.
        # Explicit generic params pin the async-callable overload (LCEL's RunnableLambda
        # stubs otherwise infer Never — the framework-indirection tax D6 acknowledged).
        # Prep = everything up to generation. Shared by both the streaming and
        # non-streaming paths so their answers cannot diverge.
        _RL = RunnableLambda[PipelineState, PipelineState]
        self._prep_chain: Runnable[PipelineState, PipelineState] = (
            _RL(self._traced("guard", self._guard))
            | _RL(self._traced("condense", self._condense))
            | _RL(self._traced("embed", self._embed))
            | _RL(self._traced("retrieve", self._retrieve))
            | _RL(self._traced("rerank", self._rerank))
            | _RL(self._traced("build_context", self._build_context))
        )
        self._chain: Runnable[PipelineState, PipelineState] = self._prep_chain | _RL(
            self._traced("generate", self._generate)
        )


    def _traced(self, name: str, fn: Any) -> Any:
        """Wrap a pipeline stage so every stage emits a span, uniformly.

        Done at the chain level rather than inside each stage body: six hand-edited
        try/with blocks would drift, and a stage added later would silently go
        untraced — the failure mode where your trace shows a gap and you cannot tell
        whether the work was fast or simply uninstrumented.

        Span attributes are PII-FREE by construction (see observability/tracing.py):
        a question fingerprint, never the question.
        """

        async def _run(state: PipelineState) -> PipelineState:
            with stage_span(name, question_fp=question_fingerprint(state.question)) as span:
                out = await fn(state)
                set_attrs(
                    span,
                    n_chunks=len(out.chunks),
                    n_citations=len(out.citations),
                    short_circuited=out.answer is not None,
                    answer_kind=out.answer.kind.value if out.answer else None,
                )
                return out

        return _run

    async def answer(
        self, question: str, history: Sequence[Message] | None = None
    ) -> Answer:
        state: PipelineState = await self._chain.ainvoke(
            PipelineState(question=question, history=list(history or []))
        )
        assert state.answer is not None
        return state.answer

    async def answer_verbose(self, question: str) -> tuple[Answer, list[str]]:
        """Answer plus the FULL text of the passages the model saw.

        Exists for evaluation (D19): RAGAS faithfulness compares answer claims against the
        retrieved context, so truncated citation snippets would penalize a perfectly
        grounded answer. The API response deliberately does not carry full passages —
        that would bloat every user-facing payload to serve an offline concern.
        """
        state: PipelineState = await self._chain.ainvoke(PipelineState(question=question))
        assert state.answer is not None
        return state.answer, [c.text for c in state.chunks]

    async def stream_answer(
        self, question: str, history: Sequence[Message] | None = None
    ) -> AsyncIterator[SourcesEvent | TokenEvent | DoneEvent]:
        """Streaming counterpart of answer().

        The prep stages (embed -> retrieve -> build_context) are the SAME LCEL chain
        used by answer() — deliberately shared, so a streamed answer can never drift
        from its non-streamed equivalent. Only the generate stage differs.
        """
        t_start = time.perf_counter()
        state: PipelineState = await self._prep_chain.ainvoke(
            PipelineState(question=question, history=list(history or []))
        )

        # No-answer gate fired during prep: emit an empty source set and finish.
        if state.answer is not None:
            yield SourcesEvent(citations=[])
            yield DoneEvent(
                kind=state.answer.kind,
                text=state.answer.text,
                citations=[],
                timings=state.answer.timings,
                refusal_category=state.answer.refusal_category,
            )
            return

        # Citations are known before generation — emit them first (see schema note).
        yield SourcesEvent(citations=state.citations)

        user = self._answer_prompt.render(context=state.context, question=state.question)
        messages = [
            Message(role="system", content=self._system_prompt.text),
            Message(role="user", content=user),
        ]

        parts: list[str] = []
        # Which leg actually produced the tokens. Defaults to the configured first leg so
        # a non-failover model (tests, a single venue) behaves exactly as before.
        served: dict[str, str | None] = {
            "model_id": self._model.model_id,
            # None rather than a guess: with no failover chain there is no leg to name,
            # and inventing one would make the field unreliable exactly where it matters.
            "venue": None,
        }

        def _record_venue(venue: str, model_id: str) -> None:
            served["model_id"] = model_id
            served["venue"] = venue

        # Providers report usage in the FINAL SSE frame, long after the first token, so it
        # cannot be a return value - it arrives through a callback or not at all. Without
        # capturing it here DoneEvent.usage stayed the empty default, and every streamed
        # answer was recorded as costing nothing.
        usage_seen = Usage()

        def _record_usage(u: Usage) -> None:
            nonlocal usage_seen
            usage_seen = u

        ttft_ms: float | None = None
        # Hold the provider stream so we can close it DETERMINISTICALLY. Relying on GC
        # to finalize it leaves the provider connection open after a client disconnects,
        # which means we keep paying for tokens nobody will read (D20).
        # on_venue exists only on FailoverModel; a plain ModelPort (tests, a single
        # configured venue) must keep working untouched, so it is passed conditionally.
        stream_kwargs: dict[str, Any] = {}
        stream_params = inspect.signature(self._model.stream).parameters
        if "on_venue" in stream_params:
            stream_kwargs["on_venue"] = _record_venue
        if "on_usage" in stream_params:
            stream_kwargs["on_usage"] = _record_usage
        provider_stream = self._model.stream(
            messages=messages,
            max_tokens=self._s.llm_max_output_tokens,
            temperature=0.2,
            **stream_kwargs,
        )
        # S10.2b DEFECT FIX: the output dosage net (D18/S12.3) ran ONLY in _generate,
        # which serves answer(). stream_answer() had no such check — and the browser uses
        # this path for every question, so the "last line of defence" defended the one
        # path real users never take. It passed every test because the eval harness calls
        # answer_verbose() and test_streaming.py asserts nothing about dosages.
        #
        # A stream cannot un-send bytes, so detection stops generation immediately and the
        # terminal DoneEvent carries the refusal. CONTRACT: done.text is AUTHORITATIVE —
        # a client MUST discard accumulated tokens whenever done.kind != "grounded".
        # Scanning the whole buffer per token is O(n^2), bounded by llm_max_output_tokens
        # (512 -> ~2KB), i.e. microseconds; correctness beats cleverness in a safety net.
        blocked = False
        try:
            async for delta in provider_stream:
                if ttft_ms is None:
                    ttft_ms = (time.perf_counter() - t_start) * 1000
                parts.append(delta)
                if contains_dosage_instruction("".join(parts)):
                    logger.warning("output guardrail blocked a dosage instruction mid-stream")
                    blocked = True
                    break
                yield TokenEvent(text=delta)
        finally:
            aclose = getattr(provider_stream, "aclose", None)
            if aclose is not None:
                await aclose()

        timings_now = state.timings.model_copy(
            update={"ttft_ms": ttft_ms, "total_ms": (time.perf_counter() - t_start) * 1000}
        )
        if blocked:
            yield DoneEvent(
                kind=AnswerKind.REFUSED,
                text=_MESSAGES[RefusalCategory.DOSAGE],
                citations=[],
                refusal_category=RefusalCategory.DOSAGE.value,
                model_id=served["model_id"],
                venue=served["venue"],
                usage=usage_seen,
                timings=timings_now,
            )
            return

        text = "".join(parts)
        timings = state.timings.model_copy(
            update={"ttft_ms": ttft_ms, "total_ms": (time.perf_counter() - t_start) * 1000}
        )
        # Same abstention rule as the non-streaming path (S3 finding).
        if _is_abstention(text):
            yield DoneEvent(
                kind=AnswerKind.NO_ANSWER,
                text=NO_ANSWER_TEXT,
                citations=[],
                model_id=served["model_id"],
                venue=served["venue"],
                usage=usage_seen,
                timings=timings,
            )
            return
        yield DoneEvent(
            kind=AnswerKind.GROUNDED,
            text=text,
            citations=state.citations,
            model_id=served["model_id"],
            venue=served["venue"],
            usage=usage_seen,
            timings=timings,
        )

    async def _guard(self, state: PipelineState) -> PipelineState:
        """Input guardrail — the FIRST stage, before any expensive or model-driven work.

        S6 measured refusal_correctness at 0.50 because refusals depended on retrieval
        failing. Classifying here makes the control structural: it cannot be prompt-
        injected (no model is involved), costs nothing (no GPU or provider call), and
        is deterministic (D18).
        """
        refusal = classify_input(state.question)
        if refusal is None:
            return state
        logger.info("input refused: category=%s", refusal.category.value)
        return replace(
            state,
            answer=Answer(
                kind=AnswerKind.REFUSED,
                text=refusal.message,
                refusal_category=refusal.category.value,
                timings=state.timings,  # citations stay empty: a refusal cites nothing
            ),
        )

    # A follow-up is short and leans on the previous turn. Gating on that shape is
    # deliberate: an unconditional LLM rewrite would add a model round-trip to EVERY
    # question, and TTFT is already ~6s because embed+rerank run on CPU before
    # generation even starts. First questions - the overwhelming majority - must not
    # pay for a feature they cannot use.
    _ANAPHORA = re.compile(
        r"\b(it|its|that|this|those|these|they|them|their|he|she|him|her|"
        r"the (condition|disease|drug|treatment|illness|infection|one))\b",
        re.IGNORECASE,
    )

    def _needs_condense(self, question: str) -> bool:
        """True when the question cannot stand on its own. See `is_followup`."""
        return is_followup(question)

    async def _condense(self, state: PipelineState) -> PipelineState:
        """Rewrite a follow-up into a standalone question, for RETRIEVAL ONLY.

        S20: "Describe the treatment options for pneumonia." answered correctly, and
        the follow-up "What causes it?" returned no_answer - because the pipeline
        embedded the literal string "What causes it?", which matches nothing in a
        medical encyclopedia. History was stored, shown in the sidebar, and never
        reached retrieval: a chat UI over a stateless engine. `condense_ms` had been
        in StageTimings since the schema was written, and was summed into total_ms by
        a stage that did not exist - the same declared-but-dead shape as trace_answer
        (I4.3) and the four unwritten metrics (I5.4).

        `state.question` is NEVER overwritten. The user is shown, and the model
        answers, what they actually typed; only the retrieval query is rewritten.
        Overwriting it would put words in the user's mouth in the transcript, in the
        Langfuse trace, and in the stored history that feeds the NEXT condense.
        """
        state.search_question = state.question
        if not state.history or not self._needs_condense(state.question):
            return state

        t0 = time.perf_counter()
        transcript = "\n".join(
            f"{m.role}: {m.content[:400]}" for m in state.history[-6:]
        )
        prompt = self._condense_prompt.render(
            history=transcript, question=state.question
        )
        try:
            completion = await self._model.complete(
                messages=[Message(role="user", content=prompt)],
                max_tokens=self._s.condense_max_tokens,
                temperature=0.0,
            )
            # `.splitlines()[0]` on an EMPTY string raises IndexError, and an empty
            # completion is not hypothetical: a reasoning model given a small max_tokens
            # spends the whole budget on reasoning and returns "". Measured on
            # groq/openai/gpt-oss-20b - 64 tokens -> "", 256 tokens -> "What causes
            # pneumonia?". The except below then swallowed the IndexError as though the
            # model had failed, so every follow-up in every thread quietly fell back to
            # searching the literal pronoun.
            lines = completion.text.strip().strip('"').splitlines()
            rewritten = lines[0].strip() if lines else ""
        except Exception:  # noqa: BLE001
            # Degrade to the literal question rather than failing the request: a
            # broken rewrite must cost CONTEXT, never the answer (D21).
            logger.warning("condense failed; searching the literal question")
            return state

        # Guard against a model that ignores the instruction and ANSWERS instead of
        # rewriting. A "rewrite" many times longer than the original is not a rewrite,
        # and feeding an essay into the embedder would poison retrieval outright.
        if rewritten and len(rewritten) <= max(200, len(state.question) * 6):
            state.search_question = rewritten
        # model_copy, not dataclasses.replace: StageTimings is a pydantic model. The
        # surrounding stages use replace() on PipelineState, which IS a dataclass - two
        # different objects, two different update calls.
        state.timings = state.timings.model_copy(
            update={"condense_ms": (time.perf_counter() - t0) * 1000}
        )
        return state

    async def _embed(self, state: PipelineState) -> PipelineState:
        if state.answer is not None:  # refused by the guardrail
            return state
        t0 = time.perf_counter()
        # The CONDENSED question, not the literal one: this is the whole point of
        # the condense stage. Generation still answers state.question.
        vec = await self._embedder.embed_query(state.search_question or state.question)
        return replace(
            state,
            query_vector=vec,
            timings=state.timings.model_copy(
                update={"embed_ms": (time.perf_counter() - t0) * 1000}
            ),
        )

    async def _retrieve(self, state: PipelineState) -> PipelineState:
        if state.answer is not None:  # refused upstream
            return state
        t0 = time.perf_counter()
        kwargs: dict[str, object] = {
            "query_vector": state.query_vector,
            "query_text": state.search_question or state.question,
            "top_k": self._s.retrieval_top_k,
        }
        # Hybrid (D3): BM25 sparse alongside dense, fused server-side by RRF. Optional so
        # the pipeline still works dense-only (tests, or before a hybrid re-index).
        if self._sparse is not None:
            # DEGRADE to dense-only rather than failing the request.
            #
            # S20.10: `Bm25Encoder._model` is a cached_property that constructs
            # SparseTextEmbedding on FIRST USE, and fastembed downloads the model from
            # HuggingFace at that moment. Nothing warms it, so the first real query paid
            # the download - and when the network blipped, the raw httpx ConnectError
            # propagated out of _retrieve untyped, past every degradation ladder, into the
            # generic `except Exception` in the stream route. 17 requests were counted as
            # medbot_errors_total{error_type="unhandled",status="500"}.
            #
            # Dense retrieval alone still answers; losing the sparse half costs RECALL on
            # keyword-ish queries, which is a quality regression, not an outage. So it is
            # metered like the reranker fallback instead of being invisible.
            try:
                kwargs["sparse_vector"] = await asyncio.to_thread(
                    self._sparse.encode_query, state.search_question or state.question
                )
            except Exception:  # noqa: BLE001 - any transport/model failure degrades
                degradations_total.labels(
                    component="sparse", reason="unavailable"
                ).inc()
                logger.warning(
                    "sparse encoder unavailable; serving DENSE-ONLY retrieval "
                    "(recall degraded)",
                    exc_info=True,
                )
        chunks = await self._store.search(**kwargs)  # type: ignore[arg-type]
        return replace(
            state,
            chunks=chunks,
            timings=state.timings.model_copy(
                update={"retrieve_ms": (time.perf_counter() - t0) * 1000}
            ),
        )

    async def _rerank(self, state: PipelineState) -> PipelineState:
        """Cross-encoder rerank of the fused candidates (D3).

        DEGRADES, never fails (D21): if the reranker is down we serve fusion order with a
        logged quality dip. A reranker outage must not become a user-visible outage.
        """
        if self._reranker is None or not state.chunks:
            return state
        t0 = time.perf_counter()
        try:
            ranked = await self._reranker.rerank(
                query=state.search_question or state.question,
                chunks=state.chunks,
                top_k=self._s.rerank_top_k,
            )
        except RerankerError:
            # METERED, not just logged. Skipping the reranker changes which passages
            # ground the answer - it is a quality regression the user cannot see and the
            # caller is never told about. A log line cannot be graphed or alerted on, so
            # with RERANK_TIMEOUT below the reranker's own p95 this path became the NORMAL
            # path while every dashboard stayed green. A degradation that publishes no
            # signal is indistinguishable from working.
            degradations_total.labels(component="reranker", reason="unavailable").inc()
            logger.warning("reranker unavailable; serving fusion order (quality degraded)")
            return state
        return replace(
            state,
            chunks=ranked,
            timings=state.timings.model_copy(
                update={"rerank_ms": (time.perf_counter() - t0) * 1000}
            ),
        )

    async def _build_context(self, state: PipelineState) -> PipelineState:
        if state.answer is not None:  # refused upstream
            return state
        # ZERO candidates is a FAULT, not an abstention (P5.3).
        #
        # These two used to share a branch, and they mean opposite things. A vector search
        # over a populated collection always returns its nearest neighbours — however
        # irrelevant — so "scores were all too low" is a real, correct abstention. Getting
        # back NOTHING means the collection is empty, missing, or the alias points at
        # nothing: the index is unavailable.
        #
        # Conflating them is the worst failure mode this system has. A broken index would
        # answer every single question with a confident "I don't have reliable information
        # on that in my reference material" — indistinguishable, to the user, from a
        # truthful answer about a gap in the corpus. Every response is 200, no alert fires,
        # and the service looks perfectly healthy while being uniformly wrong.
        #
        # Surfaced by the P5.3 Qdrant drill: after a restart, the first query returned
        # no_answer while the collection was still loading.
        if not state.chunks:
            raise RetrievalError(
                "retrieval returned zero candidates — the index is empty, missing, or the "
                "alias resolves to nothing; refusing to report this as 'no information'"
            )
        # No-answer gate (D3): if nothing cleared the confidence floor, don't generate.
        best = max((c.effective_score for c in state.chunks), default=0.0)
        if best < self._s.no_answer_threshold:
            # total_ms MUST be summed here too. This path returns before _generate, which
            # is the only other place that computes it, so `state.timings.total_ms` was
            # still its 0.0 default - and postflight feeds exactly that number into
            # medbot_request_duration_seconds. Every free decline therefore observed ZERO
            # seconds into the latency histogram while really costing ~1.3s of embed +
            # retrieve + rerank, dragging p95 down and making the service look faster than
            # it is. Same defect as the one the comment in _generate describes, arrived at
            # from the other direction: there it under-counted, here it counted nothing.
            gate_timings = state.timings.model_copy(
                update={
                    "total_ms": (state.timings.embed_ms or 0)
                    + (state.timings.retrieve_ms or 0)
                    + (state.timings.rerank_ms or 0)
                    + (state.timings.condense_ms or 0)
                }
            )
            no_answer = Answer(
                kind=AnswerKind.NO_ANSWER, text=NO_ANSWER_TEXT, timings=gate_timings
            )
            return replace(state, answer=no_answer)
        context, citations = build_context(
            state.chunks[: self._s.rerank_top_k], max_input_tokens=self._s.llm_max_input_tokens
        )
        return replace(state, context=context, citations=citations)

    async def _generate(self, state: PipelineState) -> PipelineState:
        if state.answer is not None:  # short-circuited by the no-answer gate
            return state
        t0 = time.perf_counter()
        user = self._answer_prompt.render(context=state.context, question=state.question)
        completion = await self._model.complete(
            messages=[
                Message(role="system", content=self._system_prompt.text),
                Message(role="user", content=user),
            ],
            max_tokens=self._s.llm_max_output_tokens,
            temperature=0.2,
        )
        gen_ms = (time.perf_counter() - t0) * 1000
        # total_ms must sum EVERY stage. An earlier version omitted rerank_ms and reported
        # 354ms for a request whose wall time was 1113ms — a metric that hides the single
        # most expensive stage is worse than no metric, because it looks authoritative.
        timings = state.timings.model_copy(
            update={
                "generate_ms": gen_ms,
                "total_ms": gen_ms
                + (state.timings.embed_ms or 0)
                + (state.timings.retrieve_ms or 0)
                + (state.timings.rerank_ms or 0)
                + (state.timings.condense_ms or 0),
            }
        )
        # OUTPUT guardrail (D18) — last line of defence. If a dosage instruction slipped
        # past the input rules and the system prompt, it must not reach a user.
        if contains_dosage_instruction(completion.text):
            logger.warning("output guardrail blocked a dosage instruction")
            return replace(
                state,
                answer=Answer(
                    kind=AnswerKind.REFUSED,
                    text=_MESSAGES[RefusalCategory.DOSAGE],
                    refusal_category=RefusalCategory.DOSAGE.value,
                    model_id=completion.model_id,
                    venue=completion.venue,
                    usage=completion.usage,
                    timings=timings,
                ),
            )
        # An EMPTY completion is an abstention too — and it must be caught BEFORE the
        # grounded branch below (INFRA-5 #7).
        #
        # `Answer` refuses to construct a grounded answer with no text, and it is right to:
        # an uncited, wordless "answer" is the one thing this schema exists to prevent. But
        # the pipeline was handing it exactly that, so a legitimate model behaviour turned
        # into a ValidationError and a 500 — the user saw a crash where they should have
        # seen "I don't have reliable information on that".
        #
        # Not hypothetical, and not rare enough to ignore: a REASONING model emits its
        # reasoning inside the token budget and can return "" when the budget runs out
        # first. Observed on groq/openai/gpt-oss-20b for "Describe the treatment options
        # for pneumonia." The same root cause as the condense fix above, one stage later.
        #
        # NO_ANSWER rather than DEGRADED: from the reader's side nothing is degraded — the
        # system simply has nothing to say, which is precisely what no_answer means. It is
        # also the honest label, and honest beats flattering when the subject is medical.
        if not completion.text.strip():
            logger.warning(
                "empty completion from %s; relabelling as no_answer", completion.model_id
            )
            return replace(
                state,
                answer=Answer(
                    kind=AnswerKind.NO_ANSWER,
                    text=NO_ANSWER_TEXT,
                    model_id=completion.model_id,
                    venue=completion.venue,
                    usage=completion.usage,
                    timings=timings,
                ),
            )
        # The model abstained despite retrieval clearing the coarse threshold: relabel honestly.
        if _is_abstention(completion.text):
            return replace(
                state,
                answer=Answer(
                    kind=AnswerKind.NO_ANSWER,
                    text=NO_ANSWER_TEXT,
                    model_id=completion.model_id,
                    venue=completion.venue,
                    usage=completion.usage,
                    timings=timings,
                ),
            )
        answer = Answer(
            kind=AnswerKind.GROUNDED,
            text=completion.text,
            citations=state.citations,
            confidence=max((c.score for c in state.citations), default=0.0),
            model_id=completion.model_id,
            venue=completion.venue,
            usage=completion.usage,
            timings=timings,
        )
        return replace(state, answer=answer)
