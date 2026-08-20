# Service Packages & Production Build-Spec

> Reference document. Built on the gap analysis in `01-career-assessment.md` and `02-market-positioning.md`. Opinionated by design: each tool choice is **default + 1–2 alternatives + the trigger that flips the choice.** AWS-first (your background); Azure/GCP flagged where genuinely better.

---

# PART A — Service Package Catalogue

Eight packages you can credibly offer **after closing the gap**. No padding — each is within your realistic envelope and maps to a real buying pattern.

1. **Production-grade RAG application** — retrieval-augmented LLM app over a client's knowledge, deployed to scale.
   - Internal knowledge assistant for a 5,000-employee firm over Confluence + Google Drive + Slack history.
   - Customer-facing support bot grounded in product docs + past tickets, with citations.
   - Policy/contract Q&A for an insurer over thousands of PDFs with access control per department.

2. **Production-grade Agentic AI application** — multi-step, tool-using LLM system that takes actions, not just answers.
   - Sales-ops agent that researches leads (web + CRM), drafts outreach, and logs to HubSpot.
   - Internal "ops copilot" that queries databases, runs reports, and files Jira tickets from chat.
   - Research/analyst agent that gathers sources, synthesizes, and produces a cited brief on demand.

3. **Production-grade fine-tuned LLM application** — app built around a model fine-tuned to a client's domain/voice/task.
   - Brand-voice content generator fine-tuned on a marketing team's approved copy.
   - Domain classifier/extractor (e.g., medical-coding or legal-clause tagging) fine-tuned for accuracy + cost.
   - Small open-weight model fine-tuned to replace an expensive frontier API for a high-volume narrow task.

4. **Multi-modal GenAI application** — combines text with vision and/or audio in one product.
   - Insurance claim triage from uploaded damage photos + a text description.
   - Visual product search + Q&A for e-commerce ("find me this, but cheaper, in blue").
   - Video/meeting summarizer: transcript + slides + screenshots into searchable notes.

5. **Document intelligence pipeline** — high-accuracy ingestion, extraction, and structuring from messy documents at volume.
   - Invoice/receipt extraction into structured ERP records for an accounting firm.
   - Loan-application packet parsing (IDs, statements, forms) into a validated schema.
   - Contract digitization: clause extraction, obligation tracking, anomaly flagging across a back-catalog.

6. **AI microservice into an existing system** — a GenAI capability dropped into a client's current product/codebase, not a greenfield app.
   - "Summarize" / "draft reply" / "smart search" endpoints added to an existing SaaS.
   - An embeddings + reranking service behind a client's existing search bar.
   - A moderation/classification microservice consumed by a client's existing backend.

7. **Voice / conversational AI** — real-time speech-in/speech-out assistant or phone agent.
   - Inbound support voice agent (STT → LLM + tools → TTS) with human handoff.
   - Multilingual voice FAQ/IVR replacement for an SMB.
   - Voice-driven field-data capture for technicians with hands full.

8. **LLM evaluation & observability platform** — a standalone offering to measure, monitor, and de-risk someone else's (or your own) LLM system.
   - Eval harness + CI gate for a startup whose RAG quality silently regresses on every prompt change.
   - Production observability + cost/latency dashboards + alerting for a team flying blind on spend.
   - A/B testing + drift/hallucination monitoring layer over an existing GenAI product.

> **Vertical wrappers (legal / medical / financial)** are not separate specs — they are package 1/2/5 plus the §9 compliance layer hardened (HIPAA/GDPR/SOC 2, audit logging, data residency, PII handling) and domain-tuned prompts/eval sets. Sell them as premium variants; the technical bottleneck is compliance depth, not domain knowledge.

---

# SHARED BASELINE STACK

These defaults are common across packages. Each package's spec **references this baseline and lists only deltas** for shared layers, then fully specifies its package-defining layers (AI/ML core, data, scaling, cost, eval, repo, hardening, roadmap). This is deliberate, not collapsing — the bottlenecks live in the package-specific sections.

- **Frontend:** Next.js (App Router, React, TypeScript) — default. *Alt:* plain React + Vite when no SSR/SEO needed; Streamlit only for internal tools/demos (never client-facing prod). UI: Tailwind + shadcn/ui. State: TanStack Query for server state, Zustand for local. Auth UI: Clerk (fastest) or Auth.js/NextAuth. Streaming UX: SSE for token streaming, AbortController for cancellation, optimistic retry, stop button, skeleton + token-by-token render.
- **Backend:** Python + FastAPI — default (matches your stack, async-native, Pydantic). *Alt:* Node/NestJS if the client's team is JS-only; Go only if extreme throughput on the gateway justifies it. Async: `asyncio` + `httpx`; long jobs off the request path. API: REST + SSE/WebSocket for streaming. *Alt:* gRPC for internal service-to-service. Background jobs: Celery + Redis (default) or **ARQ** (lighter, async-native); *Alt:* AWS SQS + workers for cloud-native. Schemas: Pydantic v2 everywhere at boundaries. Rate limiting: `slowapi`/Redis token bucket at app, plus gateway-level (below).
- **Infra/deploy:** Docker (multi-stage, slim base) → Kubernetes on **AWS EKS** (default). *Alt:* ECS Fargate when you don't need GPUs or K8s flexibility (simpler, cheaper to operate); Lambda for spiky low-volume inference glue. IaC: Terraform, modular. CI/CD: GitHub Actions. GitOps: ArgoCD for K8s deploys. Secrets: AWS Secrets Manager + External Secrets Operator.
- **Observability:** OpenTelemetry SDK → traces/metrics/logs. Metrics: Prometheus + Grafana. Logs: Loki (default, cheap) or CloudWatch; ELK only if the client already runs it. LLM-specific: **Langfuse** (default, OSS, self-hostable) — *Alt:* LangSmith if already in the LangChain ecosystem and want managed; Arize Phoenix for heavier eval/drift. Alerting: Alertmanager → PagerDuty/Slack.
- **Security baseline:** OAuth2/OIDC (Clerk/Auth0/Cognito), JWT, RBAC. Secrets in Secrets Manager (never env files in repo). TLS everywhere, mTLS service-to-service if mesh present. WAF (AWS WAF) + rate limits + per-tenant quotas. Input/output guardrails (see per-package). Audit logging to an append-only store.
- **Data baseline:** Postgres (primary, default — `pgvector` for small/medium vector needs), Redis (cache + queue broker), S3 (blobs/artifacts). Dedicated vector DB per package below.
- **CI/CD baseline:** Trunk-based git, short-lived feature branches, PR + required checks. Stages: lint/type-check → unit → integration → build image → scan (Trivy) → push to ECR → deploy to staging (ArgoCD) → eval gate → manual/auto promote to prod → smoke test → rollback on failure (Argo Rollouts canary).

Model-serving cheat sheet (referenced throughout):

| Option | Use when | Avoid when |
|---|---|---|
| **Bedrock / OpenAI / Anthropic API** | Default. No infra, frontier quality, variable/low-mid volume | Extreme volume where token cost dominates; strict data-residency self-host needs |
| **Amazon Bedrock (provisioned)** | AWS-native, need guardrails + provisioned throughput | Need a model not on Bedrock |
| **vLLM** (self-host on GPU) | High, steady QPS on open-weight models; cost control; continuous batching | Low/spiky volume (idle GPU = money burned) |
| **TGI** (HF) | Self-host, tight HF ecosystem fit | You need vLLM's throughput edge |
| **SageMaker endpoints** | AWS-managed self-host, your existing skill, async/serverless options | You want lowest cost at very high volume (vLLM on raw EC2/EKS wins) |
| **Triton** | Multi-model, mixed CV/LLM, max GPU utilization | Pure single-LLM serving (vLLM is simpler) |

---

# PART B — Full Build-Specs

---

## PACKAGE 1 — Production-grade RAG Application

**1. Definition and target use cases.** Retrieval-augmented LLM app over client knowledge, deployed to scale. Use cases: 5,000-employee internal assistant over Confluence/Drive/Slack; support bot grounded in docs + tickets with citations; insurer policy/contract Q&A with per-department access control.

**2. Frontend layer.** Baseline. Deltas: citation rendering (source chips with click-through to original), confidence/"no answer found" states, conversation history with retrieval-trace inspector for admins, file-upload + ingestion-status UI. Stream tokens via SSE; show retrieved-sources panel before/while answer streams.

**3. Backend layer.** Baseline. Deltas: separate **ingestion service** (async, queue-driven) from **query service** (sync + streaming). Ingestion is the heavy background-job path (Celery/ARQ). Query path: retrieve → rerank → construct context → LLM stream. Per-tenant rate limits and per-tenant index isolation enforced in the query service.

**4. AI/ML core.**
- **LLM strategy:** Bedrock (Claude) or OpenAI as default answer model; route cheap queries to a small model (Haiku/GPT-mini), escalate hard ones. Self-host (vLLM) only at high steady volume.
- **Orchestration:** **LlamaIndex** for the retrieval/ingestion pipeline (default — best ingestion + retrieval primitives), or **LangChain LCEL** if you want one ecosystem. *Avoid* heavy frameworks for the query path if a thin custom pipeline is clearer — RAG query logic is simple enough to own.
- **Prompt management:** versioned prompts in repo + registry in Langfuse; never inline-magic-string prompts in prod.
- **Chunking:** start with structure-aware + recursive splitting (~512–1024 tokens, 10–15% overlap); upgrade to **semantic chunking** for heterogeneous docs. Store rich metadata (source, section, ACL, timestamp).
- **Embeddings:** default `text-embedding-3-large` (OpenAI) or Cohere embed v3; *Alt:* `bge-large`/`e5` self-hosted when cost or residency demands. Pick once, re-embed on change (versioned).
- **Retrieval pattern:** **hybrid (dense + BM25) + reranker** is the production default. Reranker: Cohere Rerank (default) or `bge-reranker` self-hosted. Add MMR for diversity. Top-k retrieve ~20 → rerank → top ~5 into context.
- **Context construction:** dedup, order by relevance, include citations/metadata, enforce a token budget, drop-and-summarize overflow.

**5. Data layer.** Vector DB: **Qdrant** (default — OSS, self-hostable, hybrid + filtering, scales) — *Alt:* pgvector if volume is small and you want one DB; Pinecone if the client wants fully managed and will pay. Primary DB: Postgres (docs metadata, ACLs, chat history). Cache: Redis (semantic cache of query→answer, embedding cache). Object storage: S3 (raw docs). Search index: BM25 via Qdrant/OpenSearch for the sparse half of hybrid.

**6. Infrastructure and deployment.** Baseline EKS. Ingestion workers on CPU node pool with queue-depth autoscaling (KEDA on SQS/Redis depth). Query service on CPU pool, HPA on RPS/latency. Vector DB: managed Qdrant Cloud or self-hosted StatefulSet with PVCs + replication. Embeddings/reranker self-hosted → small GPU node pool (or call hosted APIs to start). Terraform modules: `vpc`, `eks`, `qdrant`, `data` (RDS/Redis/S3), `app`. Inference: Bedrock/OpenAI to start; vLLM on GPU pool only if self-hosting the generator.

**7. CI/CD and version control.** Baseline. Deltas: **eval gate is mandatory** — a RAG eval set runs in CI and blocks deploy on regression. Version embeddings + chunking config (re-embed pipeline triggered on change). Prompt changes go through the same PR + eval gate. Monorepo (frontend, query svc, ingestion svc, infra) is fine at this size.

**8. Observability.** Baseline + Langfuse traces on every query (retrieval hits, scores, reranked set, tokens, latency per stage, cost). Dashboards: retrieval latency, LLM latency, end-to-end p95, cost/query, "no-answer" rate, cache hit rate. Eval-in-prod: sample live answers for groundedness/faithfulness scoring; alert on drift.

**9. Security and compliance.** Per-document/per-tenant ACLs enforced **at retrieval time** (filter the vector query by the user's permissions — never post-filter after generation). PII redaction on ingestion if needed. Prompt-injection defense: treat retrieved content as untrusted, instruct model accordingly, output filtering. Secrets in Secrets Manager. Audit log every query + sources returned. Data residency: keep vector DB + embeddings in-region for regulated clients.

**10. Scaling for millions of users.**
- Caching: semantic cache (Redis) for repeated/similar queries; embedding cache; CDN for static + cacheable answers.
- Model routing/tiering: cheap model first, escalate on low confidence or complex query.
- Separate read-heavy query path (scale horizontally, stateless) from write-heavy ingestion (queue + workers).
- Vector DB: shard + replicate; pre-warm; cap top-k.
- **Bottleneck checklist (breaks first → fix):** (1) Vector DB latency/throughput under concurrent queries → replicas + sharding + caching. (2) LLM provider rate limits/cost → routing, semantic cache, provisioned throughput. (3) Ingestion backlog on large doc loads → queue + autoscaled workers + batch embedding. (4) Reranker latency → cache, smaller reranker, or skip on high-confidence dense hits. (5) Context-window cost blowup → tighter top-k + token budget.

**11. Cost controls.** Token-budget per request; model routing (cheap-first); semantic + response cache (biggest single lever — measure hit-rate ROI); batch embeddings; cache embeddings to avoid re-embedding; spend dashboards + Anomaly alerts (CloudWatch/Langfuse); hard per-tenant token kill switch.

**12. Testing and evaluation strategy.** Code: unit (chunking, retrieval filters, prompt builders), integration (ingest→query end-to-end), e2e (UI flow). LLM eval: **RAGAS** (faithfulness, answer relevancy, context precision/recall) on a curated golden set, run in CI; **promptfoo** for prompt regression; online eval sampling in prod; A/B prompts/models behind a flag. Load test: k6/Locust against query path, measure p95 + cost/query at target RPS.

**13. Reference project structure.**
```
rag-app/
├── apps/
│   ├── web/                # Next.js frontend
│   ├── query-service/      # FastAPI: retrieve+rerank+generate+stream
│   └── ingestion-service/  # FastAPI+workers: load, chunk, embed, upsert
├── packages/
│   ├── core/               # shared: prompts, schemas (Pydantic), clients
│   └── eval/               # RAGAS sets, eval runners, golden data
├── infra/
│   ├── terraform/          # vpc, eks, qdrant, data, app modules
│   └── k8s/                # Helm charts / ArgoCD manifests
├── .github/workflows/      # ci, eval-gate, cd
├── tests/                  # unit, integration, e2e, load (k6)
└── docs/                   # architecture, runbooks, ADRs
```

**14. Production hardening checklist.** ACL-at-retrieval verified with tests; eval gate green and meaningful; Langfuse tracing live; p95 latency + cost dashboards; semantic cache with measured hit-rate; autoscaling tested under k6 load; secrets in Secrets Manager; prompt-injection + output filtering; per-tenant rate limits + kill switch; rollback (canary) proven; runbook for "retrieval returns garbage" and "provider outage"; backups for vector DB + Postgres; PII handling documented.

**15. Transformation roadmap — simple portfolio → production-grade.**
1. Get a working baseline: ingest one corpus, dense retrieval, single LLM, simple UI. (Likely already have this.)
2. Refactor into clean services: split ingestion vs query; Pydantic schemas at all boundaries; config-driven (no hardcoded keys/prompts).
3. Add hybrid retrieval (BM25 + dense) and a reranker; measure quality lift on a small eval set.
4. Build the RAGAS golden eval set + a CLI eval runner; record a baseline score.
5. Wire Langfuse tracing end-to-end (retrieval, tokens, cost, latency per stage).
6. Add semantic + embedding caching in Redis; measure hit-rate and latency/cost delta.
7. Implement per-tenant/per-doc ACL filtering at retrieval; add tests proving isolation.
8. Add guardrails: treat retrieved text as untrusted, output filtering, prompt-injection tests.
9. Dockerize all services (multi-stage); local docker-compose parity with prod.
10. Terraform: VPC, EKS, RDS, Redis, S3, Qdrant; deploy to a staging cluster.
11. Helm/ArgoCD manifests; HPA + KEDA (queue-depth) autoscaling; canary rollouts.
12. GitHub Actions: lint/test/build/scan/push + ArgoCD deploy + **RAGAS eval gate** blocking regressions.
13. Add model routing (cheap-first, escalate) + token budgets + spend alerts + kill switch.
14. k6 load test query path; tune HPA, vector DB replicas, top-k; document the bottleneck order.
15. Write runbooks + ADRs; verify rollback; final hardening-checklist pass.

---

## PACKAGE 2 — Production-grade Agentic AI Application

**1. Definition and target use cases.** Multi-step, tool-using LLM system that takes actions. Use cases: sales-ops agent (web + CRM research → outreach → HubSpot); internal ops copilot (query DBs, run reports, file Jira); research analyst agent (gather → synthesize → cited brief).

**2. Frontend layer.** Baseline. Deltas: **agent-trace UI** (show plan, tool calls, intermediate results — transparency is the product), streaming of steps not just tokens, **human-in-the-loop approval** controls (approve/edit/reject a tool action before it runs), run history, cancellation mid-run.

**3. Backend layer.** Baseline. Deltas: agent runs are **long-lived async jobs**, not request/response — run them on workers with a durable state store; stream progress over WebSocket/SSE. Each run has an ID, persisted state, and a step log. Strict per-run timeouts, step caps, and cost caps. Tool calls go through a typed, validated tool layer.

**4. AI/ML core.**
- **LLM strategy:** strong reasoning model for planning (Claude Sonnet/Opus, GPT-class); cheaper model for sub-tasks. Function/tool-calling-native models required.
- **Agent framework:** **LangGraph** (default — explicit graph, durable state, human-in-the-loop, checkpointing; production-grade control flow). *Alt:* a thin custom loop when the workflow is simple and deterministic (more reliable than a framework's magic); CrewAI/AutoGen only for genuine multi-agent collaboration patterns, with caution (harder to make reliable).
- **Tool/function calling:** every tool has a typed Pydantic schema, validation, timeout, and idempotency. Tools are deterministic, well-documented contracts. Wrap external APIs with retries + circuit breakers.
- **Planning & memory:** short-term (run state/scratchpad in the graph checkpoint), long-term (vector + structured store per user/session). Persist state for resumability.
- **Multi-agent:** only when justified (orchestrator-worker, evaluator-optimizer). Default to a single capable agent with good tools before reaching for multi-agent.
- **Reliability:** loop guards, max steps, cost guards, fallback chains, deterministic exits, human checkpoints on destructive actions.

**5. Data layer.** Postgres: run state, step logs, tool audit, results (default; durable + queryable). Redis: fast scratch + queue. Vector DB (Qdrant) for agent long-term memory + any RAG tool. S3: artifacts the agent produces. Message queue (SQS/Redis) for run dispatch.

**6. Infrastructure and deployment.** Baseline EKS. Agent workers as a separate, scalable Deployment (CPU; GPU only if self-hosting models). KEDA autoscale on run-queue depth. Durable state in RDS so workers are replaceable mid-run (checkpoint/resume). Network egress controls for tools that call external services. Inference: hosted APIs default; vLLM if self-hosting at volume.

**7. CI/CD and version control.** Baseline. Deltas: **tool contracts are versioned and tested in isolation** (each tool has its own unit + contract tests). Agent trajectories evaluated in CI (does the agent reach the goal on a fixed task suite?). Prompt/graph changes gated by trajectory eval. Monorepo with a clear `tools/` package.

**8. Observability.** Baseline + Langfuse **agent tracing** (every step, tool call, token, cost, latency, decision). Dashboards: steps-per-run, tool-failure rate, run success rate, cost-per-run, time-per-run, human-intervention rate. Alert on runaway runs (steps/cost over threshold) and tool-error spikes. This is the highest-observability package — agents fail silently and expensively without it.

**9. Security and compliance.** **Tool authorization is the core risk** — agents can take real actions. Least-privilege per tool, per-user; destructive actions require human approval; sandbox code-execution tools (gVisor/Firecracker/isolated containers). Prompt-injection is severe here (injected content can hijack tool use) — validate tool inputs, allowlist tools per context, never let retrieved/external text directly trigger privileged tools. Full audit log of every action taken. Secrets per-tool in Secrets Manager.

**10. Scaling for millions of users.**
- Runs are expensive and long — scale workers horizontally, queue aggressively, cap concurrency per tenant.
- Cache deterministic tool results; cache planning for repeated task types.
- Tier models: cheap model for routine steps, escalate for planning.
- **Bottleneck checklist:** (1) Worker pool saturation from long runs → queue + KEDA autoscale + per-tenant concurrency caps. (2) Cost explosion from loops/over-planning → step + cost guards, cheaper sub-task models. (3) Tool/downstream API rate limits → circuit breakers, backoff, caching, queued tool calls. (4) State store contention → Postgres connection pooling, partition by tenant. (5) Provider rate limits → routing + provisioned throughput.

**11. Cost controls.** Hard per-run step + token + dollar caps (non-negotiable for agents). Model tiering per step. Cache tool results + plans. Spend dashboards per tenant; anomaly alerts; global kill switch. Alert *before* a run gets expensive, not after.

**12. Testing and evaluation strategy.** Code: unit per tool, integration of the agent loop, e2e of a full task. Agent eval: **trajectory/task-success eval** on a fixed task suite (did it reach the goal? how many steps? cost?) — run in CI; LangSmith/Langfuse datasets or custom. Tool mocking for deterministic tests. Adversarial/prompt-injection test suite. Load test concurrent runs with k6 + measure worker scaling and cost/run.

**13. Reference project structure.**
```
agent-app/
├── apps/
│   ├── web/                 # Next.js: agent-trace + approval UI
│   ├── api/                 # FastAPI: run dispatch, status, streaming
│   └── worker/              # agent execution (LangGraph), checkpointing
├── packages/
│   ├── agents/              # graphs, planners, prompts
│   ├── tools/               # typed tools, each with schema + tests
│   ├── core/                # schemas, clients, state models
│   └── eval/                # task suites, trajectory eval, adversarial
├── infra/{terraform,k8s}/
├── .github/workflows/
├── tests/                   # unit, integration, e2e, load, injection
└── docs/                    # tool contracts, runbooks, ADRs
```

**14. Production hardening checklist.** Step/cost/time caps enforced + tested; tool authz least-privilege + audited; destructive actions gated by human approval; code-exec tools sandboxed; prompt-injection suite passing; durable state with resume-after-worker-death proven; trajectory eval gate green; per-tenant concurrency + kill switch; Langfuse agent tracing live; runaway-run alerts; rollback proven; runbooks for "agent stuck in loop" and "tool taking bad actions."

**15. Transformation roadmap.**
1. Working baseline: single agent, 2–3 tools, in-memory loop, simple UI.
2. Move to LangGraph with explicit nodes + a persisted checkpoint store (Postgres).
3. Refactor tools into a typed `tools/` package; Pydantic schemas + per-tool unit tests.
4. Add step/cost/time guards and deterministic exit conditions; test the guards fire.
5. Make runs async jobs on a worker + queue; stream progress over WebSocket; add run IDs + step logs.
6. Add human-in-the-loop approval for destructive tools (LangGraph interrupts).
7. Build a trajectory eval task suite + runner; record baseline success/steps/cost.
8. Wire Langfuse agent tracing (steps, tools, cost, latency).
9. Add tool authz (least-privilege per user/context) + audit logging; sandbox any code-exec tool.
10. Add adversarial/prompt-injection tests; harden tool-trigger paths against injected content.
11. Dockerize api + worker; docker-compose parity.
12. Terraform + EKS + RDS + Redis + Qdrant; deploy worker pool with KEDA queue autoscaling.
13. ArgoCD + GitHub Actions with trajectory eval gate + tool contract tests.
14. Add model tiering, caching of tool results/plans, per-tenant concurrency caps, kill switch.
15. k6 concurrent-run load test; tune worker autoscaling; runbooks + final hardening pass.

---

## PACKAGE 3 — Production-grade Fine-tuned LLM Application

**1. Definition and target use cases.** App built around a model fine-tuned to a client's domain/voice/task. Use cases: brand-voice content generator on approved copy; domain extractor/classifier (medical-coding, legal-clause) for accuracy + cost; small open-weight model fine-tuned to replace an expensive frontier API on a narrow high-volume task.

**2. Frontend layer.** Baseline (often lighter — many fine-tune apps are API-first/internal). Deltas: feedback capture UI (thumbs + correction) to build the next training set; A/B toggle between base and fine-tuned outputs for the client to see the lift.

**3. Backend layer.** Baseline. Deltas: an inference API in front of the fine-tuned model + a fallback to a hosted frontier model on low confidence/failure. A feedback ingestion endpoint feeding the data-prep pipeline.

**4. AI/ML core.**
- **Decision first:** confirm fine-tuning is actually warranted vs RAG/prompting. Fine-tune for *form/format/voice/latency/cost on a narrow task*; use RAG for *knowledge*. State this to the client explicitly — it's the most common place this package is mis-sold.
- **Base model:** open-weight in the 7–8B class default (Llama-3.x-8B, Mistral-7B, Qwen) for self-hostable cost wins; *Alt:* fine-tune a hosted model (OpenAI/Bedrock fine-tuning) when the client wants zero infra and accepts API cost.
- **Method:** **QLoRA** (default — best cost/quality, fits on modest GPUs, your existing skill). *Alt:* LoRA (no quant) when GPU memory allows and you want speed; full fine-tune only with strong justification + budget; **DPO** after SFT when you have preference data and need alignment to a quality bar; instruction-tuning when building a chat/instruct model from a base.
- **Data prep pipeline:** the real work. Collect → clean → dedup → format to chat/instruction schema → split → validate → version (DVC/HF datasets). Quality + diversity of data dominates outcome.
- **Training infra:** SageMaker training jobs (default — your skill, managed, Spot for cost) — *Alt:* a single GPU on EC2/Lambda Labs/RunPod for small jobs; Axolotl/HF `trl` (SFTTrainer/DPOTrainer) as the training stack. Mixed precision + double quantization (QLoRA).
- **Serving:** **vLLM** (default — high throughput, serves LoRA adapters, big cost win at volume) — *Alt:* SageMaker endpoint (managed, your skill); TGI (HF fit). Serve multiple LoRA adapters off one base model where applicable.

**5. Data layer.** S3: training data (versioned), model artifacts, adapters. DVC or HF Hub: dataset + model versioning. Postgres: feedback, eval results, experiment metadata. **MLflow** (default): experiment tracking + model registry. Vector DB only if the app also does RAG.

**6. Infrastructure and deployment.** Two distinct planes: **training** (ephemeral GPU — SageMaker jobs or Spot GPU EC2, spun up per run) and **serving** (persistent GPU node pool on EKS running vLLM, or a SageMaker endpoint). Terraform: separate `training` and `serving` modules. GPU node pools with the right instance type (e.g., g5/g6 for serving 7–8B; bigger for larger). Autoscale serving on GPU utilization/queue; scale-to-zero for low traffic (SageMaker async/serverless or KEDA). This is the most GPU-cost-sensitive package — get instance selection and autoscaling right.

**7. CI/CD and version control.** Two pipelines: **code CI/CD** (baseline) and a **model pipeline** (data version → train → eval → register in MLflow → gated promotion → deploy adapter). Model promotion is gated by an eval set + the base-vs-tuned comparison. Roll back by serving the previous adapter/model version (registry-backed). Version: code (git), data (DVC), model (MLflow registry), prompts (registry).

**8. Observability.** Baseline + serving metrics: GPU utilization, tokens/sec, queue depth, p95 latency, cost/1k tokens. Quality monitoring: live sampling scored against the eval rubric; drift detection (input distribution shift vs training data → retrain trigger). Langfuse for request-level traces. Track fine-tuned vs fallback rates.

**9. Security and compliance.** Training data is often the most sensitive asset — encrypt at rest (S3 KMS), strict IAM, PII handling/redaction before training, document data lineage. Risk of training-data memorization/leakage — test for it. Model artifacts access-controlled. Standard auth/authz/secrets baseline. For regulated clients: data residency on training + serving, audit the data pipeline.

**10. Scaling for millions of users.**
- Self-hosted serving is the scale story: vLLM continuous batching, multi-replica GPU pool, autoscale on utilization.
- Route: fine-tuned small model for the common narrow task (cheap, fast), escalate to frontier API for edge cases.
- Cache responses where deterministic.
- **Bottleneck checklist:** (1) GPU saturation under load → more replicas + continuous batching + right instance; quantize for throughput. (2) Cold starts on scale-from-zero → warm pool / min replicas / provisioned. (3) GPU cost → quantization, batching, scale-to-zero off-peak, Spot for training. (4) Quality drift over time → drift monitor + retrain loop. (5) Long-tail queries the small model fails → confidence-based fallback to frontier.

**11. Cost controls.** The whole package is often *justified by* cost savings vs frontier APIs — measure and prove unit cost (tuned-self-host vs API). Quantization, continuous batching, scale-to-zero/Spot, batch offline jobs. Cap fallback-to-frontier usage. Monitor cost/1k tokens and GPU-hours; alert on spend.

**12. Testing and evaluation strategy.** Code: unit/integration/e2e baseline. **Model eval is central:** held-out test set with task-specific metrics (accuracy/F1 for extraction/classification; rubric/LLM-judge for generation/voice); always report **base vs fine-tuned** lift; regression-test new model versions before promotion. Online eval sampling + drift. A/B fine-tuned vs base/frontier in prod. Load-test the serving tier (k6) for tokens/sec + p95 + cost at target QPS.

**13. Reference project structure.**
```
finetune-app/
├── apps/
│   ├── web/                 # optional UI + feedback capture
│   └── inference-api/       # FastAPI: serve tuned model + fallback
├── training/
│   ├── data_pipeline/       # collect, clean, format, version (DVC)
│   ├── train/               # QLoRA/trl/Axolotl configs + scripts
│   └── eval/                # test sets, base-vs-tuned, metrics
├── serving/                 # vLLM config, adapter loading
├── infra/
│   └── terraform/           # training (ephemeral GPU) + serving (GPU pool)
├── .github/workflows/       # code CI + model pipeline (train→eval→register→deploy)
├── mlflow/                  # tracking + registry config
└── docs/                    # data lineage, model cards, runbooks
```

**14. Production hardening checklist.** Base-vs-tuned lift measured + documented (model card); eval gate before promotion; MLflow registry with rollback to prior version; data lineage + PII handling documented; memorization/leakage tested; vLLM serving autoscaled + load-tested; cost/1k-tokens proven vs alternative; drift monitor + retrain trigger; confidence-based fallback to frontier; GPU instance right-sized; secrets + KMS on data; runbooks for "quality regression" and "GPU pool saturation."

**15. Transformation roadmap.**
1. Baseline: a QLoRA fine-tune on a small dataset, manual eval, local inference (likely have this).
2. Build the data pipeline: clean, dedup, format to chat schema, train/val/test split, version with DVC.
3. Establish the eval set + metrics; record **base-model** baseline scores before tuning.
4. Reproducible training: parameterized QLoRA config (trl/Axolotl), MLflow experiment tracking, SageMaker/Spot GPU job.
5. Automated eval after training: base-vs-tuned report, register in MLflow only if it beats the bar.
6. Stand up vLLM serving with the adapter; benchmark tokens/sec + p95.
7. Build the inference API with confidence-based fallback to a frontier model.
8. Add feedback capture → feed the next dataset version (close the data loop).
9. Dockerize training + serving (GPU base images, layer-cache weights); compose for local.
10. Terraform: separate training (ephemeral GPU) + serving (GPU node pool) modules on EKS.
11. Serving autoscaling (KEDA/GPU-util) + scale-to-zero off-peak; ArgoCD deploy.
12. Model pipeline in CI: data→train→eval→register→gated deploy; rollback to prior adapter.
13. Add drift monitoring + retrain trigger; quality sampling in prod (Langfuse).
14. Prove unit-cost vs frontier API; add spend monitoring + fallback caps + alerts.
15. k6 load test serving tier; right-size GPU; model card + runbooks + final hardening.

---
## PACKAGE 4 — Multi-modal GenAI Application

**1. Definition and target use cases.** Combines text with vision and/or audio in one product. Use cases: insurance claim triage from damage photos + text; visual product search + Q&A for e-commerce; video/meeting summarizer (transcript + slides + screenshots → searchable notes).

**2. Frontend layer.** Baseline. Deltas: media upload (image/audio/video) with client-side validation + progress, drag-drop, camera/mic capture, media preview with annotated overlays (bounding boxes/regions the model referenced), mixed-media result rendering. Stream text; show media-processing status separately (it's slower).

**3. Backend layer.** Baseline. Deltas: media processing is heavy + slow → always async via queue + workers; pre-signed S3 upload URLs (don't proxy large media through the API); separate pipelines per modality that converge into a unified context. Strict file-type/size validation + virus scan on upload.

**4. AI/ML core.**
- **LLM strategy:** multi-modal frontier model (GPT-4-class vision, Claude vision, Gemini) as default for vision+text reasoning. Specialized models per modality where cheaper/better.
- **Vision:** frontier VLM for understanding/reasoning; *Alt:* self-hosted (Qwen-VL, LLaVA) at volume; classic CV (YOLO/Detectron — you have this) for detection/segmentation pre-processing before the VLM. Generation: DALL·E/SDXL/Flux when image *output* is needed.
- **Audio:** **Whisper** (default STT — you have it; large-v3 or `faster-whisper`/`whisper.cpp` for speed) → text into the LLM. TTS only if voice output needed (see Package 7).
- **Orchestration:** custom pipeline per modality + a fusion step; LangGraph if the flow is multi-step/branching. Don't force a single framework across modalities.
- **Fusion/context:** convert each modality to a common representation (captions/transcripts/structured extractions + the raw media reference), construct a unified prompt, keep token budget in check (media descriptions are verbose).
- **Multi-modal RAG:** embed images (CLIP-style) + text in the vector store; retrieve across modalities (you've studied multi-modal RAG).

**5. Data layer.** S3: all media (raw + derived: thumbnails, transcripts, frames) — the dominant storage cost. Vector DB (Qdrant): multi-modal embeddings. Postgres: media metadata, extraction results, job status. Redis: cache + queue. CDN (CloudFront) for media delivery.

**6. Infrastructure and deployment.** Baseline EKS. Modality workers as separate Deployments (vision worker, audio worker) — GPU pool for self-hosted vision/Whisper, CPU for orchestration. KEDA autoscale on queue depth per modality. Heavy media → ensure worker timeouts + chunking (long video). S3 + CloudFront for media. Inference: frontier multi-modal APIs default; GPU self-host (Whisper, VLM) at volume. SageMaker async endpoints are a good fit for batchy media jobs.

**7. CI/CD and version control.** Baseline. Deltas: test fixtures include sample media (images/audio) — keep them small/in LFS or S3. Eval gate covers per-modality accuracy (caption quality, transcription WER, extraction accuracy). Version the per-modality model choices.

**8. Observability.** Baseline + per-modality metrics: processing latency (vision vs audio vs fusion), queue depth per modality, cost per modality per request, failure rate by media type. Langfuse for the LLM/fusion step. Alert on stuck media jobs and modality-specific error spikes.

**9. Security and compliance.** Media often contains PII/faces/sensitive content — encrypt at rest (S3 KMS), access-controlled pre-signed URLs with expiry, redact/blur faces if required, content-moderation scan on uploads (abuse prevention), virus scan. Data residency on media storage for regulated clients. Audit media access. Strip EXIF/geolocation if privacy-sensitive.

**10. Scaling for millions of users.**
- Async-everything for media; never block request threads on processing.
- Pre-signed direct-to-S3 uploads (offload bandwidth from your API).
- Cache derived artifacts (transcripts, captions, embeddings) — never reprocess the same media.
- CDN for media delivery; thumbnail/transcode tiers.
- **Bottleneck checklist:** (1) Media processing throughput (GPU-bound vision/Whisper) → autoscaled GPU workers + batching + smaller/faster models. (2) S3 bandwidth/cost on large media → direct upload, lifecycle policies, compression. (3) Long video timeouts → chunk + parallelize + reassemble. (4) Multi-modal token cost (verbose descriptions) → tighter extraction, caching. (5) Cold GPU starts → min replicas / warm pool.

**11. Cost controls.** Cache derived artifacts aggressively (biggest lever — media reprocessing is expensive). Route: cheap classic-CV/specialized model first, frontier VLM only when needed. Compress/downsample media before model calls. Batch media jobs. S3 lifecycle (Glacier for cold raw media). Monitor cost per modality; alert + caps.

**12. Testing and evaluation strategy.** Code: unit per modality pipeline, integration of fusion, e2e with sample media. Eval: per-modality (transcription WER, caption/extraction accuracy on a golden media set, detection mAP if CV), plus end-to-end answer quality (RAGAS-style if RAG). Regression on model swaps. Load test with realistic media sizes/mix (k6 + S3).

**13. Reference project structure.**
```
multimodal-app/
├── apps/
│   ├── web/                 # upload + mixed-media result UI
│   ├── api/                 # FastAPI: presigned uploads, jobs, fusion+stream
│   ├── vision-worker/       # VLM/CV processing
│   └── audio-worker/        # Whisper STT processing
├── packages/
│   ├── pipelines/           # per-modality pipelines + fusion
│   ├── core/                # schemas, clients, media utils
│   └── eval/                # per-modality + e2e eval sets
├── infra/{terraform,k8s}/   # GPU pools, S3, CloudFront
├── .github/workflows/
├── tests/                   # unit, integration, e2e, load, sample-media
└── docs/
```

**14. Production hardening checklist.** Async media pipeline with presigned uploads; per-modality eval gates; derived-artifact caching; GPU worker autoscaling load-tested; media encryption + access-controlled URLs with expiry; content moderation + virus scan + EXIF strip; CDN + S3 lifecycle; per-modality cost monitoring + caps; long-media chunking proven; runbooks for "stuck media job" and "GPU saturation."

**15. Transformation roadmap.**
1. Baseline: single-modality-at-a-time flow (e.g., image→description→answer) working.
2. Refactor into per-modality pipelines + a fusion step; clean schemas.
3. Move media handling to presigned direct-to-S3 uploads + async job workers + status.
4. Add the second modality (audio/Whisper or vision) as its own worker.
5. Build per-modality eval sets (WER, caption/extraction accuracy); baseline scores.
6. Multi-modal embedding + cross-modal retrieval in Qdrant (if RAG needed).
7. Cache derived artifacts (transcripts/captions/embeddings); never reprocess.
8. Langfuse + per-modality metrics/dashboards.
9. Security: KMS, presigned-with-expiry, moderation/virus/EXIF, face-blur if needed.
10. Dockerize workers (GPU images for vision/Whisper); compose for local.
11. Terraform: GPU pools, S3, CloudFront; EKS deploy; KEDA per-modality autoscaling.
12. ArgoCD + CI with per-modality eval gates.
13. Add routing (cheap model first), media compression, cost monitoring + caps.
14. Long-media chunking + parallelization; k6 load test with realistic media mix.
15. Runbooks + final hardening pass.

---

## PACKAGE 5 — Document Intelligence Pipeline

**1. Definition and target use cases.** High-accuracy ingestion, extraction, and structuring from messy documents at volume. Use cases: invoice/receipt → structured ERP records; loan-packet (IDs, statements, forms) → validated schema; contract digitization (clause extraction, obligation tracking, anomaly flagging) across a back-catalog. Distinct from RAG: the deliverable is **structured data**, not chat answers.

**2. Frontend layer.** Baseline (often an internal review tool). Deltas: a **human-review/correction UI** (document viewer with extracted fields overlaid on the source, confidence highlighting, edit + approve) — central, because this package usually needs human-in-the-loop verification. Batch-upload + job-status dashboard.

**3. Backend layer.** Baseline. Deltas: a batch-oriented async pipeline (queue + workers); idempotent processing (same doc → same result, safe retries); a validation layer (schema + business rules) between extraction and persistence; per-document confidence scoring that routes low-confidence docs to human review.

**4. AI/ML core.**
- **LLM strategy:** vision-capable LLM for layout-aware extraction (GPT-4-class/Claude vision/Gemini) as default — handles messy/varied layouts better than rules. Cheaper model for clean/templated docs.
- **OCR/parsing:** **AWS Textract** (default — forms/tables/queries, AWS-native, your stack) — *Alt:* Azure Document Intelligence (often best-in-class for forms/layout — flag this even on AWS), or open-source (`docling`, `unstructured`, PaddleOCR, Tesseract) for cost/residency. Layout models (LayoutLM family) for structured forms.
- **Extraction pattern:** OCR/layout → LLM with a strict **structured-output schema** (Pydantic + JSON-mode/function-calling/`instructor`) → validation → confidence → route. Few-shot per doc type.
- **Orchestration:** custom pipeline (default — deterministic, testable; doc intelligence is ETL, not chat) — *Alt:* LlamaIndex/LangChain for the parsing primitives only.
- **Validation:** schema validation + business rules (totals add up, dates valid, required fields present) + cross-field checks; confidence thresholds drive human-review routing.
- **Optional RAG layer** on top for Q&A over the extracted/structured corpus.

**5. Data layer.** S3: raw docs + derived (OCR output, page images). Postgres: structured extractions (the product), validation results, review status, audit (default — relational, queryable, the deliverable is structured). Redis: queue + cache. Vector DB (Qdrant) only if adding RAG/search. Optionally a search index (OpenSearch) over extracted data.

**6. Infrastructure and deployment.** Baseline EKS, batch-pipeline shaped. Extraction workers (CPU; GPU only if self-hosting OCR/layout models) autoscaled on queue depth (KEDA). Textract/Azure DI are managed (no GPU needed). Good fit for **AWS Step Functions** or Airflow to orchestrate multi-stage doc pipelines + retries (you have both). S3 + lifecycle. SageMaker async/Batch for large back-catalog jobs.

**7. CI/CD and version control.** Baseline. Deltas: extraction accuracy eval gate (per doc type, per field) blocks deploy on regression. Version extraction schemas + prompts + doc-type configs. Golden document set in test fixtures (small/representative).

**8. Observability.** Baseline + pipeline metrics: throughput (docs/hr), extraction accuracy (sampled), confidence distribution, human-review rate, per-field error rate, cost/doc, validation-failure rate. Alert on accuracy drop, review-queue backlog, throughput stall. Trace extractions in Langfuse.

**9. Security and compliance.** Documents are usually highly sensitive (financial, identity, legal) — this is the most compliance-heavy package after vertical wrappers. Encrypt at rest (S3 KMS) + in transit; strict IAM; PII detection/redaction; data residency (Textract/Azure DI region pinning); full audit trail (who accessed/edited which doc/field); retention/deletion policies; access control per doc/client. Often needs SOC 2 / GDPR alignment — price accordingly.

**10. Scaling for millions of documents.**
- Batch + queue + idempotent workers; horizontal scale on doc volume.
- Tier: cheap path (templated/clean docs, rules/cheap model) vs expensive path (messy docs, vision LLM).
- Cache OCR results (don't re-OCR); dedup identical docs.
- **Bottleneck checklist:** (1) OCR/extraction throughput → autoscale workers + Textract concurrency limits (request quota increases) + tiering. (2) Vision-LLM cost on large volumes → route clean docs to cheaper paths, cache. (3) Human-review bottleneck → raise confidence thresholds, improve extraction, prioritize queue. (4) Step Functions/queue limits at scale → batch + partition. (5) Postgres write throughput → batch inserts, partition by client.

**11. Cost controls.** Tier by doc complexity (cheap path for templated docs is the biggest lever). Cache OCR + dedup. Batch processing (Textract/Batch). Cap vision-LLM usage; monitor cost/doc; alert + caps. For back-catalog one-time jobs, use Spot + Batch.

**12. Testing and evaluation strategy.** Code: unit (parsers, validators, schema), integration (full pipeline), e2e. Eval: **field-level extraction accuracy** (precision/recall per field) on a golden set per doc type; validation-rule coverage; confidence-calibration check; regression on model/prompt/schema changes. Load test throughput (docs/hr) at target volume.

**13. Reference project structure.**
```
doc-intel/
├── apps/
│   ├── review-ui/           # human review/correction tool
│   ├── api/                 # FastAPI: ingest, jobs, results, review
│   └── worker/              # OCR → extract → validate → persist
├── packages/
│   ├── extraction/          # per-doc-type schemas, prompts, parsers
│   ├── validation/          # schema + business rules
│   ├── core/                # clients (Textract/LLM), models
│   └── eval/                # golden docs, field-accuracy eval
├── orchestration/           # Step Functions / Airflow DAGs
├── infra/{terraform,k8s}/
├── .github/workflows/
├── tests/                   # unit, integration, e2e, golden-set, load
└── docs/                    # schemas, compliance, runbooks
```

**14. Production hardening checklist.** Field-level accuracy eval gate per doc type; confidence-based human-review routing; idempotent retry-safe pipeline; validation + business rules enforced; PII handling + KMS + audit trail + retention; data residency pinned; OCR caching + dedup; throughput load-tested; cost/doc monitored + tiered + capped; review-queue backlog alerts; runbooks for "accuracy regression" and "queue backlog."

**15. Transformation roadmap.**
1. Baseline: single doc type, OCR + LLM extraction to JSON, manual check.
2. Define strict Pydantic output schemas + structured-output extraction (`instructor`/JSON-mode).
3. Add a validation layer (schema + business rules) + per-field confidence scoring.
4. Build golden doc sets + field-level accuracy eval; baseline scores.
5. Async batch pipeline: queue + idempotent workers + job status.
6. Human-review UI with source overlay + confidence highlighting + edit/approve.
7. Confidence-based routing (auto-accept high, route low to review).
8. Persist structured results to Postgres with audit trail; OCR caching + dedup.
9. Langfuse + pipeline dashboards (throughput, accuracy, review rate, cost/doc).
10. Compliance: KMS, PII redaction, residency, retention, access control.
11. Dockerize; orchestrate multi-stage with Step Functions/Airflow.
12. Terraform + EKS + S3 + RDS; KEDA queue autoscaling; ArgoCD.
13. CI with field-accuracy eval gate; version schemas/prompts/doc-type configs.
14. Add complexity tiering (cheap vs vision path) + cost monitoring/caps; k6 throughput test.
15. Runbooks + final hardening pass.

---

## PACKAGE 6 — AI Microservice into an Existing System

**1. Definition and target use cases.** A GenAI capability dropped into a client's *current* product/codebase — not greenfield. Highest-demand, lowest-friction package: clients already have a system and want one AI feature. Use cases: "summarize"/"draft reply"/"smart search" endpoints added to an existing SaaS; an embeddings + reranking service behind a client's existing search bar; a moderation/classification microservice consumed by the client's backend.

**2. Frontend layer.** Usually **none of your own** — you expose an API the client's existing frontend calls. Deliverable: clean API + (optionally) a drop-in React/web component + integration docs. If you do supply UI, it's an embeddable widget, not a full app.

**3. Backend layer.** This is the core deliverable. FastAPI microservice (default), designed to **fit the client's existing architecture** — match their auth, their API conventions, their deployment target. Clean REST/gRPC contract, OpenAPI spec, versioned API, backward-compatibility discipline. Async + background jobs if needed. Rate limiting + quotas. The skill here is *integration*, not greenfield freedom.

**4. AI/ML core.**
- **LLM strategy:** hosted API (Bedrock/OpenAI) default — clients adding a feature rarely want GPU infra; self-host only if they already have it or volume demands.
- **Orchestration:** keep it thin — the lighter the better for a microservice. Direct SDK calls or minimal LangChain. *Avoid* dragging a heavy framework into a client's stack.
- **Capability-specific:** RAG mini-pipeline (Package 1 patterns, scoped down), or classification/extraction (structured output), or embeddings+rerank service, depending on the feature.
- **Prompt management:** versioned, in the service repo; Langfuse if the client allows.
- **Contract-first:** the AI is an implementation detail behind a stable API — design the contract so you can swap models without breaking the client.

**5. Data layer.** Minimize footprint — ideally use the client's existing stores. Add only what's needed: a vector DB (Qdrant/pgvector — pgvector if they already run Postgres, to avoid new infra), Redis cache, maybe a small table for the service's own state. Respect their data boundaries; don't sprawl.

**6. Infrastructure and deployment.** **Deploy where the client lives** — their EKS/ECS/Lambda/their cloud. Containerized, 12-factor, config via env/secrets manager. If standalone: ECS Fargate (default — simpler than EKS for a single service) or Lambda (spiky/low-volume). Terraform module that drops into their IaC. Don't impose your stack on their infra. Inference: their cloud's managed LLM (Bedrock on AWS, Azure OpenAI on Azure) to stay in their ecosystem/residency.

**7. CI/CD and version control.** Fit their workflow (their GitHub/GitLab, their pipeline conventions). Polyrepo (this service stands alone). Strong API contract tests + backward-compat checks. Semantic versioning of the API. Staging → prod promotion matching their process. Eval gate for the AI capability.

**8. Observability.** Emit metrics/logs/traces in **their** stack's format (OTel → wherever they aggregate). Don't force Langfuse if they won't run it — but push token/cost/latency metrics into their observability so the feature isn't a black box. Health/readiness endpoints matching their orchestrator's expectations.

**9. Security and compliance.** Inherit and respect the client's security model — their auth (validate their JWTs/API keys), their secrets manager, their data-residency and compliance posture. Service-to-service auth (mTLS/signed requests). Don't exfiltrate their data to a model provider without explicit approval + a DPA. Input/output guardrails. This package lives or dies on *not* being the weak link in their system.

**10. Scaling for millions of users.**
- Stateless service, horizontal scale behind their load balancer.
- Caching (semantic/response) to cut provider load + cost.
- Match their scaling model (their HPA/autoscaling).
- Graceful degradation: if the AI provider is down, fail in a way that doesn't take down their system (fallback/queue/feature-flag-off).
- **Bottleneck checklist:** (1) Provider rate limits → caching, routing, provisioned throughput, request queueing. (2) Latency added to their UX → streaming, caching, async where possible, tight timeouts. (3) Their system's blast radius if your service fails → circuit breaker on their side, graceful degradation. (4) Cost attribution → per-tenant metering. (5) Coupling → keep the contract stable, version it.

**11. Cost controls.** Caching (semantic/response — protects both latency and cost), model routing/tiering, token budgets, per-tenant metering (the client needs to attribute cost), spend alerts + caps, kill switch (feature flag to disable AI feature without redeploy).

**12. Testing and evaluation strategy.** Code: unit, integration **against their system's contracts** (mock their APIs), contract tests, backward-compat tests. Eval: capability-specific (RAGAS for RAG feature, accuracy for classification) gated in CI. Load test at *their* expected traffic + verify graceful degradation under provider failure.

**13. Reference project structure.**
```
ai-microservice/
├── src/
│   ├── api/                 # FastAPI routes, OpenAPI contract
│   ├── core/                # AI capability logic, prompts, clients
│   ├── adapters/            # integration w/ client's auth/stores/APIs
│   └── observability/       # OTel exporters in client's format
├── infra/terraform/         # module that drops into client's IaC
├── deploy/                  # Dockerfile, ECS/EKS/Lambda manifests
├── .github|.gitlab/         # pipeline matching client conventions
├── tests/                   # unit, integration, contract, load
└── docs/                    # API spec, integration guide, runbook
```

**14. Production hardening checklist.** Stable versioned API + contract tests + backward-compat; deploys in client's infra/cloud; uses client's auth + secrets + observability; graceful degradation on provider failure + feature kill switch; caching live; per-tenant cost metering; capability eval gate; load-tested at client traffic; DPA/data-flow approved; integration guide + runbook delivered; no new attack surface introduced.

**15. Transformation roadmap.**
1. Baseline: the AI capability working standalone (RAG/classify/summarize) with a rough API.
2. Define a clean, versioned API contract + OpenAPI spec; freeze it with contract tests.
3. Build adapters for the client's auth (validate their tokens) and stores (reuse, don't duplicate).
4. Add capability eval (RAGAS/accuracy) + gate it in CI.
5. Wire observability in the client's format (OTel → their backend) + token/cost/latency metrics.
6. Caching (semantic/response) + token budgets + per-tenant metering.
7. Graceful degradation + circuit breaker + feature kill switch.
8. Security: secrets manager, service-to-service auth, guardrails, DPA-compliant data flow.
9. Dockerize 12-factor; Terraform module that drops into their IaC.
10. Deploy to staging in their cloud (ECS/EKS/Lambda) matching their conventions.
11. Pipeline in their CI tool with contract + backward-compat + eval gates.
12. Load test at their expected traffic; verify degradation under provider outage.
13. Add model routing/tiering + spend alerts + caps.
14. Integration guide + runbook + API docs handed to their team.
15. Production cutover behind a feature flag; monitor; final hardening pass.

---

## PACKAGE 7 — Voice / Conversational AI

**1. Definition and target use cases.** Real-time speech-in/speech-out assistant or phone agent. Use cases: inbound support voice agent (STT → LLM + tools → TTS) with human handoff; multilingual voice FAQ/IVR replacement for an SMB; voice-driven field-data capture for hands-busy technicians. The hard constraint is **latency** — conversational turn-taking must feel real-time (<~800ms perceived).

**2. Frontend layer.** Web: WebRTC for mic capture + audio playback, voice-activity/interrupt UI (barge-in), live transcript display, push-to-talk + continuous modes. Phone: Twilio/telephony integration (no UI). State: clear speaking/listening/thinking indicators. Streaming audio both directions.

**3. Backend layer.** Baseline + **real-time streaming pipeline** is the architecture: WebSocket/WebRTC audio in → streaming STT → LLM (streaming) → streaming TTS → audio out, with barge-in/interrupt handling. Low-latency, stateful per-session connections. Telephony via Twilio/LiveKit. Background tools called mid-conversation must not block the audio loop.

**4. AI/ML core.**
- **Realtime stack:** **OpenAI Realtime API / Gemini Live** (default — speech-to-speech, lowest latency, handles turn-taking) — *Alt:* a composed pipeline (Deepgram STT + LLM + ElevenLabs/Cartesia TTS) when you need model flexibility or cost control; **Pipecat** or **LiveKit Agents** as the orchestration framework for the composed pipeline (default for composed).
- **STT:** Deepgram (default — fast streaming) or Whisper/`faster-whisper` self-hosted; streaming + interim results required.
- **TTS:** ElevenLabs (default — quality) or Cartesia (low latency) or Amazon Polly (cheap/AWS-native); streaming synthesis required.
- **LLM:** fast model (Haiku/GPT-mini/Sonnet) — latency over raw capability; tool/function calling for actions.
- **Conversation management:** turn detection, barge-in/interruption, context/history per session, tool calls mid-turn, human handoff trigger. Endpointing tuned carefully.

**5. Data layer.** Redis: session state + conversation context (low-latency, ephemeral). Postgres: call logs, transcripts, outcomes, tool-action audit. S3: audio recordings (if retained — compliance-sensitive). Vector DB (Qdrant) if RAG-grounded answers. Telephony provider holds the media path.

**6. Infrastructure and deployment.** Baseline EKS, but **latency + stateful sessions** dominate: deploy near users (regional), keep sessions sticky, minimize hops. WebRTC infra (LiveKit self-host or cloud). Self-hosted STT/TTS → GPU pool; hosted APIs avoid GPU. Autoscale on concurrent-session count, not RPS. Provider/telephony egress + redundancy. This package is the most latency-sensitive — every architectural hop costs perceived responsiveness.

**7. CI/CD and version control.** Baseline. Deltas: eval includes latency budgets (STT/LLM/TTS each measured) + conversation-quality tests. Hard to test automatically — invest in recorded-conversation replay suites. Version voice/prompt/turn-detection configs.

**8. Observability.** Baseline + **latency breakdown per turn** (STT, LLM, TTS, total perceived) is the key metric; also: interruption rate, turn-success, tool-call success, human-handoff rate, call duration, cost/minute. Langfuse for the LLM. Alert on latency budget breaches and handoff spikes. Record/sample calls for quality review.

**9. Security and compliance.** Voice is biometric/PII — heavy compliance (call recording consent laws vary by jurisdiction — handle explicitly), encrypt recordings (KMS), access control, retention policies. PII in transcripts → redaction. For support agents taking actions: tool authz + audit (Package 2 concerns). Telephony fraud/abuse prevention. Data residency on recordings. Often regulated (TCPA, GDPR, regional consent) — price for it.

**10. Scaling for millions of users.**
- Scale on concurrent sessions; each session is a stateful long-lived connection (very different from stateless RPS scaling).
- Regional deployment to cut latency; sticky sessions.
- Connection/session pooling; graceful overflow to queue or callback.
- **Bottleneck checklist:** (1) Concurrent-session capacity (each holds STT+LLM+TTS streams) → horizontal session workers + connection limits + regional pods. (2) End-to-end latency under load → co-locate components, fast models, streaming everything, regional. (3) STT/TTS provider rate limits/cost → self-host at volume, caching of common TTS phrases. (4) Telephony concurrency limits → provider capacity planning. (5) GPU for self-hosted STT/TTS → autoscale + batching.

**11. Cost controls.** Voice is expensive (STT + LLM + TTS per minute) — measure cost/minute relentlessly. Self-host STT/TTS at volume (big lever). Cache common TTS phrases. Fast/cheap LLM. Cap call duration; route simple calls to cheaper paths/IVR. Spend alerts + caps + kill switch.

**12. Testing and evaluation strategy.** Code: unit (turn logic, endpointing), integration (full pipeline), e2e with recorded audio. Eval: latency budgets per stage, transcription accuracy (WER), conversation success/task completion, interruption handling, on recorded-conversation replay sets. Load test concurrent sessions (not just RPS) + measure latency degradation.

**13. Reference project structure.**
```
voice-ai/
├── apps/
│   ├── web/                 # WebRTC client, transcript, barge-in
│   ├── session-service/     # WS/WebRTC: STT↔LLM↔TTS realtime loop
│   └── telephony/           # Twilio/LiveKit integration
├── packages/
│   ├── pipeline/            # turn detection, endpointing, interruption
│   ├── core/                # STT/TTS/LLM clients, session state
│   └── eval/                # recorded convos, latency + WER eval
├── infra/{terraform,k8s}/   # regional, sticky sessions, GPU if self-host
├── .github/workflows/
├── tests/                   # unit, integration, replay, load(sessions)
└── docs/                    # consent/compliance, runbooks
```

**14. Production hardening checklist.** Per-turn latency budget met + measured; barge-in/interruption works; concurrent-session load-tested; regional deployment + sticky sessions; recording consent + encryption + retention compliant; PII redaction in transcripts; tool authz + audit (if actions); human-handoff path; cost/minute monitored + capped + kill switch; telephony fraud prevention; runbooks for "latency spike" and "provider outage."

**15. Transformation roadmap.**
1. Baseline: turn-based STT → LLM → TTS working (not yet real-time/streaming).
2. Move to streaming everything (interim STT, streaming LLM, streaming TTS); measure per-stage latency.
3. Add turn detection + endpointing + barge-in/interruption handling.
4. WebRTC/WebSocket session service with per-session state in Redis.
5. Establish latency budgets + a recorded-conversation replay eval suite; baseline.
6. Add tool calling mid-conversation + human-handoff trigger (if agentic).
7. Telephony integration (Twilio/LiveKit) if phone is in scope.
8. Langfuse + latency-breakdown dashboards + cost/minute tracking.
9. Compliance: consent flow, recording encryption, retention, PII redaction.
10. Dockerize; GPU pool if self-hosting STT/TTS; compose for local.
11. Terraform + EKS regional deployment + sticky sessions; autoscale on sessions.
12. ArgoCD + CI with latency-budget + WER eval gates.
13. Cost controls: self-host STT/TTS at volume, TTS caching, duration caps, kill switch.
14. Concurrent-session load test; tune capacity + regional pods; verify degradation.
15. Runbooks + final hardening pass.

---

## PACKAGE 8 — LLM Evaluation & Observability Platform

**1. Definition and target use cases.** A standalone offering to measure, monitor, and de-risk an LLM system (yours or a client's). Sells on its own because most teams ship GenAI blind. Use cases: eval harness + CI gate for a startup whose RAG silently regresses on every prompt change; production observability + cost/latency/spend dashboards + alerting for a team flying blind; A/B testing + drift/hallucination monitoring over an existing GenAI product.

**2. Frontend layer.** A dashboard is the product here: Next.js + a charting lib (Recharts/Tremor) for eval results, score trends, cost/latency/token dashboards, A/B comparisons, trace explorer, alert config. *Alt:* deploy self-hosted Langfuse/Phoenix UIs and build a thin custom layer on top rather than reinventing — recommend this unless the client needs bespoke views.

**3. Backend layer.** Baseline. Deltas: an **ingestion API** for traces/events (high write throughput) + an **eval-runner service** (batch + scheduled) + a **metrics/query API** for the dashboard. Async, queue-buffered ingestion (trace volume is high). Webhook/CI integration endpoints.

**4. AI/ML core.**
- **Eval frameworks:** **RAGAS** (RAG metrics: faithfulness, relevancy, context precision/recall) + **DeepEval** or **promptfoo** (general LLM eval, regression, CI-native) — default combination. *Alt:* custom metric harness when you need bespoke scoring.
- **LLM-as-judge:** for subjective quality at scale (with calibration against human labels to control judge bias) — default for open-ended outputs; pair with deterministic metrics where possible.
- **Observability core:** **Langfuse** (default — OSS, self-hostable, traces + eval + prompt mgmt in one) — *Alt:* Arize Phoenix (heavier eval/drift/embedding analysis), Helicone (proxy-based, simplest to bolt on), LangSmith (managed, LangChain-native).
- **Online eval:** sample production traffic, score live (groundedness, toxicity, drift), feed dashboards + alerts.
- **A/B + regression:** statistical comparison of prompt/model variants; regression detection vs a golden set in CI.

**5. Data layer.** Time-series/analytics store for traces + metrics: **ClickHouse** (default — what Langfuse uses, handles high-volume analytical queries) — *Alt:* TimescaleDB/Postgres at smaller scale. Postgres: eval configs, golden sets, A/B definitions. S3: raw trace archive, eval artifacts. Redis: ingestion buffer + cache.

**6. Infrastructure and deployment.** Baseline EKS. High-write ingestion path (buffer + batch into ClickHouse). Eval-runner workers (CPU; GPU only if self-hosting judge models) on queue/schedule. Self-host Langfuse + ClickHouse as a base, build custom layers around it. Multi-tenant if offering as a platform to multiple clients. Inference for judges: hosted APIs default.

**7. CI/CD and version control.** Baseline + **this package's whole point is being a CI gate** — ship a GitHub Action / CLI that runs eval suites and blocks merges on regression. Version golden eval sets + metric definitions + judge prompts (judges drift too). Promotion gated by the platform's own evals (dogfood).

**8. Observability.** It *is* the observability layer — but instrument the platform itself (meta-observability): ingestion lag, eval-runner throughput, judge cost, dashboard query latency, alert delivery. Standard OTel for the platform's own health.

**9. Security and compliance.** Handles the client's prompts/outputs/traces — often their most sensitive data + their users' PII. Strict tenant isolation, encryption, access control, PII redaction on ingestion, retention/deletion, data residency. Audit access to traces. If multi-tenant SaaS: hard isolation between clients. Don't let trace data leak to judge-model providers without approval.

**10. Scaling for millions of events.**
- Trace ingestion is the scale challenge (every LLM call = events): buffer (Redis/Kafka) → batch → ClickHouse; sample at high volume.
- Async eval (never block the client's request path).
- Pre-aggregate metrics for dashboards; partition by tenant/time.
- **Bottleneck checklist:** (1) Trace ingestion throughput → buffering + batching + sampling + ClickHouse scaling. (2) Dashboard query latency on big data → pre-aggregation + materialized views + time partitioning. (3) Eval-runner + judge cost on large suites → batch, cache judge results, cheaper judge models. (4) Storage growth → retention/tiering to S3. (5) Multi-tenant noisy-neighbor → per-tenant quotas + isolation.

**11. Cost controls.** Judge-model calls are the main cost — cache judge results, use cheaper judges, sample (don't eval 100% of prod traffic), batch eval runs. Trace-storage retention/tiering. Per-tenant cost metering (it's a platform). Spend alerts + caps on eval/judge usage.

**12. Testing and evaluation strategy.** Code: unit (metrics, scorers, aggregations), integration (ingest→store→query), e2e (run an eval suite end-to-end). Meta-eval: validate judge calibration against human labels; test metric correctness on known-good/known-bad fixtures. Load test ingestion throughput + dashboard query latency at target event volume.

**13. Reference project structure.**
```
llm-evalops/
├── apps/
│   ├── dashboard/           # Next.js: scores, cost, traces, A/B
│   ├── ingestion-api/       # high-throughput trace/event intake
│   ├── eval-runner/         # batch + scheduled eval workers
│   └── metrics-api/         # query API for dashboard
├── packages/
│   ├── evals/               # RAGAS/DeepEval/custom metrics, judges
│   ├── golden-sets/         # versioned eval datasets
│   ├── sdk/                 # client SDK + CI action/CLI
│   └── core/                # schemas, clients
├── infra/{terraform,k8s}/   # ClickHouse, buffer, workers
├── .github/workflows/       # incl. the shippable eval-gate action
├── tests/                   # unit, integration, e2e, meta-eval, load
└── docs/                    # metric defs, integration guide
```

**14. Production hardening checklist.** Ingestion buffered + batched + load-tested; ClickHouse scaled + retention/tiering; judge calibration validated; eval-gate CI action/CLI shipped + documented; golden sets + judge prompts versioned; dashboards pre-aggregated + fast; tenant isolation + encryption + PII redaction + residency; per-tenant quotas + cost metering; sampling at high volume; alerting on ingestion lag + regressions; runbooks for "ingestion backlog" and "judge cost spike."

**15. Transformation roadmap.**
1. Baseline: an offline eval script (RAGAS/DeepEval) over a golden set, results to console.
2. Stand up self-hosted Langfuse + ClickHouse as the trace/eval backbone.
3. Build a client SDK + tracing instrumentation (or use Langfuse SDK) to capture LLM calls.
4. Version golden eval sets + metric/judge definitions; baseline scores.
5. Ship the eval-gate as a GitHub Action/CLI that blocks on regression.
6. Buffered high-throughput ingestion API (Redis/Kafka → batch → ClickHouse).
7. Eval-runner workers: batch + scheduled online eval (sample prod, score live).
8. Dashboard: score trends, cost/latency/token, A/B comparison, trace explorer.
9. Drift + hallucination/groundedness monitoring + alerting.
10. Calibrate LLM-as-judge against human labels; meta-eval the metrics.
11. Multi-tenant isolation + encryption + PII redaction + residency.
12. Dockerize all services; Terraform + EKS + ClickHouse; ArgoCD.
13. CI for the platform (dogfood its own eval gate); version everything.
14. Cost controls: judge caching, sampling, cheaper judges, per-tenant metering + caps.
15. Load test ingestion + dashboard queries; pre-aggregate; runbooks + final hardening.

---

## Cross-Package Execution Notes

- **Build order that compounds:** do **Package 1 (RAG)** first — it teaches the whole production stack (eval, observability, caching, IaC, autoscaling) on the simplest core. Then **Package 8 (Eval/Observability)** — it forces eval/observability depth you'll reuse everywhere and is a sellable product on its own. Then **Package 2 (Agentic)** and **Package 6 (Microservice)**. Packages 3/4/5/7 are specializations to pick based on the client demand you actually see.
- **Reuse is real:** the baseline stack (FastAPI, Next.js, EKS, Terraform modules, CI/CD, Langfuse, security) is ~60% shared across packages. Build it once as templates; each new package is mostly the AI/ML-core + data + scaling deltas. This is what makes 10–15 production projects feasible in the timeline from `01-career-assessment.md`.
- **The honest gating reminder (from §8 of the career assessment):** these specs make you a *credible builder and a plausible operator*. Demonstrating them at small scale with synthetic load proves the patterns; it does not prove operation at millions-of-users scale with real traffic and on-call. Build to these specs anyway — they are exactly what makes the build/configuration ~80% claim true — and treat the operational ceiling as the thing a real production role later removes.

