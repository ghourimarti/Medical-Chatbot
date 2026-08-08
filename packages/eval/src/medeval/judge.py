"""Judge identity — pinned and versioned (Decision Gate B).

Every before/after comparison in this project assumes THIS judge. Changing the model,
temperature, or ragas version invalidates cross-run comparisons; bump JUDGE_VERSION
and re-baseline if any of them must change.
"""

from __future__ import annotations

from typing import Any

JUDGE_MODEL_ID = "llama-3.3-70b-versatile"
JUDGE_EMBEDDINGS_ID = "sentence-transformers/all-MiniLM-L6-v2"
JUDGE_VERSION = f"judge_v1({JUDGE_MODEL_ID}, temp=0)"


def build_judge_llm() -> Any:
    from langchain_groq import ChatGroq

    return ChatGroq(model=JUDGE_MODEL_ID, temperature=0.0, max_retries=4)


def build_judge_embeddings() -> Any:
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(model_name=JUDGE_EMBEDDINGS_ID)
