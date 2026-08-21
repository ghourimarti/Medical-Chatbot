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
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from langchain_core.runnables import Runnable, RunnableLambda

from medapi.guardrails import (
    _MESSAGES,
    RefusalCategory,
    classify_input,
    contains_dosage_instruction,
)
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
    query_vector: list[float] = field(default_factory=list)
    chunks: list[RetrievedChunk] = field(default_factory=list)
    context: str = ""
    citations: list[Citation] = field(default_factory=list)
    answer: Answer | None = None
    timings: StageTimings = field(default_factory=StageTimings)


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
        # Self-authored stages, composed with LCEL. Each is inspectable and unit-testable.
        # Explicit generic params pin the async-callable overload (LCEL's RunnableLambda
        # stubs otherwise infer Never — the framework-indirection tax D6 acknowledged).
        # Prep = everything up to generation. Shared by both the streaming and
        # non-streaming paths so their answers cannot diverge.
        _RL = RunnableLambda[PipelineState, PipelineState]
        self._prep_chain: Runnable[PipelineState, PipelineState] = (
            _RL(self._traced("guard", self._guard))
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

    async def answer(self, question: str) -> Answer:
        state: PipelineState = await self._chain.ainvoke(PipelineState(question=question))
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
        self, question: str
    ) -> AsyncIterator[SourcesEvent | TokenEvent | DoneEvent]:
        """Streaming counterpart of answer().

        The prep stages (embed -> retrieve -> build_context) are the SAME LCEL chain
        used by answer() — deliberately shared, so a streamed answer can never drift
        from its non-streamed equivalent. Only the generate stage differs.
        """
        t_start = time.perf_counter()
        state: PipelineState = await self._prep_chain.ainvoke(PipelineState(question=question))

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
        ttft_ms: float | None = None
        # Hold the provider stream so we can close it DETERMINISTICALLY. Relying on GC
        # to finalize it leaves the provider connection open after a client disconnects,
        # which means we keep paying for tokens nobody will read (D20).
        provider_stream = self._model.stream(
            messages=messages,
            max_tokens=self._s.llm_max_output_tokens,
            temperature=0.2,
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
                model_id=self._model.model_id,
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
                model_id=self._model.model_id,
                timings=timings,
            )
            return
        yield DoneEvent(
            kind=AnswerKind.GROUNDED,
            text=text,
            citations=state.citations,
            model_id=self._model.model_id,
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

    async def _embed(self, state: PipelineState) -> PipelineState:
        if state.answer is not None:  # refused by the guardrail
            return state
        t0 = time.perf_counter()
        vec = await self._embedder.embed_query(state.question)
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
            "query_text": state.question,
            "top_k": self._s.retrieval_top_k,
        }
        # Hybrid (D3): BM25 sparse alongside dense, fused server-side by RRF. Optional so
        # the pipeline still works dense-only (tests, or before a hybrid re-index).
        if self._sparse is not None:
            kwargs["sparse_vector"] = await asyncio.to_thread(
                self._sparse.encode_query, state.question
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
                query=state.question, chunks=state.chunks, top_k=self._s.rerank_top_k
            )
        except RerankerError:
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
            no_answer = Answer(
                kind=AnswerKind.NO_ANSWER, text=NO_ANSWER_TEXT, timings=state.timings
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
            usage=completion.usage,
            timings=timings,
        )
        return replace(state, answer=answer)
