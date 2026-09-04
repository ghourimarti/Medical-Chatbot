"""Shared contracts for the medical RAG chatbot.

Domain types, port protocols, configuration, typed errors and the prompt registry, and
nothing else. No vendor SDK is imported here: adapters live in apps/ and depend inward on
these contracts, never the reverse.
"""

__version__ = "0.1.0"
