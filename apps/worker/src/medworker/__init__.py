"""Durable, queue-driven ingestion.

Replaces an in-repo reindex script that ran in the foreground, wrote into the live
collection (so queries could see a half-ingested corpus), and left the index in an unknown
state with no retry after a crash.

This fixes all three: SQS for durability and retries, a fresh collection per run, and an
atomic alias swap that happens only once ingestion has fully succeeded.
"""

__version__ = "0.1.0"
