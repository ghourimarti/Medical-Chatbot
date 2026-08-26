"""Domain contracts.

DECISION GATE A (locked): an Answer is not a string. `kind` makes "grounded",
"no answer", "refused", and "degraded" *typed, distinguishable states* — because the
degradation ladder (D21), the eval harness (D19), and the cache (D10, which must never
store a refusal) all have to branch on them. A str cannot be branched on safely.
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
    """A corpus chunk returned by retrieval. Carries per-stage scores so hybrid fusion
    (D3) and reranking are observable rather than collapsed into one opaque number."""

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
    """Per-stage latency. Exists because D6 chose owned control flow specifically so every
    stage is measurable against the Phase-1 budget (retrieval p95 250ms, TTFT p95 2.0s)."""

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


class Answer(BaseModel):
    """The API's response contract. Invariant: a GROUNDED answer must cite its sources
    (D18: output-must-cite). Enforcing it here means an uncited medical claim cannot be
    constructed at all — the type system carries the safety rule, not a code review."""

    kind: AnswerKind
    text: str
    citations: list[Citation] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    model_id: str | None = None
    usage: Usage = Field(default_factory=Usage)
    timings: StageTimings = Field(default_factory=StageTimings)
    cache_hit: bool = False
    # WHICH safety rule fired (D18/S10.2). The guardrail already classifies EMERGENCY /
    # SELF_HARM / DOSAGE / DIAGNOSIS / INJECTION and has distinct copy for each, but the
    # category was logged and then DISCARDED — so every client had to re-derive it by
    # pattern-matching refusal prose. That is two sources of truth for a safety rule, and
    # the copy-side one drifts the first time someone rewords a message. "Contact
    # emergency services now" and "ask your pharmacist" must never render identically.
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
        """D10: never cache refusals, no-answers, or degraded responses."""
        return self.kind is AnswerKind.GROUNDED and not self.cache_hit


class QueryRequest(BaseModel):
    """Request-size caps are a security control (D18), not a nicety."""

    question: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, max_length=128)
    stream: bool = True
    # Which saved thread this turn belongs to (S20b). Optional: the anonymous single-thread
    # path predates conversations and must keep working with no thread at all (D24).
    #
    # CALLER-SUPPLIED AND THEREFORE UNTRUSTED. Ownership is verified in serving.preflight
    # before anything is written; passing it straight to the writer would let anyone append
    # turns to a stranger's thread, and since a thread is prompt context, that is a write
    # into someone else's conversation rather than merely a read of it.
    conversation_id: uuid.UUID | None = None


# ---------------------------------------------------------------------------
# Streaming contract (D7). FROZEN: the frontend (S10) builds against these names.
#
# Ordering matters and is a deliberate UX decision: in RAG, retrieval completes
# *before* generation starts, so citations are known up front. Emitting `sources`
# first lets a client paint the source panel while the answer is still being
# written — better perceived latency at zero cost.
# ---------------------------------------------------------------------------


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
    # observably equivalent — the property the DoneEvent docstring already promises.
    refusal_category: str | None = None


class ErrorEvent(BaseModel):
    """Terminal event on failure. Once bytes are on the wire an HTTP status can no
    longer be changed, so errors must be in-band — this carries the RFC 7807 body."""

    problem: dict[str, Any]
