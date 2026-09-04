"""cost attribution, spend breaker, and kill switch."""

from __future__ import annotations

import pytest
from medapi.budget import KillSwitch, SpendState, SpendTracker
from medapi.pricing import PRICE_TABLE, UNKNOWN_MODEL_PRICE, cost_usd, is_self_hosted, price_for

from medcore.schema import Usage


class FakeRedis:
    def __init__(self, *, broken: bool = False) -> None:
        self.store: dict[str, str] = {}
        self.broken = broken

    async def get(self, key: str) -> bytes | None:
        if self.broken:
            raise ConnectionError("redis down")
        v = self.store.get(key)
        return v.encode() if v is not None else None

    async def set(self, key: str, value: object, ex: int | None = None) -> None:
        if self.broken:
            raise ConnectionError("redis down")
        self.store[key] = str(value)

    def pipeline(self) -> FakePipe:
        return FakePipe(self)


class FakePipe:
    def __init__(self, r: FakeRedis) -> None:
        self._r = r
        self._ops: list[tuple[str, str, float]] = []

    def incrbyfloat(self, key: str, amount: float) -> None:
        self._ops.append(("incrbyfloat", key, amount))

    def expire(self, key: str, seconds: int) -> None:
        self._ops.append(("expire", key, 0))

    async def execute(self) -> list[float]:
        if self._r.broken:
            raise ConnectionError("redis down")
        out: list[float] = []
        for op, key, amount in self._ops:
            if op == "incrbyfloat":
                total = float(self._r.store.get(key, "0")) + amount
                self._r.store[key] = str(total)
                out.append(total)
            else:
                out.append(1)
        return out


# pricing


def test_self_hosted_models_cost_zero_per_token() -> None:
    """Their cost is GPU-HOURS, not tokens — time-based, incurred whether you serve one
    request or a million. Pricing them per token would make a forgotten $600/mo instance
    look free."""
    assert is_self_hosted("Qwen/Qwen2.5-7B-Instruct-AWQ")
    heavy = Usage(prompt_tokens=10_000, completion_tokens=5_000)
    assert cost_usd("Qwen/Qwen2.5-7B-Instruct-AWQ", heavy) == 0.0


def test_hosted_cost_matches_the_published_rate() -> None:
    # llama-3.1-8b-instant: $0.05/1M prompt, $0.08/1M completion
    one_million_each = Usage(prompt_tokens=1_000_000, completion_tokens=1_000_000)
    assert cost_usd("llama-3.1-8b-instant", one_million_each) == pytest.approx(0.13)


def test_realistic_query_is_inside_the_nfr() -> None:
    """Phase-1 NFR: <= $0.0005/query for the LLM leg. A 2k-in/300-out query on the 8B model."""
    cost = cost_usd("llama-3.1-8b-instant", Usage(prompt_tokens=2000, completion_tokens=300))
    assert cost < 0.0005


def test_unknown_model_is_priced_high_not_free() -> None:
    """A $0 default would hide spend from the very breaker meant to catch it."""
    assert price_for("some-new-model-2027") == UNKNOWN_MODEL_PRICE
    assert cost_usd("some-new-model-2027", Usage(prompt_tokens=1000, completion_tokens=1000)) > 0


def test_vendor_prefixes_resolve_to_the_same_price() -> None:
    """Venues name models differently ('groq/llama-...' vs bare)."""
    assert price_for("groq/llama-3.1-8b-instant") == PRICE_TABLE["llama-3.1-8b-instant"]


# spend tracker


@pytest.mark.asyncio
async def test_spend_accumulates_and_trips_thresholds() -> None:
    tracker = SpendTracker(FakeRedis(), "ns", daily_limit_usd=1.0)
    assert tracker.state_for(await tracker.record(0.30)) is SpendState.OK
    assert tracker.state_for(await tracker.record(0.30)) is SpendState.SOFT_ALERT  # 0.60
    assert tracker.state_for(await tracker.record(0.50)) is SpendState.EXCEEDED  # 1.10


@pytest.mark.asyncio
async def test_daily_key_rolls_over_without_a_cron_job() -> None:
    """The key encodes the UTC date, so a new day is simply a new key and the old one
    expires on its own — no scheduled reset to forget or fail."""
    redis = FakeRedis()
    tracker = SpendTracker(redis, "ns", daily_limit_usd=1.0)
    await tracker.record(0.5)
    assert any("spend:" in k for k in redis.store)


@pytest.mark.asyncio
async def test_spend_tracking_fails_open() -> None:
    """a cost control must not take the product down when Redis blips."""
    tracker = SpendTracker(FakeRedis(broken=True), "ns", daily_limit_usd=1.0)
    assert await tracker.record(5.0) == 0.0
    assert await tracker.state() is SpendState.OK


@pytest.mark.asyncio
async def test_zero_limit_disables_the_breaker() -> None:
    tracker = SpendTracker(FakeRedis(), "ns", daily_limit_usd=0.0)
    assert tracker.state_for(await tracker.record(999.0)) is SpendState.OK


# kill switch


@pytest.mark.asyncio
async def test_kill_switch_flips_at_runtime_without_redeploy() -> None:
    redis = FakeRedis()
    ks = KillSwitch(redis, "ns", env_enabled=True)
    assert await ks.llm_enabled() is True
    await ks.set_enabled(False, reason="cost incident")
    assert await ks.llm_enabled() is False
    await ks.set_enabled(True, reason="resolved")
    assert await ks.llm_enabled() is True


@pytest.mark.asyncio
async def test_env_setting_is_a_floor_that_redis_cannot_override() -> None:
    """If LLM_ENABLED=false was shipped, no stale runtime flag may turn generation back
    on — an operator's static decision outranks whatever is in Redis."""
    redis = FakeRedis()
    ks = KillSwitch(redis, "ns", env_enabled=False)
    assert await ks.set_enabled(True, reason="try to re-enable") is False
    assert await ks.llm_enabled() is False


@pytest.mark.asyncio
async def test_kill_switch_falls_back_to_env_when_redis_is_down() -> None:
    assert await KillSwitch(FakeRedis(broken=True), "ns", env_enabled=True).llm_enabled() is True
    assert await KillSwitch(FakeRedis(broken=True), "ns", env_enabled=False).llm_enabled() is False


@pytest.mark.asyncio
async def test_without_redis_the_env_setting_governs() -> None:
    assert await KillSwitch(None, "ns", env_enabled=True).llm_enabled() is True
    assert await KillSwitch(None, "ns", env_enabled=False).llm_enabled() is False
