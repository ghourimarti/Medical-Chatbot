"""medcore — shared contracts for the P5 medical RAG chatbot.

This package holds *only* domain types, port protocols, configuration, typed errors,
and the prompt registry. It imports no vendor SDK by design (Decision 22): adapters
live in apps/, and depend inward on these contracts — never the reverse.
"""

__version__ = "0.1.0"
