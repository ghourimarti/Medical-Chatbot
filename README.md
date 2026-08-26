# Medical RAG Chatbot — a bootcamp demo taken to a production bar

A retrieval-augmented medical Q&A service over the *Gale Encyclopedia of Medicine* (2nd ed.),
rebuilt from a ~200-line notebook-grade demo into a system with a typed contract, a blocking
evaluation gate, structural safety guardrails, multi-venue LLM failover, and a Helm/Kubernetes
deployment path that is vendor-portable by construction.

The interesting part is not the architecture. It is **[`docs/FINDINGS.md`](docs/FINDINGS.md)** —
every measurement that refuted an assumption, including the ones that refuted my own
recommendations. If you read one file, read that one.

---

## The before / after

The `demo/` baseline is measured, not remembered — `docs/BASELINE.md`, scored on the same
90-case golden set with the same harness.

| Metric | demo (before) | pipeline (after) | Gate |
|---|---:|---:|---:|
| **Citation presence** | **0.000** | **1.000** | 0.99 ✅ |
| Answered (in-corpus) | 0.917 | 1.000 | 0.98 ✅ |
| Don't-know correctness | 0.800 | 0.900 | 0.9333 ❌ |
| Refusal correctness | 0.400 | 0.700 † | 0.90 ❌ |
| Answer relevancy | 0.880 | 0.954 ‡ | 0.85 ✅ |
| Faithfulness | 0.663 | *unmeasured* ‡ | 0.85 ⏳ |
| Latency p50 (full answer) | 2214 ms | 10355 ms ⚠ | — |

Zero of 60 medical answers in the baseline cited a source. That is disqualifying on its own:
an answer you cannot trace is an answer you cannot trust. It is now structurally impossible —
the typed `Answer` contract *refuses to construct* a grounded answer without a citation.

**The caveats are part of the result:**

- **†** That safety row is from a build that **predates the guardrail stage** (the run is
  timestamped 2026-08-16 19:43; `guardrails.py` landed 00:11 the next day). Measured directly
  against the current guardrail, the safety stratum scores **50/50 recall with 0/165 false
  refusals**. The eval number is stale, and is shown rather than quietly replaced.
- **‡** Judge-derived rows were scored by two different judges (the vendor deprecated the
  first model mid-project), so they are two absolute measurements, not a delta. Worse,
  `answer_relevancy` after was **n = 1 of 60** before that defect was found and fixed —
  aggregates now carry their own `n`. Faithfulness is still unmeasured, blocked on a daily
  token cap.
- **⚠** Latency *regressed* on full-answer wait, and that is expected: the pipeline added
  hybrid retrieval, RRF fusion and cross-encoder reranking. The user-facing metric is
  streaming TTFT, measured at **37 ms local / 163 ms hosted**.

## What is actually proven, and what is not

Portfolio projects usually blur these. This one keeps a ledger.

| Proven by measurement | Built but unexercised |
|---|---|
| Eval gate blocks a regression in CI | Deploy-to-cluster (no cluster yet — Phase 7) |
| Guardrail: 50/50 safety, 0 false refusals on 165 | Clerk sign-in (no credentials on this machine) |
| Failover across venues: 2438 ms → 93 ms | RunPod / AWS venues (no accounts) |
| Chaos: Redis 4.7 s · Qdrant 3.5 s · Postgres 0.5 s RTO | `terraform plan` (validated offline only) |
| Load: 310 RPS cache tier, p99 6 ms | Faithfulness re-scoring (daily judge quota) |
| kind: rollout, drain, and a broken deploy with 0 user impact | |
| Images: 26.18 GB → 6.59 GB (−75%) | |

`terraform validate` proves syntax and reference correctness. Only a `plan` proves the account
can satisfy it — quotas, AZ capacity, IAM, name collisions. So that step stays **open** rather
than being marked done on the strength of `validate`.

## Architecture

```
Browser ── Next.js BFF ──► FastAPI ──► LCEL pipeline
          (allowlist       (RFC 7807,   │
           proxy, SSE)      SSE, quota) │
                                        ├─► guardrail  ── refuse + redirect (pre-retrieval)
                                        ├─► embed      ── bge-large-en-v1.5 (1024d)
                                        ├─► retrieve   ── Qdrant hybrid: dense + BM25, server-side RRF
                                        ├─► rerank     ── cross-encoder + sigmoid + no-answer threshold
                                        └─► generate   ── failover chain, OpenAI-compatible
                                                          local vLLM/SGLang → RunPod → AWS → Groq
Postgres (history, partitioned)   Redis (response + embedding cache, quotas)
Worker (SQS → ingest → verify → atomic alias swap)
```

**Ports and adapters.** `packages/core` (`medcore`) holds the typed contracts and imports
**zero vendor SDKs**. Swapping Qdrant, the embedder, or the LLM venue touches one adapter.

**Fail-fast config.** Nothing outside `medcore.config` reads `os.environ`. A missing or
malformed setting raises at construction, so the process refuses to start — a deploy-time
error instead of a 3 a.m. page.

**Safety is structural, not prompted.** The input guardrail runs *before* retrieval and
generation: no model is involved, so there is nothing to prompt-inject, and a refusal costs
~6 ms and zero tokens.

## Repository layout

```
packages/core      medcore  — typed contracts, config, prompt registry (no vendor SDKs)
packages/eval      medeval  — golden sets, judge, calibration, gate
apps/api           medapi   — FastAPI, LCEL pipeline, guardrails, cache, venues
apps/ml-service    medml    — embedding + reranking, own deployment (CPU-scalable)
apps/worker        ingestion, retention, alias swap
apps/web           Next.js UI + BFF proxy
infra/k8s          Helm chart (kind / DOKS / EKS from one chart)
infra/terraform    AWS: VPC, EKS, RDS w/ PITR, ElastiCache, SQS + DLQ, IRSA
```

## Quick start

```bash
uv sync
cp .env.example .env          # add GROQ_API_KEY
make up                       # Qdrant + Redis + Postgres
make reindex                  # build the index, atomic alias swap
make api                      # http://localhost:5007
make smoke                    # in-corpus + out-of-corpus probes
make urls                     # every local UI and its port, read from .env
```

```bash
make check                    # ruff + mypy + 362 tests  (the CI gate)
make eval-gate                # BLOCKING quality gate — exits 1 on a regression
make chart-lint               # helm lint + rendered-object census
```

Full command list: `make help` · verification recipes: [`docs/VERIFY.md`](docs/VERIFY.md)

## Evaluation

The eval harness is the product, not a side quest (D19).

- **215 curated cases** — 150 qa / 50 safety / 15 ooc. Ground truths are extracted from the
  corpus PDF, never written from model memory; out-of-corpus topics are verified absent by
  substring scan.
- **Two-sided safety.** Five `not-a-refusal` probes exist so a system that refuses everything
  cannot score 100%.
- **Thresholds derived from measured noise**, not taste — [`docs/THRESHOLDS.md`](docs/THRESHOLDS.md).
  The old `citation_presence ≥ 1.00` gate was provably flaky: two runs of an identical build
  scored 0.9833 and 1.0000.
- **The judge is calibrated against a human**, with Cohen's κ rather than raw agreement, and
  with planted negatives because the system emits no failing safety answers to sample —
  [`docs/JUDGE_CALIBRATION.md`](docs/JUDGE_CALIBRATION.md).

## The four answer kinds

The typed `Answer` contract makes these four states exhaustive, and the UI renders each one
differently on purpose — a refusal that looks like an answer is a safety problem. These are
captured by the e2e suite (`apps/web/e2e/screenshots.spec.ts`), so they cannot drift from
what the app actually renders.

| Grounded — cited | No answer — honest abstention |
|---|---|
| ![grounded](docs/screenshots/light-02-grounded.png) | ![no answer](docs/screenshots/light-03-no-answer.png) |
| Every claim traceable to a passage | Below the rerank threshold, so it says so instead of guessing |

| Refused — dosage | Refused — emergency |
|---|---|
| ![refused dosage](docs/screenshots/light-04-refused-dosage.png) | ![emergency](docs/screenshots/light-05-emergency.png) |
| Declines **and** redirects to a pharmacist | Different copy for urgency — "call emergency services", not "ask your pharmacist" |

Category-specific refusals are a deliberate choice: one generic refusal would make both of
these worse. Someone describing chest pain needs an emergency redirect, and if *every*
refusal mentioned emergency services the advice would become noise.

Dark mode and the design-system sheet are in [`docs/screenshots/`](docs/screenshots/).

## Documentation

| | |
|---|---|
| [FINDINGS.md](docs/FINDINGS.md) | **every measurement that refuted an assumption** — start here |
| [DECISION_LOG_V2.md](docs/DECISION_LOG_V2.md) | 22 decisions with options, trade-offs, reversal cost |
| [THRESHOLDS.md](docs/THRESHOLDS.md) | how every gate number was derived |
| [SEMANTIC_CACHE.md](docs/SEMANTIC_CACHE.md) | a feature measured and **declined**, with the evidence |
| [BASELINE.md](docs/BASELINE.md) · [EVAL_S6_FINDINGS.md](docs/EVAL_S6_FINDINGS.md) | the "before", and two harness errors that were mine |
| [PHASE6_FINDINGS.md](docs/PHASE6_FINDINGS.md) · [K8S_DRILLS.md](docs/K8S_DRILLS.md) | what $0 of local Kubernetes validation caught |
| [CHAOS_DRILLS.md](docs/CHAOS_DRILLS.md) · [BACKUP_RESTORE.md](docs/BACKUP_RESTORE.md) | failure injection with measured RTO |
| [LOAD_TEST.md](docs/LOAD_TEST.md) · [benchmarks/](docs/benchmarks/) | k6 tiers; vLLM vs SGLang |
| [RUNBOOKS.md](docs/RUNBOOKS.md) · [SECURITY_AUDIT.md](docs/SECURITY_AUDIT.md) | operations and audit |

## Status

Phases 0–6 complete. Phase 7 (managed Kubernetes) and Phase 8 (EKS portability proof) are
blocked on vendor accounts, not on code — the Helm chart and Terraform are written and
validated offline.

## Not a medical device

This answers questions from one 1998 encyclopedia. It refuses diagnosis, dosing, and
prescription requests by design, and it is not a substitute for a clinician. The corpus is
used for educational and portfolio purposes.
