"""Find Gale 'Definition' blocks for topics so ground truths are corpus-grounded.

Gale articles follow: <Topic heading> / 'Definition' / <1-3 sentence definition> / 'Description'.
This locates the Definition-to-Description span in the flattened page cache.

Usage: uv run python packages/eval/tools/find_definitions.py Asthma Appendicitis Botulism
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CACHE = REPO_ROOT / ".cache" / "gale_pages.json"


def main() -> None:
    pages: list[str] = json.loads(CACHE.read_text(encoding="utf-8"))
    full = "\n".join(pages)
    full = full.replace("’", "'").replace("�", "'")
    for topic in sys.argv[1:]:
        # Definition block: the marker, then text up to 'Description'
        pat = re.compile(
            rf"{re.escape(topic)}\s*\n\s*Definition\s*(.+?)\s*Description",
            re.IGNORECASE | re.DOTALL,
        )
        m = pat.search(full)
        print(f"\n########## {topic} ##########")
        if m:
            text = re.sub(r"[ \t]+", " ", m.group(1)).strip()
            print(text[:900])
        else:
            # fallback: any 'Definition' within 200 chars after the topic word
            loose = re.search(
                rf"{re.escape(topic)}.{{0,80}}?Definition\s*(.{{80,600}}?)\s*Description",
                full,
                re.IGNORECASE | re.DOTALL,
            )
            print(re.sub(r"[ \t]+", " ", loose.group(1)).strip()[:900] if loose else "NOT FOUND")


if __name__ == "__main__":
    main()
