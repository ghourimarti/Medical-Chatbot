"""Context construction. Pure, no I/O.

Passages are numbered [1], [2], ... and the model is told to cite those numbers. The same
numbering drives Citation extraction, so a rendered citation maps to an exact retrieved
chunk. The token budget is approximated by characters (~4 chars/token), which is close
enough here; a real tokenizer-based budget can come later.
"""

from __future__ import annotations

from collections.abc import Sequence

from medcore.schema import Citation, RetrievedChunk

_CHARS_PER_TOKEN = 4


def build_context(
    chunks: Sequence[RetrievedChunk], *, max_input_tokens: int
) -> tuple[str, list[Citation]]:
    """Return (numbered_context_string, citations). Drops lowest-ranked chunks first when
    the budget is exceeded, so citations stay consistent with what the model actually saw."""
    budget_chars = max_input_tokens * _CHARS_PER_TOKEN
    used = 0
    blocks: list[str] = []
    citations: list[Citation] = []
    for i, chunk in enumerate(chunks, start=1):
        block = f"[{i}] (source: {chunk.source}" + (
            f", p.{chunk.page})" if chunk.page is not None else ")"
        )
        block += f"\n{chunk.text.strip()}"
        if used + len(block) > budget_chars and blocks:
            break
        blocks.append(block)
        used += len(block)
        citations.append(
            Citation(
                chunk_id=chunk.id,
                source=chunk.source,
                page=chunk.page,
                snippet=chunk.text[:160].strip(),
                score=chunk.effective_score,
            )
        )
    return "\n\n".join(blocks), citations
