# S6 eval — findings, corrections, and what the numbers actually mean

> First full evaluation of the transformed pipeline against the S1 demo baseline.
> **Two errors were found — one in the eval harness, one in the test setup — and both were
> mine, not the pipeline's.** Recording them here because the corrections are the useful part.

## Correction 1 — the abstention metric was coupled to one phrasing

S1's `expresses_uncertainty()` used substring matching, including `"don't have information"`.
The transformed pipeline's abstention text is:

> "I don't have reliable information on that in my reference material."

The word **"reliable"** sits between "have" and "information", so the substring never matched.
Result: **`dont_know_correctness` scored 0.0 while the system answered all 10 out-of-corpus
questions perfectly.** A total-failure score for flawless behavior.

**Fix:** replaced substrings with a regex tolerant of intervening words
(`(?:don'?t|do not|cannot)\s+\w*\s*(?:have|find|contain)…`), verified against the real
answers from both runs.

**Lesson:** *a metric must survive a reword of the thing it measures.* Substring matching
against implementation phrasing creates a metric that silently breaks the moment the system
improves. Corrected score: **1.000 — every out-of-corpus question correctly refused.**

## Correction 2 — the two systems were evaluated on different corpora

The first pipeline run used an index built with `--limit 1500`, i.e. ~220 of the corpus's
759 pages (**~13%**). The demo baseline used the **full** FAISS index. Most golden-set
topics (chickenpox, cirrhosis, dementia, diphtheria, endometriosis, botulism) live beyond
chunk 1500 — so the new pipeline was being asked about content it had never been given.

**Evidence that this is the explanation, not an excuse:**
- `answered` = **0.617** — 23 of 60 answerable questions returned "I don't have reliable
  information", i.e. the system correctly abstained on content that was genuinely absent.
- `context_recall` = **1.000** — when the content *was* indexed, retrieval found it every time.
- Faithfulness and answer-relevancy are dragged down mechanically by abstentions: a
  don't-know answer is neither grounded in context nor relevant to the question.

**Fix:** re-index the full corpus (`gale_medical_full_v1`) and re-run. The `--limit` flag
exists for fast dev loops and must never be used for an evaluation run.

## Run 1 results (partial corpus — NOT a valid comparison, kept for the record)

| Metric | demo (full corpus) | pipeline (13% corpus) | Reading |
|---|---:|---:|---|
| dont_know_correctness | 0.800 | **1.000** | ✅ real win |
| citation_presence | 0.000 | **0.650** | ✅ real win (target 1.0) |
| context_recall | 0.654 | **1.000** | ✅ retrieval is working |
| answered | 0.917 | 0.617 | 🚨 artifact of the missing 87% |
| faithfulness | 0.663 | 0.500 | dragged down by abstentions |
| answer_relevancy | 0.880 | 0.740 | dragged down by abstentions |
| context_precision | 0.714 | 0.420 | real: 4 chunks retrieved, several noisy |
| refusal_correctness | 0.400 | 0.350 | real gap — see below |
| latency p50 | 2214 ms | 9052 ms | real: rerank cost, see below |

## Real issues confirmed (not artifacts)

### 1. Safety questions fall through to "no answer" instead of refusing — S12 gap
13 of 20 safety cases returned the abstention text rather than an explicit refusal with a
redirect to a healthcare provider. Declining to answer a dosage question is *safe*, but it
is not the specified behavior, and it depends on retrieval happening to fail.

**Correct design:** the refusal guardrail must fire **before retrieval**, as an input
classifier — not as an accident of the retrieval path. Scheduled for **S12**; the current
prompt-only approach cannot reach the 0.95 refusal-correctness bar.

### 2b. RESOLVED — full-corpus re-run confirms the diagnosis

Re-indexed the complete corpus (**7,080 chunks**, all 759 pages) and re-ran:

| Metric | demo | pipeline @21% corpus | **pipeline @full corpus** | |
|---|---:|---:|---:|:--|
| answered | 0.917 | 0.617 | **0.983** | ✅ recovered |
| citation_presence | 0.000 | 0.650 | **0.983** | ✅ 59/60 cited |
| dont_know_correctness | 0.800 | 1.000 | **0.900** | ✅ passes 0.90 gate |
| refusal_correctness | 0.400 | 0.350 | 0.450 | ❌ still fails 0.95 |

**The control held.** Every corpus-dependent metric recovered while `refusal_correctness`
stayed low — confirming the safety gap is architectural (see issue 1), not a data artifact.

### 2c. The 9.5s eval latency was rate limiting, not the pipeline

Eval reported p50 **9568 ms**. Direct measurement immediately after showed **~1113 ms wall**:

```
embed 104ms + retrieve 9ms + rerank 800ms + generate 200ms ≈ 1113ms
```

Groq generation was **~200 ms** in isolation versus **~9,000 ms during the eval**, which ran
right after the daily judge quota was exhausted — calls were being throttled. **Latency
measured during a rate-limited window is not system latency.**

### 2d. A latency-metric bug found by that investigation
`total_ms` summed generate + embed + retrieve and **omitted `rerank_ms`** — reporting
**354 ms** for a request whose wall time was **1113 ms**. It hid the single most expensive
stage while looking authoritative. Fixed, with a regression test asserting
`total_ms == sum(all stages)`.

### 2. Latency is far over budget — the S5.9 decision, now with data
```
embed 102 ms + retrieve 13 ms + rerank 826 ms ≈ 941 ms   (NFR: retrieval p95 ≤ 250 ms)
eval-observed end-to-end p50 9052 ms
```
Hybrid retrieval itself is **8–13 ms** on 7,080 chunks (RRF fused server-side in Qdrant —
one round trip). The cost is entirely the cross-encoder.

**Measured sweep (warm, LLM excluded so rate limiting cannot distort it):**

| top_k | embed | retrieve | rerank | retrieval path | vs 250 ms NFR |
|---:|---:|---:|---:|---:|:--|
| 15 | 98 | 8 | 574 | 681 ms | ❌ |
| 10 | 98 | 8 | 373 | 479 ms | ❌ |
| 5 | 101 | 8 | 187 | **297 ms** | ❌ |

**Reranking costs ~37 ms per candidate — linear.** The decisive finding: **even at k=5 the
path is 297 ms**, still over budget, because embedding is a fixed ~100 ms floor.

### ⚠ S5.9 UPDATE — the ONNX recommendation below was WRONG. Measurement refuted it.

The projection "ONNX int8 → ~175 ms" was not borne out. Measured (fastembed ONNX Runtime):

| | torch | ONNX | speedup |
|---|---:|---:|---:|
| embed (1 query) | 126 ms | 86 ms | **1.46×** |
| rerank (k=20) | 640 ms | 673 ms | **0.95× — SLOWER** |
| rerank (k=10) | 362 ms | 381 ms | 0.95× |

Also: torch-vs-ONNX embedding **cosine similarity was only 0.938**, not ~1.0 — so swapping
the embedding backend would have required a full re-index (and the divergence is likely a
query-instruction difference in fastembed rather than quantization, which is itself a reason
to be careful about mixing embedding implementations).

**Root cause of the wrong call:** I assumed the bottleneck was *framework overhead*, which
ONNX addresses. It is actually *model size*, which ONNX does not.

### ✅ S5.9 RESOLUTION — smaller reranker, not a different runtime

| Reranker | params | rerank k=20 (warm) |
|---|---:|---:|
| `BAAI/bge-reranker-base` (current) | 278M | 540 ms |
| `Xenova/ms-marco-MiniLM-L-6-v2` | 22M | **90 ms** |
| `jinaai/jina-reranker-v1-tiny-en` | 33M | **64 ms** |

**Retrieval path, projected from measurements:**
```
ONNX embed 86 + qdrant 10 + jina-tiny rerank 64  = 160 ms  ✅ under the 250 ms NFR
torch embed 126 + qdrant 10 + jina-tiny rerank 64 = 200 ms  ✅ still under
```

**Decision:** switch the reranker model (config: `RERANKER_MODEL_ID`) rather than the
runtime. `bge-reranker-base` remains available for a quality comparison. **The quality cost
is unmeasured** — a smaller cross-encoder ranks less well — so the final choice is gated on
a `medeval compare` run across reranker variants once judge quota resets. Latency is solved;
the quality/latency trade-off is the remaining question.

**Runtime choice:** keep ONNX for embedding only if the 0.938 divergence is explained and a
re-index is done; the 1.46× is not worth an unexplained vector change on its own.

---

**(superseded) S6.7 / S5.9 DECISION — evidence-based:**
1. **Candidate reduction alone is insufficient.** It cannot reach 250 ms at any k worth
   using, and k=5 would trade real recall for a target it still misses.
2. **ONNX int8 is REQUIRED**, on both the embedder and the reranker. Projected: embed
   ~35 ms, rerank@k=10 ~130 ms → **~175 ms total**, inside budget with headroom.
3. **Target config: ONNX int8 + top_k=10**, with the quality cost of 20→10 measured by
   `medeval compare` once judge quota permits.
4. GPU pool for ml-service remains the escalation path if ONNX under-delivers (S15).

The `EmbeddingBackend` / `RerankBackend` protocols added in S5 exist precisely so this
lands without touching routes or the pipeline.

### 3. `context_precision` 0.42 — real, and expected to improve
Passing 4 chunks when 1–2 are relevant. Directly connected to issue 2: reranking fewer,
better candidates may improve precision *and* latency together.

## Operational finding — evaluation has a quota budget
The run exhausted **Groq's 100k tokens/day** free-tier limit on `llama-3.3-70b-versatile`
(the judge) at job 238/240. One full 90-case RAGAS evaluation ≈ one day's free-tier quota.

**This validates the D19 design** — 20-case smoke on PR, full set nightly — and it is now a
measured constraint rather than a guess. It also motivated `medeval rescore`, which
recomputes deterministic metrics from saved answers with **zero** model calls.

## Tooling added in response
- `medeval compare` — delta table with direction-aware metrics (higher-is-better vs
  lower-is-better) and D19 gate evaluation; `--gate` exits non-zero for CI (S17).
- `medeval rescore` — recompute deterministic metrics on saved reports when a classifier is
  fixed, so historical runs stay comparable without re-spending judge quota.

---

# S6.12 — the faithfulness re-run, and four defects it exposed

S6.12 was parked as "blocked on Groq judge quota". The judge (`judge_v2`, `openai/gpt-oss-120b`)
answers on the first try, so the recorded blocker was already stale. Unblocking it turned up
four problems that mattered more than the metric that motivated the work.

## Defect 1 — an aggregate with no `n` is an anecdote

The S6 pipeline report published:

```
answer_relevancy: 0.9537
```

computed from **one of sixty** qa cases. The S1 demo baseline published
`faithfulness: 0.6634` from **23 of 60**. Neither number is arithmetically wrong; both are
uninterpretable, and both were printed in exactly the format a full-sample result uses.

The mechanism: a rate-limited judge does not raise — RAGAS returns `NaN` per row, `NaN`
becomes `None`, `None` is skipped by the mean, and the survivors are averaged. Nothing in
the pipeline distinguishes "0.95 across sixty cases" from "0.95 across one".

This is the same class as P5.5.4 (`errors_total` declared but never emitted) and S19.3f
(the harness scoring its own refusals as answers): **not a wrong value, but a value whose
wrongness is unobservable.** Reports now carry `coverage` per metric and render `n scored`
in the table. `compare` refuses to present a metric below 80% coverage without a **THIN
COVERAGE** warning.

Two identical `_aggregate` implementations existed (runner + rescore), so the fix would have
had to be made twice or drift; they are now one `medeval.aggregate` module.

## Defect 2 — the offline re-judge path was designed but never built

S6.10 began persisting `contexts` in every report with an explicit comment saying it was so
judge metrics could be recomputed without a re-run. The consumer was never written, so when
the judge was throttled the only remedy remained a full 15-minute pipeline re-run — to fix
scores whose inputs were already on disk.

`medeval rejudge` closes that: it rebuilds judge inputs from a saved report and evaluates in
small batches, retrying only the cases still missing the primary metric. Batching is the
point — one throttled window can no longer void a whole run — and any case still unscored at
the end is written into the report's notes as `UNSCORED`, not quietly averaged away.

## Defect 3 — credentials arrived as a side effect

The first rejudge run scored **zero of sixty** across thirty batches. Not quota:

```
The api_key client option must be set either by passing api_key to the client
or by setting the GROQ_API_KEY environment variable
```

`load_dotenv()` was called inside `DemoTarget.__init__`. So `medeval run --target demo`
had credentials, and every command that does not construct a target — `rejudge`, and
`calibrate score` — silently did not. Environment loading now happens once in `main()`.

Worth recording: **the Defect-1 and Defect-2 machinery caught this.** The retry loop ran, the
coverage line reported `n=1/60`, and the warning fired. Defences built for throttling
surfaced an unrelated bug within minutes, because both failures look identical from the
outside — and the system was no longer able to hide either.

## Defect 4 — the baseline is now permanently unreproducible

Re-running the demo target to regenerate its missing contexts returned:

```
404 - The model `llama-3.1-8b-instant` does not exist or you do not have access to it
```

Groq has now retired **both** the model that generated the S1 baseline *and* the judge that
scored it (`llama-3.3-70b-versatile`, found in S19.0). The original demo report predates
context persistence, so its faithfulness cannot be recomputed either. The number `0.6634`
is a historical artifact that no longer has a reproduction path.

Consequences, stated plainly:

- **The before/after faithfulness delta cannot be made rigorous.** Before was measured by a
  deleted judge on 23 of 60 cases; after is measured by a different judge. `compare` now
  emits a **JUDGE MISMATCH** warning rather than presenting the subtraction as if it meant
  something.
- The defensible claim is the **absolute** one: the current pipeline's faithfulness under
  `judge_v2` at full coverage, against the D19 gate of 0.85.
- The deterministic metrics (citations, refusal, don't-know) are judge-independent and
  remain fully comparable. They carry the money chart.

This is the strongest argument the project has produced for D4b's multi-venue design, and it
is not the one D4b was written for. Outage protection was the stated rationale; **vendor
retirement of a pinned model** is the sharper risk. A self-hosted vLLM venue serves weights
we hold as a file — it cannot 404. An eval baseline that depends on a hosted model has a
shelf life set by someone else's product roadmap.

**Practice change:** reports are the archive of record, not the models. Persist answers,
contexts, and the judge identity with every run, because any of the three may become
unobtainable — and prefer a self-hosted judge for anything intended as a long-lived baseline.
