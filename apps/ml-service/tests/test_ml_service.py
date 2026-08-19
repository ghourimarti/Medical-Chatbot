"""ml-service contract + wiring tests. Model-free where possible: the heavy models are
exercised in the integration test, not on every `make check`."""

from __future__ import annotations

import pytest
from medml.backends import QUERY_INSTRUCTION
from medml.schema import MAX_BATCH, EmbedRequest, RerankRequest
from pydantic import ValidationError


def test_query_instruction_is_defined_once() -> None:
    """D5 gate: the bge query prefix lives in exactly one place. If apps/api ever
    re-implements it, ingestion and query-time can drift apart silently."""
    assert QUERY_INSTRUCTION.endswith(": ")
    assert "searching relevant passages" in QUERY_INSTRUCTION


def test_embed_request_defaults_to_document_mode() -> None:
    """Documents must NOT get the query prefix — defaulting to False is the safe default
    because ingestion is the high-volume path."""
    assert EmbedRequest(texts=["a"]).is_query is False


def test_batch_cap_enforced() -> None:
    with pytest.raises(ValidationError):
        EmbedRequest(texts=["x"] * (MAX_BATCH + 1))
    with pytest.raises(ValidationError):
        EmbedRequest(texts=[])


def test_rerank_request_validation() -> None:
    with pytest.raises(ValidationError):
        RerankRequest(query="", passages=["p"])
    with pytest.raises(ValidationError):
        RerankRequest(query="q", passages=[])
    assert RerankRequest(query="q", passages=["p"], top_k=1).top_k == 1
