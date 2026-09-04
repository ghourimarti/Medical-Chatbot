# Semantic cache — go/no-go

**Decision: NO-GO.** `semantic_cache_enabled` stays `False` and the layer is not built. The
reason is measured, and it is not the reason D10 anticipated.

Reproduce: `uv run python packages/eval/tools/semantic_cache_probe.py`
Raw output: `eval-reports/semantic-cache-probe.json`

---

## First, a correction

`cache.py` stated the semantic cache "is implemented but ships DISABLED." It was never
implemented. `semantic_cache_enabled` and `semantic_cache_threshold` are declared in
`Settings` and referenced **nowhere else in the codebase** — there is no `SemanticCache`
class, no lookup path, no call site. So this is a decision about whether to *build* the
thing, not whether to *switch it on*.

D10 also justified its double guard with a specific claim: *"aspirin dose adult" and
"aspirin dose child" sit far closer than 0.95 in embedding space.* Measured against the
production embedder (bge-large-en-v1.5, `"Represent this sentence for searching relevant
passages: "`, L2-normalised):

| pair | asserted | **measured** |
|---|---|---|
| "aspirin dose adult" / "aspirin dose child" | "far closer than 0.95" | **0.8235** |

Off by 0.13, and in the safe direction. The gate was guarding against a danger that, for
this embedder, is not where it was thought to be.

## Experiment A — golden-set collisions

All 23,005 pairs of the 215 `golden_core_v2` questions:

| statistic | value |
|---|---|
| max pair similarity | **0.8541** |
| mean | 0.4448 |
| 99.9th percentile | 0.7641 |
| pairs ≥ 0.95 / 0.97 / 0.98 / 0.99 | **0 / 0 / 0 / 0** |

Not one pair of distinct golden questions reaches even 0.95. D10's literal bar — *zero
false hits on the golden set* — is **cleared with room to spare.**

That result is also nearly meaningless on its own, which is why it isn't the decision. The
golden set is deliberately *diverse*: every case is a different question. It therefore
under-samples precisely the near-duplicate region a cache lives in. Passing here proves the
cache would not confuse two unrelated questions; it says nothing about whether the cache
would ever fire, or what happens near the boundary.

## Experiment B — adversarial minimal pairs

15 hand-authored pairs differing by one clinically decisive token — the failure mode that
actually matters, where a cache hit returns a confidently *wrong* medical answer:

| similarity | distinction |
|---|---|
| **0.9133** | maximum / minimum daily dose |
| 0.9125 | how long / how often to take antibiotics |
| 0.8874 | bacterial / viral meningitis |
| 0.8871 | with / without alcohol |
| 0.8704 | taking / stopping prednisone |
| 0.8630 | start / stop warfarin |
| 0.8552 | hypoglycemia / hyperglycemia |
| 0.8307 | adult / infant dosage |
| 0.8235 | adult / child dose |
| 0.8214 | hypertension / hypotension |
| 0.8128 | type 1 / type 2 diabetes |
| 0.7942 | contagious / cancerous |
| 0.7523 | miss / double a dose |

**False hits at 0.97: 0/15.** Also 0/15 at 0.95. The ceiling on dangerous similarity is
**0.9133**.

## Experiment C — would it ever fire?

12 paraphrase pairs: same intent, same correct answer, different wording — the traffic a
semantic cache exists to catch. Pure case/punctuation variants are excluded, because
`normalize_question` already collapses those in the exact-match `ResponseCache`; counting
them would credit the semantic layer with hits it does not earn.

| threshold | paraphrases caught |
|---|---|
| 0.99 | 0 / 12 |
| **0.97 (the configured value)** | **1 / 12 (8%)** |
| 0.95 | 3 / 12 (25%) |
| 0.92 | 5 / 12 (42%) |

max 0.9820 · mean 0.9002

## The decision

| | |
|---|---|
| highest **dangerous** pair | 0.9133 |
| highest **useful** pair | 0.9820 |
| safe-and-useful window | (0.9133, 0.9820] |

A window exists. That is the argument *for* building it, and it is not good enough:

**At the configured 0.97 the cache is safe but inert** — it would catch 1 paraphrase in 12.
The exact-match layer already handles verbatim repeats, so the semantic layer's entire
contribution is that thin sliver. It cannot pay for its own complexity.

**Making it useful destroys the margin.** Reaching a 42% catch rate requires ~0.92 — which
sits **0.007** above a *known* dangerous pair ("maximum daily dose" vs "minimum daily dose",
0.9133). And 0.9133 is not the ceiling on danger; it is the maximum over **15 pairs I
happened to think of**. With a sample that small, the true ceiling over real traffic is
certainly higher. **The safety margin at a useful threshold is smaller than the sampling
error on the danger estimate** — which means the number would be chosen by luck, not
evidence.

For a medical system where a false hit is a patient-safety bug rather than a stale page,
that is not a trade to make for a single-digit hit-rate gain.

### What was not tested, and why it does not change the answer

D10's second guard — *identical top-3 chunk IDs* — was **not measured**; it needs a live
Qdrant with the full index. The conclusion is robust to it by construction: an additional
AND-condition can only ever **lower** the hit rate and **lower** the false-hit rate. Since
false hits are already 0 it can add nothing there, while the useful-hit rate (already the
binding constraint at 1/12) can only get worse. Testing it could strengthen the no-go; it
cannot overturn it.

### Also unverified

The 25-35% hit rate cited in `cache.py` as worth ~$4-6k/month is an **assumption**, never
measured — no production traffic exists yet. It describes the exact-match cache, not this
layer, and should not be read as evidence for either.

## Revisit when

1. **Real traffic exists.** Paraphrase rate in production is the number that decides this,
   and no offline proxy substitutes for it. If genuine near-duplicates cluster above 0.95,
   the economics change.
2. **The adversarial set is large enough to bound the danger ceiling** — hundreds of pairs,
   ideally mined from real traffic rather than imagined, so a threshold can be set on a
   distribution instead of a maximum-of-15.
3. **A cheaper safety net exists**, e.g. requiring the cached answer to cite the same chunk
   IDs the new query retrieves (D10's second guard) *and* an entailment check.

Until then the two exact-match layers stand: `ResponseCache` (normalised question →
grounded answers only) and `EmbeddingCache`. Both are safe by construction, because an
exact key cannot collide across meanings.
