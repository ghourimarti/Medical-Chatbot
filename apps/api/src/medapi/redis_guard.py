"""Circuit breaker around Redis (P5.3 finding).

The drill that produced this: stop Redis, and the API kept answering correctly — fail-open
worked exactly as D10 specified — but **latency went from 2.0s to 20.4s**. Functionally up,
operationally dead: the SLO is 3s at p95.

The arithmetic explains it. Fail-open is implemented per CALL, and one request makes about
ten Redis calls: response-cache get, embedding-cache get, four quota buckets, spend read,
kill-switch read, then cache and embedding writes. With a 2s socket timeout each, a
dependency that is DOWN costs 10 x 2s before every one of those calls gives up and degrades.

  Per-call fail-open is correct. Per-call TIMEOUT is the bug.

The fix is to remember. After a few consecutive failures the breaker opens and subsequent
calls raise instantly from local state, so the existing fail-open handlers run at ~0ms
instead of 2s. Every N seconds one probe is allowed through to discover recovery.

This is the same pattern as the venue breaker in `adapters/failover.py`, applied to the
other remote dependency in the request path — and the reason it was missing there is
instructive: the venue is *expected* to fail (that is why it has a chain), while Redis was
treated as infrastructure that is simply present.
"""

from __future__ import annotations

from typing import Any

from medapi.circuit import Breaker


class RedisCircuitOpen(Exception):
    """Raised locally, without touching the network, while the breaker is open.

    Deliberately an ordinary exception: every Redis call site already sits inside
    `except Exception:` with a fail-open/fail-safe branch, so opening the circuit reuses
    those tested paths rather than introducing a second degradation mechanism.
    """


class _GuardedPipeline:
    """Buffers commands like a real pipeline, but fails fast when the circuit is open."""

    def __init__(self, guard: GuardedRedis, inner: Any | None) -> None:
        self._guard = guard
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        # Command staging (incr, expire, incrbyfloat...) is buffered by redis-py and does
        # no I/O, so when the circuit is open we can safely accept and discard them; the
        # failure surfaces at execute(), which is where callers already handle it.
        if self._inner is None:
            return lambda *a, **kw: self
        return getattr(self._inner, name)

    async def execute(self) -> Any:
        if self._inner is None:
            raise RedisCircuitOpen("redis circuit open")
        try:
            result = await self._inner.execute()
        except Exception:
            self._guard._breaker.record_failure()
            raise
        self._guard._breaker.record_success()
        return result


class GuardedRedis:
    """Drop-in wrapper exposing the Redis surface this codebase uses."""

    def __init__(
        self, client: Any, *, failure_threshold: int = 5, cooldown_seconds: float = 10.0
    ) -> None:
        self._client = client
        self._breaker = Breaker(
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown_seconds,
            name="redis"
        )

    @property
    def circuit_open(self) -> bool:
        return self._breaker.is_open

    async def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        if self._breaker.is_open:
            raise RedisCircuitOpen("redis circuit open")
        try:
            result = await getattr(self._client, method)(*args, **kwargs)
        except Exception:
            self._breaker.record_failure()
            raise
        self._breaker.record_success()
        return result

    async def get(self, key: str) -> Any:
        return await self._call("get", key)

    async def set(self, key: str, value: Any, **kwargs: Any) -> Any:
        return await self._call("set", key, value, **kwargs)

    async def ping(self) -> Any:
        return await self._call("ping")

    def pipeline(self) -> _GuardedPipeline:
        if self._breaker.is_open:
            return _GuardedPipeline(self, None)
        return _GuardedPipeline(self, self._client.pipeline())

    async def aclose(self) -> None:
        await self._client.aclose()
