"""medworker — durable, queue-driven ingestion (D11).

Replaces `scripts/reindex.py`, which had three properties unacceptable in production:
it ran in the foreground, it wrote into the LIVE collection (so queries could observe a
half-ingested corpus), and a crash left the index in an unknown state with no retry.

This package fixes all three: SQS for durability and retries, a fresh collection per run,
and an ATOMIC alias swap that only happens once ingestion has fully succeeded.
"""

__version__ = "0.1.0"
