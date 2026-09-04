"""Qdrant vector store, implementing VectorStorePort.

Hybrid retrieval: a named sparse vector alongside the dense one, fused server-side with RRF
via the Query API (`prefetch` + `FusionQuery`). Fusing in Qdrant rather than in Python is
one round trip instead of two, and the fusion runs next to the data.

The collection dimension comes from config (EMBEDDING_DIM = 1024), never a literal.
Changing it means a new collection and a re-index, never an in-place mutation of a serving
index.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence

from qdrant_client import AsyncQdrantClient, models

from medcore.errors import RetrievalError
from medcore.schema import RetrievedChunk

logger = logging.getLogger("medapi.vector_store")

# Qdrant point IDs must be uint or UUID, but our chunk IDs are content hashes, so derive a
# stable UUID from each and keep the original in the payload. uuid5 is deterministic, so
# re-ingesting the same chunk overwrites instead of duplicating.
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

        The API used to call `ensure_collection()` at startup, which creates the collection
        when it's absent. On a fresh cluster that's harmful twice over:

          1. `QDRANT_COLLECTION` names an alias. Ingestion builds `gale_live_v1` and
             repoints `gale_live` atomically, and Qdrant won't let an alias and a
             collection share a name, so auto-creating a collection called `gale_live`
             permanently blocks the alias the zero-downtime swap needs. Found on kind,
             where Qdrant starts empty: `gale_live` existed as a collection, aliases [].
          2. It turns "corpus missing" into "corpus present but empty", which is worse:
             the pod reports Ready and every query fails deep in the request path.

        Creation belongs to ingestion, which knows what to put in it. The read path checks
        and fails loudly when the answer is no.
        """
        if not await self._client.collection_exists(self._collection):
            raise ValueError(
                f"'{self._collection}' does not exist in Qdrant. The API does not create "
                f"it: '{self._collection}' is an alias that ingestion creates and "
                "repoints. Run the ingestion worker before serving traffic."
            )
        await self._check_dimension()

    async def ensure_collection(self) -> None:
        """Idempotent create-or-validate. Ingestion only; see verify_collection()."""
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
        query_text: str,  # noqa: ARG002 (sparse path uses sparse_vector below)
        top_k: int,
        filters: Mapping[str, object] | None = None,  # noqa: ARG002 (ACL filters, later)
        sparse_vector: models.SparseVector | None = None,
    ) -> list[RetrievedChunk]:
        """Hybrid when a sparse vector is supplied, dense-only otherwise.

        RRF combines the two rankings by rank rather than by score, which is what makes it
        safe to fuse cosine similarities with BM25 weights living on different scales.
        """
        # Wrapping isn't cosmetic. With Qdrant stopped the raw client exception
        # propagated and the API returned an opaque 500, which tells the caller nothing
        # and pollutes the bug-rate signal with a dependency outage. RetrievalError was
        # already defined as 503 + retryable + degradable; it just wasn't raised here.
        # 500 means we have a bug, 503 means a dependency is down.
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
        """Point `alias` at `collection`, atomically.

        Qdrant applies alias operations atomically, which is what makes zero-downtime
        re-indexing work: build the new collection alongside the live one, then repoint in
        a single operation. Readers never see a half-ingested corpus.
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

    async def prune_superseded(
        self, alias: str, *, keep: int = 1, prefix: str | None = None
    ) -> list[str]:
        """Delete versioned collections the alias no longer points at, keeping `keep`.

        A re-ingest builds `gale_live_vN` and repoints the alias, but used to leave every
        previous collection in place: five stale copies of a 7,080-chunk corpus at ~29MB
        each, growing on a schedule nobody watches. Storage is the visible cost; the real
        one is that `GET /collections` becomes unreadable, so "which collection is live?"
        gets harder every re-index.

        Keeping exactly one previous version makes rollback a single alias operation with
        no re-ingest, which is the point of the alias indirection. Keeping all of them
        buys nothing: you'd never roll back four versions to a corpus since re-cut twice.

        Never deletes the live target, and never deletes anything when the alias can't be
        resolved. An unresolvable alias means we don't know what is live, and deleting in
        that state is how a re-index becomes an outage. Returns the names removed.
        """
        live = await self.resolve_alias(alias)
        if live is None:
            logger.warning(
                "alias %s does not resolve; pruning nothing", alias
            )
            return []

        stem = prefix or f"{alias}_v"
        try:
            existing = await self._client.get_collections()
        except Exception:  # noqa: BLE001 - housekeeping must not fail an ingest
            logger.warning("could not list collections; skipping prune", exc_info=True)
            return []

        # Newest first. The suffix is a unix timestamp, so lexical order on a
        # fixed-width number is chronological - but sort on the parsed integer
        # anyway, because a width change would silently reverse the meaning of
        # 'newest' and start deleting the wrong end.
        def _version(name: str) -> int:
            tail = name[len(stem):]
            return int(tail) if tail.isdigit() else -1

        candidates = sorted(
            (c.name for c in existing.collections
             if c.name.startswith(stem) and c.name != live),
            key=_version,
            reverse=True,
        )

        removed: list[str] = []
        for name in candidates[keep:]:
            try:
                await self._client.delete_collection(name)
                removed.append(name)
            except Exception:  # noqa: BLE001
                logger.warning("could not delete %s; leaving it", name, exc_info=True)
        if removed:
            logger.info(
                "pruned %d superseded collection(s): %s", len(removed), ", ".join(removed)
            )
        return removed
    async def delete_collection(self, collection: str) -> None:
        await self._client.delete_collection(collection)

    async def count(self, collection: str) -> int:
        result = await self._client.count(collection_name=collection, exact=True)
        return int(result.count)

    async def health(self) -> bool:
        """Readiness must mean "can serve", not "a name resolves".

        This used to return True for an empty collection, so a freshly deployed pod
        reported Ready while every query failed with `retrieval returned zero candidates`.
        Readiness that can't tell an empty index from a usable one sends traffic to a pod
        guaranteed to fail it, and the query path already treats an empty index as a fault,
        so the two disagreed about the same state.
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
