"""Delta comparison + gate logic. These are the rules the CI gate enforces."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

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


# incomparability must announce itself


def _rep(run_id: str, judge: str, aggregates: dict, coverage: dict | None = None, n_qa: int = 10):
    from medeval.schema import CaseResult

    rows = [
        CaseResult(
            case_id=f"qa-{i:03d}", category="qa", scores={}, answer="a",
            n_contexts=1, latency_ms=1.0,
        )
        for i in range(1, n_qa + 1)
    ]
    return EvalReport(
        run_id=run_id, created_at=datetime.now(UTC), target="t", dataset="d.jsonl",
        dataset_sha256="0" * 64, judge=judge, n_cases=n_qa, aggregates=aggregates,
        coverage=coverage or {}, per_case=rows,
    )


def test_judge_mismatch_is_announced() -> None:
    """Groq retiring a judge mid-project made every stored judge score incomparable to
    every new one. The delta must say so rather than leaving it to a careful reader."""
    before = _rep("before", "judge_v1(llama-3.3-70b, temp=0)", {"faithfulness": 0.66})
    after = _rep("after", "judge_v2(gpt-oss-120b, temp=0)", {"faithfulness": 0.91})
    out = compare(before, after)
    assert "JUDGE MISMATCH" in out
    assert "NOT comparable" in out


def test_same_judge_produces_no_mismatch_warning() -> None:
    j = "judge_v2(gpt-oss-120b, temp=0)"
    out = compare(_rep("b", j, {"faithfulness": 0.66}), _rep("a", j, {"faithfulness": 0.91}))
    assert "JUDGE MISMATCH" not in out


def test_thin_coverage_is_flagged() -> None:
    """The defect: 1 of 60 cases scored, printed as a run-level result."""
    j = "judge_v2(gpt-oss-120b, temp=0)"
    after = _rep("after", j, {"answer_relevancy": 0.9537}, coverage={"answer_relevancy": 1})
    before = _rep("before", j, {"answer_relevancy": 0.88}, coverage={"answer_relevancy": 10})
    out = compare(before, after)
    assert "THIN COVERAGE" in out
    assert "n=1/10" in out


def test_full_coverage_is_not_flagged() -> None:
    j = "judge_v2(gpt-oss-120b, temp=0)"
    cov = {"answer_relevancy": 10}
    out = compare(
        _rep("b", j, {"answer_relevancy": 0.88}, coverage=cov),
        _rep("a", j, {"answer_relevancy": 0.95}, coverage=cov),
    )
    assert "THIN COVERAGE" not in out


# the gate must not compare against a run that never produced a result


def _write_report(tmp: Path, run_id: str, aggregates: dict) -> Path:
    p = tmp / f"{run_id}.json"
    p.write_text(
        json.dumps({
            "run_id": run_id, "created_at": "2026-01-01T00:00:00Z", "target": run_id.split("-")[0],
            "dataset": "d.jsonl", "dataset_sha256": "0" * 64, "judge": "j",
            "n_cases": 1, "aggregates": aggregates, "per_case": [],
        }),
        encoding="utf-8",
    )
    return p


def test_all_errored_run_is_not_a_usable_baseline(tmp_path: Path) -> None:
    """A run where every case errored records that the harness ran, not what the system did."""
    from medeval.compare import is_usable_baseline

    broken = _write_report(tmp_path, "demo-20260820", {"error_rate": 1.0, "completed": 0.0})
    good = _write_report(tmp_path, "demo-20260710", {"error_rate": 0.0, "completed": 1.0})
    assert is_usable_baseline(broken) is False
    assert is_usable_baseline(good) is True


def test_latest_report_skips_the_broken_newer_run(tmp_path: Path) -> None:
    """The exact trap: the BROKEN report is newest, so a naive `latest` picks it and
    the delta reports `error_rate 1 -> 0` as a PASS."""
    from medeval.compare import latest_report

    _write_report(tmp_path, "demo-20260710", {"error_rate": 0.0, "completed": 1.0})
    _write_report(tmp_path, "demo-20260820", {"error_rate": 1.0, "completed": 0.0})
    assert latest_report(tmp_path, "demo").name == "demo-20260710.json"


def test_no_usable_report_raises_rather_than_guessing(tmp_path: Path) -> None:
    from medeval.compare import latest_report

    _write_report(tmp_path, "demo-20260820", {"error_rate": 1.0, "completed": 0.0})
    with pytest.raises(FileNotFoundError, match="no USABLE reports"):
        latest_report(tmp_path, "demo")


def test_corrected_variant_outranks_the_report_it_corrects(tmp_path: Path) -> None:
    """A rescored report exists BECAUSE the original was wrong, so it must win selection.
    Plain name sort does the opposite ('-' < '.'), which silently fed the gate the very
    metrics a rescore had been run to fix."""
    from medeval.compare import latest_report

    ok = {"error_rate": 0.0, "completed": 1.0}
    _write_report(tmp_path, "pipeline-20260816-194331", ok)
    _write_report(tmp_path, "pipeline-20260816-194331-rescored", ok)
    assert latest_report(tmp_path, "pipeline").name == "pipeline-20260816-194331-rescored.json"


def test_newer_run_beats_an_older_corrected_one(tmp_path: Path) -> None:
    """Derivation rank must only break ties WITHIN a run, never override recency."""
    from medeval.compare import latest_report

    ok = {"error_rate": 0.0, "completed": 1.0}
    _write_report(tmp_path, "pipeline-20260101-000000-rescored", ok)
    _write_report(tmp_path, "pipeline-20260816-194331", ok)
    assert latest_report(tmp_path, "pipeline").name == "pipeline-20260816-194331.json"


def test_sidecar_files_are_not_mistaken_for_reports(tmp_path: Path) -> None:
    """rejudge writes `<run>.judge-partial.json` next to the reports for resumability, and
    it matches the same *.json glob. An empty checkpoint `{}` was accepted as a usable
    report because the guard defaulted `completed` to 1.0 when the key was absent."""
    from medeval.compare import is_usable_baseline, latest_report

    (tmp_path / "pipeline-20260816-rescored.judge-partial.json").write_text("{}", encoding="utf-8")
    assert is_usable_baseline(tmp_path / "pipeline-20260816-rescored.judge-partial.json") is False

    _write_report(tmp_path, "pipeline-20260816", {"error_rate": 0.0, "completed": 1.0})
    assert latest_report(tmp_path, "pipeline").name == "pipeline-20260816.json"


def test_partially_written_checkpoint_is_also_rejected(tmp_path: Path) -> None:
    """A checkpoint with real content is still not a report."""
    from medeval.compare import is_usable_baseline

    p = tmp_path / "pipeline-x.judge-partial.json"
    p.write_text(json.dumps({"qa-001": {"faithfulness": 0.9}}), encoding="utf-8")
    assert is_usable_baseline(p) is False


# the gate's CONTRACT is its exit code


def test_cli_gate_exits_nonzero_on_regression(tmp_path: Path, capsys) -> None:
    """The gate is only a gate because CI reads its exit code. Asserting the table text
    would not catch the failure this test exists for: the print used to run BEFORE the
    gate check, so a rendering error meant the verdict never executed at all."""
    from medeval.cli import main

    _write_report(tmp_path, "demo-20260101", {"error_rate": 0.0, "completed": 1.0,
                                              "refusal_correctness": 0.95})
    _write_report(tmp_path, "pipeline-20260102", {"error_rate": 0.0, "completed": 1.0,
                                                  "refusal_correctness": 0.10})
    code = main(["compare", "--before", "demo", "--after", "pipeline",
                 "--reports", str(tmp_path), "--gate"])
    assert code == 1
    assert "GATE FAILED" in capsys.readouterr().out


def test_cli_gate_exits_zero_when_thresholds_are_met(tmp_path: Path) -> None:
    """The other half of the contract, and the half that was impossible on Windows: a
    passing run must be able to exit 0."""
    from medeval.cli import main

    good = {"error_rate": 0.0, "completed": 1.0, "refusal_correctness": 0.99,
            "unsafe_answer_rate": 0.0, "dont_know_correctness": 1.0,
            "citation_presence": 1.0, "answered": 1.0, "answer_relevancy": 0.95}
    _write_report(tmp_path, "demo-20260101", good)
    _write_report(tmp_path, "pipeline-20260102", good)
    assert main(["compare", "--before", "demo", "--after", "pipeline",
                 "--reports", str(tmp_path), "--gate"]) == 0


def test_cli_gate_survives_a_non_utf8_stdout(tmp_path: Path, monkeypatch) -> None:
    """The original defect, pinned: the delta table contains → and ✅, and on a cp1252
    console printing it raised UnicodeEncodeError before the gate ever ran."""
    import io

    from medeval.cli import main

    good = {"error_rate": 0.0, "completed": 1.0, "refusal_correctness": 0.99,
            "unsafe_answer_rate": 0.0, "dont_know_correctness": 1.0,
            "citation_presence": 1.0, "answered": 1.0, "answer_relevancy": 0.95}
    _write_report(tmp_path, "demo-20260101", good)
    _write_report(tmp_path, "pipeline-20260102", good)
    monkeypatch.setattr(
        "sys.stdout", io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    )
    assert main(["compare", "--before", "demo", "--after", "pipeline",
                 "--reports", str(tmp_path), "--gate"]) == 0
