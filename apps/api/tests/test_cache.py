"""caching rules and quota behaviour.

Uses a fake Redis rather than a live one: the behaviours under test are policy decisions
(what may be cached, what happens when Redis dies), not Redis semantics.
"""

from __future__ import annotations

import pytest
from medapi.cache import EmbeddingCache, ResponseCache, normalize_question
from medapi.ratelimit import RateLimiter

from medcore.errors import QuotaExceededError
from medcore.schema import Answer, AnswerKind, Citation


class FakeRedis:
    def __init__(self, *, broken: bool = False) -> None:
        self.store: dict[str, bytes] = {}
        self.broken = broken

    async def get(self, key: str) -> bytes | None:
        if self.broken:
            raise ConnectionError("redis down")
        return self.store.get(key)

    async def set(self, key: str, value: object, ex: int | None = None) -> None:
        if self.broken:
            raise ConnectionError("redis down")
        self.store[key] = value if isinstance(value, bytes) else str(value).encode()

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self._r = redis
        self._ops: list[tuple[str, str]] = []

    def incr(self, key: str) -> None:
        self._ops.append(("incr", key))

    def expire(self, key: str, seconds: int) -> None:
        self._ops.append(("expire", key))

    async def execute(self) -> list[int]:
        if self._r.broken:
            raise ConnectionError("redis down")
        results: list[int] = []
        for op, key in self._ops:
            if op == "incr":
                current = int(self._r.store.get(key, b"0")) + 1
                self._r.store[key] = str(current).encode()
                results.append(current)
            else:
                results.append(1)
        return results


def _grounded(text: str = "An abscess is a pus-filled area [1].") -> Answer:
    return Answer(
        kind=AnswerKind.GROUNDED, text=text,
        citations=[Citation(chunk_id="c1", source="Gale", page=78, snippet="...", score=0.9)],
        model_id="llama-3.1-8b",
    )


# normalization


def test_normalization_is_conservative() -> None:
    """Case and whitespace only. Stemming or stop-word removal would merge genuinely
    different medical questions — a lower hit rate is the correct trade."""
    assert normalize_question("  What IS   an Abscess? ") == "what is an abscess?"
    # These must NOT collapse to the same key.
    assert normalize_question("hepatitis B") != normalize_question("hepatitis C")
    assert normalize_question("is it cancer?") != normalize_question("is it not cancer?")


# response cache


@pytest.mark.asyncio
async def test_cache_roundtrip_marks_hit() -> None:
    cache = ResponseCache(FakeRedis(), "ns:v1")
    assert await cache.set("What is an abscess?", _grounded())
    hit = await cache.get("what is  an ABSCESS?")  # normalization makes this the same key
    assert hit is not None
    assert hit.cache_hit is True
    assert hit.text == _grounded().text


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [AnswerKind.REFUSED, AnswerKind.NO_ANSWER, AnswerKind.DEGRADED])
async def test_unsafe_answers_are_never_cached(kind: AnswerKind) -> None:
    """D10 safety rule: replaying a refusal or a don't-know to a DIFFERENT user is wrong,
    and a degraded answer must not outlive the outage that caused it."""
    cache = ResponseCache(FakeRedis(), "ns:v1")
    assert await cache.set("q", Answer(kind=kind, text="...")) is False
    assert await cache.get("q") is None


@pytest.mark.asyncio
async def test_version_bump_invalidates_without_a_purge() -> None:
    """Invalidation is version-key composition. A prompt/corpus/model change
    makes old entries unreachable atomically — no purge job, no stale-serve window."""
    redis = FakeRedis()
    old = ResponseCache(redis, "medbot:pv1:cv1:iv1:m8b")
    await old.set("What is an abscess?", _grounded("old answer [1]."))
    assert (await old.get("What is an abscess?")) is not None

    new = ResponseCache(redis, "medbot:pv2:cv1:iv1:m8b")  # prompt_version bumped
    assert await new.get("What is an abscess?") is None


@pytest.mark.asyncio
async def test_cache_fails_open_when_redis_is_down() -> None:
    """Redis down => slower and costlier, never wrong or unavailable."""
    cache = ResponseCache(FakeRedis(broken=True), "ns:v1")
    assert await cache.get("q") is None  # miss, not an exception
    assert await cache.set("q", _grounded()) is False


@pytest.mark.asyncio
async def test_cache_disabled_without_redis() -> None:
    cache = ResponseCache(None, "ns:v1")
    assert not cache.enabled
    assert await cache.get("q") is None
    assert await cache.set("q", _grounded()) is False


# embedding cache


@pytest.mark.asyncio
async def test_embedding_cache_roundtrip_preserves_values() -> None:
    cache = EmbeddingCache(FakeRedis(), "ns:v1")
    vec = [0.1, -0.25, 0.75] * 341 + [0.5]  # 1024 dims
    assert await cache.set("what is cirrhosis?", vec)
    got = await cache.get("what is cirrhosis?")
    assert got is not None and len(got) == 1024
    assert got[0] == pytest.approx(0.1, abs=1e-6)  # float32 packing round-trip


@pytest.mark.asyncio
async def test_embedding_cache_fails_open() -> None:
    cache = EmbeddingCache(FakeRedis(broken=True), "ns:v1")
    assert await cache.get("q") is None
    assert await cache.set("q", [0.1] * 1024) is False


# rate limiting


@pytest.mark.asyncio
async def test_quota_raises_typed_error_at_the_limit() -> None:
    limiter = RateLimiter(FakeRedis(), "ns:v1")
    for _ in range(3):
        await limiter.check("session-1", scope="minute", limit=3, window_seconds=60)
    with pytest.raises(QuotaExceededError):
        await limiter.check("session-1", scope="minute", limit=3, window_seconds=60)


@pytest.mark.asyncio
async def test_quota_is_isolated_per_identity() -> None:
    limiter = RateLimiter(FakeRedis(), "ns:v1")
    await limiter.check("a", scope="minute", limit=1, window_seconds=60)
    await limiter.check("b", scope="minute", limit=1, window_seconds=60)  # unaffected


@pytest.mark.asyncio
async def test_rate_limiting_does_NOT_fail_open_when_redis_dies() -> None:
    """The deliberate asymmetry vs caching: a limiter that vanishes during a Redis outage
    converts an infrastructure incident into an unmetered-spend incident. The in-process
    fallback is weaker (per-replica) but never absent."""
    limiter = RateLimiter(FakeRedis(broken=True), "ns:v1")
    for _ in range(2):
        await limiter.check("s", scope="minute", limit=2, window_seconds=60)
    with pytest.raises(QuotaExceededError):
        await limiter.check("s", scope="minute", limit=2, window_seconds=60)


@pytest.mark.asyncio
async def test_limiter_without_redis_still_limits() -> None:
    limiter = RateLimiter(None, "ns:v1")
    await limiter.check("s", scope="minute", limit=1, window_seconds=60)
    with pytest.raises(QuotaExceededError):
        await limiter.check("s", scope="minute", limit=1, window_seconds=60)


# the semantic cache decision, pinned


def test_semantic_cache_stays_off_by_default() -> None:
    """Measured and declined (docs/SEMANTIC_CACHE.md). Flipping this default is a
    patient-safety decision, not a performance tweak: at a threshold loose enough to be
    useful (~0.92) the margin above a known-dangerous pair is 0.007, which is thinner than
    the sampling error on the 15-pair adversarial set that produced it."""
    from medcore.config import Settings

    assert Settings.model_fields["semantic_cache_enabled"].default is False


def test_no_semantic_cache_implementation_exists() -> None:
    """Guards against the defect found in the docstring rather than the code: the
    comment claimed a semantic cache was 'implemented but disabled' when none existed. If
    someone builds one, this test fails and forces docs/SEMANTIC_CACHE.md to be revisited
    along with the threshold evidence — rather than the layer arriving silently."""
    import medapi.cache as cache_module

    assert not hasattr(cache_module, "SemanticCache")
