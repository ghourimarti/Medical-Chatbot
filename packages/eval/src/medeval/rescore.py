"""Recompute DETERMINISTIC metrics on a saved report — no model calls (D19).

Two reasons this exists:
  1. Metric definitions evolve. When a classifier is fixed (as in S6, where the abstention
     regex was coupled to one phrasing), every historical report must be re-scored or
     before/after comparisons silently mix metric versions.
  2. Judge calls cost money and quota. The S6 run exhausted Groq's 100k tokens/day tier;
     re-running 90 cases to fix a regex would be absurd when every answer is already saved.

RAGAS scores are carried through untouched — they cannot be recomputed without the judge.
"""

from __future__ import annotations

import statistics
from pathlib import Path

from medeval.dataset import load_cases
from medeval.metrics import CLASSIFIER_VERSION, deterministic_scores
from medeval.schema import CaseResult, EvalCase, EvalReport, TargetAnswer

_RAGAS_KEYS = {"faithfulness", "answer_relevancy", "context_precision", "context_recall"}


def rescore(report: EvalReport, dataset_path: Path) -> EvalReport:
    by_id: dict[str, EvalCase] = {c.id: c for c in load_cases(dataset_path)}
    results: list[CaseResult] = []
    for row in report.per_case:
        case = by_id.get(row.case_id)
        if case is None:  # dataset changed since the run — keep the row untouched
            results.append(row)
            continue
        answer = TargetAnswer(
            answer=row.answer,
            contexts=[""] * row.n_contexts,
            latency_ms=row.latency_ms,
            error=row.error,
        )
        merged: dict[str, float | None] = dict(deterministic_scores(case, answer))
        # RAGAS values are judge-derived and cannot be recomputed offline — carry them.
        merged.update({k: v for k, v in row.scores.items() if k in _RAGAS_KEYS})
        results.append(row.model_copy(update={"scores": merged}))

    return report.model_copy(
        update={
            "run_id": f"{report.run_id}-rescored",
            "per_case": results,
            "aggregates": _aggregate(results),
            "notes": [*report.notes, f"rescored with {CLASSIFIER_VERSION}"],
        }
    )


def _aggregate(results: list[CaseResult]) -> dict[str, float]:
    agg: dict[str, list[float]] = {}
    for r in results:
        for k, v in r.scores.items():
            if v is not None:
                agg.setdefault(k, []).append(v)
    out = {k: round(statistics.fmean(v), 4) for k, v in agg.items() if v}
    lat = sorted(r.latency_ms for r in results)
    if lat:
        out["latency_p50_ms"] = round(statistics.median(lat), 1)
        out["latency_p95_ms"] = round(lat[min(len(lat) - 1, int(0.95 * len(lat)))], 1)
    out["error_rate"] = round(sum(1 for r in results if r.error) / len(results), 4)
    return out
