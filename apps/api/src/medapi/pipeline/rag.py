"""The RAG query pipeline, an LCEL chain of self-authored runnables.

Every stage is a plain async function wrapped as a RunnableLambda, composed with `|`. LCEL
supplies the composition, streaming and batching plumbing and nothing else. Prebuilt chains
(RetrievalQA, create_retrieval_chain) are ruff-banned: that kind of opacity is what let the
original k=1 ship unexamined.

Order: condense -> embed -> retrieve -> rerank -> no-answer gate -> build_context ->
generate.
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
    """Minimal structural contract for BM25 encoding, so the pipeline needs no
    fastembed or qdrant import of its own."""

    def encode_query(self, text: str) -> object: ...


NO_ANSWER_TEXT = "I don't have reliable information on that in my reference material."

# The model emits NO_ANSWER_TEXT when the context is insufficient. When it does, the answer
# isn't grounded even though retrieval cleared the threshold, so relabel it NO_ANSWER and
# drop the citations. Hybrid retrieval plus the reranker moves more of this work back onto
# the retrieval-side gate.
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
    # What retrieval searches for. Usually the same as `question`; for a follow-up it's
    # the condensed standalone form. Kept separate so the user sees, and the model answers,
    # the question they actually typed rather than our rewrite of it.
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
    """Loose test for whether to attempt a condense rewrite.

    Two cheap signals: the question refers to something (anaphora), or is too short to name
    a subject at all ("why?"). Over-eager on purpose, since a false positive costs one small
    rewrite that returns the question unchanged.
    """
    if len(question.split()) <= 3:
        return True
    return bool(_ANAPHORA_RE.search(question))


def is_context_dependent(question: str) -> bool:
    """Strict test for whether a question is safe to cache.

    Not the same predicate as `is_followup`, and the difference matters, because the two
    have opposite cost asymmetries:

      condense  a false positive wastes one cheap rewrite, so over-eager is right.
      cache     a false positive permanently disables caching for that question shape.

    `is_followup` treats three words or fewer as dependent, which suits condense and is
    wrong here: "What is cirrhosis?" is three words. Reusing it would have switched off the
    response cache for the most common question shape in the product, a silent cost increase
    no test would report as a failure. There's a test asserting the fast path survives for
    exactly that reason.

    So this asks the narrower question: does the text point at something outside itself?
    Anaphora does. A one- or two-word fragment ("why?", "and then?") does too, having no
    room to name a subject. "What is cirrhosis?" names its subject and is cacheable.
    """
    if len(question.split()) <= 2:
        return True
    # A continuation opener ("and the treatment?", "what about children?") carries the
    # subject forward without a pronoun, so the pronoun test alone misses it.
    if _CONTINUATION_RE.match(question.strip()):
        return True
    # Pronouns only, not the looser `the (condition|treatment|...)` alternation
    # `is_followup` uses. That one matches "Describe the treatment options for pneumonia",
    # which names its own subject and is safe to cache, so treating it as thread-bound
    # would lose the hit on an ordinary phrasing for no correctness gain. Anything getting
    # this far and still referring outward does so with a pronoun.
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
        # The explicit generic params pin the async-callable overload; RunnableLambda's
        # stubs otherwise infer Never.
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
        grounded answer. The API response doesn't carry full passages, since that would
        bloat every user-facing payload to serve an offline concern.
        """
        state: PipelineState = await self._chain.ainvoke(PipelineState(question=question))
        assert state.answer is not None
        return state.answer, [c.text for c in state.chunks]

    async def stream_answer(
        self, question: str, history: Sequence[Message] | None = None
    ) -> AsyncIterator[SourcesEvent | TokenEvent | DoneEvent]:
        """Streaming counterpart of answer().

        The prep stages (embed -> retrieve -> build_context) are the same LCEL chain
        answer() uses, shared so a streamed answer can't drift from its non-streamed
        equivalent. Only the generate stage differs.
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

        # Citations are known before generation, so emit them first.
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

        # Providers report usage in the final SSE frame, long after the first token, so it
        # can't be a return value: it arrives via callback or not at all. Without capturing
        # it here DoneEvent.usage stayed empty and every streamed answer looked free.
        usage_seen = Usage()

        def _record_usage(u: Usage) -> None:
            nonlocal usage_seen
            usage_seen = u

        ttft_ms: float | None = None
        # Hold the provider stream so it can be closed deterministically. Leaving it to GC
        # keeps the connection open after a client disconnects, so we go on paying for
        # tokens nobody will read.
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
        # The output dosage net used to run only in _generate, which serves answer().
        # stream_answer() had no check at all, and the browser uses this path for every
        # question, so the last line of defence covered the one path real users never take.
        # It passed every test because the eval harness calls answer_verbose() and the
        # streaming tests assert nothing about dosages.
        #
        # A stream can't un-send bytes, so detection stops generation immediately and the
        # terminal DoneEvent carries the refusal. done.text is authoritative: a client must
        # discard accumulated tokens whenever done.kind != "grounded".
        #
        # Rescanning the whole buffer per token is O(n^2), but bounded by
        # llm_max_output_tokens (512, so ~2KB) it's microseconds.
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
        """Input guardrail, and the first stage, before any expensive or model-driven work.

        An early eval put refusal_correctness at 0.50 because refusals depended on
        retrieval failing. Classifying here makes the control structural: no model is
        involved so it can't be prompt-injected, it costs no GPU or provider call, and it
        is deterministic.
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

    # A follow-up is short and leans on the previous turn, so gate on that shape. An
    # unconditional LLM rewrite adds a model round-trip to every question, and TTFT is
    # already ~6s with embed and rerank on CPU before generation starts. First questions,
    # which are most of them, shouldn't pay for a feature they can't use.
    _ANAPHORA = re.compile(
        r"\b(it|its|that|this|those|these|they|them|their|he|she|him|her|"
        r"the (condition|disease|drug|treatment|illness|infection|one))\b",
        re.IGNORECASE,
    )

    def _needs_condense(self, question: str) -> bool:
        """True when the question cannot stand on its own. See `is_followup`."""
        return is_followup(question)

    async def _condense(self, state: PipelineState) -> PipelineState:
        """Rewrite a follow-up into a standalone question, for retrieval only.

        "Describe the treatment options for pneumonia." answered correctly while the
        follow-up "What causes it?" returned no_answer, because the pipeline embedded the
        literal string "What causes it?", which matches nothing in a medical encyclopedia.
        History was stored and shown in the sidebar but never reached retrieval: a chat UI
        over a stateless engine. `condense_ms` had been in StageTimings since the schema was
        written and was summed into total_ms by a stage that did not exist.

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
            # `.splitlines()[0]` on an empty string raises IndexError, and an empty
            # completion isn't hypothetical: a reasoning model with a small max_tokens
            # spends the whole budget reasoning and returns "". On gpt-oss-20b, 64 tokens
            # gave "" and 256 gave "What causes pneumonia?". The except below then
            # swallowed the IndexError as if the model had failed, so every follow-up fell
            # back to searching the literal pronoun.
            lines = completion.text.strip().strip('"').splitlines()
            rewritten = lines[0].strip() if lines else ""
        except Exception:  # noqa: BLE001
            # Degrade to the literal question rather than failing the request. A broken
            # rewrite should cost context, never the answer.
            logger.warning("condense failed; searching the literal question")
            return state

        # Guard against a model that ignores the instruction and answers instead of
        # rewriting. A "rewrite" many times longer than the original isn't one, and feeding
        # an essay to the embedder poisons retrieval.
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
        # BM25 sparse alongside dense, fused server-side by RRF. Optional, so the pipeline
        # still works dense-only in tests or before a hybrid re-index.
        if self._sparse is not None:
            # Degrade to dense-only rather than failing the request.
            #
            # `Bm25Encoder._model` is a cached_property that builds SparseTextEmbedding on
            # first use, and fastembed downloads the model from HuggingFace at that moment.
            # Nothing warms it, so the first real query paid the download, and when the
            # network blipped the raw httpx ConnectError propagated out of _retrieve
            # untyped, past every degradation ladder, into the generic `except Exception`
            # in the stream route. 17 requests were counted as unhandled 500s.
            #
            # Dense retrieval alone still answers. Losing the sparse half costs recall on
            # keyword-ish queries, which is a quality regression rather than an outage, so
            # it's metered like the reranker fallback instead of being invisible.
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

        Degrades, never fails: if the reranker is down, serve fusion order and log the
        quality dip. A reranker outage shouldn't become a user-visible one.
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
            # Metered, not just logged. Skipping the reranker changes which passages
            # ground the answer, and that's a quality regression nobody can see. A log line
            # can't be graphed or alerted on, so with RERANK_TIMEOUT set below the
            # reranker's own p95 this became the normal path while dashboards stayed green.
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
        # Zero candidates is a fault, not an abstention.
        #
        # These two used to share a branch and they mean opposite things. A vector search
        # over a populated collection always returns its nearest neighbours, however
        # irrelevant, so "scores were all too low" is a real abstention. Getting back
        # nothing means the collection is empty or missing, or the alias resolves to
        # nothing: the index is unavailable.
        #
        # Conflating them is the worst failure mode here. A broken index answers every
        # question with a confident "I don't have reliable information on that in my
        # reference material", which to a user is indistinguishable from a truthful answer
        # about a gap in the corpus. Every response is 200, no alert fires, and the service
        # looks healthy while being uniformly wrong.
        #
        # Found in a Qdrant drill: after a restart the first query returned no_answer while
        # the collection was still loading.
        if not state.chunks:
            raise RetrievalError(
                "retrieval returned zero candidates — the index is empty, missing, or the "
                "alias resolves to nothing; refusing to report this as 'no information'"
            )
        # No-answer gate: if nothing cleared the confidence floor, don't generate.
        best = max((c.effective_score for c in state.chunks), default=0.0)
        if best < self._s.no_answer_threshold:
            # total_ms has to be summed here too. This path returns before _generate,
            # which is the only other place that computes it, so `state.timings.total_ms`
            # was still 0.0, and postflight feeds exactly that into the duration histogram.
            # Every free decline observed zero seconds while really costing ~1.3s of embed
            # + retrieve + rerank, dragging p95 down. Same defect as the one _generate
            # describes, from the other direction: there it under-counted, here it counted
            # nothing.
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
        # total_ms sums every stage. An earlier version omitted rerank_ms and reported
        # 354ms for a request whose wall time was 1113ms.
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
        # Output guardrail, the last line of defence. If a dosage instruction slipped past
        # the input rules and the system prompt, it must not reach a user.
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
        # An empty completion is an abstention too, and has to be caught before the
        # grounded branch below.
        #
        # `Answer` refuses to construct a grounded answer with no text, which is right: an
        # uncited, wordless answer is what the schema exists to prevent. But the pipeline
        # was handing it exactly that, so ordinary model behaviour became a ValidationError
        # and a 500, and the user saw a crash instead of "I don't have reliable information
        # on that".
        #
        # Not rare either: a reasoning model spends the token budget on reasoning and can
        # return "" when it runs out. Seen on gpt-oss-20b for "Describe the treatment
        # options for pneumonia." Same root cause as the condense fix above, one stage on.
        #
        # NO_ANSWER rather than DEGRADED, because from the reader's side nothing is
        # degraded: the system has nothing to say, which is what no_answer means.
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
