"""Golden-set loading, validation, and stratified sampling."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from medeval.schema import EvalCase


def load_cases(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            case = EvalCase.model_validate(json.loads(line))
        except Exception as e:
            raise ValueError(f"{path.name}:{lineno}: {e}") from e
        if case.id in seen:
            raise ValueError(f"{path.name}:{lineno}: duplicate id {case.id}")
        seen.add(case.id)
        cases.append(case)
    if not cases:
        raise ValueError(f"{path.name}: no cases found")
    return cases


def dataset_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def category_counts(cases: list[EvalCase]) -> dict[str, int]:
    return dict(Counter(c.category for c in cases))


def stratified_sample(cases: list[EvalCase], n: int) -> list[EvalCase]:
    """Deterministic proportional sample, at least one case per category present. Cases
    come in file order within a category, so the sample is stable across runs."""
    if n >= len(cases):
        return list(cases)
    by_cat: dict[str, list[EvalCase]] = {}
    for c in cases:
        by_cat.setdefault(c.category, []).append(c)
    take: dict[str, int] = {
        cat: max(1, round(n * len(items) / len(cases))) for cat, items in by_cat.items()
    }
    while sum(take.values()) > n:
        biggest = max(take, key=lambda c: take[c])
        take[biggest] -= 1
    picked: list[EvalCase] = []
    for cat, items in by_cat.items():
        picked.extend(items[: take[cat]])
    return picked
