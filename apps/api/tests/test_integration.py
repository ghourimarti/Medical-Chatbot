"""Integration: real Qdrant (docker compose), real bge-large embedder. NO Groq — the
generate stage is stubbed so the test is deterministic and offline-for-the-LLM, while
proving the parts a unit test can't: the 1024-dim collection, the transport, and that a
real embedding retrieves the right passage.

Skips automatically if Qdrant isn't reachable, so `make check` stays green without Docker.
Run the real thing with:  RUN_QDRANT_TESTS=1 uv run pytest apps/api/tests/test_integration.py
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Sequence

import pytest
from medapi.adapters.embedder import BgeEmbedder
from medapi.adapters.vector_store import QdrantVectorStore
from medapi.pipeline.rag import RagPipeline

from medcore.config import get_settings
from medcore.schema import Completion, Message, RetrievedChunk

pytestmark = pytest.mark.integration


async def _qdrant_reachable(url: str) -> bool:
    import httpx

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            return (await client.get(f"{url}/readyz")).status_code == 200
    except Exception:
        return False


class StubModel:
    model_id = "stub-llm"

    async def complete(
        self, *, messages: Sequence[Message], max_tokens: int, temperature: float
    ) -> Completion:
        # Echo that the context reached the model, proving retrieval fed generation.
        ctx = messages[-1].content
        cited = "cirrhosis" in ctx.lower()
        return Completion(
            text="Cirrhosis is scarring of the liver [1]." if cited else "no context",
            model_id=self.model_id,
        )

    async def stream(self, **_: object) -> object:  # pragma: no cover
        raise NotImplementedError

    async def health(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_end_to_end_retrieval_at_1024_dim() -> None:
    settings = get_settings()
    if not (os.getenv("RUN_QDRANT_TESTS") or await _qdrant_reachable(settings.qdrant_url)):
        pytest.skip("Qdrant not reachable; start it with `docker compose up -d qdrant`")

    coll = f"test_{uuid.uuid4().hex[:8]}"
    embedder = BgeEmbedder(settings.embedding_model_id, settings.embedding_dim)
    store = QdrantVectorStore(settings.qdrant_url, coll, settings.embedding_dim)
    await store.ensure_collection()

    docs = [
        "Cirrhosis is a chronic degenerative disease in which normal liver cells are "
        "damaged and replaced by scar tissue.",
        "Asthma is a chronic respiratory condition that inflames and narrows the airways.",
        "Chickenpox, also called varicella, is an infectious childhood disease.",
    ]
    vecs = await embedder.embed_documents(docs)
    chunks = [
        RetrievedChunk(id=f"d{i}", text=d, source="Gale", page=i, metadata={"_vector": v})
        for i, (d, v) in enumerate(zip(docs, vecs, strict=True))
    ]
    assert await store.upsert(chunks, collection=coll) == 3

    pipe = RagPipeline(settings=settings, embedder=embedder, store=store, model=StubModel())
    ans = await pipe.answer("What is cirrhosis?")

    assert ans.kind.value == "grounded"
    assert ans.citations, "a grounded answer must cite"
    # The top retrieved chunk for a cirrhosis query must be the cirrhosis passage.
    assert "liver" in ans.citations[0].snippet.lower()

    await store._client.delete_collection(coll)
    await store.close()
