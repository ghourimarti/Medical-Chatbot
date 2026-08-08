"""The RAG query pipeline as an LCEL chain of SELF-AUTHORED runnables (D6 v2.1).

Every stage is a plain async function wrapped as a RunnableLambda; they compose with `|`.
LCEL supplies composition/streaming/batching plumbing — never hidden business logic. No
prebuilt chain (RetrievalQA, create_retrieval_chain) is used or importable (ruff-banned):
that opacity is exactly what let demo's k=1 ship unexamined.

S3 pipeline: embed -> retrieve -> (no-answer gate) -> build_context -> generate.
Reranking/hybrid (S6), streaming (S4), and caching (S8) slot in as added stages later.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace

from langchain_core.runnables import Runnable, RunnableLambda

from medapi.pipeline.context import build_context
from medcore.config import Settings
from medcore.ports import EmbedderPort, ModelPort, VectorStorePort
from medcore.prompts import load_prompt
from medcore.schema import Answer, AnswerKind, Citation, Message, RetrievedChunk, StageTimings

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
    ) -> None:
        self._s = settings
        self._embedder = embedder
        self._store = store
        self._model = model
        self._system_prompt = load_prompt("system", settings.prompt_version)
        self._answer_prompt = load_prompt("answer", settings.prompt_version)
        # Self-authored stages, composed with LCEL. Each is inspectable and unit-testable.
        # Explicit generic params pin the async-callable overload (LCEL's RunnableLambda
        # stubs otherwise infer Never — the framework-indirection tax D6 acknowledged).
        self._chain: Runnable[PipelineState, PipelineState] = (
            RunnableLambda[PipelineState, PipelineState](self._embed)
            | RunnableLambda[PipelineState, PipelineState](self._retrieve)
            | RunnableLambda[PipelineState, PipelineState](self._build_context)
            | RunnableLambda[PipelineState, PipelineState](self._generate)
        )

    async def answer(self, question: str) -> Answer:
        state: PipelineState = await self._chain.ainvoke(PipelineState(question=question))
        assert state.answer is not None
        return state.answer

    async def _embed(self, state: PipelineState) -> PipelineState:
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
        t0 = time.perf_counter()
        chunks = await self._store.search(
            query_vector=state.query_vector,
            query_text=state.question,
            top_k=self._s.retrieval_top_k,
        )
        return replace(
            state,
            chunks=chunks,
            timings=state.timings.model_copy(
                update={"retrieve_ms": (time.perf_counter() - t0) * 1000}
            ),
        )

    async def _build_context(self, state: PipelineState) -> PipelineState:
        # No-answer gate (D3): if nothing cleared the confidence floor, don't generate.
        best = max((c.effective_score for c in state.chunks), default=0.0)
        if not state.chunks or best < self._s.no_answer_threshold:
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
        timings = state.timings.model_copy(
            update={
                "generate_ms": gen_ms,
                "total_ms": gen_ms + (state.timings.embed_ms or 0)
                + (state.timings.retrieve_ms or 0),
            }
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
