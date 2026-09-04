# Decision Log — P5 Medical RAG Chatbot (Portfolio → Production)

> **Status: DRAFT v1 — awaiting sign-off.** Each entry cites the Phase 1 NFR or upstream decision that justifies it.
> Full production option landscape per decision: see [DECISION_OPTIONS_CATALOG.md](DECISION_OPTIONS_CATALOG.md).
> Phase 1 anchors: 10k DAU / peak 10 RPS / proof 25 RPS · TTFT p95 2.5s · retrieval p95 300ms · SLO 99.5% · LLM ≤$0.001/q, blended ≤$0.005/q · idle infra ≤$30/mo, burst ≤$150/mo · no PHI, GDPR-lite, us-east-1 · corpus ≤100k chunks · team of 1.

---

## Decision dependency graph (why this order)

```
Tier 0  Phase 1 NFRs (constraints — everything cites these)
Tier 1  STATE & PARADIGM (hardest to reverse — 80% of deliberation lives here)
        D3 RAG paradigm ── D1 primary DB ── D5 embedding model ⇄ D2 vector DB
        (D5's dimension is baked into D2's schema — coupled decision, one gate)
Tier 2  ENGINES        D4 LLM/tiering → D12 serving   ·   D3 → D6 orchestration
Tier 3  APP SHELL      D6 → D7 backend → D8 frontend, D9 auth · D1/D4 → D10 cache → D11 queue
Tier 4  PLATFORM       D14 cloud → D15 containers/IaC → D16 CI/CD, D17 secrets
Tier 5  CROSS-CUTTING  D13 observability, D18 security, D19 eval, D20 cost, D21 failure modes, D22 repo
```

- **Expensive-to-reverse ranking (deliberation budget):** D5 ≈ D1/D2 (re-embed + data migration) > D7 (rewrite) > D15 (infra rebuild) > D22 (structure churn) ≫ everything else (config-level, gets a flip-trigger instead of a debate).
- **Decision order ≠ build order.** D19 (eval) is decided 19th but built ~first in Phase 4 (you need a baseline before refactoring); D22 (repo) is decided last but used first. Deciding late ≠ building late.
- **Gate for every entry:** Reasoning must cite an NFR or an upstream decision. If it can't, it's taste, not engineering — rejected.
- **Common mistakes:** picking tools before paradigm; equal deliberation on all 22 (spend ∝ reversal cost); missing couplings (D5 dim inside D2 schema); letting the framework dictate architecture instead of the reverse.

**Senior-vs-junior (Phase 2):** senior spends 80% of the argument on the five expensive-to-reverse decisions and writes one-line flip-triggers for the rest; junior debates the frontend longest because it's the most opinion-friendly.

---

## Decision 1: Primary database
**Question:** System-of-record for sessions, messages, feedback, audit, ingestion-job state.
**Options considered:**
- **A — SQLite:** zero-ops file DB | Pros: free, trivial | Cons: single-writer, breaks >1 replica, no managed path | Cost: $0 | Fits scale? **N**
- **B — Postgres 16:** relational + pgvector option | Pros: fits chat/audit shape; unlocks D2; RDS path; you know SQL; SQLAlchemy/Alembic | Cons: a service to run | Cost: $0 dev (container) / ~$13/mo RDS t4g.micro demo | Fits? **Y**
- **C — DynamoDB:** serverless KV | Pros: ~$0 idle | Cons: rigid access patterns, no vector, local-dev friction | Fits? Y but no advantage
**Decision:** **B — Postgres 16** (SQLAlchemy 2 async + Alembic).
**Reasoning:** One database can serve relational *and* vector needs at our corpus size (≤100k chunks) — the largest ops simplification available to a team of 1 under the $30/mo ceiling.
**Trade-offs accepted:** Running/patching one stateful service vs. serverless.
**Reversibility:** Moderate — repository pattern contains it; migrations accrete over time.

## Decision 2: Vector database
**Question:** Where embeddings live and how hybrid retrieval is served.
**Options considered:**
- **A — pgvector (in D1's Postgres):** HNSW index | Pros: no second stateful service; SQL metadata filtering; hybrid via `tsvector` + RRF; transactional consistency with doc metadata; one backup story | Cons: Postgres FTS ≈ BM25 (not exact); ceiling ~few M vectors; you don't get dedicated-vector-DB ops experience here | Cost: $0 extra | Fits? **Y**
- **B — Qdrant (Package-1 spec default):** Pros: native hybrid/sparse, course-known, scales far | Cons: second stateful service (+ops or ~$25/mo cloud); overkill at ≤100k chunks | Fits? Y
- **C — Pinecone:** managed | Cons: data egress, vendor lock, no local parity | Fits? Y
- **D — keep FAISS:** Cons: pickle load with `allow_dangerous_deserialization=True`, no filtering, no incremental upsert, per-replica index drift | Fits? **N**
**Decision:** **A — pgvector**, behind a `VectorStorePort` interface.
**Reasoning:** Corpus NFR (≤100k chunks) + retrieval p95 300ms is comfortably inside pgvector HNSW territory; $30 ceiling and solo-ops veto a second stateful service. **Flip-trigger to Qdrant:** corpus >1–2M chunks, filtered-query p95 >300ms, or multi-tenant isolation.
**Trade-offs accepted:** Approximate BM25 (eval verifies adequacy); forgo the Qdrant résumé line in this project.
**Reversibility:** Moderate — port interface makes swap ~1–2 days; dimension coupling handled at D5 gate.

## Decision 3: RAG vs Agentic vs Hybrid
**Question:** Which paradigm serves grounded medical Q&A.
**Options considered:**
- **A — Naive RAG (current, k=1):** | Fits? **N** — quality floor unacceptable
- **B — Advanced RAG:** hybrid retrieve → cross-encoder rerank → conversation-aware query condensation → token-budgeted context w/ citations → no-answer threshold | Pros: deterministic, traceable, fits TTFT budget | Fits? **Y**
- **C — Agentic RAG (LangGraph loops):** Pros: multi-hop quality | Cons: kills TTFT p95 2.5s, nondeterminism in a medical domain, cost | Fits? **N**
**Decision:** **B — Advanced RAG.** HyDE/multi-query exist as eval-gated config flags, OFF by default.
**Reasoning:** Medical wrapper demands determinism + citations (Phase 1 quality bar); latency budget rules out iterative loops; corpus QA doesn't need tool use.
**Trade-offs accepted:** Ceiling on genuinely multi-hop questions.
**Reversibility:** Easy — pipeline stages are composable functions.

## Decision 4: LLM provider & model tiering
**Question:** Which models answer, and what happens when they can't.
**Options considered:**
- **A — Groq two-tier:** `llama-3.1-8b-instant` default → `llama-3.3-70b-versatile` escalation | Pros: TTFT 200–400ms (feeds p95 2.5s); ~$0.0002/q (inside $0.001 line); open-weight portability story; existing integration | Cons: rate limits; younger provider | Fits? **Y**
- **B — OpenAI mini-tier:** solid, ~$0.0006/q | same third-party posture | Fits? Y
- **C — Anthropic Haiku:** best safety tone | ~$0.003/q busts the LLM line | Fits? marginal
- **D — self-host vLLM:** idle GPU $300–700/mo vs $30 ceiling | Fits? **N** (see D12 arithmetic)
**Decision:** **A**, escalation triggered by low retrieval confidence / long queries / condensation steps; **cross-provider fallback chain** (Groq → OpenAI-mini if key present → cache-only degraded mode) behind a thin model-client abstraction, model IDs pinned in config.
**Trade-offs accepted:** Two provider keys to manage; model-ID churn risk (config-pinned, not hardcoded — fixes demo's hardcoded default).
**Reversibility:** Easy.

## Decision 5: Embedding model
**Question:** Which embedding model, knowing the dimension bakes into the D2 schema.
**Options considered:**
- **A — keep `all-MiniLM-L6-v2`:** 384d, known | mediocre MTEB retrieval quality | Fits? Y
- **B — `BAAI/bge-small-en-v1.5`:** 384d drop-in, better retrieval, CPU-fast, **local (health queries never leave the box — privacy NFR)** | *New-for-you primer:* same `sentence-transformers` API; only difference is a recommended query-instruction prefix | Fits? **Y**
- **C — OpenAI `text-embedding-3-small`:** 1536d, strong | API cost + external dep on hot path + queries to third party | Fits? Y, privacy-worse
**Decision:** **B — bge-small-en-v1.5 (384d)**, config-versioned (`embedding_version` column) with a re-embed pipeline; golden-set eval confirms vs A before lock (corpus is small — re-embed ≈ 30 min).
**⚠ DECISION GATE:** dimension must be fixed **before the first Alembic migration** — changing it later = migration + full re-embed.
**Trade-offs accepted:** English-only (in scope), self-hosted CPU cost at ingest (negligible).
**Reversibility:** Moderate-hard — mitigated by version column + small corpus.

## Decision 6: Orchestration framework
**Question:** What runs the query pipeline.
**Options considered:**
- **A — LangChain chains (current):** `RetrievalQA` is deprecated; opaque control flow | Fits? **N**
- **B — LCEL end-to-end:** known | still framework-shaped hot path; latency debugging through runnable stack | Fits? marginal
- **C — LlamaIndex:** best ingestion primitives | second framework for a team of 1 | Fits? N
- **D — Thin custom pipeline, LangChain as component library only** (loaders, splitter, `ChatGroq`, embeddings): explicit async functions `condense → retrieve → fuse → rerank → build_context → generate`, Pydantic contracts, one OTel span per stage | Cons: we own ~300 lines a framework would hide | Fits? **Y**
**Decision:** **D.**
**Reasoning:** Package-1 spec itself warns off heavy frameworks on the query path; the per-stage latency budget (Phase 1) and per-stage tracing are near-free on owned control flow and painful through framework indirection.
**Trade-offs accepted:** We maintain the plumbing.
**Reversibility:** Easy.

## Decision 7: Backend language & framework
**Question:** What serves the API.
**Options considered:**
- **A — keep Flask:** sync WSGI; SSE awkward; culture of per-request rebuilds | Fits? **N**
- **B — FastAPI:** async SSE native; Pydantic v2 at boundaries; OpenAPI free; lifespan singletons (kills rebuild-per-request bug); inventory-known | Fits? **Y**
- **C — Litestar / Node / Go:** fine tools; smaller ecosystem or wrong language for team of 1 | Fits? N
**Decision:** **B — FastAPI**, REST + **SSE** (one-way stream — simpler than WebSocket at every hop), gunicorn+uvicorn workers in container.
**Trade-offs accepted:** Rewriting the app layer (~60 lines — cheap).
**Reversibility:** Moderate.

## Decision 8: Frontend & streaming UX
**Question:** What users see, and how tokens stream.
**Options considered:**
- **A — keep Jinja SSR:** no streaming, no citation UX | Fits? **N**
- **B — HTMX + SSE:** minimal ops, real streaming | weak portfolio signal, poor rich-client state | Fits? Y
- **C — Next.js (App Router, TS, Tailwind):** streaming via fetch `ReadableStream`, `AbortController` cancellation, citation chips, disclaimer banner, skeleton + token render; inventory-known; strong portfolio signal | second deployable to operate | Fits? **Y**
**Decision:** **C — Next.js.** Deploy target (static/standalone container vs Vercel free tier) settled in Phase 6 by cost.
**Trade-offs accepted:** Two apps to operate.
**Reversibility:** Easy — the API contract is the boundary.

## Decision 9: Authentication & authorization
**Question:** Who can do what, with accounts out of scope (Phase 1).
**Options considered:**
- **A — none (current):** can't rate-limit fairly; admin endpoints open | Fits? **N**
- **B — anonymous server-side sessions** (HTTP-only signed cookie, Redis-backed) + per-IP/session limits + **hashed static API keys** for admin/ingestion | Fits? **Y**
- **C — Clerk/Auth0/Cognito:** accounts are out-of-scope v1; Clerk documented as the v2 path
**Decision:** **B.** Stable session secret from SSM (kills the `os.urandom(24)` restart/replica bug); sessions survive redeploys.
**Trade-offs accepted:** No cross-device history (meaningless for anonymous users anyway).
**Reversibility:** Easy — session middleware is the seam Clerk would slot into.

## Decision 10: Caching strategy
**Question:** What we cache, and what we refuse to cache.
**Options considered:** Redis vs Memcached (no persistence/structures) vs in-process LRU (per-replica drift) → **Redis 7**.
**Decision — four layers with a medical-domain twist:**
1. **Exact/normalized response cache** (Redis, TTL 24h, key = `sha256(normalized_query + prompt_version + index_version + model_id)`) — biggest lever, zero correctness risk.
2. **Semantic cache — ships OFF.** Near-miss queries are dangerous here ("aspirin dose adult" ≈ "aspirin dose child" at cosine 0.95). Enable only behind cosine ≥0.97 **and** identical top-3 retrieved chunk IDs, and only if eval shows zero false hits.
3. **Query-embedding cache** (tiny, free win).
4. Provider prompt cache: n/a on Groq (documented; matters if provider swaps).
**Invalidation:** version-key composition — bump `prompt_version`/`index_version` and old entries go cold; no manual purges ever.
**Reasoning:** Cache is the #1 blended-cost lever (Phase 1 ≤$0.005/q) and the cached-path p95 300ms NFR.
**Trade-offs accepted:** Lower hit rate than aggressive semantic caching — correctness outranks hit rate in this vertical.
**Reversibility:** Easy.

## Decision 11: Queue & async work
**Question:** How ingestion (PDF → chunk → embed → upsert; CPU-bound; ~1/week) and scheduled jobs run.
**Options considered:**
- **A — FastAPI BackgroundTasks:** dies with the pod, no retry | Fits? **N**
- **B — Celery + Redis broker:** inventory-known; prefork suits CPU-bound embedding; retries + beat schedules | config ceremony | Fits? **Y**
- **C — ARQ:** lighter, async-native | new tool; async loop is a poor fit for CPU-bound embedding | Fits? marginal
- **D — SQS + worker:** cloud-cred | localstack friction; overkill at 1 job/week | Fits? Y
**Decision:** **B — Celery** (Redis broker/result), used *only* for ingestion + scheduled eval sampling. Tasks idempotent via content-hash dedup so retries are safe.
**Trade-offs accepted:** Celery ceremony for tiny volume — bought back as job-market signal + retry semantics.
**Reversibility:** Easy — task interface is thin.

## Decision 12: Inference serving
**Question:** Provider API vs self-host.
**The arithmetic (this decision is arithmetic, not taste):** g6.xlarge spot ≈ $260/mo idle-or-not vs 30k q/day × $0.0002 ≈ **$6/mo on Groq**. Break-even ≈ sustained ~500k q/day of 8B-class traffic.
**Decision:** **Provider API (Groq) per D4.** Documented flip-triggers to vLLM on EKS: sustained volume past break-even, data-residency mandate, or a fine-tuned model (Package 3 territory). SageMaker serverless rejected (cold starts vs TTFT NFR); Bedrock rejected for now (pricier for llama-class; revisit if an enterprise client demands private networking).
**Trade-offs accepted:** Provider dependency — mitigated by D4 fallback chain + D21 degraded mode.
**Reversibility:** Easy behind the D4 model-client abstraction.

## Decision 13: Observability stack
**Question:** What we trace/log/measure, and where it goes.
**Options considered (LLM plane):** **Langfuse** (OSS, self-hostable, traces+cost+prompt-registry+eval datasets — *new-for-you primer:* "self-hostable LangSmith; SDK decorator + callback, UI shows per-stage traces") vs LangSmith (course-known, managed, data egress, tier limits) vs Phoenix (eval-heavy, later).
**Decision:**
- **Traces:** OTel SDK, span per pipeline stage (condense/retrieve/rerank/generate) with attrs: TTFT, tokens, cost, cache-hit, no-answer, refusal, scores. **Langfuse** for LLM-level traces (compose-hosted dev; Langfuse Cloud free tier demo).
- **Metrics:** Prometheus format → dev: compose Prom+Grafana; cloud: Grafana Cloud free tier + CloudWatch basics.
- **Logs:** `structlog` JSON → **stdout** (12-factor fix of the file logger) → CloudWatch/Loki. No raw query text in logs.
- **Alerts:** SLO burn-rate (fast+slow), TTFT p95 breach, error rate, spend thresholds, **no-answer-rate spike** (cheapest retrieval-regression proxy) → Grafana → email/Slack.
**Reasoning:** SLO 99.5% is unenforceable without burn-rate alerts; cost NFR needs per-query cost attribution; eval-in-prod rides on these traces.
**Trade-offs accepted:** Langfuse adds a dev-compose service.
**Reversibility:** Easy-moderate — OTel is vendor-neutral by design; that's why it's first.

## Decision 14: Cloud provider & core services
**Question:** Which cloud, which primitives.
**Decision:** **AWS, us-east-1** (Phase 1; your background; spec default).
- **Object:** S3 (corpus, artifacts, Terraform state w/ native lockfile).
- **Secrets:** **SSM Parameter Store SecureString** (free) over Secrets Manager ($0.40/secret/mo) — trade-off: no managed rotation → quarterly manual rotation runbook. Cost-honest.
- **DB/cache (demo window):** RDS Postgres t4g.micro (~$13/mo, pgvector supported) + Upstash Redis free tier (keeps steady state ≈$25/mo, inside ceiling); ElastiCache only inside the burst window. Dev = local compose, $0.
- **Network:** minimal VPC 2-AZ; **NAT Gateway ($32/mo) exists only during burst windows** — dev/demo paths avoid NAT by design.
- Azure/GCP flagged per spec: no genuine advantage for this workload (no OCR, no Azure-only model need).
**Reasoning:** every line traces to the $30 idle / $150 burst NFR.
**Reversibility:** Moderate.

## Decision 15: Container, orchestration, IaC
**Question:** The NFR fight the cost ceiling picked on purpose.
**Options considered:**
- **A — EKS always-on (spec default):** $73/mo control plane + nodes ≈ $150+/mo idle | violates $30 NFR | **N**
- **B — ECS Fargate steady demo:** no control-plane fee; api task ≈ $9/mo; real AWS orchestration | not Kubernetes (your #1 audit gap) | **Y**
- **C — App Runner (course path):** simplest | least learning; hides the gap | N
- **D — EC2 + compose:** cheapest | no orchestration story | dev fallback only
- **E — local kind + Helm ($0) + ephemeral EKS window:** Terraform EKS module `plan`ned always, `apply`d only for the load-test/demo window (~$10–20), destroyed after | best learning-per-dollar | **Y**
**Decision:** **B + E hybrid**, sequenced by Phase 6: local compose → kind+Helm (K8s proof, $0) → `terraform plan` → **ECS Fargate steady demo** → **ephemeral EKS+ArgoCD window** for the k6 load test, then `destroy`. Evidence = tf code, Grafana screenshots, k6 reports.
**Docker:** multi-stage (uv builder → slim runtime), non-root, HEALTHCHECK, `.dockerignore` (kills the 27MB-artifacts-in-image bug). **Helm over Kustomize** (env templating + portfolio-legible chart). **Terraform modules:** `network`, `data`, `app-ecs`, `eks` (ephemeral), `observability`.
**Reasoning:** K8s is the top audit gap and *must* appear, but the wallet NFR forbids always-on EKS — this split satisfies both without lying about either.
**Trade-offs accepted:** Two orchestrators to document — deliberately: ECS = steady cheap reality, EKS = controlled-cost skill demonstration.
**Reversibility:** Moderate-hard; Terraform mitigates.

## Decision 16: CI/CD pipeline shape
**Question:** Pipeline, environments, promotion, rollback.
**Options considered:** GitHub Actions (free for public repo; market default) vs Jenkins (already demonstrated in `demo/`; self-hosted ops burden nobody funds) vs GitLab CI (repo is GitHub).
**Decision:** **GitHub Actions.** PR: ruff + mypy → unit → integration (compose Postgres+Redis services) → **RAGAS eval gate — BLOCKING** (20-sample smoke on PR; full set nightly + pre-deploy) → build multi-stage image → **Trivy scan FAILS on HIGH/CRITICAL** (fixing demo's `|| true` theater) → gitleaks + pip-audit → push ECR (SHA + semver tags, never bare `:latest`). main → dev auto-deploy; staging/prod-demo via GH Environments manual approval. **Rollback:** redeploy previous pinned task-def/image tag (documented one-liner); DB migrations follow expand-migrate-contract so rollbacks never fight schema. ArgoCD only in the EKS window (GitOps demo).
**Reasoning:** the eval gate is the package-defining feature (Phase 1 quality bar enforced by machinery, not intention); `:latest`-only tagging in the demo made rollback impossible.
**Reversibility:** Easy.

## Decision 17: Secrets & configuration
**Decision:** `pydantic-settings` typed config, env-vars only (12-factor); `.env` gitignored local. Cloud: **SSM SecureString** per env (`/medbot/{env}/GROQ_API_KEY`…) injected via ECS task-def secrets / External Secrets Operator in the EKS window. **CI: GitHub OIDC → assume IAM role — zero long-lived AWS keys in GitHub** (senior tell). gitleaks pre-commit + CI. Rotation: quarterly manual, runbooked (accepted trade-off of SSM over Secrets Manager, per D14).
**Reversibility:** Easy.

## Decision 18: Security posture
**Threat model → mitigation (LLM-specific first):**
| Threat | Mitigation |
|---|---|
| Prompt injection (user query) | Instruction-hierarchy system prompt; answers must cite; **no tools exist to hijack** (D3 kept the system toolless deliberately); adversarial suite in CI |
| Indirect injection via corpus PDF | Retrieved text framed as data-not-instructions; operator-only corpus uploads (provenance); injection strings in golden adversarial set |
| Jailbreak → personal medical advice | Refusal policy prompt + output pattern filter (dosage-like regexes) + refusal-correctness eval ≥95% gate |
| PII leakage in logs | No raw queries in app logs (hash+length only); Langfuse = the one sanctioned store, access-controlled, 30-day retention |
| Cost/DoS abuse | Per-IP+session rate limits (Redis token bucket), token budgets, global breaker |
| Supply chain | uv lockfile, Trivy, pip-audit, gitleaks, Dependabot |
| Container | non-root, read-only rootfs, slim base, no build tools in runtime layer |
| Session hijack | HTTP-only SameSite=Lax signed cookies, stable SSM-held secret |
| **Killed by design** | FAISS pickle `allow_dangerous_deserialization` (gone with D2); raw exception text to users (RFC 7807 error envelope; details to logs only) |
**Deferred with reasons:** WAF, mTLS (cost/scope; documented as enterprise-client add-ons).
**Reversibility:** n/a — posture is continuous.

## Decision 19: Evaluation strategy
**Question:** How quality is measured, gated, and monitored — the layer that separates demo from system.
**Decision:**
- **Build the eval harness BEFORE the refactor** and baseline the *current demo pipeline* — the before/after delta is the portfolio's before/after comparison.
- **Golden set (versioned in-repo):** ~60 curated Gale Q&A (stratified: definitions / symptoms / treatment-info / cross-topic), ~25 adversarial safety (diagnosis, dosage, emergency, injection), ~15 out-of-corpus (must say "I don't know").
- **Metrics:** RAGAS faithfulness / answer-relevancy / context-precision / context-recall + custom: citation-coverage, refusal-correctness, no-answer precision. Thresholds = Phase 1 bar (faithfulness ≥0.85, relevancy ≥0.80, refusal ≥95%, don't-know precision ≥90%). *New-for-you primer:* RAGAS = pip library; feed `{question, answer, contexts, ground_truth}` rows, get metric scores; wire as pytest fixtures.
- **Judge:** Groq 70B as LLM-judge, **calibrated once against your human labels on 20 samples (report agreement %)**; judge prompts versioned — judges drift too.
- **CI:** 20-sample smoke on PR (cost cap); full set nightly + pre-deploy, blocking.
- **Online:** Langfuse 5% trace sampling + UI thumbs feedback → weekly scoring job; drift alert on no-answer-rate / feedback dip.
- **A/B:** offline paired-comparison harness for prompt/model variants; *online* A/B infra honestly deferred — no traffic volume to power it.
**Reversibility:** Easy; the datasets are the asset.

## Decision 20: Cost controls
**Decision:** Per-request: context token budget enforced at build_context + max_output 350. Per-session: daily token quota (Redis counter). Per-IP: rate limit. **Global: daily spend counter (tokens × price table per call) → soft alert at 50%, hard circuit-breaker at 100% flips `CACHE_ONLY_MODE`** (degraded banner, no provider calls). Infra: CloudWatch billing alarms $20/$50/$100 (8h lag noted — the app-level counter is the real-time guard); `make destroy-burst` teardown target for demo resources. Dashboards: cost/query panel (Langfuse/OTel attrs). **Kill switch:** env flag + admin endpoint, chaos-tested in Phase 5.
**Reasoning:** direct implementation of the $0.005/q + $30/$150 NFRs.
**Reversibility:** Easy.

## Decision 21: Failure modes & degradation
| Failure | Detection | Behavior | User experience |
|---|---|---|---|
| Groq outage/429 | health probe, error rate | fallback provider | transparent |
| Both providers down | breaker | **cache-only mode** | banner: "answers may be limited" — never a raw 500 |
| Retrieval empty / low score | score threshold | honest "I don't have reliable information" + rephrase hint | **never generate ungrounded** (medical rule) |
| Postgres down | readiness probe | LB stops routing; sessions degrade to transient | maintenance notice |
| pgvector slow >2s | timeout + breaker (3 fails/30s) | cached / don't-know path | degraded |
| Redis down | ping | **bypass cache** (slower, costlier, correct); rate-limit falls back to in-proc approximation | none |
| Worker dies mid-ingest | stale-job alert | idempotent re-run (content-hash upsert); **index alias swaps only on completion** — half-ingested never serves | none |
| Token budget exceeded | context builder | drop lowest-ranked chunks first; citations stay consistent; truncation metric | none |
| SSE client disconnect | server-side cancel | provider stream aborted (cost stops) | n/a |
**Chaos drills (Phase 5):** kill provider, kill Redis, kill Postgres — top 3 by likelihood × blast radius.

## Decision 22: Repo structure & code organization
**Options:** polyrepo (×3 ops for one person — N) · flat single app (couples api/worker deploys — N) · **monorepo (Y)**.
**Decision:** monorepo at repo root, uv workspace:
```
P5-Medical-Chatbot/
├── apps/
│   ├── api/            # FastAPI: routes, SSE, middleware
│   ├── worker/         # Celery ingestion tasks
│   └── web/            # Next.js
├── packages/
│   ├── core/           # pipeline stages, prompts/ (versioned), schemas, model+vector ports
│   └── eval/           # golden sets, RAGAS runners, adversarial suites
├── infra/
│   ├── terraform/      # network, data, app-ecs, eks (ephemeral), observability
│   └── k8s/            # Helm chart
├── .github/workflows/
├── tests/              # unit, integration, e2e, load (k6)
├── docs/               # DECISION_LOG.md, runbooks/, architecture.md
└── demo/               # read-only reference (gitignored) until end-of-life
```
Prompts live in `packages/core/prompts/` as versioned files (semver constants) + registered in Langfuse. Evals live in `packages/eval` — they're code, they get reviewed like code.
**Reversibility:** Moderate — cheap to change now, expensive after Phase 4; that's why it's decided last but *before* any code.

---

# Decision summary — at a glance (DRAFT, pending sign-off)

| # | Decision | Available options | Pick | Why this pick (NFR anchor) | Prod-grade? | Fills audit gap? | Reversibility & flip-trigger | Notes (cost / new tool) |
|---|---|---|---|---|---|---|---|---|
| 1 | Primary DB | SQLite / Postgres 16 / MongoDB / DynamoDB | **Postgres 16** (SQLAlchemy + Alembic) | Relational fits sessions+audit; unlocks pgvector → one DB, two jobs, under $30/mo | ✅ | SQL depth, migrations | Moderate · reopen only if access goes KV-at-huge-scale | $0 dev; ~$13/mo RDS demo window |
| 2 | Vector DB | pgvector / Qdrant / Pinecone / Milvus / keep FAISS | **pgvector** behind `VectorStorePort` | ≤100k chunks is deep inside HNSW comfort; no 2nd stateful service; kills pickle CVE | ✅ at this scale | Hand-built hybrid-search internals | Moderate · flip→Qdrant: >1–2M chunks, filtered p95 >300ms, or multi-tenant | $0 extra; port = 1–2 day swap |
| 3 | RAG paradigm | Naive / Advanced RAG / Agentic | **Advanced RAG** (hybrid+rerank+condense+no-answer) | TTFT p95 2.5s + medical determinism; citations mandatory | ✅ | Rerank, query condensation, no-answer thresholds | Easy · HyDE/multi-query exist as eval-gated flags, OFF | Agentic saved for a Package-2 project |
| 4 | LLM & tiering | Groq 2-tier / OpenAI-mini / Anthropic Haiku / self-host | **Groq 8B→70B** + cross-provider fallback | TTFT 200–400ms; ~$0.0002/q vs $0.001/q ceiling | ✅ | Model routing + fallback chains | Easy · model IDs config-pinned | Fallback: OpenAI-mini → cache-only degraded |
| 5 | Embedding | keep MiniLM / bge-small-en-v1.5 / OpenAI 3-small | **bge-small-en-v1.5** (384d, local) | Better retrieval, same dim+API; local = health queries never leave the box | ✅ | Embedding versioning + re-embed pipeline | ⚠ Mod-hard · **dim freezes at first migration**; eval confirms pre-lock | New-for-you (tiny delta); $0 |
| 6 | Orchestration | LC chains / LCEL / LlamaIndex / custom-thin | **Custom-thin pipeline**, LangChain as component lib | Per-stage latency budget + OTel spans need owned control flow; RetrievalQA is deprecated | ✅ | Owning control flow (senior signal) | Easy | LC stays for loaders/splitter/clients |
| 7 | Backend | keep Flask / FastAPI / Litestar / Node/Go | **FastAPI** + SSE | Async streaming native; Pydantic v2 boundaries; lifespan singletons kill rebuild-per-request bug | ✅ | Async Python patterns | Moderate | gunicorn+uvicorn workers in container |
| 8 | Frontend | keep Jinja / HTMX+SSE / Next.js / Streamlit | **Next.js** App Router + TS | Real streaming UX (ReadableStream, AbortController), citation chips; market signal | ✅ | Streaming UX engineering | Easy · API is the contract | Deploy target picked Phase 6 by cost |
| 9 | Auth | none / anon sessions + admin keys / Clerk / Cognito | **Anon server-side sessions + hashed admin API keys** | Fair rate-limiting; kills `os.urandom` restart/replica bug; accounts out of scope | ✅ | Session security done right | Easy · Clerk seam documented for v2 | Session secret lives in SSM |
| 10 | Caching | Redis multi-layer / Memcached / in-proc LRU | **Redis**: exact ON, semantic OFF-gated, embed cache | #1 blended-cost lever; semantic near-miss = patient-safety bug in this vertical | ✅ | Cache-risk analysis (medical nuance) | Easy | Version-key invalidation; no manual purges |
| 11 | Queue | BackgroundTasks / Celery+Redis / ARQ / SQS | **Celery + Redis**, ingestion only | Retries + idempotency; prefork fits CPU-bound embedding; inventory-known | ✅ | Idempotent job design | Easy · thin task seam | Content-hash dedup = safe retries |
| 12 | Inference serving | Provider API / vLLM / TGI / SageMaker / Bedrock | **Provider API (Groq)** | $6/mo API vs $260/mo idle GPU at 30k q/day; break-even ≈500k q/day | ✅ | Serving economics arithmetic | Easy · flip: volume > break-even, residency mandate, fine-tuned model | The decision is one line of math |
| 13 | Observability | OTel+Prom+Grafana+Langfuse / LangSmith / Phoenix / CW-only | **OTel + Prom/Grafana + structlog→stdout + Langfuse** | 99.5% SLO unenforceable without burn-rate alerts; cost/query attribution | ✅ | **Top-3 gap: observability** | Easy-mod · OTel is vendor-neutral by design | NEW: Langfuse; free tiers dev+demo |
| 14 | Cloud & services | AWS / Azure / GCP | **AWS us-east-1**: S3, SSM, RDS-in-window, Upstash-free Redis | Your background; every service line costed against $30/$150 | ✅ | AWS depth (VPC, IAM, SSM) | Moderate | NAT GW ($32/mo) burst-window only |
| 15 | Containers / IaC | EKS always-on / ECS Fargate / App Runner / EC2-compose / kind+ephemeral-EKS | **ECS steady + kind local + ephemeral EKS window**; Terraform; Helm | K8s = #1 gap but $73/mo control plane vs $30 ceiling — split honors both | ✅ (ECS); EKS window = skill evidence | **Top-3 gap: K8s + Terraform** | Mod-hard · Terraform mitigates rebuild cost | EKS window ≤$20, destroyed after k6 |
| 16 | CI/CD | GitHub Actions / Jenkins / GitLab CI | **GHA**: lint→types→tests→**blocking RAGAS gate**→**failing Trivy gate**→ECR sha-tags→envs w/ approvals | Quality bar enforced by machinery; demo's `:latest`-only made rollback impossible | ✅ | Eval-gated CD | Easy | Jenkins already evidenced in demo/ |
| 17 | Secrets & config | SSM+OIDC / Secrets Manager / env files | **SSM SecureString + GitHub OIDC→IAM role** | $0 vs $0.40/secret/mo; zero long-lived AWS keys in CI | ✅ | OIDC federation (senior tell) | Easy | Trade-off: quarterly manual rotation, runbooked |
| 18 | Security posture | Posture (per-threat mitigations, not either/or) | Injection hierarchy · toolless-by-design · refusal filter · PII-free logs · non-root RO container · RFC 7807 errors | Medical wrapper: wrong-but-confident is the top product risk | ✅ | **Top-3 gap: AI security** | n/a — continuous | Kills pickle CVE + raw-error leak; WAF/mTLS deferred w/ reasons |
| 19 | Evaluation | RAGAS+custom / DeepEval / promptfoo / none | **RAGAS + calibrated LLM-judge + CI gate**, built BEFORE refactor | Phase 1 bar (faith ≥0.85, refusal ≥95%) enforced; before/after delta = portfolio before/after comparison | ✅ | **#1 audit gap: evaluation** | Easy · golden sets are the versioned asset | NEW: RAGAS; judge calibrated vs human labels |
| 20 | Cost controls | Mechanisms (budgets/quotas/breakers) | Token budgets · session quotas · **daily-spend breaker → CACHE_ONLY_MODE** · kill switch · billing alarms | $0.005/q blended; $30/$150 ceilings | ✅ | Cost engineering | Easy | App counter is real-time; CW billing lags ~8h |
| 21 | Failure & degradation | Per-failure explicit behaviors | Fallback chain · cache-only degraded · honest don't-know · alias-swap ingest · SSE cancel propagation | SLO 99.5%; never a raw 500; never ungrounded medical answer | ✅ | Degradation design | n/a | Chaos drills (top-3) in Phase 5 |
| 22 | Repo structure | Polyrepo / flat single-app / monorepo | **uv-workspace monorepo** (apps/ packages/ infra/ tests/ docs/) | Team of 1; atomic cross-cutting commits; single CI | ✅ | Packaging discipline | Moderate · cheap now, dear later | Prompts + evals versioned as code |
