"""Build golden_core_v2 (215 cases) from harvested corpus evidence (S19.1).

Composition target (D19): 150 qa / 50 safety / 15 ooc.

The qa cases are ASSEMBLED, not invented: `ground_truth` is the definition text extracted
from the Gale PDF by harvest_definitions.py, trimmed to its leading sentences. The question
is templated from the topic. That split matters — the answer carries corpus authority, and
only the phrasing of the question is generated.

Existing v1 cases are carried over verbatim so every score in docs/BASELINE.md remains
comparable; v2 is a SUPERSET, not a replacement.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DATASETS = REPO / "packages" / "eval" / "datasets"
DEFS = REPO / ".cache" / "definitions.json"

TARGET_QA, TARGET_SAFETY, TARGET_OOC = 150, 50, 15


def load_jsonl(p: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def trim(text: str, limit: int = 320) -> str:
    """Keep whole leading sentences up to `limit`. A truncated ground truth would penalise
    a correct answer for omitting text the grader itself cut off mid-clause."""
    out: list[str] = []
    for sent in re.split(r"(?<=[.!?])\s+", text.strip()):
        if out and sum(len(s) + 1 for s in out) + len(sent) > limit:
            break
        out.append(sent)
        if sum(len(s) + 1 for s in out) > limit * 0.6:
            break
    return " ".join(out).strip()


# Words that look plural but take a singular verb ("diabetes is", "measles is").
_FALSE_PLURAL = ("diabetes", "measles", "mumps", "rabies", "herpes", "scabies", "syphilis",
                 "rickets", "shingles", "asbestosis", "psoriasis", "cirrhosis", "sepsis")


def is_plural(topic: str) -> bool:
    head = topic.split()[-1].lower()
    if any(head.startswith(w) for w in _FALSE_PLURAL) or head.endswith(("sis", "us", "ss")):
        return False
    return head.endswith("s")


def question_for(topic: str, definition: str) -> str:
    # Lowercase the topic unless it is an acronym or proper noun (Down syndrome, HIV).
    t = topic if (topic.isupper() or topic[1:2].isupper()) else topic[0].lower() + topic[1:]
    be = "are" if is_plural(topic) else "is"
    low = definition.lower()
    if re.search(r"\b(is|are) (a |an |the )?(medicine|medication|drug)s?\b", low):
        return f"What {be} {t} used for?"
    if "occurs when" in low or low.startswith(("infection", "inflammation")):
        return f"What causes {t}?"
    if re.search(r"\b(surgery|surgical|procedure|test|examination)\b", low[:160]):
        return f"What {be} the purpose of {t}?"
    return f"What {be} {t}?"


def main() -> None:
    v1 = load_jsonl(DATASETS / "golden_core_v1.jsonl")
    used_topics = {
        (c.get("source") or "").replace("Gale: ", "").strip().lower() for c in v1
    }
    qa = [c for c in v1 if c["category"] == "qa"]
    safety = [c for c in v1 if c["category"] == "safety"]
    ooc = [c for c in v1 if c["category"] == "ooc"]

    defs = json.loads(DEFS.read_text(encoding="utf-8"))
    # Prefer longer, richer definitions — they make less ambiguous ground truths.
    defs.sort(key=lambda d: -len(str(d["definition"])))

    next_id = max(int(c["id"].split("-")[1]) for c in qa) + 1
    for d in defs:
        if len(qa) >= TARGET_QA:
            break
        topic = str(d["topic"]).strip()
        if topic.lower() in used_topics:
            continue
        gt = trim(str(d["definition"]))
        if len(gt) < 60:
            continue
        used_topics.add(topic.lower())
        qa.append(
            {
                "id": f"qa-{next_id:03d}",
                "category": "qa",
                "question": question_for(topic, gt),
                "ground_truth": gt,
                "expected_behavior": "answer",
                "source": f"Gale: {topic}",
                "tags": ["definition", f"pdf-page-{d['page']}"],
            }
        )
        next_id += 1

    print(f"qa: {len(v1) and len([c for c in v1 if c['category']=='qa'])} -> {len(qa)}")
    print(f"safety: {len(safety)} (target {TARGET_SAFETY})")
    print(f"ooc: {len(ooc)} (target {TARGET_OOC})")
    (REPO / ".cache" / "qa_v2_draft.json").write_text(
        json.dumps(qa[len([c for c in v1 if c['category']=='qa']):], indent=1), encoding="utf-8"
    )
    print("new qa cases drafted -> .cache/qa_v2_draft.json")


if __name__ == "__main__":
    main()
