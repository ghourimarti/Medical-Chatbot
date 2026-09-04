# Round 6 — cost, caching, and where the money goes

Every other round asks whether the answer is right. This one asks what it **cost**, and
whether the same answer could have been free.

Three levers decide the bill: which venue served, whether the cache answered instead of the
model, and — the one nobody expects — **which of the two decline paths a "no" took**.

> **Instrument reference:** Parts 0–4 of [INSPECTION_ROUND3.md](INSPECTION_ROUND3.md).

```bash
make cache-clear && make cache-ls
```

---

## The three numbers that decide the bill

```
                              ┌── cache hit ─────────► 0 tokens,  ~21 ms
question ──► guardrail ──►────┤
                 │            └── generate ──────────► ~1000 prompt tokens
                 │
                 └── refused ──────────────────────► 0 tokens,  ~15 ms
                                retrieval gate ─────► 0 tokens,  ~1.3 s  (work done, discarded)
                                model abstained ────► ~1000 tokens to say "no"
```

**Four of those five outcomes produce no answer, and they cost wildly different amounts.**
`medbot_answers_total{kind}` collapses them into two buckets. Only **Declines by path** and
**Cache events** separate them.

---

## Q1 — What is actually cached

Measured: each question asked twice, cache cleared first.

| kind | 1st call | 2nd call | cached? |
|---|---|---|---|
| `refused` (*How much ibuprofen can I take?*) | `cache_hit=False` | **`cache_hit=False`** | **no** |
| `no_answer` (*What is zzqx syndrome?*) | `cache_hit=False` | **`cache_hit=False`** | **no** |
| `grounded` (*What is chickenpox?*) | `cache_hit=False` | **`cache_hit=True`** | **yes** |

**Only GROUNDED answers are cached.** This is deliberate and worth understanding:

- Caching a **refusal** would freeze a safety decision. If a guardrail is later fixed, cached
  refusals would keep serving the old verdict.
- Caching a **no_answer** would freeze a corpus gap. Re-ingest the corpus and the cache would
  keep insisting the answer does not exist.

### Prometheus
```promql
medbot_cache_events_total{layer="response",result="hit"}    only ever moves for grounded
medbot_cache_events_total{layer="response",result="skip"}   refusals and no_answers land here
```

### Grafana
**Cache events/sec** (row 3) — watch the `skip` series. A high skip rate is not a broken
cache; it means your traffic is dominated by refusals and declines, which is a *quality*
signal wearing a cost signal's clothes.

---

## Q2 — Exactly how forgiving is the cache key?

Baseline cached: **"What is chickenpox?"**. Then, measured:

| variant | cache | what it tells you |
|---|---|---|
| `WHAT IS CHICKENPOX?` | **hit** | case is normalised |
| `What is chickenpox?` | **hit** | internal whitespace is collapsed |
| ` what is CHICKENPOX? ` | **hit** | leading/trailing space trimmed too |
| `What is chickenpox` *(no `?`)* | **MISS** | **punctuation is significant** |
| `Chickenpox, what is it?` | miss | word order matters — expected |
| `What is chicken pox?` | miss | tokenisation matters — expected |

### The finding worth acting on

**Dropping a question mark costs a full generation** — ~1000 prompt tokens and ~2.6 s for a
byte-identical answer. Plenty of people type without one. Case and whitespace are already
normalised, so the normaliser exists; trailing punctuation simply is not in it.

The last two misses are the honest limit of an **exact-match** cache and are not bugs. They
are, however, the number that decides whether semantic caching is worth building: if a large
share of your traffic is paraphrase, an embedding-keyed cache pays for itself.

### Prometheus
```promql
sum(rate(medbot_cache_events_total{layer="response",result="hit"}[5m]))
  / clamp_min(sum(rate(medbot_cache_events_total{layer="response"}[5m])), 0.001)
```

### Grafana
**Cache hit rate** (row 3). Ask the same question five times with and without the question
mark and watch the two shapes — the difference between those runs is the value of one
`.rstrip("?")`.

---

## Q3 — The cache does not save the whole request

Measured on an identical question:

```
1st (miss)   2614 ms   1017 prompt / 38 completion
2nd (hit)      21 ms   0 tokens generated
```

A hundredfold difference. But look at what the **response body** says on the cache hit:

```json
{"cache_hit": true, "usage": {"prompt_tokens": 1017, "completion_tokens": 38},
 "timings": {"total_ms": 2614}}
```

Those are the **stored answer's** numbers, replayed as content. They are deliberately *not*
re-observed into the metrics — Prometheus records 21 ms and zero tokens for this request.

> **This was a real bug once.** Replaying the original duration into the histogram made
> the cache look like a *regression*: p95 got worse the more traffic it served. If you ever
> see `Request p95` climb while `Cache hit rate` climbs, this is the first thing to check.

### Grafana
| panel | cache hit |
|---|---|
| **Request p95** | pulled **down** by a ~21 ms sample |
| **Tokens/sec** | flat |
| **1a - local-sglang** | **unchanged** — the venue label is `cache`, not the engine |
| **Cache hit rate** | up |

**Why `venue="cache"` and not `local-sglang`:** crediting the hit to the engine would let
sub-millisecond reads drag that engine's latency percentiles down and make it look faster
than it serves. The per-venue rows would then reward caching by lying about the hardware.

### Jaeger
**3 spans, ~21 ms, zero pipeline spans.** No embed, no rerank, no generate — nothing ran.

### Langfuse
**No trace at all.** Langfuse records model calls; a cache hit is the absence of one. A trace
here would double-count your spend.

---

## Q4 — The expensive "no"

> **How are asthma and cirrhosis related?**

Measured: `no_answer`, **1000 prompt tokens, 14 completion tokens.**

Both concepts are in the corpus, so retrieval returns confident candidates for each. The
coarse threshold clears, the model reads a full prompt, and honestly reports no connection.

Compare with a decline that costs nothing:

> **What is nemonia?** → `no_answer`, **0 tokens.** Nothing cleared the threshold, so the
> model was never called.

| | free decline | paid decline |
|---|---|---|
| path | `retrieval_gate` | `model_abstained` |
| prompt tokens | **0** | **~1000** |
| `generate` span | absent | **present** |
| wall time | still ~1.3 s of CPU | ~2.2 s |
| **Answers by kind** | identical | identical |

**Nonsense is cheap. Plausible-but-absent is not.** At scale this is a real line item, and the
only panel that separates them is **Declines by path**.

> A free decline is free in *tokens*, not in *time*. It still paid embed + retrieve + rerank —
> about 1.3 seconds of CPU — and threw the result away. That matters when sizing hardware.

---

## Q5 — What a venue change costs

Run the failover drill from [INSPECTION_ROUND3.md](INSPECTION_ROUND3.md) Part 6 and watch
**Tokens/sec by venue and direction** (row 3).

Measured during one ~8-minute local outage:

```
local-sglang   prompt  9,776   completion    680      (entire history)
groq           prompt 10,471   completion  2,862      (FOUR answers)
```

**Four answers during one short outage consumed more tokens than the local engine's entire
lifetime.** That single comparison is the argument for venue-labelled accounting: without the
`venue` label those tokens are one undifferentiated number and the outage is invisible in the
bill until the invoice arrives.

### Grafana
| panel | what to watch |
|---|---|
| **Tokens/sec by venue** | the `groq` series appearing at all is the alert |
| **Cost / request p95** | leaves `$0.000000` the moment a hosted leg serves |
| **1c - groq** row | fills in — before a failover it reads *"not served since restart"* |
| **Serving venue circuit breakers** | `local-sglang` climbs to **2 (open)** |

**`$0.000000` is the correct reading when self-hosted.** Any value above zero means a hosted
leg served — either you chose that, or you failed over without noticing.

---

## What to conclude

1. **Only grounded answers are cached**, and that is a correctness decision, not an
   optimisation. Cached refusals would freeze safety verdicts.
2. **The cache key normalises case and whitespace but not punctuation.** A missing `?` costs a
   full generation for a byte-identical answer.
3. **A cache hit is 100× faster and must not be credited to the engine.** `venue="cache"`
   exists so the per-venue panels keep telling the truth about hardware.
4. **The most expensive answer in the system is a plausible "no".** ~1000 tokens, recorded
   under the same `kind` as a free one.
5. **A local outage is a cost event.** Without the `venue` label you find out from the invoice.

```bash
python scripts/inspect_stack.py     # cost/request p95 and the token split
```
