"""Dataset and report contracts. The golden set outlives every pipeline it scores."""

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
    # Retrieved passages, kept so judge metrics can be recomputed offline. A throttled
    # judge once returned NaN for all 60 faithfulness scores and the only remedy was a
    # 30-minute re-run against a rate-limited provider. ~180KB for 90 cases.
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
    # How many cases actually fed each aggregate. Without it, a report published
    # `answer_relevancy: 0.9537` computed from one of 60 qa cases: a throttled judge
    # returns NaN, NaNs drop out before the mean, and what survives averages into
    # something that reads like a full-sample result. Carrying the n makes thin coverage
    # hard to publish by accident.
    coverage: dict[str, int] = Field(default_factory=dict)
