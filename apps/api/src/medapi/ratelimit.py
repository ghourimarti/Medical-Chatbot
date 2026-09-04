"""Rate limiting and quotas.

Caching fails open (Redis down means slower but still correct). Rate limiting must not: a
limiter that disappears during a Redis outage turns an infrastructure incident into an
unmetered-spend one, exactly when you can least afford it. So there's an in-process
fallback, weaker (per-replica, so the effective global limit is N x replicas) but never
absent.

Fixed-window counters (INCR + EXPIRE) rather than a sliding-window log or token bucket.
Fixed windows allow up to 2x the limit across a boundary, which is fine for abuse
prevention and costs one round trip instead of a Lua script and a sorted set. That
imprecision would matter for billing; it doesn't for throttling.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any

from medapi.logthrottle import ThrottledLogger
from medcore.errors import QuotaExceededError

logger = logging.getLogger("medapi.ratelimit")
_throttled = ThrottledLogger()


class _InProcessLimiter:
    """Fallback for when Redis is unavailable. Per-replica, so it under-restricts across
    multiple replicas, but that beats no limit during an outage."""

    def __init__(self) -> None:
        self._buckets: dict[tuple[str, int], int] = defaultdict(int)

    def hit(self, key: str, *, limit: int, window_seconds: int) -> tuple[bool, int]:
        bucket = int(time.time() // window_seconds)
        # Bound memory: drop windows older than the current one.
        for k in [k for k in self._buckets if k[1] < bucket]:
            del self._buckets[k]
        self._buckets[(key, bucket)] += 1
        count = self._buckets[(key, bucket)]
        return count <= limit, max(0, limit - count)


class RateLimiter:
    def __init__(self, client: Any | None, namespace: str) -> None:
        self._client = client
        self._ns = namespace
        self._fallback = _InProcessLimiter()

    async def check(
        self, identity: str, *, scope: str, limit: int, window_seconds: int
    ) -> int:
        """Consume one unit. Returns remaining allowance; raises QuotaExceededError at 0.

        Raising a typed error rather than returning a bool lets the RFC 7807 handler map
        it to a 429, so the route never builds an error response itself.
        """
        key = f"{self._ns}:rl:{scope}:{identity}"
        allowed, remaining = await self._hit(key, limit=limit, window_seconds=window_seconds)
        if not allowed:
            raise QuotaExceededError(f"rate limit exceeded: scope={scope} identity={identity}")
        return remaining

    async def _hit(self, key: str, *, limit: int, window_seconds: int) -> tuple[bool, int]:
        if self._client is None:
            return self._fallback.hit(key, limit=limit, window_seconds=window_seconds)
        try:
            bucket = int(time.time() // window_seconds)
            redis_key = f"{key}:{bucket}"
            # INCR then EXPIRE in one round trip. EXPIRE is set every time rather than
            # only on creation: one extra command, and it removes the race where a key
            # created just before a crash never gets a TTL and leaks.
            pipe = self._client.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, window_seconds * 2)
            count = (await pipe.execute())[0]
            return int(count) <= limit, max(0, limit - int(count))
        except Exception:
            # Throttled, because this runs once per request and an unthrottled traceback
            # here is a self-inflicted I/O storm during the incident it is reporting.
            _throttled.warning(
                "redis-ratelimit",
                "redis rate-limit failed; using in-process fallback",
                exc_info=True,
            )
            return self._fallback.hit(key, limit=limit, window_seconds=window_seconds)
