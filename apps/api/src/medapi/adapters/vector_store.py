"""Qdrant vector store (D2). Implements VectorStorePort.

DECISION GATE (D5): the collection is created with `dimension` taken from config
(EMBEDDING_DIM = 1024), never a literal. This is where the frozen constant becomes
real infrastructure. S3 does dense-only search; the `query_text`/sparse path in the
port signature is already present so S6's hybrid retrieval needs no interface change.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence

from qdrant_client import AsyncQdrantClient, models

from medcore.schema import RetrievedChunk

# Qdrant point IDs must be uint or UUID. Our chunk IDs are content hashes (strings), so we
# derive a STABLE UUID from each and keep the original id in the payload. uuid5 is
# deterministic, so re-ingesting the same chunk overwrites rather than duplicates.
_POINT_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


def _point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_POINT_NAMESPACE, chunk_id))


class QdrantVectorStore:
    """VectorStorePort backed by Qdrant. One collection per corpus/index version."""

    def __init__(self, url: str, collection: str, dimension: int) -> None:
        # check_compatibility=False: server image is pinned (v1.12.4) and the client is
        # pinned to the matching minor in pyproject; the advisory check adds only noise.
        self._client = AsyncQdrantClient(url=url, prefer_grpc=False, check_compatibility=False)
        self._collection = collection
        self._dimension = dimension

    async def ensure_collection(self) -> None:
        """Idempotent. Creates the collection at the configured dimension if absent, and
        refuses to run against a collection whose dimension disagrees with config."""
        if await self._client.collection_exists(self._collection):
            info = await self._client.get_collection(self._collection)
            existing = info.config.params.vectors.size  # type: ignore[union-attr]
            if existing != self._dimension:
                raise ValueError(
                    f"collection '{self._collection}' has dim {existing}, config wants "
                    f"{self._dimension}. Re-index into a new index_version, don't mutate."
                )
            return
        await self._client.create_collection(
            collection_name=self._collection,
            vectors_config=models.VectorParams(
                size=self._dimension, distance=models.Distance.COSINE
            ),
        )

    async def search(
        self,
        *,
        query_vector: Sequence[float],
        query_text: str,  # noqa: ARG002 — sparse/hybrid arrives S6; signature stable now
        top_k: int,
        filters: Mapping[str, object] | None = None,  # noqa: ARG002 — ACL filters arrive later
    ) -> list[RetrievedChunk]:
        hits = await self._client.query_points(
            collection_name=self._collection,
            query=list(query_vector),
            limit=top_k,
            with_payload=True,
        )
        chunks: list[RetrievedChunk] = []
        for point in hits.points:
            payload = point.payload or {}
            chunks.append(
                RetrievedChunk(
                    id=str(payload.get("chunk_id", point.id)),
                    text=str(payload.get("text", "")),
                    source=str(payload.get("source", "unknown")),
                    page=payload.get("page"),
                    dense_score=point.score,
                    metadata={
                        k: v for k, v in payload.items() if k not in ("text", "chunk_id")
                    },
                )
            )
        return chunks

    async def upsert(self, chunks: Sequence[RetrievedChunk], *, collection: str) -> int:
        points = [
            models.PointStruct(
                id=_point_id(chunk.id),
                vector=chunk.metadata["_vector"],
                payload={
                    "chunk_id": chunk.id,
                    "text": chunk.text,
                    "source": chunk.source,
                    "page": chunk.page,
                    **{k: v for k, v in chunk.metadata.items() if not k.startswith("_")},
                },
            )
            for chunk in chunks
        ]
        await self._client.upsert(collection_name=collection, points=points)
        return len(points)

    async def health(self) -> bool:
        try:
            return await self._client.collection_exists(self._collection)
        except Exception:
            return False

    async def close(self) -> None:
        await self._client.close()
