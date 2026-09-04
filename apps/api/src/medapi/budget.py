"""Daily spend tracking and the kill switch.

Two controls with different jobs:

  SpendTracker  automatic. Accumulates real cost per UTC day and trips at a configured
                ceiling.

  KillSwitch    manual. An operator decision, flippable at runtime with no redeploy, so
                stopping a runaway doesn't wait on a CI pipeline.

Both resolve to CACHE_ONLY_MODE: serve from cache, otherwise return an honest degraded
answer. Never a raw error, never an unbounded bill.

They fail in opposite directions, which is intentional. Spend tracking fails open, since a
Redis blip shouldn't take the product offline over a cost control. The kill switch fails
closed to its last known state and the env floor always applies, so generation that an
operator turned off can't quietly turn itself back on.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from medapi.logthrottle import ThrottledLogger

logger = logging.getLogger("medapi.budget")
_throttled = ThrottledLogger()

KILL_SWITCH_KEY = "killswitch:llm_enabled"


class SpendState(StrEnum):
    OK = "ok"
    SOFT_ALERT = "soft_alert"  # >= 50% of the daily ceiling
    EXCEEDED = "exceeded"  # >= 100%, generation stops


class SpendTracker:
    """Per-UTC-day spend accumulator. `client=None` disables tracking entirely."""

    def __init__(
        self,
        client: Any | None,
        namespace: str,
        *,
        daily_limit_usd: float,
        soft_alert_ratio: float = 0.5,
    ) -> None:
        self._client = client
        self._ns = namespace
        self._limit = daily_limit_usd
        self._soft = soft_alert_ratio

    def _key(self) -> str:
        # The key encodes the UTC date, so rollover needs no cron job: a new day is a
        # new key, and the old one expires on its own.
        return f"{self._ns}:spend:{datetime.now(UTC):%Y-%m-%d}"

    async def record(self, cost_usd: float) -> float:
        """Add cost, return the running daily total (0.0 when tracking is unavailable)."""
        if self._client is None or cost_usd <= 0:
            return 0.0
        try:
            key = self._key()
            pipe = self._client.pipeline()
            pipe.incrbyfloat(key, cost_usd)
            pipe.expire(key, 60 * 60 * 48)  # 2 days: survives a late-night rollover
            total = float((await pipe.execute())[0])
        except Exception:
            _throttled.warning("spend-write", "spend tracking failed; continuing", exc_info=True)
            return 0.0
        return total

    async def total_today(self) -> float:
        if self._client is None:
            return 0.0
        try:
            raw = await self._client.get(self._key())
        except Exception:
            _throttled.warning(
                "spend-read", "spend read failed; assuming under budget", exc_info=True
            )
            return 0.0
        return float(raw) if raw else 0.0

    def state_for(self, total: float) -> SpendState:
        if self._limit <= 0:
            return SpendState.OK
        if total >= self._limit:
            return SpendState.EXCEEDED
        if total >= self._limit * self._soft:
            return SpendState.SOFT_ALERT
        return SpendState.OK

    async def state(self) -> SpendState:
        """Fails open: an unreadable counter shouldn't take the product down."""
        return self.state_for(await self.total_today())


class KillSwitch:
    """Runtime on/off for generation, without a deploy.

    Precedence: the env setting is a floor. If `LLM_ENABLED=false` shipped, no Redis value
    turns generation back on; a static operator decision outranks a stale
    runtime flag.
    """

    def __init__(self, client: Any | None, namespace: str, *, env_enabled: bool) -> None:
        self._client = client
        self._ns = namespace
        self._env_enabled = env_enabled

    def _key(self) -> str:
        return f"{self._ns}:{KILL_SWITCH_KEY}"

    async def llm_enabled(self) -> bool:
        if not self._env_enabled:
            return False  # env floor: shipped-off stays off
        if self._client is None:
            return True
        try:
            raw = await self._client.get(self._key())
        except Exception:
            # Redis unavailable: honour the env setting rather than guessing.
            _throttled.warning(
                "killswitch-read", "kill-switch read failed; falling back to env", exc_info=True
            )
            return self._env_enabled
        if raw is None:
            return True
        value = raw.decode() if isinstance(raw, bytes) else str(raw)
        return value.lower() not in ("0", "false", "off")

    async def set_enabled(self, enabled: bool, *, reason: str = "") -> bool:
        """Flip at runtime. Returns the effective state after applying the env floor."""
        if self._client is None:
            logger.warning("kill switch requires Redis; ignoring request")
            return self._env_enabled
        await self._client.set(self._key(), "1" if enabled else "0")
        logger.warning("kill switch set to enabled=%s reason=%r", enabled, reason)
        return enabled and self._env_enabled
