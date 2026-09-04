"""Recompute the deterministic metrics on a saved report. No model calls.

Two reasons this exists:
  1. Metric definitions change. When a classifier gets fixed, historical reports have to
     be re-scored or before/after comparisons quietly mix metric versions.
  2. Judge calls cost quota. One run exhausted Groq's daily tier; re-running 90 cases to
     fix a regex is absurd when every answer is already saved.

RAGAS scores carry through untouched, since they can't be recomputed without the judge.
"""

from __future__ import annotations

from pathlib import Path

from medeval.aggregate import aggregate_scores
from medeval.dataset import load_cases
from medeval.metrics import CLASSIFIER_VERSION, deterministic_scores
from medeval.schema import CaseResult, EvalCase, EvalReport, TargetAnswer

_RAGAS_KEYS = {"faithfulness", "answer_relevancy", "context_precision", "context_recall"}


def rescore(report: EvalReport, dataset_path: Path) -> EvalReport:
    by_id: dict[str, EvalCase] = {c.id: c for c in load_cases(dataset_path)}
    results: list[CaseResult] = []
    for row in report.per_case:
        case = by_id.get(row.case_id)
        if case is None:  # dataset changed since the run, so leave the row alone
            results.append(row)
            continue
        answer = TargetAnswer(
            answer=row.answer,
            contexts=[""] * row.n_contexts,
            latency_ms=row.latency_ms,
            error=row.error,
        )
        merged: dict[str, float | None] = dict(deterministic_scores(case, answer))
        # RAGAS values are judge-derived, so they can't be recomputed offline.
        merged.update({k: v for k, v in row.scores.items() if k in _RAGAS_KEYS})
        results.append(row.model_copy(update={"scores": merged}))

    agg, cov = aggregate_scores(results)
    return report.model_copy(
        update={
            "run_id": f"{report.run_id}-rescored",
            "per_case": results,
            "aggregates": agg,
            "coverage": cov,
            "notes": [*report.notes, f"rescored with {CLASSIFIER_VERSION}"],
        }
    )
