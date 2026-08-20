"""Dataset and report contracts. The golden set outlives every pipeline — schema first."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

Category = Literal["qa", "safety", "ooc"]
ExpectedBehavior = Literal["answer", "refuse_redirect", "dont_know"]

EXPECTED_BEHAVIOR_FOR: dict[str, ExpectedBehavior] = {
    "qa": "answer",
    "safety": "refuse_redirect",
    "ooc": "dont_know",
}


class EvalCase(BaseModel):
    """One golden-set case. `ground_truth` is required for qa, absent for safety/ooc
    (their ground truth IS the expected behavior)."""

    id: str = Field(pattern=r"^(qa|safety|ooc)-\d{3}$")
    category: Category
    question: str = Field(min_length=8)
    ground_truth: str | None = None
    expected_behavior: ExpectedBehavior
    source: str | None = None
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.category == "qa" and not self.ground_truth:
            raise ValueError(f"{self.id}: qa cases require ground_truth")
        if self.expected_behavior != EXPECTED_BEHAVIOR_FOR[self.category]:
            raise ValueError(
                f"{self.id}: category '{self.category}' requires expected_behavior "
                f"'{EXPECTED_BEHAVIOR_FOR[self.category]}', got '{self.expected_behavior}'"
            )
        if not self.id.startswith(self.category):
            raise ValueError(f"{self.id}: id prefix must match category '{self.category}'")
        return self


class TargetAnswer(BaseModel):
    """What a pipeline under evaluation returned for one question."""

    answer: str
    contexts: list[str] = Field(default_factory=list)
    latency_ms: float
    model_id: str | None = None
    error: str | None = None


class CaseResult(BaseModel):
    case_id: str
    category: Category
    scores: dict[str, float | None]
    answer: str
    n_contexts: int
    latency_ms: float
    error: str | None = None
    # Retrieved passages, persisted so JUDGE metrics can be recomputed offline.
    # Learned in S6.10: a throttled judge returned NaN for all 60 faithfulness scores, and
    # without contexts the only remedy was a full 30-minute re-run against a rate-limited
    # provider. Storing them (~180KB for 90 cases) makes judge metrics re-scorable from a
    # saved report — the same reason deterministic metrics already are.
    contexts: list[str] = Field(default_factory=list)


class EvalReport(BaseModel):
    run_id: str
    created_at: datetime
    target: str
    dataset: str
    dataset_sha256: str
    judge: str
    n_cases: int
    aggregates: dict[str, float]
    per_case: list[CaseResult]
    notes: list[str] = Field(default_factory=list)
    # How many cases actually contributed to each aggregate (S6.12a).
    # Found while unblocking S6.12: the pipeline report published
    # `answer_relevancy: 0.9537` computed from ONE of 60 qa cases, and the demo baseline
    # published `faithfulness: 0.6634` from 23 of 60 — a throttled judge returns NaN,
    # NaNs are dropped before the mean, and the survivors are averaged into a number that
    # looks exactly like a full-sample result. Same silent-wrongness class as P5.5.4
    # (a metric declared but never emitted). An aggregate without its n is not a
    # measurement, it is an anecdote; reports now carry the n so thin coverage is
    # impossible to publish by accident.
    coverage: dict[str, int] = Field(default_factory=dict)
