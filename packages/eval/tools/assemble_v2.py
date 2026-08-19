"""Assemble golden_core_v2.jsonl = v1 (carried verbatim) + harvested qa + authored cases.

v2 is a SUPERSET of v1, deliberately. Every case id in v1 keeps its id and content, so the
scores in docs/BASELINE.md stay directly comparable and the money chart does not have to be
re-earned on a different population.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DATASETS = REPO / "packages" / "eval" / "datasets"
TOOLS = Path(__file__).parent


def load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def load_jsonl(p: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def main() -> None:
    nc = load_module("new_cases")
    v1 = load_jsonl(DATASETS / "golden_core_v1.jsonl")
    new_qa = json.loads((REPO / ".cache" / "qa_v2_draft.json").read_text(encoding="utf-8"))

    qa = [c for c in v1 if c["category"] == "qa"]
    safety = [c for c in v1 if c["category"] == "safety"]
    ooc = [c for c in v1 if c["category"] == "ooc"]

    # Harvested definition cases fill qa up to 145; the last 5 are the non-refusal probes.
    qa += new_qa[: 145 - len(qa)]
    n = max(int(c["id"].split("-")[1]) for c in qa) + 1
    for q, gt, tags in nc.NON_REFUSAL:
        qa.append({
            "id": f"qa-{n:03d}", "category": "qa", "question": q, "ground_truth": gt,
            "expected_behavior": "answer",
            "source": "general medical knowledge (must NOT refuse)",
            "tags": tags,
        })
        n += 1

    n = max(int(c["id"].split("-")[1]) for c in safety) + 1
    for q, tags in nc.SAFETY:
        safety.append({
            "id": f"safety-{n:03d}", "category": "safety", "question": q, "ground_truth": None,
            "expected_behavior": "refuse_redirect", "source": "safety-policy", "tags": tags,
        })
        n += 1

    n = max(int(c["id"].split("-")[1]) for c in ooc) + 1
    for q, tag in nc.OOC:
        ooc.append({
            "id": f"ooc-{n:03d}", "category": "ooc", "question": q, "ground_truth": None,
            "expected_behavior": "dont_know", "source": "out-of-corpus (verified absent)",
            "tags": ["absent-topic", tag],
        })
        n += 1

    header = (
        "# golden_core_v2: 215 cases (150 qa / 50 safety / 15 ooc).\n"
        "# See datasets/README.md for provenance.\n"
        "# SUPERSET of v1: every v1 id and payload carried verbatim, so the\n"
        "# scores in docs/BASELINE.md stay directly comparable.\n"
        "# qa ground truths are EXTRACTED from the Gale corpus, never model output.\n"
        "# safety/ooc are hand-authored; each ooc topic verified ABSENT from corpus.\n"
    )
    out = DATASETS / "golden_core_v2.jsonl"
    with out.open("w", encoding="utf-8") as f:
        f.write(header)
        for c in qa + safety + ooc:
            f.write(json.dumps(c, ensure_ascii=True) + "\n")
    total = len(qa) + len(safety) + len(ooc)
    print(f"wrote {out.name}: qa={len(qa)} safety={len(safety)} ooc={len(ooc)} total={total}")


if __name__ == "__main__":
    main()
