# Round 4 — retrieval under stress

Round 3 asked whether the pipeline works. This round asks a narrower and harder question:
**when does RETRIEVAL fail, and can you tell from the instruments which half failed?**

Every query here is answerable in principle — the corpus contains the material — but each one
attacks a different weakness in how a question becomes a vector. The interesting result is
never "it answered"; it is *which* of the two decline paths it took, and what that cost.

> **Instrument reference:** Parts 0–4 of [INSPECTION_ROUND3.md](INSPECTION_ROUND3.md) explain
> every metric, panel, span and Langfuse field. This round assumes them and focuses on
> behaviour.

```bash
make cache-clear     # mandatory - a cached answer proves nothing about retrieval
```

## What this round exercises

The retrieval half of the pipeline is three stages, and each query below stresses a different
one:

```
question ──embed──► 1024-dim vector ──retrieve──► 20 candidates ──rerank──► 4 passages
             ▲                            ▲                           ▲
        Q1 Q2 Q3                        Q4 Q6                       Q5 Q6
     (vocabulary)                  (recall/fusion)              (ordering)
```

The panels that matter here are **Stage latency p95** (row 3), **Declines by path** (row 2)
and **Tokens/sec** (row 3). The span that matters is `retrieve` / `rerank` and their
`n_chunks` attribute.

---

## The headline result

All six measured on this stack, cache cleared before each:

| # | query | kind | tokens | rerank | total | what it proves |
|---|---|---|---|---|---|---|
| Q1 | *What is COPD?* | `grounded` | 998/57 | 1111ms | 3008ms | acronyms resolve |
| Q2 | *What is high blood pressure?* | `grounded` | 1010/86 | 1178ms | 3425ms | synonyms resolve |
| Q3 | *What is nemonia?* | `no_answer` | **0/0** | 1353ms | ~1.3s | misspelling → **FREE** decline |
| Q4 | *asthma* | `grounded` | 1008/51 | 1188ms | 2872ms | bare keyword works |
| Q5 | *difference between emphysema and chronic bronchitis* | `grounded` | 1002/87 | 1252ms | 3597ms | comparative works, costs most |
| Q6 | *How are asthma and cirrhosis related?* | `no_answer` | **1000/14** | 1247ms | 2181ms | unrelated pair → **PAID** decline |

**Q3 and Q6 are both `no_answer`, and one is free while the other costs 1000 prompt tokens.**
That contrast is the whole point of this round. Read on.

---

## Q1 — Acronym

> **What is COPD?**

The corpus is a 1998 encyclopedia; "COPD" as a string is rare, but emphysema and chronic
bronchitis articles are present.

**Result:** `grounded`, 4 citations, 998/57 tokens.

### Prometheus
```promql
medbot_answers_total{kind="grounded"}                             +1
medbot_tokens_total{venue="local-sglang",direction="prompt"}      +998
medbot_stage_duration_seconds_count{stage="rerank"}               +1
```

### Grafana
- **Answers by kind** — `grounded` rises.
- **Stage latency p95** — rerank 1111ms, the usual dominant bar.
- **1a - local-sglang** — request p95 gains a ~3.0s sample.

### Jaeger
Full 12-span shape. **Open `retrieve` and read `n_chunks`.** If dense embedding resolved the
acronym, the 20 candidates will be emphysema/bronchitis passages. If it did not, retrieval
leaned on BM25 keyword matching instead — and you would see it in the rerank scores rather
than the span count.

### Langfuse — the one that answers the question
`input.n_contexts = 4`. **Read the passages.** Are they about COPD-related conditions, or did
something unrelated score highly? This is the only place that distinguishes *"the embedding
understood the acronym"* from *"BM25 got lucky on four letters"*. The trace shape is identical
either way; only the content differs.

---

## Q2 — Synonym

> **What is high blood pressure?**

The corpus indexes this as **hypertension**. The question never uses that word.

**Result:** `grounded`, 1010/86 tokens — the **longest completion of the four grounded
queries**, which is itself a signal: the model had plenty of material.

### Why this matters
This is what dense retrieval is *for*. BM25 alone would score poorly — "high blood pressure"
and "hypertension" share no tokens. If this query ever starts returning `no_answer`, the dense
half of hybrid retrieval has broken, and BM25 is carrying the system alone.

### Grafana
**Stage latency p95** — nothing unusual. The lesson is that a synonym costs no more than a
literal match; the work is identical, only the vector differs.

### Langfuse
`n_contexts = 4`, passages about hypertension. **The question said "high blood pressure" and
the passages say "hypertension" — that gap, visible in one screen, is dense retrieval
working.**

---

## Q3 — Misspelling (the FREE decline)

> **What is nemonia?**

**Result:** `no_answer`, **0 prompt tokens, 0 completion tokens.**

### Prometheus — read carefully
```promql
medbot_answers_total{kind="no_answer"}              +1
medbot_no_answers_total{path="retrieval_gate"}      +1      <-- the FREE path (verified)
medbot_tokens_total                                 UNCHANGED
medbot_request_duration_seconds{outcome="no_answer",venue="none"}  +1
```

Nothing cleared the confidence floor, so **the model was never called.** `venue` is `null`
because no venue served it.

### What actually happened
```
embed_ms     168.3     the misspelling still produced a vector
retrieve_ms   21.8     Qdrant still returned candidates
rerank_ms   1143.2     the cross-encoder scored them all
             ------
best score  < no_answer_threshold  →  decline before generating
```

**The work was done and thrown away.** A free decline is free in *tokens*, not in *time* — it
still cost ~1.3 seconds of CPU. That distinction matters when you are sizing hardware.

### Grafana
| panel | what happens |
|---|---|
| **Declines by path** | the `retrieval_gate` line rises — **the free one** |
| **Tokens/sec** | completely flat. No spend |
| **Stage latency p95** | embed, retrieve and rerank all get points; **`generate` does not** |
| **End-to-end p95 by outcome** | a `no_answer` sample of ~1.3s |

### Jaeger
The trace runs `guard → condense → embed → retrieve → rerank → build_context` and **stops
there. `generate` is ABSENT.**

> **A subtlety worth getting right.** `build_context` IS present, even though no context was
> built. The span wraps the `_build_context` method, and the no-answer gate lives *inside*
> that method — so the span opens, the gate decides to decline, and the method returns early.
> Verified by reading the instrumentation, after an earlier draft of this document claimed
> the span was absent. **`generate` is the discriminator, not `build_context`.**

Three different truncation points, three different meanings:
```
guard only ....................... refusal      (guardrail, before anything ran)
...through build_context ......... this query   (retrieval gate, FREE)
...through generate .............. Q6           (model abstained, PAID)
```

### Langfuse
A trace exists with `model: None` and `tokens: 0/0` — the same signature as a refusal, for a
different reason. `n_contexts` shows what *was* retrieved and rejected. **This is where you
see the threshold working rather than trusting it.**

> **A bug this query found, now fixed and VERIFIED.** The retrieval-gate path left
> `total_ms` at its `0.0` default, so every free decline observed **zero seconds** into
> `medbot_request_duration_seconds` while really costing over a second — dragging p95 down
> and making the service look faster than it is. `_generate` is the only other place that
> computes `total_ms`, and this path returns before reaching it.
>
> After the fix, measured on the running stack:
> `stages_sum = 3064ms, total_ms = 3064ms` — they now agree exactly.

---

## Q4 — Bare keyword

> **asthma**

One word. No verb, no question mark.

**Result:** `grounded`, 1008/51 tokens.

### Why it is worth asking
The condense gate fires on cheap signals — a pronoun, or **≤3 words**. A single-word question
is exactly the shape that trips it. On a *first* turn there is no history to condense from, so
`condense` should be present-but-trivial or absent.

### Jaeger
**Check the `condense` span.** Duration should be ~0ms. If a first-turn single-word question
produces a real condense round-trip, the gate is paying for a model call it cannot use.

### Grafana
**Stage latency p95** — if a `condense` line appears with real duration on first turns, that
is the finding.

---

## Q5 — Comparative (two concepts, both present)

> **What is the difference between emphysema and chronic bronchitis?**

**Result:** `grounded`, 1002/87 tokens, **rerank 1252ms and total 3597ms — the most expensive
grounded query of the six.**

### Why it costs more
Both concepts are in the corpus, so retrieval returns plausible candidates for *each*. The
reranker has more genuinely-competitive passages to score, and the model has more to say —
87 completion tokens, the highest here.

### Grafana
- **Stage latency p95** — rerank at its highest.
- **Tokens/sec** — the `completion` line rises more than usual.

### Langfuse — the real test
`n_contexts = 4`. **Do the four passages cover BOTH conditions, or all four the same one?**
If they all discuss emphysema, retrieval anchored on the first term and the answer is
comparing one thing against nothing. Prometheus records an ordinary grounded answer either
way. **Only Langfuse can catch this.**

This is the single most valuable check in the round: a confident, well-formed, grounded
comparison built on one-sided evidence is far more dangerous than a decline.

---

## Q6 — Two real concepts, no real relationship (the PAID decline)

> **How are asthma and cirrhosis related?**

Both are in the corpus. The *relationship* is not.

**Result:** `no_answer`, **1000 prompt tokens, 14 completion tokens.**

### Prometheus
```promql
medbot_no_answers_total{path="model_abstained"}   +1      <-- the PAID path
medbot_tokens_total{direction="prompt"}           +1000   <-- YOU PAID FOR THIS
medbot_tokens_total{direction="completion"}       +14
```

### The contrast with Q3, which is the point of this round
Both are `no_answer`. Both look identical in **Answers by kind**. They are completely
different events:

| | Q3 misspelling | Q6 unrelated pair |
|---|---|---|
| path | `retrieval_gate` | `model_abstained` |
| prompt tokens | **0** | **1000** |
| `generate` span | **absent** | **present** |
| Langfuse `model` | `None` | the model id |
| what failed | the question never matched anything | retrieval matched, the model found no link |

Retrieval cleared the coarse threshold — asthma and cirrhosis passages both score well — then
the model read a full prompt and honestly reported no connection. **That honesty costs a
full prompt every time.**

At scale this is a real cost line. Every plausible-but-absent question pays full price to
decline, and the only panel that separates it from the free path is **Declines by path**.

### Grafana
| panel | what happens |
|---|---|
| **Declines by path** | `model_abstained` rises — put this beside Q3's `retrieval_gate` rise |
| **Tokens/sec** | `prompt` climbs ~1000, `completion` barely moves — **the signature of a paid decline** |
| **Answers by kind** | indistinguishable from Q3. This is exactly why the by-path panel exists |

### Jaeger
**`generate` IS present.** That span is the proof the model was called and billed. Compare
side by side with Q3's trace, which ends at `rerank`.

---

## What to conclude

1. **Vocabulary is handled.** Acronyms (Q1), synonyms (Q2) and bare keywords (Q4) all resolve.
   Dense retrieval is doing its job.
2. **A misspelling is a cliff, not a slope.** Q3 did not degrade gracefully — it fell straight
   through the gate to zero. Fuzzy matching would change that, at the cost of precision.
3. **The expensive failure mode is the plausible one.** Q6 cost 1000 tokens to say no,
   because the question was *reasonable*. Nonsense is cheap; near-misses are not.
4. **`Answers by kind` cannot tell 2 and 3 apart.** Only **Declines by path** can, and only
   Langfuse can tell you *why* either happened.

```bash
python scripts/inspect_stack.py
```
