# Transformation Plan — demo/ → production monorepo (v2.1 architecture)

> **Status: DRAFT — awaiting Phase-3 approval.** Implements [DECISION_LOG_V2.md](DECISION_LOG_V2.md) (v2.1, locked).
> Rules: every step is one focused session (½–1 day), ends with a **working, deployable system**, has tests + independent verification + a Definition of Done, and maps to Decision Log entries (commit messages reference them). Risk is front-loaded. `demo/` keeps serving until parity (strangler-fig), then retires.

## Invariants that hold across ALL steps

1. **Never broken:** at any commit boundary, `docker compose up` yields a working system (early: `demo/`; later: the new stack).
2. **Eval before/after:** any step touching retrieval, prompts, or models re-runs the eval smoke set and records the delta.
3. **One step = one commit** (user runs git; commands + message prepared per Protocol B).
4. **Budget:** local/compose/kind = $0 default; GPU work uses WSL2-local or spot windows (gate in S3b); no standing cloud resources until Phase 6.

---

## The steps

### S1 — Eval harness + golden set (core 90) + BASELINE of demo/  `[D19]` · 1–1.5 sessions
**What changes:** `packages/eval/` created standalone: RAGAS runner, dataset schema, judge client (Groq-70B), core golden set (60 QA / 20 safety-adversarial / 10 out-of-corpus, stratified over Gale corpus), baseline script that drives the *existing demo pipeline* unmodified.
**Tests:** unit: dataset loader, metric plumbing on known-good/known-bad fixtures (meta-eval).
**Verify:** `uv run eval --target demo --smoke 20` prints scores; full run produces `eval/reports/baseline_demo.json`.
**DoD:** Baseline numbers for demo/ recorded (faithfulness, relevancy, refusal, don't-know) + committed report. Thresholds NOT gating yet — demo is *expected* to fail them; that gap is the money chart.
**Risk front-loaded:** "Is the quality bar even measurable/achievable?" — answered before a single line is refactored.

### S2 — Monorepo skeleton + contracts + CI shell  `[D22, D17, D16-partial]` · 1 session
**What changes:** uv workspace (`apps/`, `packages/`, `infra/`, `tests/`); `packages/core`: Pydantic schemas (QueryRequest, Answer, Citation, RetrievedChunk, PipelineContext), ports (`VectorStorePort`, `ModelPort`, `EmbedderPort`, `RerankerPort`), `pydantic-settings` fail-fast config; ruff+mypy+pytest wired; GH Actions: lint→type→unit on PR. `demo/` untouched, still the app.
**Tests:** schema round-trips, config fail-fast (missing key ⇒ boot error).
**Verify:** `uv run pytest` green locally; CI green on PR.
**DoD:** Empty-but-typed monorepo; CI enforces lint/type/unit; demo still runs.

### S3 — Thin vertical slice: `apps/api` end-to-end  `[D2, D5, D6, D7]` · 1 session
**What changes:** FastAPI app (`/healthz`, `/readyz`, `POST /api/v1/query` non-streaming), LCEL pipeline v0 (self-authored runnables: embed → dense-retrieve → build_context → generate), bge-large-1024 via sentence-transformers (in-process for now), **Qdrant via docker compose — collection created at 1024d (D5 gate executed)**, hosted Groq adapter behind `ModelPort`, `scripts/reindex.py` (temporary; replaced in S9). Dockerfile (multi-stage, non-root) + compose parity.
**Tests:** pipeline unit (mock ports), integration (compose Qdrant): ingest 50 chunks → query → grounded answer with citations.
**Verify:** `docker compose up` → `curl POST /api/v1/query` returns cited answer.
**DoD:** New stack answers a real medical question from Qdrant end-to-end. Eval smoke vs this slice recorded (expect ≈ demo-level; quality comes in S6).

### S3b — GPU venue spike (timeboxed 2–3h)  `[D12 de-risk]` · 0.5 session
**What changes:** nothing in-repo but a doc: run vLLM hello-world (Llama-3.1-8B AWQ) on the chosen venue — **DECISION GATE: WSL2+local NVIDIA GPU vs cloud spot g6.xlarge (~$0.50–0.80/hr)**. Measure basic TTFT/tok/s.
**DoD:** `docs/gpu-venue.md`: venue chosen, model loads, one completion served, cost/session estimated. **Kills the biggest environmental unknown 9 steps before integration needs it.**

### S4 — SSE streaming + typed errors + resilience floor  `[D7, D21-partial]` · 1 session
**What changes:** `/api/v1/query/stream` (SSE via sse-starlette), server-side client-disconnect cancellation (provider stream aborted — spend stops), RFC 7807 error envelope, per-stage timeouts, retrieval-empty ⇒ honest don't-know path.
**Tests:** SSE integration (tokens arrive incrementally), disconnect-cancels-provider test, 7807 shape tests, don't-know path test.
**Verify:** `curl -N` shows token flow; kill curl mid-stream → server log shows cancellation.
**DoD:** Streaming works with cancellation; no raw 500 paths remain in the API surface.

### S5 — `apps/ml-service`: embeddings + reranker  `[D5, D22]` · 1 session
**What changes:** dedicated FastAPI CPU service: `/embed` (bge-large ONNX int8) + `/rerank` (bge-reranker ONNX int8); api's in-process embedding swapped for the service via `EmbedderPort`/`RerankerPort`; compose gets the service; latency budget instrumented.
**Tests:** contract tests per endpoint; api-integration with service mocked and live.
**Verify:** compose up → query flows through ml-service; `/embed` p95 logged <40ms local.
**DoD:** CPU-bound work fully out of the api event loop (D7 discipline holds under load).

### S6 — Advanced retrieval + THE EVAL DELTA  `[D3, D5-checkpoint]` · 1–1.5 sessions
**What changes:** hybrid retrieval (Qdrant dense + sparse/BM25) → RRF fusion → rerank top-20 → top-4 → no-answer confidence floor; conversation-aware query condensation; **side-by-side index bge-small vs bge-large (D5 checkpoint — measured, then loser deleted)**.
**Tests:** fusion determinism, threshold behavior, condensation unit tests; eval FULL run.
**Verify:** eval report shows lift vs S1 baseline; D5 checkpoint table (small vs large) recorded.
**DoD:** Faithfulness ≥0.85 / relevancy ≥0.80 on the core set met or gap explained; **before/after chart exists — the portfolio money chart.** Eval thresholds become BLOCKING from this step onward.

### S7 — Postgres: sessions, history, retention  `[D1, D9-partial]` · 1 session
**What changes:** RDS-shaped local Postgres (compose), SQLAlchemy 2 async + Alembic, day-partitioned `messages`, anonymous signed session cookie (Redis-backed session id in S8; cookie now), `/clear` = real deletion, partition-drop retention job.
**Tests:** migration up/down, partition create/drop, deletion-actually-deletes test, characterization test of history behavior.
**Verify:** restart survives history; `SELECT` proves partition pruning; retention job drops >30d partitions in a seeded test.
**DoD:** Stateful chat with provable GDPR deletion + retention.

### S8 — Redis: caching layers + quotas  `[D10, D20-partial]` · 1 session
**What changes:** ElastiCache-shaped Redis (compose): exact/normalized response cache (version-keyed), query-embedding cache, per-session + per-IP token-bucket rate limits, session store. **Semantic cache code lands behind a flag OFF** — enablement requires S19's false-hit proof (per D10 guard).
**Tests:** cache hit/miss/version-bump-invalidates, quota 429 (typed 7807), fail-open-on-Redis-down test.
**Verify:** repeated query → cache hit p95 <50ms local; flood → 429.
**DoD:** Cost levers live and measured; rate limiting enforced; Redis outage degrades, never errors.

### S9 — Ingestion pipeline: worker + SQS + alias swap  `[D11]` · 1–1.5 sessions
**What changes:** `apps/worker`: SQS consumer (LocalStack in compose), idempotent jobs (content-hash), pipeline load→chunk→embed(ml-service)→upsert to *new* collection → **alias swap on completion**; DLQ; admin `POST /admin/ingest` (auth seam: dev-key locally, Cognito OIDC in cloud per D9); `scripts/reindex.py` deleted.
**Tests:** idempotency (re-run = no dupes), kill-worker-mid-run → resume, alias-swap atomicity (half-ingested never serves), DLQ after N failures.
**Verify:** enqueue Gale PDF → watch alias flip with zero query downtime (continuous curl loop during swap).
**DoD:** Zero-downtime corpus updates; the committed-index-in-git anti-pattern is dead.

### S10 — `apps/web` Next.js + demo retirement  `[D8]` · 1–1.5 sessions
**What changes:** Next.js App Router chat UI: SSE consumption (fetch + ReadableStream), AbortController stop button, token render, citation chips + source popover, disclaimer banner, degraded/no-answer/error states, history + clear. **`demo/` archived to read-only reference; root README switches to the new stack.**
**Tests:** Playwright smoke (ask → stream → citation → stop button → clear).
**Verify:** compose up full stack → browser flow end-to-end.
**DoD:** Feature parity + streaming UX; strangler-fig migration complete — old app retired.

### S11 — Observability  `[D13]` · 1–1.5 sessions
**What changes:** OTel SDK spans per LCEL stage (Langfuse LC callback + OTel), attrs (TTFT, tokens, cost, cache-hit, no-answer, refusal); compose: Langfuse, Prometheus, Grafana, Loki, Alertmanager; structlog JSON→stdout with **PII redaction (no raw query text)**; dashboards: RED per stage, cost/query, cache hit rate, no-answer rate; burn-rate alert rules (fast 14.4×/1h, slow 6×/6h); sampling config (head 1–5% + tail 100% errors/slow).
**Tests:** redaction unit tests (queries never appear in log sink), span-emission integration test.
**Verify:** one query = one full trace in Langfuse with stage latencies; Grafana panels render; grep logs for query text → zero hits.
**DoD:** A stranger can answer "why was this query slow?" from dashboards alone.

### S12 — Security posture pass  `[D18]` · 1 session
**What changes:** instruction-hierarchy system prompt (retrieved text framed as data), output-must-cite check, refusal filter (dosage-regex + policy prompt), security headers/CSP, request-size caps, injection adversarial cases added to eval suite as BLOCKING, non-root/read-only-fs verified in images.
**Tests:** the adversarial suite IS the test (refusal ≥95%, injection resistance documented); header tests.
**Verify:** eval safety run green; attempt injections manually and via suite.
**DoD:** OWASP-LLM-Top-10 mapping documented; safety gates blocking in CI.

### S13 — Multi-venue serving: 4 venues + 2 engines + failover chain  `[D4, D4b, D12]` · 2.5–3 sessions
*(expanded in v1.1 to make Decision 4b explicit — it was previously implied by one line)*

**Sub-steps, each independently shippable:**
| # | Sub-step | Venue/engine | Gate |
|---|---|---|---|
| **S13.1** | `OpenAICompatModel` adapter — one class, configurable `base_url`, serves ALL venues | — | contract tests vs recorded fixtures |
| **S13.2** | Venue registry + `SERVING_PRIMARY` / `SERVING_FALLBACK_CHAIN` config | — | config tests; unknown venue fails fast |
| **S13.3** | **Venue 1 — `local`** (RTX 3060, vLLM, INT4) | local | ✅ already proven in S3b |
| **S13.4** | **Venue 4 — `groq`** (hosted floor) | hosted | ✅ already proven in S3b; port the existing GroqModel behind S13.1 |
| **S13.5** | **Venue 2 — `runpod`** (non-AWS cloud GPU, native Linux, L4/A10) | cloud | benchmark parity run; teardown documented |
| **S13.6** | **Venue 3 — `aws`** (g6 spot, needs quota approval) | cloud | Terraform-launched in S16; benchmark parity |
| **S13.7** | **SGLang** as second engine on any GPU venue | engine | same model, same GPU, A/B swap by config |
| **S13.8** | Failover chain + per-leg circuit breakers + health checks | all | **staged kill test**: kill vLLM→SGLang; kill GPU venue→cloud; kill all→hosted; kill hosted→cache |
| **S13.9** | Per-leg eval parity (D4: venues may quantize differently ⇒ answers can drift) | all | RAGAS per venue; drift documented |

**DoD:** `SERVING_PRIMARY=<venue>` switches the active venue with no code change; the failover
chain is proven by demonstration, not diagram; every venue has measured TTFT/tok-s in
`docs/gpu-venue.md`.

### S13-old — vLLM + SGLang serving integration  `[D4, D12]` *(superseded by S13.1–S13.9)*
**What changes:** `ModelPort` adapters for vLLM + SGLang (OpenAI-compatible endpoints); Llama-3.1-8B AWQ served on S3b's venue; prompts harmonized + eval'd per leg; failover chain wired: **vLLM → SGLang → hosted (Groq/Bedrock) → cache → degraded** with per-leg circuit breakers; escalation router (confidence/length → hosted 70B).
**Tests:** adapter contract tests (recorded fixtures), breaker state-machine unit tests, chain integration (kill vLLM → SGLang; kill both → hosted) with stub servers.
**Verify:** end-to-end query answered by local vLLM; staged kills walk the chain live; eval parity run (vLLM 8B vs Groq 8B answers).
**DoD:** Self-hosted primary serving works; failure chain proven by demonstration, not diagram.

### S14 — vLLM vs SGLang benchmark  `[D12]` · 1 session
**What changes:** k6 benchmark harness (same model, same GPU, same prompts): TTFT p50/p95, tokens/s aggregate, p95 under concurrency ramps, structured-output timing; `docs/benchmarks/vllm-vs-sglang.md` with methodology + results + which-when guidance.
**Verify:** reproducible via `make benchmark`.
**DoD:** Published benchmark artifact — the "measured evidence" D12 promised.

### S15 — Helm charts + kind full-stack  `[D15-partial]` · 1–1.5 sessions
**What changes:** Helm charts (api, ml-service, worker, web) + community charts (Qdrant, Prometheus, Grafana, Loki, Langfuse); values-{env}; probes wired to real readiness; NetworkPolicies default-deny; PDBs; KEDA manifest for worker (SQS depth); kind cluster runs the whole stack (serving legs point hosted — kind has no GPU).
**Tests:** `helm lint`, `helm template` golden tests, kind smoke (query flows in-cluster).
**Verify:** `make kind-up && make kind-smoke` green.
**DoD:** The system is Kubernetes-native at $0; manifests are the same ones EKS will use.

### S16 — Terraform modules + plan  `[D14, D15]` · 1–1.5 sessions
**What changes:** modules `network` (VPC 3-AZ), `eks` (managed node groups + **GPU node group: taints, NVIDIA plugin, spot staging**), `data` (RDS, ElastiCache, S3, SQS), `observability`, `app` (ECR, IRSA roles, Secrets Manager + ESO, CloudFront+WAF); backend state S3.
**Tests:** `terraform validate` + fmt in CI; `terraform plan` reviewed line-by-line — **NO APPLY (Phase 6 gates that)**.
**DoD:** Clean, reviewed plan for dev env; cost estimate per env documented (Infracost).

### S17 — CI/CD completion  `[D16]` · 1 session
**What changes:** full pipeline: lint/type → unit → integration (compose services) → **RAGAS smoke gate (BLOCKING)** → build images → **Trivy (FAIL on HIGH/CRIT)** → gitleaks + pip-audit → ECR push via **GitHub OIDC** (no stored keys) → ArgoCD app manifests + Argo Rollouts canary spec (10→50→100, metric-driven rollback).
**Tests:** seed a deliberate quality regression on a branch → gate must block it (prove the gate bites).
**DoD:** The pipeline that Phase 6 will drive is complete and demonstrably strict.

### S18 — Cost controls + kill switch  `[D20]` · 1 session
**What changes:** token budgets at build_context + max-output cap; per-session daily quota; real-time spend counter (tokens × price table incl. GPU-hour amortization) → soft alert 50% / hard breaker 100% → `CACHE_ONLY_MODE`; admin kill switch endpoint; Grafana spend + GPU-utilization panels; scale-to-zero policy documented.
**Tests:** simulated overspend flips CACHE_ONLY (integration); kill switch flips without redeploy.
**DoD:** A runaway bot cannot bankrupt the project; the wallet has machinery, not intentions.

### S19 — Full golden set (215) + judge calibration + online eval  `[D19, D10-enable]` · 1 session
**What changes:** golden set grown to ~150 QA + 50 safety + 15 OOC; judge calibrated vs ~20 human labels (agreement % reported); nightly full-eval job; online 1% sampled scoring from Langfuse traces + drift alerts; **semantic-cache false-hit eval → if zero false hits, flag flips ON (D10 guard satisfied)**.
**DoD:** Eval is a system, not a script; semantic cache earns its enablement with evidence.

---

## Reordering log

**v1.2 — S10 (Next.js frontend) deferred; S13 (multi-venue serving) pulled forward.**
Rationale: S10 is a separate deployable behind a stable API contract (frozen in S4), so
nothing downstream depends on it — deferring costs nothing and blocks nothing. S13, by
contrast, is where D4b's four-venue design becomes real, and two of its venues (`local`,
`groq`) are already measured and waiting to be wired. `demo/` therefore remains the
reference UI until S10 lands.

## Parallel execution tracks (added v1.1)

The plan is written as one ordered list, but the *dependency graph* is not a straight line.
Several steps touch disjoint subsystems and can run concurrently. What follows is honest
about which kind of parallelism each track actually is.

```
TRACK A — retrieval quality (strictly sequential; each gates the next)
   S5 ml-service ──► S6 hybrid+rerank+EVAL DELTA ──► S12 security/safety gates

TRACK B — state & infrastructure (independent of Track A; no shared files)
   S7 Postgres ──► S8 Redis ──► S9 worker/SQS

TRACK C — serving venues (D4b; mostly background/waiting)
   S3b spike ✅ ──► S13.1-13.4 (adapter + local + groq: no new infra)
                └─► S13.5 runpod ─┐
                └─► S13.6 aws ────┴─► S13.7 SGLang ─► S13.8 failover ─► S14 benchmark

TRACK D — user-side async (zero agent time; start early, they have lead time)
   AWS G-instance quota request (24-48h)  ·  RunPod account + credits
   HF license acceptance for Llama-3.1 ✅ done

TRACK E — platform (needs the app broadly stable; starts after Track A+B land)
   S15 kind ──► S16 terraform plan ──► S17 CI/CD
```

**Three genuinely different kinds of "parallel" — worth distinguishing:**
1. **True background** — long downloads, cloud provisioning, quota approvals. These run
   unattended while foreground work continues. *(S3b's 90-minute download ran alongside all
   of S4 — that is this kind, and it worked.)*
2. **Track interleaving** — Track A and Track B touch disjoint modules, so their steps can be
   reordered or alternated freely without merge pain. This is scheduling flexibility, not
   simultaneous execution.
3. **User-side async** — Track D costs zero implementation time and has multi-day latency, so
   it must be *started first* even though it *finishes last*.

**Rule that keeps this safe:** the invariant is unchanged — every commit boundary leaves a
working system. Parallel tracks may interleave, but two half-finished steps must never be
committed together. One step per commit still holds.

**Recommended interleave for the next stretch:**
| Foreground (agent) | Background / user-side |
|---|---|
| S5 → S6 (Track A) | AWS quota request; RunPod account (Track D) |
| S7 → S8 (Track B) | Any cloud venue provisioning that lands |
| S13.1–13.4 (adapter, local+groq already proven) | RunPod/AWS instances spin up on demand |

## Sequencing rationale (risk front-load map)

| Risk | Where killed |
|---|---|
| Quality bar unachievable | S1 (measured) → S6 (closed) |
| GPU environment unknown | S3b spike (2–3h, 9 steps before S13 needs it) |
| Retrieval migration degrades quality | S6 eval delta, blocking thresholds from then on |
| CPU work stalls the event loop | S5 separation before any load testing matters |
| K8s/EKS complexity | S15 kind ($0) before S16 plan before Phase-6 apply |
| Eval gate is theater | S17 proves it blocks a seeded regression |

**Estimated total: ~20–24 focused sessions.** (+2–4 vs pre-pushback plan, per v2.1 feedback — the GPU/serving/benchmark work items.)

**Phase 5 (hardening: chaos drills, 500-RPS stubbed load test, backup/restore, runbooks) and Phase 6 (local Docker → kind → tf plan → dev → staging+load → prod) consume this plan's outputs; they are not steps here.**
