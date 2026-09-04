"""Wire contract between apps/api and apps/ml-service.

Batching is first-class: ingestion embeds thousands of passages, and a one-text-at-a-time
endpoint turns a minutes-long job into an hours-long one.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

MAX_BATCH = 512  # request-size cap is a resource control (D18), not a nicety


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=MAX_BATCH)
    # bge models want an instruction prefix on queries and nothing on documents. An
    # explicit flag rather than inference is what stops ingestion and query time drifting
    # apart, which would quietly cost retrieval quality.
    is_query: bool = False


class EmbedResponse(BaseModel):
    vectors: list[list[float]]
    model_id: str
    dimension: int
    duration_ms: float


class RerankRequest(BaseModel):
    query: str = Field(min_length=1)
    passages: list[str] = Field(min_length=1, max_length=MAX_BATCH)
    top_k: int | None = None


class ScoredPassage(BaseModel):
    index: int  # position in the submitted passages list
    score: float


class RerankResponse(BaseModel):
    results: list[ScoredPassage]  # sorted by score desc
    model_id: str
    duration_ms: float
