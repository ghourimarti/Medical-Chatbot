"""medapi — the FastAPI query service.

Vendor SDKs (qdrant-client, groq, sentence-transformers) are imported here, behind the
medcore port protocols — never in medcore itself. This is the layer where D2/D4/D5/D12
adapters live and stay swappable.
"""

__version__ = "0.1.0"
