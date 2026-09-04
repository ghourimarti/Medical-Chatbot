"""Redis circuit breaker.

Measured in the drill: with Redis stopped the API still answered correctly — fail-open
worked — but latency went 2.0s -> 20.4s, because one request makes ~10 Redis calls and each
paid a full 2s socket timeout before degrading.

Per-call fail-open is right. Per-call TIMEOUT is the bug.
"""

from __future__ import annotations

import asyncio

import pytest
from medapi.redis_guard import GuardedRedis, RedisCircuitOpen


class _DeadRedis:
    """A Redis that HANGS then fails, like a real one that is down — not one that raises
    instantly. The distinction is the entire point: an instant-raise fake would have shown
    this system as healthy."""

    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self.calls = 0

    async def get(self, key: str) -> bytes:
        self.calls += 1
        await asyncio.sleep(self.delay)
        raise ConnectionError("connection refused")

    async def set(self, key: str, value: object, **kw: object) -> bool:
        self.calls += 1
        await asyncio.sleep(self.delay)
        raise ConnectionError("connection refused")

    def pipeline(self) -> object:
        raise AssertionError("pipeline must not be built while the circuit is open")


class _LiveRedis:
    def __init__(self) -> None:
        self.calls = 0

    async def get(self, key: str) -> bytes:
        self.calls += 1
        return b"value"


@pytest.mark.asyncio
async def test_calls_pass_through_while_healthy() -> None:
    guard = GuardedRedis(_LiveRedis(), failure_threshold=3, cooldown_seconds=60)
    assert await guard.get("k") == b"value"
    assert not guard.circuit_open


@pytest.mark.asyncio
async def test_circuit_opens_after_threshold_failures() -> None:
    dead = _DeadRedis()
    guard = GuardedRedis(dead, failure_threshold=3, cooldown_seconds=60)
    for _ in range(3):
        with pytest.raises(ConnectionError):
            await guard.get("k")
    assert guard.circuit_open
    assert dead.calls == 3


@pytest.mark.asyncio
async def test_open_circuit_stops_paying_the_timeout() -> None:
    """The property that fixes the 20s latency: once open, calls cost local time only."""
    dead = _DeadRedis(delay=0.05)
    guard = GuardedRedis(dead, failure_threshold=3, cooldown_seconds=60)
    for _ in range(3):
        with pytest.raises(ConnectionError):
            await guard.get("k")

    loop = asyncio.get_running_loop()
    start = loop.time()
    for _ in range(20):
        with pytest.raises(RedisCircuitOpen):
            await guard.get("k")
    elapsed = loop.time() - start

    assert dead.calls == 3, "no further network calls once open"
    # 20 calls x 50ms would be 1.0s if each still hit the socket.
    assert elapsed < 0.10, f"open circuit should be ~free, took {elapsed:.3f}s"


@pytest.mark.asyncio
async def test_circuit_open_is_an_ordinary_exception() -> None:
    """Call sites already wrap Redis in `except Exception` with a fail-open branch. The
    breaker must reuse those tested paths, not introduce a second degradation mechanism."""
    dead = _DeadRedis()
    guard = GuardedRedis(dead, failure_threshold=1, cooldown_seconds=60)
    with pytest.raises(ConnectionError):
        await guard.get("k")
    assert isinstance(RedisCircuitOpen("x"), Exception)
    try:
        await guard.get("k")
    except Exception:
        pass  # exactly what cache.py / ratelimit.py do
    else:
        pytest.fail("expected the open circuit to raise")


@pytest.mark.asyncio
async def test_half_open_probe_allows_recovery() -> None:
    dead = _DeadRedis()
    guard = GuardedRedis(dead, failure_threshold=2, cooldown_seconds=0.05)
    for _ in range(2):
        with pytest.raises(ConnectionError):
            await guard.get("k")
    assert guard.circuit_open

    await asyncio.sleep(0.06)
    assert not guard.circuit_open, "cooldown elapsed -> one probe allowed"

    guard._client = _LiveRedis()  # dependency came back
    assert await guard.get("k") == b"value"
    assert not guard.circuit_open


@pytest.mark.asyncio
async def test_a_failed_probe_reopens_rather_than_flapping() -> None:
    dead = _DeadRedis()
    guard = GuardedRedis(dead, failure_threshold=2, cooldown_seconds=0.05)
    for _ in range(2):
        with pytest.raises(ConnectionError):
            await guard.get("k")
    await asyncio.sleep(0.06)
    with pytest.raises(ConnectionError):
        await guard.get("k")  # the probe, and it fails
    assert guard.circuit_open, "a failed probe must re-open, not reset the counter"


@pytest.mark.asyncio
async def test_pipeline_fails_fast_without_building_one() -> None:
    dead = _DeadRedis()
    guard = GuardedRedis(dead, failure_threshold=1, cooldown_seconds=60)
    with pytest.raises(ConnectionError):
        await guard.get("k")
    pipe = guard.pipeline()  # _DeadRedis.pipeline() would assert if it were called
    pipe.incr("a").expire("a", 60)  # staging is buffered, does no I/O
    with pytest.raises(RedisCircuitOpen):
        await pipe.execute()
