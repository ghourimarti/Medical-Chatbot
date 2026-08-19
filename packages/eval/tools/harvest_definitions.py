"""Harvest grounded Definition blocks from the Gale corpus for golden-set curation (S19.1).

WHY THIS EXISTS. S1 established the rule that makes the money chart trustworthy: every
`qa` ground truth must come from text extracted from the corpus, never written from model
memory. Synthetic ground truth inherits the model's own blind spots, so a system evaluated
against it can look perfect while being wrong in exactly the ways the model is wrong.

Gale articles follow a stable shape:

    <Topic>
    Definition
    <definition prose>
    Description | Causes and symptoms | Treatment | ...

This walks the flattened page text, finds every `Definition` marker, and captures the
heading that precedes it plus the prose that follows. Output is JSON for curation — a human
still writes the question and trims the answer. The tool supplies EVIDENCE, not cases.

    uv run python packages/eval/tools/harvest_definitions.py \
        --min-len 80 --out .cache/definitions.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CACHE = REPO_ROOT / ".cache" / "gale_pages.json"

# A heading is a short line in Title Case with no terminal punctuation. Gale sets article
# titles on their own line, so this is a reliable-enough filter to then verify by eye.
_HEADING = re.compile(r"^(?!.*[.:;,])([A-Z][A-Za-z'\-]*(?:\s+[a-zA-Z'\-]+){0,4})\s*$")
_SECTION_END = re.compile(
    r"\n\s*(Description|Causes and symptoms|Causes|Symptoms|Diagnosis|Treatment|"
    r"Prognosis|Prevention|Precautions|Purpose|Key ?terms|Resources)\b"
)
# Page furniture that would otherwise be mistaken for prose.
_NOISE = re.compile(r"GALE ENCYCLOPEDIA OF MEDICINE|^\d+$|http|ORGANIZATIONS|PERIODICALS")


def load_pages() -> list[str]:
    if not CACHE.is_file():
        raise SystemExit(
            f"missing {CACHE}. Build it first:\n"
            "  uv run python packages/eval/tools/extract_corpus.py --build-cache"
        )
    return json.loads(CACHE.read_text(encoding="utf-8"))


def clean(text: str) -> str:
    # The PDF extractor emits U+FFFD for curly quotes it cannot map, plus assorted
    # typographic characters. Normalising here (rather than in the golden set) keeps the
    # dataset ASCII-clean and diffable.
    for bad, good in (
        ("�", "'"), ("’", "'"), ("‘", "'"),
        ("“", '"'), ("”", '"'),
        ("—", "-"), ("–", "-"), (" ", " "),
    ):
        text = text.replace(bad, good)
    text = re.sub(r"-\n(?=[a-z])", "", text)  # rejoin hyphenated line breaks
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\s*\n\s*", " ", text).strip()


def harvest(pages: list[str], min_len: int, max_len: int) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    seen: set[str] = set()
    for page_no, raw in enumerate(pages):
        for m in re.finditer(r"\n\s*Definition\s*\n", raw):
            # Heading: the last heading-shaped line before the Definition marker.
            before = raw[max(0, m.start() - 220) : m.start()].split("\n")
            topic = next(
                (
                    h.group(1).strip()
                    for line in reversed(before)
                    if (h := _HEADING.match(line.strip())) and not _NOISE.search(line)
                ),
                None,
            )
            if not topic or topic.lower() in seen:
                continue
            # Reject cross-reference stubs ("X see Y") and page furniture. These carry a
            # heading-shaped line but the prose below belongs to a DIFFERENT article, so
            # accepting them would attach a real definition to the wrong topic — a silently
            # wrong ground truth, which is the one defect a golden set must never contain.
            if " see " in topic or topic.isupper() or len(topic) < 4:
                continue
            tail = raw[m.end() : m.end() + 1400]
            stop = _SECTION_END.search(tail)
            body = clean(tail[: stop.start()] if stop else tail)
            if not (min_len <= len(body) <= max_len) or _NOISE.search(body):
                continue
            # SELF-CONSISTENCY GATE: the topic's first significant word must appear in its
            # own definition. Gale definitions restate their subject ("Cirrhosis is a..."),
            # so a mismatch means the heading and body were mis-paired by the page walk.
            head_word = topic.split()[0].lower().rstrip("s")
            if len(head_word) > 3 and head_word not in body.lower():
                continue
            seen.add(topic.lower())
            out.append({"topic": topic, "page": page_no, "definition": body})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-len", type=int, default=80)
    ap.add_argument("--max-len", type=int, default=600)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / ".cache" / "definitions.json")
    ap.add_argument("--sample", type=int, default=0, help="print N examples to stdout")
    args = ap.parse_args()

    items = harvest(load_pages(), args.min_len, args.max_len)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(items, indent=1), encoding="utf-8")
    print(f"harvested {len(items)} grounded definitions -> {args.out}")
    for it in items[: args.sample]:
        print(f"\n[{it['topic']}] (pdf page {it['page']})\n  {str(it['definition'])[:200]}")


if __name__ == "__main__":
    main()
