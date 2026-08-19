# P5.3 — Chaos drills

> Reproduce: `make chaos` · Date: 2026-08-17 · Harness: [tests/chaos/drill.py](../tests/chaos/drill.py)
> **Safety:** the harness only runs `docker stop` / `docker start`. It never runs `docker rm`,
> never touches volumes, and only acts on the four container names it is given.

## Why drill when the degradation paths already have tests

The unit tests use fakes that raise **instantly on command**. A real dependency does not
fail that politely, and every finding below was invisible to a fake:

- A stopped container refuses connections **fast**; a wedged one accepts and never answers.
  Only the second exercises timeouts — and only the second is what overload looks like.
- Recovery requires the connection **pool** to heal, not just the dependency. A fake has no
  pool, so "it works again afterwards" was untested.
- Fail-**open** (caching, D10) and fail-**safe** (quotas, D20) are opposite requirements
  living in one request path. A drill is how you learn one of them took the other's
  behaviour.

## Results — after fixes

| Dependency | Behaviour while down | Status | Recovery |
|---|---|---|---|
| **Postgres** | Answers served, grounded, latency unchanged | ✅ 200 | 4.6 s |
| **Redis** | Answers served, cache off, quotas per-replica | ✅ 200 | 4.1 s |
| **Qdrant** | Typed, retryable refusal | ✅ 503 `retrieval-unavailable` | 5.1 s |
| **Provider** | Typed, retryable refusal | ✅ 503 `service-degraded` | 64.8 s |

Nothing crashed, nothing hung, everything recovered without a restart. **The provider's
64.8 s is the real RTO** — the model has to reload into GPU memory, and no amount of
application code shortens it. That is the number an SLO must budget for, not the 5 s the
other dependencies show.

## Findings

### 1. Redis outage caused a 10x latency blowup 🔴

The service kept answering — fail-open worked exactly as D10 specified — but:

| | Steady | Redis down |
|---|---|---|
| Before fix | 2.0 s | **18.4 / 20.4 / 20.2 s** |
| After fix | 2.0 s | **12.4 s (first), then 4.7 / 6.8 s** |

The arithmetic: fail-open is implemented per **call**, and one request makes ~10 Redis
calls — response cache, embedding cache, four quota buckets, spend read, kill-switch read,
then two writes. At a 2 s socket timeout each, a dead Redis costs ~20 s before every one of
those calls individually gives up and degrades correctly.

> **Per-call fail-open is right. Per-call *timeout* is the bug.**

Fixed with [redis_guard.py](../apps/api/src/medapi/redis_guard.py): after 5 consecutive
failures the breaker opens and calls raise instantly from local state, so the existing
fail-open handlers run at ~0 ms instead of 2 s. One probe is admitted every 10 s to detect
recovery; a failed probe re-opens rather than resetting the counter. `RedisCircuitOpen` is
a plain `Exception` **on purpose** — every call site already sits inside `except Exception`
with a tested degradation branch, so the breaker reuses those paths instead of adding a
second degradation mechanism.

The first request still pays full price. That is deliberate: the breaker cannot know Redis
is down until something fails.

### 2. Qdrant outage returned an opaque 500 🔴

`RetrievalError` (503, retryable, degradable) was already defined — it was simply never
raised. The raw client exception propagated to the generic handler.

**500 means "we have a bug". 503 means "a dependency is down, retry."** Conflating them
makes the bug-rate alert fire on every dependency blip and hides real bugs inside outage
noise. Now: `503 retrieval-unavailable`.

### 3. An empty index reported itself as "no information" 🔴🔴

The most dangerous finding, surfaced by the Qdrant recovery probe returning `no_answer`
while the collection was still loading.

```python
if not state.chunks or best < self._s.no_answer_threshold:   # BEFORE
```

Those two conditions mean **opposite things**. A vector search over a populated collection
always returns its nearest neighbours, however irrelevant — so "all scores below the floor"
is a genuine abstention. Getting back **nothing** means the collection is empty, missing, or
the alias resolves to nothing.

Conflated, a broken index answers *every* question with a confident *"I don't have reliable
information on that in my reference material."* Every response is 200. No alert fires. The
service looks perfectly healthy while being uniformly wrong, and the user cannot tell the
difference between a broken index and a truthful statement about a gap in the corpus.

For a medical assistant that is the worst available failure mode: **silent, confident, and
externally undetectable.** Zero candidates now raises `RetrievalError`; the threshold gate
still returns `NO_ANSWER`. Both halves pinned by tests.

### 4. The harness reported a false pass — twice 🟠

The first Qdrant drill said the service was unaffected by Qdrant being stopped. It was not:
every probe was a **cache hit**, so retrieval never ran. The second run repeated it, because
the question pool restarts per process and earlier drills had warmed those entries.

**A chaos drill that lands on a cache tests the cache.** The harness now flushes answer-cache
keys before each drill (never `FLUSHDB`, never a volume), and explicitly flags any probe that
returns `cache_hit=True` as not meaningful.

This one is worth dwelling on: a broken drill fails **safe-looking**. It reports success,
which is the most dangerous way for a test to be wrong — an alarm that cannot ring is worse
than no alarm, because you stop listening for one.

### 5. The pass criterion was wrong 🟠

The first provider drill was flagged as a hard failure for returning 503 — which is the
*designed* response. Corrected to `{200, 429, 503} = pass`, `500 / no-response = fail`. The
criterion was wrong, not the system.

## Confirmed live

P5.2's empty venue error message is now proven fixed by observation, not just by test.
Stopping SGLang produced:

```
domain error: local: local: ConnectError: All connection attempts failed
```

where before the fix it read `local: ` — an empty string.

## Not yet drilled

- **Wedged, not stopped** — a dependency that accepts connections and never replies. This
  is the harder and more common production failure, and the drills so far only cover clean
  refusal.
- Partial failures: Qdrant up but the collection missing; Redis up but out of memory.
- Network partition and packet loss (needs `tc`/toxiproxy, not `docker stop`).
- Failure **during** a stream, mid-token.
- Multi-dependency simultaneous failure.
