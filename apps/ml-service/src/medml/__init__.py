"""CPU inference service for embeddings and reranking.

Split out of apps/api for two reasons. Topology first: embedding and reranking are
CPU-bound and scale on a different curve to the concurrency-bound API, so they want their
own deployment and HPA. Performance second: a single in-process query embedding measured
223ms against a 250ms retrieval budget, and owning the backend here allows a torch ->
ONNX int8 swap.
"""

__version__ = "0.1.0"
