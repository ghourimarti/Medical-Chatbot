"""Ingestion pipeline: build a new collection, then swap the alias (D11, D3).

THE INVARIANT: the alias is repointed ONLY after the new collection is fully built and
verified. Every failure mode — crash, OOM, provider error, a killed pod — leaves the alias
pointing at the previous, complete collection. A partially-ingested corpus can never be
served, because it is never named.

That is a different guarantee from "the job retries". Retries fix availability of the
*pipeline*; the alias fixes correctness of the *data* readers see meanwhile.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from medapi.adapters.embedder import BgeEmbedder
from medapi.adapters.sparse import Bm25Encoder
from medapi.adapters.vector_store import QdrantVectorStore
from pypdf import PdfReader

from medcore.config import Settings
from medcore.schema import RetrievedChunk

logger = logging.getLogger("medworker.ingest")

SOURCE_NAME = "Gale Encyclopedia of Medicine (2nd ed.)"
UPSERT_BATCH = 256


@dataclass(slots=True)
class IngestResult:
    collection: str
    alias: str
    chunks: int
    duration_s: float
    previous_collection: str | None


def _next_collection_name(alias: str, previous: str | None) -> str:
    """Monotonic versioning: alias `gale` -> gale_v1, gale_v2, ...

    Never reuses a name. A fresh name per run means the previous collection stays intact
    and queryable for rollback until it is explicitly removed.
    """
    if previous and previous.startswith(f"{alias}_v"):
        try:
            return f"{alias}_v{int(previous.rsplit('_v', 1)[1]) + 1}"
        except (ValueError, IndexError):
            pass
    return f"{alias}_v{int(time.time())}"


def load_chunks(
    pdf_path: Path, *, chunk_size: int, overlap: int, limit: int | None = None
) -> list[tuple[str, int]]:
    reader = PdfReader(str(pdf_path))
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=overlap)
    out: list[tuple[str, int]] = []
    for page_no, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        if len(text) < 40:
            continue
        for piece in splitter.split_text(text):
            out.append((piece, page_no))
            if limit and len(out) >= limit:
                return out
    return out


def chunk_id(text: str, page: int) -> str:
    """Content-addressed id. This is what makes the job IDEMPOTENT: SQS guarantees
    at-least-once delivery, so a duplicate message must overwrite the same points rather
    than duplicate them. Qdrant point ids are a deterministic uuid5 of this value (S3)."""
    return hashlib.sha1(f"{page}:{text}".encode()).hexdigest()  # noqa: S324 — id, not a MAC


async def ingest_corpus(
    settings: Settings,
    pdf_path: Path,
    *,
    alias: str,
    limit: int | None = None,
) -> IngestResult:
    started = time.perf_counter()
    embedder = BgeEmbedder(settings.embedding_model_id, settings.embedding_dim)
    sparse = Bm25Encoder() if settings.hybrid_search else None

    probe = QdrantVectorStore(settings.qdrant_url, alias, settings.embedding_dim)
    previous = await probe.resolve_alias(alias)
    target = _next_collection_name(alias, previous)
    logger.info("ingesting into %s (alias=%s, previous=%s)", target, alias, previous)

    store = QdrantVectorStore(settings.qdrant_url, target, settings.embedding_dim)
    await store.ensure_collection()

    raw = load_chunks(
        pdf_path, chunk_size=settings.chunk_size, overlap=settings.chunk_overlap, limit=limit
    )
    logger.info("chunked %s passages; embedding at %sd", len(raw), settings.embedding_dim)
    vectors = await embedder.embed_documents([t for t, _ in raw])
    sparse_vectors = (
        list(sparse.encode_documents([t for t, _ in raw])) if sparse else [None] * len(raw)
    )

    chunks: list[RetrievedChunk] = []
    for (text, page), vec, sv in zip(raw, vectors, sparse_vectors, strict=True):
        meta: dict[str, object] = {"_vector": vec}
        if sv is not None:
            meta["_sparse"] = sv
        chunks.append(
            RetrievedChunk(
                id=chunk_id(text, page), text=text, source=SOURCE_NAME, page=page, metadata=meta
            )
        )

    written = 0
    for i in range(0, len(chunks), UPSERT_BATCH):
        written += await store.upsert(chunks[i : i + UPSERT_BATCH], collection=target)
        logger.info("upserted %s/%s", written, len(chunks))

    # VERIFY BEFORE SWAP. Swapping to a collection with the wrong count would publish a
    # silently-truncated corpus — exactly the failure the alias exists to prevent.
    actual = await store.count(target)
    if actual != len(chunks):
        await store.delete_collection(target)
        raise RuntimeError(
            f"ingest verification failed: expected {len(chunks)} points, found {actual}. "
            f"Alias left pointing at {previous!r}; incomplete collection removed."
        )

    await store.ensure_alias(alias, target)
    logger.info("alias %s -> %s (%s chunks)", alias, target, actual)

    # AFTER the swap, never before: the alias must already point at the new collection,
    # so a crash here leaves extra collections (harmless, and the next run cleans them)
    # rather than deleting something still serving traffic.
    #
    # I3.7: without this, every re-ingest left its predecessor behind forever - five
    # stale copies of the corpus at ~29MB each. Keeping ONE previous version is what
    # makes rollback a single alias operation, which is the entire point of the D11
    # indirection; keeping all of them just makes `GET /collections` unreadable.
    pruned = await store.prune_superseded(alias, keep=1)
    if pruned:
        logger.info("pruned %d superseded collection(s): %s", len(pruned), ", ".join(pruned))

    await store.close()
    await probe.close()

    return IngestResult(
        collection=target,
        alias=alias,
        chunks=actual,
        duration_s=time.perf_counter() - started,
        previous_collection=previous,
    )
