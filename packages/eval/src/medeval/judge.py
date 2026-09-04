"""Judge identity, pinned and versioned.

Every before/after comparison assumes this judge. Changing the model, the temperature or
the ragas version invalidates cross-run comparisons, so bump JUDGE_VERSION and re-baseline
if any of them has to change.
"""

from __future__ import annotations

from typing import Any

JUDGE_MODEL_ID = "openai/gpt-oss-120b"
JUDGE_EMBEDDINGS_ID = "sentence-transformers/all-MiniLM-L6-v2"
# v2 because Groq removed the v1 judge (llama-3.3-70b-versatile). The version goes into
# every report: scores from different judges aren't comparable, and without the stamp a
# silent model swap would make the old baseline look comparable to later runs.
JUDGE_VERSION = f"judge_v2({JUDGE_MODEL_ID}, temp=0)"


def build_judge_llm() -> Any:
    from langchain_groq import ChatGroq

    return ChatGroq(model=JUDGE_MODEL_ID, temperature=0.0, max_retries=4)


def build_judge_embeddings() -> Any:
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(model_name=JUDGE_EMBEDDINGS_ID)
