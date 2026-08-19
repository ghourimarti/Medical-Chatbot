"""HTTP clients for apps/ml-service, implementing EmbedderPort and RerankerPort.

Timeouts are mandatory, not defensive habit: without them a hung ml-service would hang
every API request holding a connection, and one slow dependency takes down the whole tier
(D21). Failures are converted to typed domain errors so the degradation ladder can branch
on them — a reranker outage is survivable (skip reranking), an embedder outage is not.
"""

from __future__ import annotations

from collections.abc import Sequence

import httpx

from medcore.errors import RerankerError, RetrievalError
from medcore.schema import RetrievedChunk


class HttpEmbedder:
    """EmbedderPort over HTTP. Embedding failure is fatal to a query — without a vector
    there is nothing to retrieve — so it raises RetrievalError (degradable: cache/no-answer)."""

    def __init__(self, base_url: str, model_id: str, dimension: int, timeout: float) -> None:
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)
        self._model_id = model_id
        self._dimension = dimension

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([text], is_query=True))[0]

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embed(list(texts), is_query=False)

    async def _embed(self, texts: list[str], *, is_query: bool) -> list[list[float]]:
        try:
            resp = await self._client.post(
                "/embed", json={"texts": texts, "is_query": is_query}
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise RetrievalError(f"ml-service /embed failed: {e}", cause=e) from e
        payload = resp.json()
        if payload["dimension"] != self._dimension:
            raise RetrievalError(
                f"ml-service returned dim {payload['dimension']}, expected {self._dimension}"
            )
        return payload["vectors"]  # type: ignore[no-any-return]

    async def aclose(self) -> None:
        await self._client.aclose()


class HttpReranker:
    """RerankerPort over HTTP. A reranker outage is NON-fatal by design (D21): the caller
    falls back to fusion order with a logged quality dip rather than failing the request."""

    def __init__(self, base_url: str, model_id: str, timeout: float) -> None:
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)
        self._model_id = model_id

    @property
    def model_id(self) -> str:
        return self._model_id

    async def rerank(
        self, *, query: str, chunks: Sequence[RetrievedChunk], top_k: int
    ) -> list[RetrievedChunk]:
        items = list(chunks)
        if not items:
            return []
        try:
            resp = await self._client.post(
                "/rerank",
                json={"query": query, "passages": [c.text for c in items], "top_k": top_k},
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise RerankerError(f"ml-service /rerank failed: {e}", cause=e) from e
        ranked: list[RetrievedChunk] = []
        for row in resp.json()["results"]:
            chunk = items[row["index"]]
            ranked.append(chunk.model_copy(update={"rerank_score": row["score"]}))
        return ranked

    async def aclose(self) -> None:
        await self._client.aclose()
