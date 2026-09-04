"""Domain contracts.

An Answer is not a string. `kind` makes "grounded", "no answer", "refused" and "degraded"
distinguishable states, because the degradation ladder, the eval harness and the cache
(which must never store a refusal) all branch on them.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Role = Literal["system", "user", "assistant"]


class AnswerKind(StrEnum):
    GROUNDED = "grounded"
    NO_ANSWER = "no_answer"
    REFUSED = "refused"
    DEGRADED = "degraded"


class Message(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Role
    content: str


class RetrievedChunk(BaseModel):
    """A corpus chunk from retrieval. Keeps per-stage scores so fusion and reranking stay
    observable instead of collapsing into one opaque number."""

    id: str
    text: str
    source: str
    page: int | None = None
    dense_score: float | None = None
    sparse_score: float | None = None
    rerank_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def effective_score(self) -> float:
        for score in (self.rerank_score, self.dense_score, self.sparse_score):
            if score is not None:
                return score
        return 0.0


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: str
    source: str
    page: int | None = None
    snippet: str = ""
    score: float = 0.0


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class StageTimings(BaseModel):
    """Per-stage latency, so each stage can be measured against its own budget."""

    condense_ms: float | None = None
    embed_ms: float | None = None
    retrieve_ms: float | None = None
    rerank_ms: float | None = None
    generate_ms: float | None = None
    ttft_ms: float | None = None
    total_ms: float = 0.0


class Completion(BaseModel):
    """What a ModelPort returns for a non-streaming call."""

    text: str
    model_id: str
    usage: Usage = Field(default_factory=Usage)
    finish_reason: str | None = None
    # WHICH chain leg produced this (`local-sglang`, `groq`, ...). model_id cannot answer
    # that question: every venue in this chain can serve the SAME model id, and Groq's
    # model is literally named `openai/gpt-oss-20b`, so reading the venue off the model
    # name is wrong in both directions. Stamped by FailoverModel, which is the only layer
    # that knows the leg. None for a single non-failover model, where there is no chain.
    venue: str | None = None


class Answer(BaseModel):
    """The API's response contract. A grounded answer must cite its sources, and enforcing
    that here means an uncited medical claim can't be constructed in the first place."""

    kind: AnswerKind
    text: str
    citations: list[Citation] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    model_id: str | None = None
    usage: Usage = Field(default_factory=Usage)
    timings: StageTimings = Field(default_factory=StageTimings)
    cache_hit: bool = False
    # Mirrors Completion.venue onto the response contract. Without it "which engine
    # answered?" is only answerable by reading logs, which is not verification.
    venue: str | None = None
    # Which safety rule fired. The guardrail already classifies emergency / self-harm /
    # dosage / diagnosis / injection, but the category used to be logged and dropped, so
    # clients had to re-derive it by pattern-matching the refusal prose. That gives a
    # safety rule two sources of truth, and the prose one drifts on the first reword.
    refusal_category: str | None = None

    @model_validator(mode="after")
    def _grounded_answers_must_cite(self) -> Self:
        if self.kind is AnswerKind.GROUNDED:
            if not self.citations:
                raise ValueError("a grounded answer must carry at least one citation")
            if not self.text.strip():
                raise ValueError("a grounded answer must have text")
        if self.kind is AnswerKind.REFUSED and self.citations:
            raise ValueError("a refusal must not cite corpus sources")
        if self.refusal_category is not None and self.kind is not AnswerKind.REFUSED:
            raise ValueError("refusal_category is only meaningful on a refused answer")
        return self

    @property
    def is_grounded(self) -> bool:
        return self.kind is AnswerKind.GROUNDED

    @property
    def is_cacheable(self) -> bool:
        """Never cache refusals, no-answers, or degraded responses."""
        return self.kind is AnswerKind.GROUNDED and not self.cache_hit


class QueryRequest(BaseModel):
    """Request-size caps are a security control."""

    question: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, max_length=128)
    stream: bool = True
    # Which saved thread this turn belongs to. Optional, because the anonymous
    # single-thread path has to keep working with no thread at all.
    #
    # Caller-supplied, so untrusted: ownership is verified in serving.preflight before
    # anything is written. A thread is prompt context, so passing this straight to the
    # writer would let anyone append turns to a stranger's conversation.
    conversation_id: uuid.UUID | None = None


# Streaming contract. The frontend builds against these names, so treat them as frozen.
#
# Order matters: retrieval finishes before generation starts, so citations are known up
# front. Emitting `sources` first lets a client paint the source panel while the answer is
# still being written.


class StreamEventType(StrEnum):
    SOURCES = "sources"
    TOKEN = "token"
    DONE = "done"
    ERROR = "error"


class SourcesEvent(BaseModel):
    """Emitted once, before any token."""

    citations: list[Citation] = Field(default_factory=list)


class TokenEvent(BaseModel):
    text: str


class DoneEvent(BaseModel):
    """Terminal event on success. Carries the same information the non-streaming
    endpoint would have returned, so both paths stay observably equivalent."""

    kind: AnswerKind
    text: str
    citations: list[Citation] = Field(default_factory=list)
    model_id: str | None = None
    usage: Usage = Field(default_factory=Usage)
    timings: StageTimings = Field(default_factory=StageTimings)
    # Mirrors Answer.refusal_category so the streaming and non-streaming paths stay
    # observably equivalent, which is what the DoneEvent docstring promises.
    refusal_category: str | None = None
    # Streaming and non-streaming must remain observably equivalent (this class's own
    # docstring promises it), so the venue appears on both or the promise is false.
    venue: str | None = None


class ErrorEvent(BaseModel):
    """Terminal event on failure. Once bytes are on the wire the HTTP status can't change,
    so errors have to travel in-band; this carries the RFC 7807 body."""

    problem: dict[str, Any]
