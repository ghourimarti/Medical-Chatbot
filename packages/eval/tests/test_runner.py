"""Keyless end-to-end test: the mock target exercises runner -> score -> report offline,
so CI verifies the pipeline without an API key."""

from pathlib import Path

from medeval.paths import DATASETS_DIR
from medeval.runner import run_eval


def test_runner_end_to_end_mock(tmp_path: Path) -> None:
    report, path = run_eval(
        target_name="mock",
        dataset_path=DATASETS_DIR / "golden_seed_v0.jsonl",
        out_dir=tmp_path,
        skip_ragas=True,
    )
    assert report.n_cases == 10
    assert report.target == "mock"
    assert report.aggregates["error_rate"] == 0.0
    assert report.aggregates["completed"] == 1.0
    assert path.exists()
    assert (tmp_path / f"{report.run_id}.md").exists()
    # deterministic metrics were computed for each category present
    assert "citation_presence" in report.aggregates  # qa
    assert "refusal_correctness" in report.aggregates  # safety
    assert "dont_know_correctness" in report.aggregates  # ooc


def test_golden_core_is_well_formed() -> None:
    from medeval.dataset import category_counts, load_cases

    cases = load_cases(DATASETS_DIR / "golden_core_v1.jsonl")
    assert category_counts(cases) == {"qa": 60, "safety": 20, "ooc": 10}
