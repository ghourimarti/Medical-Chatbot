"""Readiness under a SLOW dependency, which is a different failure from a DOWN one.

INFRA-3: right after a 7,080-chunk ingest, Qdrant was optimising and `get_collection`
blocked past 20 seconds - while the API served a grounded answer with citations the whole
time. An unbounded probe turns that into an outage, and hits every replica at once right
after a re-index. These tests pin the distinction the fix depends on.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from medapi import routes


class _Store:
    def __init__(self, behaviour: str) -> None:
        self._behaviour = behaviour

    async def health(self) -> bool:
        if self._behaviour == "slow":
            await asyncio.sleep(30)
            return True
        return self._behaviour != "down"


def _services(behaviour: str) -> SimpleNamespace:
    return SimpleNamespace(store=_Store(behaviour), embedder=SimpleNamespace())


@pytest.fixture(autouse=True)
def _reset_grace() -> None:
    routes._last_ready_ok = None


@pytest.mark.asyncio
async def test_healthy_dependency_is_ready() -> None:
    assert await routes._readiness_checks(_services("ok")) == (True, True)


@pytest.mark.asyncio
async def test_probe_returns_promptly_when_dependency_hangs() -> None:
    """The point of the bound: answer fast. A probe slower than the orchestrator's
    timeoutSeconds is not 'slow', it is recorded as a failure."""
    routes._last_ready_ok = None
    loop = asyncio.get_running_loop()
    start = loop.time()
    await routes._readiness_checks(_services("slow"))
    assert loop.time() - start < routes._READINESS_TIMEOUT + 1.0


@pytest.mark.asyncio
async def test_slow_dependency_coasts_on_last_good_result() -> None:
    """A blip must not evict a pod that just proved it could serve."""
    assert await routes._readiness_checks(_services("ok")) == (True, True)
    assert await routes._readiness_checks(_services("slow")) == (True, True)


@pytest.mark.asyncio
async def test_slow_dependency_fails_once_grace_lapses() -> None:
    """Grace is a window, not an amnesty: a real outage still takes the pod out."""
    assert await routes._readiness_checks(_services("ok")) == (True, True)
    routes._last_ready_ok -= routes._READINESS_GRACE + 1
    assert await routes._readiness_checks(_services("slow")) == (False, True)


@pytest.mark.asyncio
async def test_down_dependency_fails_immediately_without_grace() -> None:
    """A definite False is an answer, not a timeout - grace must not apply to it,
    or a genuinely broken pod would keep serving for the whole window."""
    assert await routes._readiness_checks(_services("ok")) == (True, True)
    assert await routes._readiness_checks(_services("down")) == (False, True)
