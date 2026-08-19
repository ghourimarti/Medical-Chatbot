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
