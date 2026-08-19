"""Contract tests for the HTTP clients, using httpx MockTransport — no live service needed.

These prove the two things that matter operationally (D21):
  * a failing ml-service becomes a TYPED domain error, not a raw exception, so the
    degradation ladder can branch on it;
  * reranker failure is survivable while embedder failure is not.
"""

from __future__ import annotations

import httpx
import pytest
from medapi.adapters.ml_client import HttpEmbedder, HttpReranker

from medcore.errors import RerankerError, RetrievalError
from medcore.schema import RetrievedChunk


def _embedder(handler: object, dimension: int = 1024) -> HttpEmbedder:
    emb = HttpEmbedder("http://ml", "bge-large", dimension, 5.0)
    emb._client = httpx.AsyncClient(  # type: ignore[assignment]
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        base_url="http://ml",
    )
    return emb


def _reranker(handler: object) -> HttpReranker:
    rr = HttpReranker("http://ml", "bge-reranker", 2.0)
    rr._client = httpx.AsyncClient(  # type: ignore[assignment]
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        base_url="http://ml",
    )
    return rr


def _chunk(cid: str, text: str) -> RetrievedChunk:
    return RetrievedChunk(id=cid, text=text, source="Gale", dense_score=0.5)


@pytest.mark.asyncio
async def test_embed_query_sends_is_query_true() -> None:
    """The query/document distinction must survive the wire — it is the D5 gate."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(
            200, json={"vectors": [[0.1] * 1024], "model_id": "bge-large",
                       "dimension": 1024, "duration_ms": 12.0}
        )

    vec = await _embedder(handler).embed_query("what is cirrhosis?")
    assert seen["is_query"] is True
    assert len(vec) == 1024


@pytest.mark.asyncio
async def test_embed_documents_sends_is_query_false() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(
            200, json={"vectors": [[0.1] * 1024] * 2, "model_id": "bge-large",
                       "dimension": 1024, "duration_ms": 20.0}
        )

    await _embedder(handler).embed_documents(["a", "b"])
    assert seen["is_query"] is False


@pytest.mark.asyncio
async def test_dimension_mismatch_is_rejected() -> None:
    """A service serving the wrong model would silently poison the index."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"vectors": [[0.1] * 384], "model_id": "minilm",
                       "dimension": 384, "duration_ms": 3.0}
        )

    with pytest.raises(RetrievalError, match="dim 384"):
        await _embedder(handler).embed_query("q")


@pytest.mark.asyncio
async def test_embedder_failure_is_typed_and_degradable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream down")

    with pytest.raises(RetrievalError) as exc:
        await _embedder(handler).embed_query("q")
    assert exc.value.degradable and exc.value.retryable


@pytest.mark.asyncio
async def test_embedder_timeout_is_typed_not_raw() -> None:
    """Without this mapping a hung ml-service surfaces as a raw httpx error and the
    degradation ladder can't branch on it."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(RetrievalError):
        await _embedder(handler).embed_query("q")


@pytest.mark.asyncio
async def test_rerank_reorders_and_attaches_scores() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [{"index": 1, "score": 9.5}, {"index": 0, "score": 1.2}],
                "model_id": "bge-reranker", "duration_ms": 30.0,
            },
        )

    chunks = [_chunk("a", "irrelevant"), _chunk("b", "the good one")]
    out = await _reranker(handler).rerank(query="q", chunks=chunks, top_k=2)
    assert [c.id for c in out] == ["b", "a"]
    assert out[0].rerank_score == 9.5
    assert out[0].effective_score == 9.5  # rerank score wins over dense


@pytest.mark.asyncio
async def test_reranker_failure_is_typed_and_survivable() -> None:
    """D21: reranker down => skip reranking, don't fail the request."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(RerankerError) as exc:
        await _reranker(handler).rerank(query="q", chunks=[_chunk("a", "x")], top_k=1)
    assert exc.value.degradable


@pytest.mark.asyncio
async def test_rerank_empty_input_short_circuits() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("must not call the service for an empty list")

    assert await _reranker(handler).rerank(query="q", chunks=[], top_k=5) == []
