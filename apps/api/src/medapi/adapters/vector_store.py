"""Qdrant vector store (D2, D3). Implements VectorStorePort.

S3 shipped dense-only. S6 adds a named SPARSE vector and performs HYBRID retrieval with
server-side RRF fusion (Qdrant Query API `prefetch` + `FusionQuery`). Fusing in Qdrant
rather than in Python matters: one round trip instead of two, and the fusion runs next to
the data.

DECISION GATE (D5): collection dimension comes from config (EMBEDDING_DIM = 1024), never a
literal. Changing the schema means a NEW collection + re-index — never an in-place mutation
of a serving index.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence

from qdrant_client import AsyncQdrantClient, models

from medcore.errors import RetrievalError
from medcore.schema import RetrievedChunk

# Qdrant point IDs must be uint or UUID. Our chunk IDs are content hashes (strings), so we
# derive a STABLE UUID from each and keep the original id in the payload. uuid5 is
# deterministic, so re-ingesting the same chunk overwrites rather than duplicates.
_POINT_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")

DENSE = "dense"
SPARSE = "sparse"


def _point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_POINT_NAMESPACE, chunk_id))


class QdrantVectorStore:
    """VectorStorePort backed by Qdrant. One collection per corpus/index version."""

    def __init__(self, url: str, collection: str, dimension: int) -> None:
        # check_compatibility=False: server image is pinned and the client is pinned to a
        # matching minor in pyproject; the advisory check only adds noise.
        self._client = AsyncQdrantClient(url=url, prefer_grpc=False, check_compatibility=False)
        self._collection = collection
        self._dimension = dimension

    @property
    def client(self) -> AsyncQdrantClient:
        return self._client

    async def _check_dimension(self) -> None:
        info = await self._client.get_collection(self._collection)
        vectors = info.config.params.vectors
        existing = vectors[DENSE].size if isinstance(vectors, dict) else vectors.size  # type: ignore[union-attr,index]
        if existing != self._dimension:
            raise ValueError(
                f"collection '{self._collection}' has dim {existing}, config wants "
                f"{self._dimension}. Re-index into a new index_version, don't mutate."
            )

    async def verify_collection(self) -> None:
        """Read-side check: the target must already exist, with the right dimension.

        P6.3.5: the API used to call `ensure_collection()` at startup, which CREATES the
        collection when absent. On a fresh cluster that is actively harmful twice over:

          1. `QDRANT_COLLECTION` names an ALIAS (D11) — ingestion builds `gale_live_v1` and
             repoints `gale_live` atomically. Qdrant forbids an alias and a collection
             sharing a name, so auto-creating a COLLECTION called `gale_live` permanently
             blocks the alias the zero-downtime swap depends on. Found by deploying to kind,
             where Qdrant starts empty: `gale_live` existed as a collection, aliases were [].
          2. It converts "corpus missing" into "corpus present but empty", which is the
             worse failure: the pod reports Ready and every query fails deep in the request
             path, far from the cause.

        Creation belongs to ingestion, which knows what to put in it. The read path only
        checks, and fails loudly when the answer is no.
        """
        if not await self._client.collection_exists(self._collection):
            raise ValueError(
                f"'{self._collection}' does not exist in Qdrant. The API does not create it: "
                f"'{self._collection}' is an alias that ingestion creates and repoints "
                "(D11). Run the ingestion worker before serving traffic."
            )
        await self._check_dimension()

    async def ensure_collection(self) -> None:
        """Idempotent create-or-validate. INGESTION ONLY — see verify_collection()."""
        if await self._client.collection_exists(self._collection):
            await self._check_dimension()
            return
        await self._client.create_collection(
            collection_name=self._collection,
            vectors_config={
                DENSE: models.VectorParams(size=self._dimension, distance=models.Distance.COSINE)
            },
            sparse_vectors_config={SPARSE: models.SparseVectorParams()},
        )

    async def search(
        self,
        *,
        query_vector: Sequence[float],
        query_text: str,  # noqa: ARG002 — sparse path uses sparse_vector below
        top_k: int,
        filters: Mapping[str, object] | None = None,  # noqa: ARG002 — ACL filters arrive later
        sparse_vector: models.SparseVector | None = None,
    ) -> list[RetrievedChunk]:
        """Hybrid when a sparse vector is supplied, dense-only otherwise.

        RRF (Reciprocal Rank Fusion) combines the two rankings by RANK, not by score —
        which is what makes it safe to fuse cosine similarities with BM25 weights that
        live on completely different scales.
        """
        # Wrapping is not cosmetic (P5.3). With Qdrant stopped, the raw client exception
        # propagated and the API returned an opaque 500 "unexpected error" — which tells
        # the caller nothing, tells the on-call engineer nothing, and pollutes the
        # bug-rate signal with what is actually a dependency outage. RetrievalError is
        # already defined as 503 + retryable + degradable; it just was never raised here.
        #
        # 500 means "we have a bug". 503 means "a dependency is down, retry". Conflating
        # them makes both alerts useless.
        try:
            if sparse_vector is not None and sparse_vector.indices:
                hits = await self._client.query_points(
                    collection_name=self._collection,
                    prefetch=[
                        models.Prefetch(query=list(query_vector), using=DENSE, limit=top_k),
                        models.Prefetch(query=sparse_vector, using=SPARSE, limit=top_k),
                    ],
                    query=models.FusionQuery(fusion=models.Fusion.RRF),
                    limit=top_k,
                    with_payload=True,
                )
            else:
                hits = await self._client.query_points(
                    collection_name=self._collection,
                    query=list(query_vector),
                    using=DENSE,
                    limit=top_k,
                    with_payload=True,
                )
        except Exception as e:
            raise RetrievalError(f"qdrant search failed: {type(e).__name__}: {e}", cause=e) from e
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
                    metadata={k: v for k, v in payload.items() if k not in ("text", "chunk_id")},
                )
            )
        return chunks

    async def upsert(self, chunks: Sequence[RetrievedChunk], *, collection: str) -> int:
        points = []
        for chunk in chunks:
            vectors: dict[str, object] = {DENSE: chunk.metadata["_vector"]}
            sparse = chunk.metadata.get("_sparse")
            if sparse is not None:
                vectors[SPARSE] = sparse
            points.append(
                models.PointStruct(
                    id=_point_id(chunk.id),
                    vector=vectors,  # type: ignore[arg-type]
                    payload={
                        "chunk_id": chunk.id,
                        "text": chunk.text,
                        "source": chunk.source,
                        "page": chunk.page,
                        **{k: v for k, v in chunk.metadata.items() if not k.startswith("_")},
                    },
                )
            )
        await self._client.upsert(collection_name=collection, points=points)
        return len(points)

    async def ensure_alias(self, alias: str, collection: str) -> None:
        """Point `alias` at `collection`, atomically (D11).

        Qdrant applies alias operations atomically, which is what makes zero-downtime
        re-indexing possible: build a new collection alongside the live one, then repoint
        the alias in a single operation. Readers never observe a half-ingested corpus.
        """
        await self._client.update_collection_aliases(
            change_aliases_operations=[
                models.CreateAliasOperation(
                    create_alias=models.CreateAlias(
                        collection_name=collection, alias_name=alias
                    )
                )
            ]
        )

    async def resolve_alias(self, alias: str) -> str | None:
        """Which collection does this alias currently serve? Used by ingestion to decide
        the next version number, and by ops to answer 'what is actually live?'."""
        try:
            aliases = await self._client.get_aliases()
        except Exception:
            return None
        for entry in aliases.aliases:
            if entry.alias_name == alias:
                return entry.collection_name
        return None

    async def delete_collection(self, collection: str) -> None:
        await self._client.delete_collection(collection)

    async def count(self, collection: str) -> int:
        result = await self._client.count(collection_name=collection, exact=True)
        return int(result.count)

    async def health(self) -> bool:
        """Readiness must mean "can serve", not "a name resolves".

        P6.3.5: this returned True for an EMPTY collection, so a freshly deployed pod
        reported Ready while every single query failed with `retrieval returned zero
        candidates`. Readiness that cannot distinguish an empty index from a usable one
        sends traffic to a pod guaranteed to fail it — and the query path already treats
        an empty index as a fault (P5.3.6), so the two disagreed about the same state.
        """
        try:
            if not await self._client.collection_exists(self._collection):
                return False
            info = await self._client.get_collection(self._collection)
            return (info.points_count or 0) > 0
        except Exception:
            return False

    async def close(self) -> None:
        await self._client.close()
