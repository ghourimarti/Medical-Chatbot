# Interview notes — how to talk about this project

Written to be *used*, not admired. The claims here are ones the repo can survive being
questioned on.

---

## The 60-second version

> "I took a bootcamp RAG chatbot and rebuilt it to a production bar. The interesting part
> wasn't the retrieval architecture — it was that I built the measurement first, and then
> spent most of the project discovering the measurement was wrong.
>
> Concrete example: the safety score read 0.45, which looks like a broken guardrail. The
> actual population behind it was nine correct redirects, ten *safe* abstentions, and one
> real leak — the scorer couldn't tell 'unhelpful' from 'unsafe'. Fixing the metric mattered
> more than any change to the pipeline.
>
> The headline number is citations going from 0.000 to 1.000 — zero of sixty medical answers
> in the baseline cited a source. But the thing I'd want to be asked about is the guardrail
> that scored 100% on the twenty cases it was developed against and 37% on thirty it hadn't
> seen. The tests were green the whole time."

Then stop. That last sentence is the hook — let them pull the thread.

## The same task, done two ways

| Task | The quick way | What this repo does | Why it matters |
|---|---|---|---|
| Prove the rewrite worked | "It looks better" | Measured `demo/` baseline **first**, same harness, same 90 cases | Without a before, there is no after |
| Pick a reranker | Benchmark blog post | Measured ONNX int8 at **0.95× — slower** and published the refutation of my own proposal | The projection was arithmetic; the number was a stopwatch |
| Set a quality gate | Round numbers that feel strict | Derived from **measured run-to-run noise**; found `citation_presence ≥ 1.00` was flaky — two runs of one build straddled it | A gate that fails for reasons you can't fix trains people to re-run CI |
| Trust an LLM judge | Use the score | Calibrated against **human labels** with Cohen's κ, not raw agreement | On skewed data an always-yes rater scores 95% and carries zero information |
| Nothing fails in the sample | Report κ = 1.00 | Flagged it as **NO DISCRIMINATING DATA** and planted 12 defective answers | Absence of evidence is not a pass |
| Safety | Prompt says "don't give medical advice" | Rule engine **before** retrieval — no model to persuade, ~6 ms, 0 tokens | You cannot prompt-inject a regex |
| A guardrail misses a case | Add a pattern for it | Found the whole rule set was fitted to its own test set; rewrote around one principle and **repointed the test to the grown dataset** | Patching per-case is how you get 37% on unseen data |
| Caching | Ship it, it's free performance | Measured it and **declined** it — safe threshold is inert, useful threshold has 0.007 margin | Shipping a feature you can't justify is a liability in a medical system |
| Deploy | `kubectl apply` | One chart, `values-<vendor>.yaml`, portability claim stated **falsifiably** | If it needs a code change to move vendors, the claim failed |
| Something's blocked | Mark it done, note the caveat | `terraform validate` passes; step stays **open** because only `plan` proves the account can satisfy it | Offline validation cannot catch quotas, IAM, or name collisions |
| Rate limit hit | Retry until it works | Measured it: a hard **daily** cap, not a throttle. Recorded that a liveness check is not a capacity check | I'd already lost a 50-minute run to that assumption |

## Hard questions, and honest answers

**"Your latency got 5× worse. Isn't that a regression?"**
On full-answer wait, yes — 2214 ms to 10355 ms, and I show it. The pipeline added hybrid
retrieval, RRF fusion and cross-encoder reranking, all of which cost time and bought
groundedness. The user-facing metric is streaming TTFT, measured at 37 ms local / 163 ms
hosted, so perceived latency improved while total generation time grew. If I had to defend
one number to a product owner it would be TTFT; if I had to defend one to a clinician it
would be citation presence going 0 → 1.

**"You wrote the guardrail fixes while looking at the cases that failed. Isn't that overfitting?"**
Yes, and I say so in the docs. 50/50 is evidence of fit, not of generalisation — that case
set is now spent. The mitigation is that the rewrite was organised around one principle
(*most danger terms are only dangerous in personal context*) rather than per-case patches,
and that raised recall **and** eliminated over-refusal at the same time, which patching never
does. Proving generalisation needs cases authored after the rules were frozen. That's carried
as an open item, not claimed.

**"Why is faithfulness unmeasured? That's your headline safety metric."**
The vendor deprecated the judge model mid-project, and re-scoring is blocked on a 200k
token/day cap I've exhausted. I could have quoted the old number — it was measured with a
different judge on 23 of 60 cases and printed as if it were the full sample. That aggregate
defect is fixed (aggregates now carry their `n`), and I'd rather show a gap than a number I
know is not comparable.

**"Isn't 215 test cases small?"**
For a gate, yes. It's enough to catch category-level regressions and not enough to estimate a
distribution — which is why the noise margins in `THRESHOLDS.md` are stated as a *floor* from
two runs, not a distribution. The honest framing is that the harness is built to grow: the
215 are a strict superset of the original 90, verified case by case, so the before/after chart
didn't have to be re-earned on a different population.

**"What would you do differently?"**
Point the tests at the dataset by *version*, not by filename. One stale pin — a test still
reading `golden_core_v1` after the set grew to v2 — hid a 63% miss rate on unseen safety
cases, including two self-harm questions. Everything was green. That's the single highest-cost
mistake in the project and it was one line.

**"What's the weakest part?"**
Nothing has run on real managed Kubernetes. The chart is exercised on kind — rollouts, drains,
a deliberately broken deploy with zero user impact — and the Terraform validates offline, but
Phases 7 and 8 are unstarted. I know the difference between "validated" and "applied" and the
README keeps them in separate columns.

## Numbers worth memorising

| | |
|---|---|
| Citations | **0.000 → 1.000** |
| Guardrail recall / false refusals | **50/50** · **0/165** |
| Guardrail before the rewrite | 20/20 own cases · **11/30 unseen** |
| Failover | 2438 ms → **93 ms** |
| Images | 26.18 GB → **6.59 GB** (−75%) |
| ONNX (my refuted proposal) | **0.95×** — slower |
| Real lever on rerank | 540 ms → **64 ms** (smaller model) |
| Cache tier under load | **310 RPS**, p99 6 ms |
| RTO | Postgres 0.5 s · Qdrant 3.5 s · Redis 4.7 s |
| Semantic-cache decision | safe at 0.97 = **1/12 hits**; useful needs 0.92 = **0.007** margin |
| Judge agreement (measured) | κ **0.68** / **0.60** |
| Tests | 362 passing |

## Gaps to own before they're found

Say these first. They read as judgment when volunteered and as evasion when extracted.

- No production traffic — every hit-rate and cost figure is a projection, and labelled as one.
- Single-node Kubernetes only; HPA behaviour under real multi-node scheduling is untested.
- Clerk auth is built and the *disabled* path is fully covered; sign-in itself is unverified
  (no credentials).
- The corpus is a 1998 encyclopedia. Real medical deployment needs current sources, clinical
  review, and a regulatory conversation this project does not pretend to have had.
- κ was measured on 48 rows. That's enough to catch a broken scorer, not enough to certify a
  good one.

## Questions to ask them

Signals that you think about operating systems, not just building them.

1. "How do you know when a model change makes quality worse? Is that gate blocking?"
2. "Who calibrates your evaluators, and against what?"
3. "When a provider deprecates a model, what breaks and who finds out first?"
4. "What's your rollback for a bad index or a bad prompt — and when was it last rehearsed?"
5. "Where does safety live — the prompt, or something that can't be talked out of it?"
