# P5.2 — System load test

> Reproduce: `make load-cache` · `make load-guard` · `make load-full` · Date: 2026-08-17
> Harness: [tests/load/system_load.js](../tests/load/system_load.js)

S14 benchmarked the serving **engine**. This benchmarks the **system**: FastAPI's event
loop, Redis, Postgres, guardrails, quotas, and the retrieval pipeline.

## Environment — and why the absolute numbers are a floor, not a ceiling

Single box: API (1 uvicorn worker), Redis, Postgres, Qdrant, SGLang on one consumer GPU,
**and k6 itself**, all competing for the same CPU. The 350 RPS Phase-1 target cannot be
generated here, so the goal was to find the **saturation point and the shape of the
degradation**, then extrapolate with stated assumptions.

## Three tiers, built from what already exists

| Tier | What it exercises | Why it isolates something |
|---|---|---|
| `cache` | HTTP + async loop + Redis + session | Provider stubbed *for free* — a cache hit skips embed/retrieve/rerank/generate |
| `guard` | Input guardrails only | Refusals short-circuit before any expensive work — the cost of abuse traffic |
| `full`  | The real pipeline, cache-miss | Everything, on real golden-set questions |

## Results

### Tier A — cache path

| Target RPS | Achieved | Failed | p95 | p99 |
|---|---|---|---|---|
| 200 | 200 | 0% | 4 ms | **6 ms** |
| 600 | 315 | 0% | 5 ms | 24 ms |
| 1500 | 310 | 0% | 1471 ms | 4114 ms |

**Saturation ≈ 310 RPS per worker.** Past it, throughput plateaus and latency grows —
requests queue, nothing fails. That is the degradation shape you want.

### Tier B — full pipeline (cache miss)

| Target RPS | Achieved | Failed | wall p50 (miss) | wall p95 (miss) |
|---|---|---|---|---|
| 2 | 1.3 | 0% | 1835 ms | 2500 ms |
| 6 | 3.1 | 0% | 7677 ms | 16451 ms |

**Sustainable ≈ 2 RPS per replica** on this hardware. Per-stage, at low load:

| Stage | Median | Share |
|---|---|---|
| embed | ~210 ms | 11% |
| retrieve (Qdrant) | ~22 ms | 1% |
| **rerank (CPU)** | **~1000 ms** | **54%** |
| generate (SGLang) | ~700–1400 ms | 34% |

Reranking dominates, and it is **CPU** work — which is exactly why D22 put the ML models
behind their own service. On this box it is the binding constraint; on a GPU,
bge-reranker-base over 20 candidates is tens of milliseconds, not a second.

### Tier C — abuse traffic

Refusals cost **6 ms** (p99 18 ms) and zero tokens: unsafe traffic is rejected at roughly
**1/300th** the cost of answering it, because the guardrail runs before embedding. At 600
RPS the box absorbed 17,311 refusals with 0 failures. Cheap refusal is a capacity property,
not just a safety one.

### Cache economics, measured

Cache hit **13 ms** vs miss **1835 ms** — a **140x** latency difference on identical
questions. That is the single largest lever in the system and it validates D10's priority.

## Defects found — the point of the exercise

### 1. Rate limiting was bypassable by doing nothing (security) 🔴

The limiter keyed only on `session_id`, and `resolve()` mints a fresh UUID whenever no
cookie arrives. **Dropping the cookie minted a fresh quota bucket per request.**

| Client behaviour | 429s in 30 requests |
|---|---|
| Never sends the cookie | **0 / 30** |
| Persists the cookie | 5 / 30 |

The 20/min limit bound only clients that *volunteered* to be tracked. D18 specified per-IP
**and** per-session; only per-session shipped, and `client_hash()` sat unused in
`session.py` the whole time.

**Fixed:** both buckets are now checked. Verified — 9/20 blocked with the IP limit at 10.
X-Forwarded-For is honoured only for as many hops as we actually operate
(`trusted_proxy_hops`, default 0), because the header is client-supplied: trusting it
blindly restores the bypass, and ignoring it behind an ALB collapses every user into one
bucket. Tests: [test_ratelimit_ip.py](../apps/api/tests/test_ratelimit_ip.py).

### 2. The process died at 1500 RPS instead of shedding load 🔴

78% failures, then the process was gone. Cause: `redis.exceptions.MaxConnectionsError`.
The default pool **raises the moment every connection is checked out**, so a burst became
an error storm rather than a queue.

**Fixed:** `BlockingConnectionPool` with a bounded size and a wait, plus socket timeouts so
a wedged Redis cannot hold connections until TCP gives up. **After: 600 RPS at 0.00%
failures, and 1500 RPS degraded to queueing with zero failures and a live process.**

### 3. Error logging amplified the outage it was reporting 🟠

The failure wrote **2.3 MB of identical tracebacks in seconds** — one per request, formatted
synchronously, competing for the CPU the process needed to recover.

**Fixed:** [logthrottle.py](../apps/api/src/medapi/logthrottle.py) — first occurrence with
full detail, then one summary per interval carrying the suppressed count (which is the
number you actually want in an incident). Applied to all 12 per-request degradation paths
in `cache.py`, `budget.py`, `history.py`, `ratelimit.py`.

**An error path that runs once per request must not log once per request.**

### 4. Venue failures logged an empty message 🟠

`f"{self.venue}: {e}"` produced `local: ` — because `httpx.ConnectError`, `ReadTimeout`, and
`RemoteProtocolError` all have an **empty `str()`**. "Nothing is listening", "timed out",
and "server hung up" were indistinguishable. Fixed: log the exception type always, and the
response body for status errors (SGLang reports exact token counts on a 400).

### 5. Missing REDIS_URL degraded silently 🟠

Empty `REDIS_URL` is a fine local convenience, but it turns caching **off** and drops quotas
to **per-replica** in-process counters — so with N replicas the effective limit is N× the
configured one. Nothing warned. Now a startup failure outside `local`.

## Correction

An earlier PowerShell measurement loop showed a consistent ~2060 ms gap between wall time
and the server's `total_ms`, which looked like 2 seconds of uninstrumented work. It was
client-side overhead in `Invoke-RestMethod`. Measured properly with k6 on the same
endpoint, **unattributed time is 15 ms median / 21 ms p95** — the stage breakdown is
honest. The harness now reports `unattributed_ms` on every run so this stays visible.

The general trap: **your measurement tool's overhead can masquerade as server latency.**
Cross-check with a second tool before believing a number that implies a defect.

## Extrapolation to the 350 RPS NFR

Assumptions: 30% cache hit rate (Phase 1), ~5% refusals, so ~65% of traffic traverses the
full pipeline ≈ **228 RPS of pipeline work**.

At the measured 2 RPS/replica that is ~114 replicas — which is the *correct* answer to the
wrong configuration, and the reason it is unacceptable is instructive: **54% of that cost is
CPU reranking that should not be on the API box at all.** With reranking moved to the
ml-service on GPU (D22), per-request pipeline cost drops toward ~250-400 ms and the
generate stage becomes the constraint, sized by GPU count rather than replica count.

**The load test's real output is that number's composition, not the number.** A capacity
plan built on the 2 RPS figure would buy 100+ API replicas to run a model that belongs on
one GPU.

## Not yet measured

- Sustained 15/30-minute soak (runs here were 40-70 s) — memory growth and connection leak
  behaviour are unproven.
- Streaming (`stream=true`) under load; only the non-streaming path was exercised.
- Multi-worker/multi-replica scaling — every number above is **one uvicorn worker**.
