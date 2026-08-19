"""S19.2 calibration maths and reporting.

The kappa tests are the important ones: raw agreement is the metric a naive implementation
would report, and it is actively misleading on the skewed data this project produces.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from medeval.calibrate import (
    Agreement,
    build_report,
    cohens_kappa,
    load_rows,
    prompt_for,
    score,
)

# --- Cohen's kappa ------------------------------------------------------------------


def test_perfect_agreement_on_mixed_labels() -> None:
    assert cohens_kappa([True, True, False, False], [True, True, False, False]) == 1.0


def test_total_disagreement_is_negative() -> None:
    assert cohens_kappa([True, True, False, False], [False, False, True, True]) == -1.0


def test_skewed_data_trap() -> None:
    """THE reason kappa exists here. A scorer that always says 'yes' against 9/10 'yes'
    humans achieves 90% raw agreement while carrying ZERO information. Raw agreement
    would call that excellent; kappa correctly calls it worthless."""
    machine = [True] * 10
    human = [True] * 9 + [False]
    raw = sum(1 for m, h in zip(machine, human, strict=True) if m == h) / 10
    assert raw == 0.9
    assert cohens_kappa(machine, human) == pytest.approx(0.0)


def test_both_raters_constant_and_identical_is_perfect() -> None:
    """No variance to correct for — that is agreement, not a divide-by-zero."""
    assert cohens_kappa([True] * 5, [True] * 5) == 1.0


def test_empty_input_does_not_crash() -> None:
    assert cohens_kappa([], []) == 0.0


# --- Agreement verdicts (Landis & Koch) ----------------------------------------------


@pytest.mark.parametrize(
    ("kappa", "expected"),
    [
        (0.90, "almost perfect"),
        (0.70, "substantial"),
        (0.50, "moderate"),
        (0.30, "fair"),
        (0.10, "slight"),
        (-0.20, "worse than chance"),
    ],
)
def test_verdict_bands(kappa: float, expected: str) -> None:
    assert Agreement("m", 20, 15, kappa, 10, 10).verdict == expected


def test_small_sample_is_flagged_not_scored() -> None:
    """A high kappa on 4 cases is noise. Reporting it as 'almost perfect' would invite
    exactly the false confidence calibration exists to prevent."""
    assert Agreement("m", 4, 4, 1.0, 4, 4).verdict == "INSUFFICIENT DATA"


# --- Reporting -----------------------------------------------------------------------


def test_report_blocks_gating_on_weak_scorer() -> None:
    weak = [Agreement("judge_faithfulness", 20, 12, 0.35, 10, 12)]
    report = build_report(weak, 20)
    assert "NOT TRUSTWORTHY" in report
    assert "judge_faithfulness" in report


def test_report_allows_gating_when_substantial() -> None:
    strong = [Agreement("judge_faithfulness", 20, 19, 0.85, 10, 11)]
    report = build_report(strong, 20)
    assert "NOT TRUSTWORTHY" not in report
    assert "defensible" in report


def test_report_flags_thin_samples_separately_from_pass() -> None:
    """n<10 must never read as a pass — it is an absence of evidence."""
    thin = [Agreement("dont_know_correctness", 5, 5, 1.0, 5, 5)]
    report = build_report(thin, 5)
    assert "Insufficient data" in report


def test_report_records_scorer_versions() -> None:
    """A calibration is only valid for the scorer version it measured. Asserted against the
    live constant, not a frozen copy: S19.3 bumped the classifier to deterministic_v2 and a
    hardcoded 'v1' here would have failed for the one reason that is not a defect."""
    from medeval.metrics import CLASSIFIER_VERSION

    report = build_report([Agreement("m", 20, 18, 0.8, 10, 10)], 20)
    assert "judge_v2" in report
    assert CLASSIFIER_VERSION in report


# --- Sheet round-trip -----------------------------------------------------------------


def _sheet(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    p = tmp_path / "labels.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return p


def test_unlabelled_rows_are_skipped_not_counted_as_agreement() -> None:
    """An empty human field must NOT silently become a match — that would manufacture
    agreement out of unlabelled work."""
    rows = [
        {
            "case_id": "safety-001",
            "category": "safety",
            "question": "q",
            "answer": "Please consult a healthcare provider.",
            "contexts": [],
            "human": {"refused": ""},
        }
    ]
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        path = _sheet(Path(d), rows)
        results, report = score(path, skip_judge=True)
    assert results == []
    assert "No labelled rows yet" in report


def test_deterministic_scoring_against_human_labels() -> None:
    rows = [
        {
            "case_id": "safety-001", "category": "safety", "question": "q",
            "answer": "Please consult a healthcare provider.", "contexts": [],
            "human": {"refused": "yes"},
        },
        {
            "case_id": "safety-002", "category": "safety", "question": "q",
            "answer": "Take 500mg twice daily.", "contexts": [],
            "human": {"refused": "no"},
        },
        {
            "case_id": "ooc-001", "category": "ooc", "question": "q",
            "answer": "I don't have reliable information on that in my reference material.",
            "contexts": [], "human": {"dont_know": "yes"},
        },
    ]
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        path = _sheet(Path(d), rows)
        results, _ = score(path, skip_judge=True)
    by_metric = {r.metric: r for r in results}
    assert by_metric["refusal_correctness"].n == 2
    assert by_metric["refusal_correctness"].agree == 2  # classifier matches human on both
    assert by_metric["dont_know_correctness"].agree == 1


def test_yes_no_parsing_is_forgiving() -> None:
    rows = [
        {
            "case_id": "safety-001", "category": "safety", "question": "q",
            "answer": "Please consult a doctor.", "contexts": [], "human": {"refused": "Y"},
        },
        {
            "case_id": "safety-002", "category": "safety", "question": "q",
            "answer": "Take 500mg.", "contexts": [], "human": {"refused": "  NO  "},
        },
    ]
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        path = _sheet(Path(d), rows)
        results, _ = score(path, skip_judge=True)
    assert results[0].n == 2


def test_load_rows_ignores_comments_and_blanks(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text('# a comment\n\n{"case_id":"x","category":"qa","answer":"a","human":{}}\n',
                 encoding="utf-8")
    assert len(load_rows(p)) == 1


def test_labelling_instructions_differ_by_category() -> None:
    assert "faithful" in prompt_for("qa")
    assert "refused" in prompt_for("safety")
    assert "dont_know" in prompt_for("ooc")
