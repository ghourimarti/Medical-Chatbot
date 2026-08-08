"""Composition root. Singletons are built ONCE at startup and stored on app state, not
rebuilt per request (demo calls create_qa_chain() on every request — the bug this kills).
"""

from __future__ import annotations

from dataclasses import dataclass

from medapi.adapters.embedder import BgeEmbedder
from medapi.adapters.model import GroqModel
from medapi.adapters.vector_store import QdrantVectorStore
from medapi.pipeline.rag import RagPipeline
from medcore.config import Settings


@dataclass(slots=True)
class Services:
    settings: Settings
    embedder: BgeEmbedder
    store: QdrantVectorStore
    model: GroqModel
    pipeline: RagPipeline


def build_services(settings: Settings) -> Services:
    embedder = BgeEmbedder(settings.embedding_model_id, settings.embedding_dim)
    store = QdrantVectorStore(
        url=settings.qdrant_url,
        collection=settings.qdrant_collection,
        dimension=settings.embedding_dim,
    )
    model = GroqModel(
        api_key=settings.groq_api_key.get_secret_value(),
        model_id=settings.groq_default_model,
        timeout=settings.groq_timeout,
    )
    pipeline = RagPipeline(settings=settings, embedder=embedder, store=store, model=model)
    return Services(
        settings=settings, embedder=embedder, store=store, model=model, pipeline=pipeline
    )
