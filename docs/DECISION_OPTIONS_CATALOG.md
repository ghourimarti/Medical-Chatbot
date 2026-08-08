# Production Options Catalog — the full menu behind each decision

> Companion to [DECISION_LOG.md](DECISION_LOG.md). For each of the 22 decisions: the realistic production option space, one line on *when that option is the right call*. **Bold = our pick.** A tool being absent from our pick is not a judgment — it's the NFRs choosing.

## D1 — Primary database
- **Postgres 16 (RDS / Aurora / Neon / Supabase)** — the default relational workhorse; JSONB covers document needs; pgvector unlocks D2. Right call ~80% of the time.
- MySQL / MariaDB — fine relational alternative; weaker AI-extension ecosystem (no pgvector peer).
- SQLite / Turso (libSQL) — embedded/edge; production-legit only for single-writer or read-replica edge apps.
- MongoDB Atlas — truly fluid schemas; Atlas Vector Search bundles vectors + docs in one.
- DynamoDB — serverless KV at any scale, ~$0 idle; demands access patterns known up front.
- Aurora Serverless v2 — Postgres-compatible autoscaling for spiky loads; min-ACU floor cost.
- CockroachDB / Yugabyte — distributed SQL; only when multi-region *writes* are real.
- Neo4j / Neptune — when relationships *are* the data (graph-RAG), not a system-of-record.

## D2 — Vector database
- **pgvector (+pgvectorscale)** — in-Postgres; right up to low-millions of vectors when you already run Postgres; SQL metadata filtering; one backup story.
- Qdrant — OSS default for a *dedicated* vector DB: native hybrid sparse+dense, payload filters, quantization.
- Weaviate — hybrid + built-in vectorizer modules; GraphQL-flavored API.
- Milvus / Zilliz Cloud — billion-scale, GPU indexes; heaviest ops footprint of the OSS set.
- Pinecone — fully managed serverless; zero ops, vendor lock + egress in exchange.
- Elasticsearch / OpenSearch k-NN — when you already run ELK: real BM25 + vectors in one engine.
- Redis (vector) — ultra-low-latency small indexes; pairs as cache+vector combo.
- Chroma — prototyping/dev; single-node ceiling.
- FAISS / hnswlib (in-process libraries) — batch/offline pipelines; no CRUD, filtering, or server story.
- LanceDB — embedded, S3-native columnar; offline/analytics RAG.
- Vespa — hybrid ranking at big-league scale; steep learning curve.
- Cloud-bundled: Vertex AI Vector Search, Azure AI Search, Bedrock Knowledge Bases — when you want the platform to own the RAG plumbing.

## D3 — RAG paradigm
- Naive RAG (embed → top-k → stuff) — demos only; where the demo/ code is today (k=1).
- **Advanced RAG** — hybrid retrieval + reranker + query condensation + no-answer thresholds + citations; the production default for corpus Q&A.
- Query-enhancement add-ons — HyDE, multi-query, decomposition, step-back, RAG-Fusion: each buys recall with latency+cost; enable per eval evidence.
- Parent-document / sentence-window retrieval — small chunks for matching, big windows for context.
- Graph RAG (Neo4j/Cypher) — relationship-heavy corpora (contracts, org charts); overkill for encyclopedia articles.
- Agentic / Corrective / Adaptive / Self-RAG — retrieval inside a reasoning loop; buys multi-hop quality, costs latency + determinism (vetoed by medical + TTFT).
- Long-context stuffing (no retrieval) — small stable corpus into a 1M-token model; simple but no citations granularity, cost scales with corpus.
- Fine-tune-the-knowledge (no retrieval) — wrong tool for citable, updatable knowledge.

## D4 — LLM provider & tiering
- Frontier APIs: OpenAI (4o/mini class), Anthropic (Sonnet/Haiku), Google Gemini (Pro/Flash) — quality ceiling, cost floor varies.
- **Open-weight hosted: Groq** (LPU speed king), Together, Fireworks, DeepInfra, OpenRouter (aggregator/fallback router).
- Cloud gateways: AWS Bedrock (guardrails + provisioned throughput), Azure OpenAI (enterprise compliance), Vertex AI.
- Self-host (vLLM/TGI on GPUs) — see D12 arithmetic; volume or residency plays only.
- Tiering patterns: single-model / **cheap-default-escalate (two-tier)** / learned routers (RouteLLM-style) / task-specialized fleet.
- Fallback patterns: same-provider retry → **cross-provider chain** → **cache-only degraded mode**.

## D5 — Embedding model
- Local open (CPU-friendly): **bge-small/base/large-en**, e5, gte, nomic-embed, all-MiniLM — free, private, self-hosted.
- Hosted: OpenAI text-embedding-3-small/large, Cohere embed v3, Voyage — quality + zero infra, per-token cost + data egress.
- Multilingual: bge-m3, multilingual-e5 — when language scope widens.
- Learned sparse: SPLADE — the "better BM25" for hybrid setups.
- Late-interaction: ColBERT — top retrieval quality, index-size and infra cost.
- Fine-tuned embeddings — when you have labeled query-doc pairs and a quality plateau to break.
- Matryoshka dims (MRL) — shrink dimensions for cost at small quality loss.

## D6 — Orchestration framework
- LangChain / LCEL — biggest integration surface; hot-path opacity is the tax.
- LangGraph — stateful graphs, checkpoints, HITL; the pick *when* flows are agentic (Package 2).
- LlamaIndex — best-in-class ingestion/retrieval primitives.
- Haystack 2 — production-lean pipeline DAGs, strong docs.
- Semantic Kernel — .NET/Microsoft shops. DSPy — prompt-optimization research lean.
- **Custom thin pipeline + SDKs (LangChain as component library)** — own the hot path; the senior default once the flow is understood.

## D7 — Backend language & framework
- **Python: FastAPI** (async, Pydantic, OpenAPI), Litestar (leaner core, less ecosystem), Django+DRF (batteries/admin), Flask (sync legacy).
- Node/TS: NestJS (structure), Fastify/Hono (speed), Express (inertia).
- Go: chi/Echo/Gin — gateway-grade throughput services.
- Rust: Axum — extreme perf, hiring cost.
- JVM: Spring Boot — enterprise integration plays.
- API styles: **REST + SSE**, WebSocket (bi-directional needs), GraphQL (aggregation UIs), tRPC (TS monorepos), gRPC (internal service mesh).

## D8 — Frontend & streaming UX
- **Next.js App Router** — React SSR/ISR default, Vercel-optimized, biggest hiring pool.
- Remix / React Router 7 — web-fundamentals purist alternative.
- SvelteKit / Nuxt — smaller bundles, smaller pools.
- Astro — content-first islands; docs/marketing sites.
- React SPA + Vite — no SSR needs, simplest ops (static bucket).
- HTMX + server templates — minimal-JS shops; genuinely production-legit.
- Streamlit/Gradio — internal tools ONLY (per spec).
- Streaming plumbing: **SSE + ReadableStream + AbortController**, WebSocket, or Vercel AI SDK (fastest DX if all-in on Vercel).

## D9 — Authentication & authorization
- Managed IDaaS: Clerk (DX speed), Auth0 (enterprise SSO breadth), WorkOS (SSO/SCIM for selling to enterprises), Supabase/Firebase Auth (BaaS bundles).
- AWS Cognito — cheap at scale, rough DX.
- Self-host OSS: Keycloak (full OIDC/SAML control), Ory, Authentik — when data-residency or cost at huge MAU.
- Library-level: Auth.js/NextAuth, fastapi-users — own your tables.
- **Patterns (our layer): anonymous server-side sessions + hashed API keys for admin**; OAuth2/OIDC when accounts arrive; Postgres RLS for multi-tenant rows; mTLS service-to-service.

## D10 — Caching
- Tools: **Redis** / Valkey (ElastiCache, Upstash, MemoryDB), Memcached (pure LRU), in-proc LRU (per-replica drift), CDN edge (CloudFront) for static+cacheable GETs.
- Layers: **exact/normalized response cache**, semantic cache (GPTCache pattern — **OFF-gated here**: medical near-miss risk), **query-embedding cache**, retrieved-context cache, provider-native prompt caching (Anthropic/OpenAI/Gemini — n/a Groq).
- Invalidation: TTL, **version-key composition** (bump prompt/index/model version), event-driven purge, stale-while-revalidate.

## D11 — Queue & async work
- Python task queues: **Celery** (industry default, prefork fits CPU-bound), Dramatiq, RQ (simplest), ARQ (async-native), Huey.
- Cloud-native: SQS (+Lambda), EventBridge — ops-free, localstack friction in dev.
- Brokers: RabbitMQ (routing semantics), **Redis** (already in stack), NATS.
- Kafka / Kinesis — event *streaming*, not task queues; wrong tool at 1 job/week (explicitly out of scope per Phase 1).
- Durable workflow engines: Temporal (code-as-workflow, heavy), AWS Step Functions (serverless orchestration), Airflow/Prefect/Dagster (batch DAG platforms — data-eng scale).

## D12 — Inference serving (if/when self-hosting)
- **Provider APIs (current pick — see D4)** — below break-even volume, this *is* the production choice.
- vLLM — self-host default: continuous batching, PagedAttention, multi-LoRA. The flip-trigger destination.
- SGLang — fastest structured-output/agentic serving; rising alternative to vLLM.
- TGI — HuggingFace-ecosystem fit.
- TensorRT-LLM + Triton — max NVIDIA performance, max engineering cost.
- Ray Serve — multi-model orchestration layer above the engines.
- Ollama / llama.cpp — dev machines and edge, not high-QPS prod.
- Managed self-host: SageMaker endpoints (real-time/async/serverless), Bedrock provisioned throughput, Modal/Baseten/Replicate/RunPod (GPU serverless — spiky workloads).

## D13 — Observability
- Instrumentation standard: **OpenTelemetry** — vendor-neutral; the only non-regrettable choice.
- Metrics: **Prometheus + Grafana** (+ Thanos/Mimir at scale), CloudWatch (AWS-native basics), Datadog/New Relic (excellent, $$$).
- Logs: **structured JSON → stdout** → Loki / CloudWatch Logs / ELK-OpenSearch (if already run).
- Traces: Tempo, Jaeger, AWS X-Ray.
- LLM-specific: **Langfuse** (OSS, self-hostable), LangSmith (managed, LC-native), Arize Phoenix (drift/eval-heavy), Helicone (proxy — fastest bolt-on), W&B Weave, Braintrust, OpenLLMetry (OTel semantics for LLMs).
- Errors: Sentry — cheap signal, common add-on.
- Alerting/on-call: Alertmanager, **Grafana alerts**, PagerDuty/Opsgenie (real rotations).

## D14 — Cloud provider & core services
- **AWS** — broadest service surface; your background; Bedrock for model gateway needs.
- Azure — the pick when the client runs Microsoft/Azure OpenAI compliance.
- GCP — Vertex AI + Cloud Run are genuinely excellent; strongest "simple serverless containers" story.
- GPU neoclouds: CoreWeave, Lambda Labs, RunPod — self-host training/serving cost plays.
- PaaS: Fly.io, Railway, Render — solo-dev speed; fine for side revenue, thin enterprise story.
- EU-sovereign/cost kings: Hetzner/OVH + k3s — half the price, all the ops.

## D15 — Containers, orchestration, IaC
- Managed K8s: EKS / GKE / AKS — the enterprise default; control-plane + node cost floor.
- **ECS Fargate** — AWS-native containers without K8s tax; the mid-market workhorse.
- Cloud Run (GCP) / App Runner (AWS) — scale-to-zero containers; App Runner is the weaker sibling.
- EC2/VM + compose, k3s on VMs — cheapest real deployments; no managed-orchestration story.
- Nomad — HashiCorp shops.
- K8s tooling: **Helm** (templating, portfolio-legible) vs Kustomize (patch-based purity); **ArgoCD** vs Flux (GitOps); KEDA (event-driven autoscale).
- IaC: **Terraform** / OpenTofu (license-fork), Pulumi (real languages), AWS CDK (AWS-native TS/Python), CloudFormation (raw), Crossplane (K8s-native control plane).
- Image discipline: **multi-stage, non-root**, distroless/Chainguard bases, SBOM (Syft), signing (cosign).

## D16 — CI/CD
- **GitHub Actions** — market default, free public-repo minutes, OIDC-native.
- GitLab CI — best if repo lives there; Jenkins — self-hosted control, ops burden (already evidenced in demo/); CircleCI/Buildkite — scale/hybrid-runner plays; Azure DevOps — MS shops.
- CD patterns: push-deploy, **GitOps (ArgoCD — EKS window)**, progressive delivery (Argo Rollouts/Flagger canaries), blue/green.
- Quality gates: unit/integration, **blocking eval gate (RAGAS)**, image scan (**Trivy**/Grype/Snyk), SAST (Semgrep/CodeQL), secrets (gitleaks/trufflehog), license checks.

## D17 — Secrets & configuration
- **AWS SSM Parameter Store** (free tier, SecureString) vs Secrets Manager (rotation lambdas, $0.40/secret/mo) vs HashiCorp Vault (dynamic secrets, enterprise-grade, ops-heavy) vs Doppler/Infisical (SaaS DX) vs SOPS+age (encrypted-in-git GitOps fit).
- K8s bridges: External Secrets Operator, Sealed Secrets.
- CI identity: **OIDC federation (zero long-lived keys)** vs stored cloud keys (the anti-pattern).
- App config: **pydantic-settings/env-vars (12-factor)**; feature flags via AppConfig/LaunchDarkly/Unleash when flag volume justifies.

## D18 — Security posture (the toolbox)
- LLM guardrails: **instruction-hierarchy prompting + output-must-cite + toolless design (ours)**; Llama Guard, Bedrock Guardrails, NeMo Guardrails, Guardrails AI (schema enforcement); moderation APIs.
- Injection defense: input canonicalization, retrieved-text-as-data framing, allowlists, red-team suites (Garak, Microsoft PyRIT).
- PII: Presidio (OSS detection/redaction), AWS Comprehend/Macie.
- AppSec: WAF, rate limiting, mTLS/service mesh (Istio/Linkerd), CSP, RFC 7807 error envelopes.
- Supply chain: **Trivy, pip-audit, gitleaks, Dependabot**, SBOM + cosign signing.
- Frameworks to think with: **OWASP LLM Top 10**, MITRE ATLAS, STRIDE.

## D19 — Evaluation
- RAG-specific: **RAGAS**, TruLens, DeepEval (pytest-style asserts), Phoenix evals.
- Prompt regression/CI: **promptfoo** (noted; our gate is RAGAS+pytest), Braintrust, LangSmith datasets, OpenAI Evals, Inspect (UK AISI).
- **LLM-as-judge + human calibration (ours: Groq-70B judge, agreement reported)** — always pair with deterministic metrics.
- Adversarial/red-team: Garak, PyRIT, **hand-rolled medical safety suite (ours)**.
- Online: **trace sampling + thumbs feedback + drift alerts**; true A/B needs traffic volume (honestly deferred).

## D20 — Cost controls
- LLM gateways with budget enforcement: LiteLLM proxy (keys/budgets/routing — the consolidation path if providers multiply), Portkey, Helicone, Kong AI Gateway.
- **App-level (ours): token budgets, session quotas, daily-spend circuit breaker → CACHE_ONLY_MODE, kill switch.**
- Model-side: routing/tiering, caching, output caps, prompt compression (LLMLingua), provider batch APIs (~50% off for offline jobs).
- Infra: **billing alarms**, Cost Explorer + tagging discipline, Kubecost (K8s), Infracost (cost-diff in PRs), Savings Plans/Spot (steady/interruptible only).

## D21 — Failure modes & degradation
- Resilience patterns: retries + jittered backoff, timeouts everywhere, **circuit breakers** (tenacity/pybreaker), bulkheads, load shedding, queue-and-drain, **explicit degraded modes (cache-only, honest don't-know)**, health/readiness probes.
- Chaos: **manual drills (ours: kill provider/Redis/Postgres)**, Litmus (K8s), AWS FIS.
- DR ladder: backup/restore → pilot light → warm standby → multi-region active-active — each rung 10× the cost; **we buy rung 1 + documented RTO/RPO**.

## D22 — Repo structure & packaging
- **Monorepo (uv workspace)** — team-of-1 default; Nx/Turborepo (JS-heavy monorepos), Bazel/Pants (mega-scale).
- Polyrepo — team-boundary alignment at org scale; hybrid (infra split out) — common middle.
- Python packaging: **uv** (fast, lockfile, workspace), Poetry, PDM, Hatch, pip-tools.
- Layout patterns: **apps/ + packages/ split (ours)**, src-layout, single-app flat.
