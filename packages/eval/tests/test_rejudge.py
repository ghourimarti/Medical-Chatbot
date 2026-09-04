"""judge metrics must be recomputable from a saved report, and a throttled
judge must never be able to publish thin coverage silently."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from medeval.paths import DATASETS_DIR
from medeval.rejudge import _rows_from_report, rejudge
from medeval.schema import CaseResult, EvalReport


def _report(rows: list[CaseResult]) -> EvalReport:
    return EvalReport(
        run_id="test-run", created_at=datetime.now(UTC), target="pipeline",
        dataset="golden_core_v1.jsonl", dataset_sha256="0" * 64, judge="judge_v1",
        n_cases=len(rows), aggregates={}, per_case=rows,
    )


def _row(cid: str, category: str, *, contexts: list[str] | None = None, error: str | None = None):
    return CaseResult(
        case_id=cid, category=category, scores={"faithfulness": None}, answer="an answer",
        n_contexts=len(contexts or []), contexts=contexts or [], latency_ms=1.0, error=error,
    )


def test_rows_only_include_judgeable_qa_cases() -> None:
    """safety/ooc have no ground truth to judge; context-less and errored rows cannot be."""
    report = _report([
        _row("qa-001", "qa", contexts=["ctx"]),
        _row("qa-002", "qa", contexts=[]),            # older report shape: no contexts
        _row("qa-003", "qa", contexts=["ctx"], error="boom"),
        _row("safety-001", "safety", contexts=["ctx"]),
        _row("ooc-001", "ooc", contexts=["ctx"]),
    ])
    rows, skipped = _rows_from_report(report, DATASETS_DIR / "golden_core_v1.jsonl")
    assert [c.id for c, _ in rows] == ["qa-001"]
    assert any("no stored contexts" in s for s in skipped)
    assert any("run errored" in s for s in skipped)


def test_rejudge_refuses_a_report_it_cannot_judge() -> None:
    """A report written before contexts were persisted must fail loudly, not return
    an empty-but-successful-looking result."""
    report = _report([_row("qa-001", "qa", contexts=[])])
    with pytest.raises(RuntimeError, match="no qa rows with stored contexts"):
        rejudge(report, DATASETS_DIR / "golden_core_v1.jsonl")


def test_partial_coverage_is_recorded_not_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulates the failure: the judge scores one case and NaNs the rest. The run must
    still complete, but the report must carry the n and an explicit UNSCORED note."""
    import medeval.rejudge as rj

    def fake_ragas(batch, only=None):
        out = {}
        for case, _ in batch:
            out[case.id] = {"faithfulness": 0.9 if case.id == "qa-001" else None}
        return out

    monkeypatch.setattr(rj, "ragas_scores", fake_ragas)
    rows = [_row(f"qa-{i:03d}", "qa", contexts=["ctx"]) for i in range(1, 6)]
    out, cov = rj.rejudge(
        _report(rows), DATASETS_DIR / "golden_core_v1.jsonl",
        batch_size=5, max_attempts=2, backoff_s=0.0, sleep_between_s=0.0,
    )
    assert cov["faithfulness"] == 1
    assert out.aggregates["faithfulness"] == 0.9
    assert any("UNSCORED" in n for n in out.notes)
    assert any("judge coverage" in n for n in out.notes)


def test_rejudge_merges_scores_and_stamps_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    import medeval.rejudge as rj

    monkeypatch.setattr(
        rj, "ragas_scores",
        lambda batch, only=None: {
            c.id: {"faithfulness": 0.77, "answer_relevancy": 0.88} for c, _ in batch
        },
    )
    rows = [_row(f"qa-{i:03d}", "qa", contexts=["ctx"]) for i in range(1, 4)]
    out, cov = rj.rejudge(
        _report(rows), DATASETS_DIR / "golden_core_v1.jsonl",
        batch_size=2, max_attempts=1, backoff_s=0.0, sleep_between_s=0.0,
    )
    assert cov["faithfulness"] == 3
    assert out.aggregates["faithfulness"] == 0.77
    assert "judge_v2" in out.judge
    assert out.run_id.endswith("-rejudged")
    assert not any("UNSCORED" in n for n in out.notes)


def test_checkpoint_is_written_and_resumed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A throttled rejudge runs for tens of minutes. Without checkpointing, a timeout
    discards every judge call already paid for — which would make this module's own
    premise ("never re-run what is already on disk") false of itself."""
    import medeval.rejudge as rj

    calls: list[int] = []

    def flaky(batch, only=None):
        calls.append(len(batch))
        return {c.id: {"faithfulness": 0.8} for c, _ in batch}

    monkeypatch.setattr(rj, "ragas_scores", flaky)
    rows = [_row(f"qa-{i:03d}", "qa", contexts=["ctx"]) for i in range(1, 5)]
    ckpt = tmp_path / "run.judge-partial.json"

    rj.rejudge(_report(rows), DATASETS_DIR / "golden_core_v1.jsonl", batch_size=2,
               max_attempts=1, backoff_s=0.0, sleep_between_s=0.0, checkpoint=ckpt)
    assert ckpt.is_file()
    saved = json.loads(ckpt.read_text(encoding="utf-8"))
    assert len(saved) == 4
    first_round = sum(calls)

    # Second run must consume the checkpoint and make ZERO further judge calls.
    calls.clear()
    out, cov = rj.rejudge(_report(rows), DATASETS_DIR / "golden_core_v1.jsonl", batch_size=2,
                          max_attempts=1, backoff_s=0.0, sleep_between_s=0.0, checkpoint=ckpt)
    assert calls == [], "resume should not re-issue judge calls for already-scored cases"
    assert cov["faithfulness"] == 4
    assert first_round == 4


def test_checkpoint_absent_is_not_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import medeval.rejudge as rj

    monkeypatch.setattr(rj, "ragas_scores",
                        lambda b, only=None: {c.id: {"faithfulness": 0.5} for c, _ in b})
    rows = [_row("qa-001", "qa", contexts=["ctx"])]
    _, cov = rj.rejudge(_report(rows), DATASETS_DIR / "golden_core_v1.jsonl", batch_size=1,
                        max_attempts=1, backoff_s=0.0, sleep_between_s=0.0,
                        checkpoint=tmp_path / "does-not-exist.json")
    assert cov["faithfulness"] == 1
