"""medml — CPU inference service for embeddings and reranking.

Split out of apps/api (S5) for two reasons, in order of importance:
  1. Topology: embedding/reranking are CPU-bound and scale on a completely different
     curve than the request-concurrency-bound API. Separate deployments, separate HPAs.
  2. Performance: S3 measured 223ms for a single in-process query embedding against a
     250ms retrieval budget. Owning the backend here lets us swap torch -> ONNX int8.
"""

__version__ = "0.1.0"
