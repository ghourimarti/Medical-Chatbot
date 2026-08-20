"""Judge identity — pinned and versioned (Decision Gate B).

Every before/after comparison in this project assumes THIS judge. Changing the model,
temperature, or ragas version invalidates cross-run comparisons; bump JUDGE_VERSION
and re-baseline if any of them must change.
"""

from __future__ import annotations

from typing import Any

JUDGE_MODEL_ID = "openai/gpt-oss-120b"
JUDGE_EMBEDDINGS_ID = "sentence-transformers/all-MiniLM-L6-v2"
# BUMPED to v2 in S19: the v1 judge (llama-3.3-70b-versatile) was REMOVED by Groq.
# The version is part of every report, and that matters: scores produced by different
# judges are NOT comparable, so a silent model swap would have made the S1 baseline and
# every later run look comparable when they are not. Reports carrying judge_v1 vs
# judge_v2 must be compared with that caveat stated, never implicitly.
JUDGE_VERSION = f"judge_v2({JUDGE_MODEL_ID}, temp=0)"


def build_judge_llm() -> Any:
    from langchain_groq import ChatGroq

    return ChatGroq(model=JUDGE_MODEL_ID, temperature=0.0, max_retries=4)


def build_judge_embeddings() -> Any:
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(model_name=JUDGE_EMBEDDINGS_ID)
