import json
from pathlib import Path

import pytest

from medeval.dataset import category_counts, load_cases, stratified_sample
from medeval.schema import EvalCase


def _case(id: str, category: str, **over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": id,
        "category": category,
        "question": "What causes asthma attacks in adults?",
        "expected_behavior": {"qa": "answer", "safety": "refuse_redirect", "ooc": "dont_know"}[
            category
        ],
    }
    if category == "qa":
        base["ground_truth"] = "Asthma attacks are triggered by allergens and irritants."
    base.update(over)
    return base


def test_valid_qa_case_parses() -> None:
    case = EvalCase.model_validate(_case("qa-001", "qa"))
    assert case.category == "qa"


def test_qa_without_ground_truth_rejected() -> None:
    with pytest.raises(ValueError, match="require ground_truth"):
        EvalCase.model_validate(_case("qa-001", "qa", ground_truth=None))


def test_mismatched_behavior_rejected() -> None:
    with pytest.raises(ValueError, match="requires expected_behavior"):
        EvalCase.model_validate(_case("safety-001", "safety", expected_behavior="answer"))


def test_id_prefix_must_match_category() -> None:
    with pytest.raises(ValueError):
        EvalCase.model_validate(_case("qa-001", "safety"))


def test_jsonl_roundtrip_and_duplicate_detection(tmp_path: Path) -> None:
    lines = [json.dumps(_case("qa-001", "qa")), json.dumps(_case("safety-001", "safety"))]
    p = tmp_path / "d.jsonl"
    p.write_text("\n".join(lines), encoding="utf-8")
    cases = load_cases(p)
    assert category_counts(cases) == {"qa": 1, "safety": 1}

    p.write_text("\n".join([lines[0], lines[0]]), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate id"):
        load_cases(p)


def test_stratified_sample_keeps_category_mix() -> None:
    cases = [EvalCase.model_validate(_case(f"qa-{i:03d}", "qa")) for i in range(1, 9)]
    cases += [EvalCase.model_validate(_case(f"safety-{i:03d}", "safety")) for i in range(1, 3)]
    cases += [EvalCase.model_validate(_case("ooc-001", "ooc"))]
    picked = stratified_sample(cases, 5)
    assert len(picked) == 5
    cats = category_counts(picked)
    assert cats.get("qa", 0) >= 1 and cats.get("safety", 0) >= 1 and cats.get("ooc", 0) >= 1
    assert picked == stratified_sample(cases, 5)  # deterministic
