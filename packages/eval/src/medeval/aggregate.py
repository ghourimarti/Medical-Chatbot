"""Aggregation of per-case scores — the single place a report's headline numbers are made.

Consolidated in S6.12a. Two identical `_aggregate` copies previously lived in runner.py
and rescore.py, so the coverage defect below had to be fixed twice or not at all.

The defect: aggregates are means over non-null scores. A throttled judge returns NaN,
NaN becomes None, None is skipped — and the survivors are averaged into a value that is
printed exactly like a full-sample result. The S6 pipeline report published
`answer_relevancy: 0.9537` from ONE of 60 qa cases; the S1 demo baseline published
`faithfulness: 0.6634` from 23 of 60. Neither number was wrong arithmetically; both were
uninterpretable without an n that nothing recorded.
"""

from __future__ import annotations

import statistics

from medeval.schema import CaseResult


def aggregate_scores(results: list[CaseResult]) -> tuple[dict[str, float], dict[str, int]]:
    """Return (aggregates, coverage) where coverage[m] = cases contributing to aggregates[m]."""
    agg: dict[str, list[float]] = {}
    for r in results:
        for k, v in r.scores.items():
            if v is not None:
                agg.setdefault(k, []).append(v)

    out = {k: round(statistics.fmean(v), 4) for k, v in agg.items() if v}
    coverage = {k: len(v) for k, v in agg.items() if v}

    lat = sorted(r.latency_ms for r in results)
    if lat:
        out["latency_p50_ms"] = round(statistics.median(lat), 1)
        out["latency_p95_ms"] = round(lat[min(len(lat) - 1, int(0.95 * len(lat)))], 1)
        coverage["latency_p50_ms"] = len(lat)
        coverage["latency_p95_ms"] = len(lat)
    out["error_rate"] = round(sum(1 for r in results if r.error) / len(results), 4)
    coverage["error_rate"] = len(results)
    return out, coverage


def applicable_counts(results: list[CaseResult]) -> dict[str, int]:
    """How many cases each metric COULD have scored, by category applicability.

    Coverage alone answers "how many scored"; this answers "out of how many" — the pair is
    what makes `faithfulness 0.66 (23/60)` legible instead of `faithfulness 0.66`.
    """
    qa = sum(1 for r in results if r.category == "qa")
    safety = sum(1 for r in results if r.category == "safety")
    ooc = sum(1 for r in results if r.category == "ooc")
    total = len(results)
    return {
        "faithfulness": qa,
        "answer_relevancy": qa,
        "context_precision": qa,
        "context_recall": qa,
        "citation_presence": qa,
        "answered": qa,
        "refusal_correctness": safety,
        "unsafe_answer_rate": safety,
        "dont_know_correctness": ooc,
        "completed": total,
        "error_rate": total,
        "latency_p50_ms": total,
        "latency_p95_ms": total,
    }


def coverage_line(metric: str, coverage: dict[str, int], applicable: dict[str, int]) -> str:
    """Render `23/60` for a metric, or `23` when applicability is unknown."""
    got = coverage.get(metric)
    if got is None:
        return "—"
    total = applicable.get(metric)
    return f"{got}/{total}" if total else str(got)
