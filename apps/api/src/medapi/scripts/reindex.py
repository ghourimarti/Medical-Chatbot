"""Temporary ingestion (S3). Load the Gale PDF -> chunk -> bge-embed at 1024d -> upsert
to Qdrant. Replaced by the durable SQS/worker pipeline with alias-swap in S9.

The demo ships a 384-dim MiniLM FAISS index; it CANNOT be reused (D5). This re-embeds
the corpus at 1024 dims. `--limit N` ingests only the first N chunks for fast dev/tests.

  uv run medapi-reindex --limit 400
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from medapi.adapters.embedder import BgeEmbedder
from medapi.adapters.vector_store import QdrantVectorStore
from medcore.config import get_settings
from medcore.schema import RetrievedChunk

REPO_ROOT = Path(__file__).resolve().parents[5]
PDF_PATH = REPO_ROOT / "demo" / "data" / "The_GALE_ENCYCLOPEDIA_of_MEDICINE_SECOND.pdf"
SOURCE_NAME = "Gale Encyclopedia of Medicine (2nd ed.)"


def _load_chunks(limit: int | None) -> list[tuple[str, int]]:
    reader = PdfReader(str(PDF_PATH))
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
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


async def reindex(limit: int | None, collection: str | None) -> int:
    settings = get_settings()
    coll = collection or settings.qdrant_collection
    embedder = BgeEmbedder(settings.embedding_model_id, settings.embedding_dim)
    store = QdrantVectorStore(settings.qdrant_url, coll, settings.embedding_dim)
    await store.ensure_collection()

    raw = _load_chunks(limit)
    print(f"chunked {len(raw)} passages; embedding at {settings.embedding_dim}d ...", flush=True)
    vectors = await embedder.embed_documents([t for t, _ in raw])

    chunks: list[RetrievedChunk] = []
    for (text, page), vec in zip(raw, vectors, strict=True):
        cid = hashlib.sha1(f"{page}:{text}".encode()).hexdigest()  # noqa: S324 — id only
        chunks.append(
            RetrievedChunk(
                id=cid, text=text, source=SOURCE_NAME, page=page, metadata={"_vector": vec}
            )
        )
    n = 0
    for i in range(0, len(chunks), 256):
        n += await store.upsert(chunks[i : i + 256], collection=coll)
        print(f"upserted {n}/{len(chunks)}", flush=True)
    await store.close()
    print(f"done: {n} chunks in collection '{coll}'")
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="ingest only the first N chunks")
    ap.add_argument("--collection", default=None, help="override target collection")
    args = ap.parse_args()
    asyncio.run(reindex(args.limit, args.collection))


if __name__ == "__main__":
    main()
