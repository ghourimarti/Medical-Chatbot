"""One-off curation tool: extract topic excerpts from the Gale PDF so golden-set
ground truths are written with eyes on the actual corpus (not from model memory).

Usage:
  uv run python packages/eval/tools/extract_corpus.py --build-cache
  uv run python packages/eval/tools/extract_corpus.py --topic "Asthma" [--pages 3]

The page-text cache lives outside the repo (scratch dir) — it is a curation aid,
not an artifact.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PDF_PATH = REPO_ROOT / "demo" / "data" / "The_GALE_ENCYCLOPEDIA_of_MEDICINE_SECOND.pdf"
CACHE_PATH = Path(
    os.environ.get("MEDEVAL_SCRATCH", str(REPO_ROOT / ".cache"))
) / "gale_pages.json"


def build_cache() -> None:
    from pypdf import PdfReader

    reader = PdfReader(str(PDF_PATH))
    pages = []
    total = len(reader.pages)
    for i, page in enumerate(reader.pages):
        try:
            pages.append(page.extract_text() or "")
        except Exception as e:  # noqa: BLE001 — a bad page shouldn't kill the cache build
            pages.append("")
            print(f"page {i}: extract failed: {e}", file=sys.stderr)
        if (i + 1) % 250 == 0:
            print(f"{i + 1}/{total} pages extracted", flush=True)
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(pages), encoding="utf-8")
    print(f"cached {total} pages -> {CACHE_PATH}")


def find_topic(topic: str, n_pages: int) -> None:
    pages: list[str] = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    pattern = re.compile(rf"^\s*{re.escape(topic)}\s*$", re.IGNORECASE | re.MULTILINE)
    loose = re.compile(re.escape(topic), re.IGNORECASE)
    heading_hits = [i for i, t in enumerate(pages) if pattern.search(t)]
    hits = heading_hits or [i for i, t in enumerate(pages) if loose.search(t)][:3]
    if not hits:
        print(f"'{topic}': NOT FOUND in corpus (candidate for ooc case)")
        return
    print(f"'{topic}': heading hits at pdf-pages {heading_hits or '(none, loose matches)'}")
    start = hits[0]
    for i in range(start, min(start + n_pages, len(pages))):
        print(f"\n===== pdf-page {i} =====\n{pages[i][:3500]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-cache", action="store_true")
    ap.add_argument("--topic")
    ap.add_argument("--pages", type=int, default=3)
    args = ap.parse_args()
    if args.build_cache:
        build_cache()
    elif args.topic:
        find_topic(args.topic, args.pages)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
