"""Delta comparison + gate logic (D19). These are the rules the CI gate (S17) enforces."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from medeval.compare import GATE_THRESHOLDS, METRIC_DIRECTION, compare, gate_failures
from medeval.schema import EvalReport


def _report(target: str, **aggregates: float) -> EvalReport:
    return EvalReport(
        run_id=f"{target}-20260101-000000",
        created_at=datetime.now(UTC),
        target=target,
        dataset="golden_core_v1.jsonl",
        dataset_sha256="0" * 64,
        judge="judge_v1",
        n_cases=90,
        aggregates=aggregates,
        per_case=[],
    )


def test_quality_improvement_is_marked_better() -> None:
    table = compare(
        _report("demo", faithfulness=0.66), _report("pipeline", faithfulness=0.88)
    )
    assert "+0.22 ✅" in table


def test_quality_regression_is_flagged() -> None:
    table = compare(
        _report("demo", faithfulness=0.88), _report("pipeline", faithfulness=0.66)
    )
    assert "⚠️" in table


def test_latency_direction_is_inverted() -> None:
    """Lower latency is BETTER. Treating every metric as higher-is-better would report a
    latency regression as an improvement — the classic direction bug."""
    faster = compare(
        _report("a", latency_p95_ms=2000.0), _report("b", latency_p95_ms=900.0)
    )
    assert "✅" in faster
    slower = compare(
        _report("a", latency_p95_ms=900.0), _report("b", latency_p95_ms=2000.0)
    )
    assert "⚠️" in slower


def test_error_rate_is_lower_is_better() -> None:
    table = compare(_report("a", error_rate=0.10), _report("b", error_rate=0.00))
    assert "✅" in table


def test_gate_fails_below_threshold() -> None:
    failing = _report(
        "pipeline", faithfulness=0.70, answer_relevancy=0.90,
        refusal_correctness=0.99, dont_know_correctness=0.95, citation_presence=1.0,
    )
    assert gate_failures(failing) == ["faithfulness"]
    assert "❌ FAIL" in compare(_report("demo"), failing)


def test_gate_passes_when_all_thresholds_met() -> None:
    passing = _report(
        "pipeline", faithfulness=0.88, answer_relevancy=0.90,
        refusal_correctness=0.96, dont_know_correctness=1.0, citation_presence=1.0,
        unsafe_answer_rate=0.0, answered=1.0, error_rate=0.0,
    )
    assert gate_failures(passing) == []
    assert "✅ PASS" in compare(_report("demo"), passing)


def test_missing_metric_is_visible_not_silently_dropped() -> None:
    """A metric present in only one run must show up — silently dropping it hides
    exactly the regressions a gate exists to catch."""
    table = compare(_report("demo", faithfulness=0.66), _report("pipeline", answered=1.0))
    assert "only in one run" in table


def test_gate_only_covers_metrics_absent_from_report() -> None:
    """A report missing a gated metric must not fail on it — an unmeasured metric is not
    a failed metric (that distinction keeps --skip-ragas runs usable)."""
    assert gate_failures(_report("pipeline", answered=1.0)) == []


@pytest.mark.parametrize("metric", sorted(GATE_THRESHOLDS))
def test_every_gated_metric_has_a_sane_threshold(metric: str) -> None:
    """In range, and pointing the right way. A lower-is-better gate legitimately sits at
    0.0 (`unsafe_answer_rate` tolerates no leak), so the old `0.0 < t` bound would have
    rejected the strictest threshold in the table."""
    threshold = GATE_THRESHOLDS[metric]
    assert 0.0 <= threshold <= 1.0
    assert metric in METRIC_DIRECTION, f"{metric} is gated but has no declared direction"
    if METRIC_DIRECTION[metric] == "higher":
        assert threshold > 0.0, "a higher-is-better gate at 0.0 gates nothing"
