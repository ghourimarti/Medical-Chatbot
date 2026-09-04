"""Throttled error logging.

When a dependency fails under load, every in-flight request logs the same failure. At
1500 RPS a `logger.warning(..., exc_info=True)` in the Redis fallback path produced 2.3 MB
of identical tracebacks in seconds, and formatting and writing that is expensive and
synchronous, so the logging ate the CPU and I/O the process needed to recover.

So: an error path that runs once per request shouldn't log once per request. Log the first
occurrence in full, then collapse the rest into a periodic summary with the suppressed
count, which is the more useful number anyway ("12,043 in 10s" beats 12,043 tracebacks).
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger("medapi.throttled")


class ThrottledLogger:
    """Emits at most one message per `interval` per key, with a suppression count."""

    def __init__(self, interval_seconds: float = 10.0) -> None:
        self._interval = interval_seconds
        self._lock = threading.Lock()
        self._last: dict[str, float] = {}
        self._suppressed: dict[str, int] = {}

    def warning(self, key: str, message: str, *, exc_info: bool = False) -> None:
        now = time.monotonic()
        emit = False
        suppressed = 0
        with self._lock:
            last = self._last.get(key)
            if last is None or now - last >= self._interval:
                emit = True
                suppressed = self._suppressed.pop(key, 0)
                self._last[key] = now
            else:
                self._suppressed[key] = self._suppressed.get(key, 0) + 1
        if not emit:
            return
        if suppressed:
            message = f"{message} [+{suppressed} suppressed in the last {self._interval:.0f}s]"
        # exc_info only on the first emission of a burst: the traceback is identical every
        # time, and formatting it is the expensive part.
        logger.warning(message, exc_info=exc_info)
