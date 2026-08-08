"""Typed, fail-fast configuration (Decision 17).

demo/ reads `os.environ.get("GROQ_API_KEY")` at import time. Missing key => `None` =>
the app boots "successfully" and dies on the first user request. Here, a missing or
malformed setting raises at construction: the process refuses to start. Deploy-time
error, not 3 a.m. pager.

Nothing outside this module may read os.environ.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# DECISION GATE B (locked, D5 v2.1): bge-large-en-v1.5 => 1024 dims.
# This constant is baked into the Qdrant collection schema and every stored vector.
# Changing it = new collection + full re-embed. It is the most expensive-to-reverse
# constant in the repo, which is why it is a Literal, not an int.
EMBEDDING_DIM: Literal[1024] = 1024

Environment = Literal["local", "dev", "staging", "prod"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    environment: Environment = "local"
    log_level: str = "INFO"

    # --- LLM providers (D4: self-host primary lands in S13; hosted is the outage leg) ---
    groq_api_key: SecretStr
    groq_default_model: str = "llama-3.1-8b-instant"
    groq_escalation_model: str = "llama-3.3-70b-versatile"
    openai_api_key: SecretStr | None = None
    openai_fallback_model: str = "gpt-4o-mini"
    groq_timeout: float = 10.0

    # --- Embeddings (D5) ---
    embedding_model_id: str = "BAAI/bge-large-en-v1.5"
    embedding_dim: Literal[1024] = EMBEDDING_DIM
    reranker_model_id: str = "BAAI/bge-reranker-base"
    rerank_timeout: float = 2.0

    # --- Retrieval (D3) ---
    retrieval_top_k: int = Field(default=20, ge=1, le=100)
    rerank_top_k: int = Field(default=4, ge=1, le=20)
    no_answer_threshold: float = Field(default=0.30, ge=0.0, le=1.0)

    # --- Vector store (D2) ---
    qdrant_url: str = "http://localhost:1104"
    qdrant_collection: str = "gale_medical"

    # --- Cost controls / kill switch (D20) ---
    llm_enabled: bool = True
    cache_only_mode: bool = False
    llm_max_input_tokens: int = 3000
    llm_max_output_tokens: int = 512

    # --- DECISION GATE C (locked, D10): cache invalidation is version-key composition.
    # Bump a version => old entries go cold. No code ever writes a manual purge. ---
    prompt_version: str = "v1"
    corpus_version: str = "v1"
    index_version: str = "v1"

    @property
    def cache_namespace(self) -> str:
        """Composite key prefix. Every cached value is scoped by the exact configuration
        that produced it, so a prompt or re-index bump can never serve a stale answer."""
        return (
            f"medbot:p{self.prompt_version}:c{self.corpus_version}"
            f":i{self.index_version}:m{self.groq_default_model}"
        )

    @property
    def is_production(self) -> bool:
        return self.environment == "prod"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor. Call once at process start (FastAPI lifespan) so a bad config
    fails the readiness probe rather than the first request."""
    return Settings()  # type: ignore[call-arg]  # values come from env/.env
