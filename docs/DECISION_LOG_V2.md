# Decision Log v2 — P5 Medical RAG Chatbot (10M-MAU revision)

> **Status: DRAFT v2.1 — sign-off revisions applied (user pushback on D4/D5/D6/D12), awaiting final lock.** Supersedes [DECISION_LOG.md](DECISION_LOG.md) (v1, 100k-MAU) after the Phase-1 scale revision. **v1 is preserved untouched** — same system at two scales is itself a portfolio artifact: watch which answers flip and which survive.
> Full option landscape per decision: [DECISION_OPTIONS_CATALOG.md](DECISION_OPTIONS_CATALOG.md) (bolds there reflect v1 picks; v2 divergences are listed below).
>
> **Phase 1 v2 anchors:** 10M MAU / 1.5M DAU / 4.5M queries-day / **350 RPS peak** (500 burst, 700 autoscale ceiling) / **~2,100 concurrent SSE streams** / TTFT p50 800ms, p95 2.0s / retrieval p95 250ms / cached p95 200ms / **SLO 99.9%** (error budget 43.8 min/mo — 2 min of 500s at peak ≈ the whole month) / LLM ≤$0.0005/q, blended ≤$0.001/q / ≤$25k/mo full load / portfolio deploy: ≤$50/mo idle (kind local), ≤$200 burst (ephemeral EKS) / GDPR-real, **no PHI** / us-east-1 multi-AZ / team of 1 / corpus ≤100k chunks — **read-heavy, tiny-write**.

---

## What changed v1 → v2 (the flip list)

| D# | v1 pick (100k MAU) | v2 pick (10M MAU) | What forced the flip |
|---|---|---|---|
| D2 | pgvector in Postgres | **Qdrant, 3-replica StatefulSet** | 350 RPS reads contend with the primary DB; independent read-scaling + native hybrid |
| D4 | Fallback = OpenAI-mini "if key present" | **Mandatory chain: Groq → Bedrock → cache-only** + breakers + quota procurement | 99.9%: a sole-provider outage burns the month's error budget in ~2 min |
| D9 | Hashed static API keys for admin | **Cognito OIDC for humans; IRSA for services** | GDPR-real audit posture; admin is a real privileged surface at this exposure |
| D10 | Semantic cache ships OFF | **ON behind double guard** (cosine ≥0.97 ∧ identical top-3 chunk IDs ∧ eval zero-false-hit proof) | It's now a ~$4–6k/mo lever — worth engineering the safety case v1 only documented |
| D11 | Celery + Redis broker | **SQS + DLQ + KEDA-scaled workers** | Durable queue + DLQ + queue-depth autoscaling on the now-justified EKS platform |
| D13 | Free-tier Grafana Cloud / Langfuse Cloud | **Self-hosted Prom+Grafana+Loki+Langfuse with sampling** (1–5% head, 100% errors/slow tail) | 4.5M traces/day makes observability its own cost center; sampling is the control |
| D15 | ECS-steady + ephemeral EKS "window" | **EKS multi-AZ as THE platform** (kind local daily; ephemeral staging windows for wallet) | 350 RPS autoscaling, PDBs, KEDA, IRSA — scale now justifies what the $30 ceiling vetoed |
| D17 | SSM SecureString + quarterly manual rotation | **Secrets Manager + External Secrets Operator, managed rotation** | Rotation + audit trail stop being optional at GDPR-real; $0.40/secret is noise vs $25k/mo |
| D18 | WAF deferred | **CloudFront + AWS WAF + bot control un-deferred** | Anonymous × 10M ⇒ abuse is statistical certainty, and it attacks the *cost* NFR directly |
| D22 | apps: api / worker / web | + **apps/ml-service** (embedding + reranker, CPU pods) | CPU-bound embed/rerank must leave the async event loop and scale independently |

**Survivors (re-anchored, not flipped):** D1 Postgres (now Multi-AZ + day-partitioned), D3 Advanced RAG, D7 FastAPI+SSE, D8 Next.js, D14 AWS, D16 GitHub Actions (+ Argo Rollouts canary now), D19 eval-before-refactor, D20 enforced cost controls, D21 degradation ladder.

---

## Sign-off revisions v2 → v2.1 (user pushback, accepted with corrections)

| D# | v2 draft | v2.1 locked direction | Driver | Senior correction applied |
|---|---|---|---|---|
| D4 | Hosted tiered (Groq→Bedrock) | **Self-hosted Llama-3.1-8B (vLLM) default; hosted 70B-class escalation; hosted leg retained as outage fallback** | Gap-closure (#1: serving) + privacy: health queries never leave the box | Escalation/fallback stays hosted — self-hosting 70B is GPU-indefensible, and 99.9% needs an infra-independent leg |
| D5 | bge-small (384d) | **bge-large-en-v1.5 (1024d)** | Maximum retrieval quality | Latency mitigation (ONNX int8 → GPU option) + baseline eval vs bge-small + documented flip-down trigger |
| D6 | Custom thin pipeline | **LCEL composition — self-authored runnables only** | LangChain fluency = market signal; Langfuse LC-callback tracing ≈ free | Constraint: prebuilt chains banned (RetrievalQA-class opacity is how demo's `k=1` shipped); span-per-stage stays mandatory |
| D12 | Hosted APIs behind seam | **vLLM primary + SGLang second engine (benchmark + engine failover); hosted = outage leg** | Both engines = maximum exposure; benchmark = portfolio artifact | **Failure-domain fix:** SGLang shares vLLM's GPU pool/cluster — it is NOT outage protection; the hosted leg is |

---

## Decision dependency graph (unchanged from v1 — the *logic* of the order survives scale)

```
Tier 0  Phase 1 v2 NFRs (constraints — everything cites these)
Tier 1  STATE & PARADIGM (hardest to reverse)
        D3 RAG paradigm ── D1 primary DB ── D5 embedding model ⇄ D2 vector DB
        (D5's dimension bakes into D2's collection schema — coupled, one gate)
Tier 2  ENGINES        D4 LLM/tiering → D12 serving   ·   D3 → D6 orchestration
Tier 3  APP SHELL      D6 → D7 backend → D8 frontend, D9 auth · D1/D4 → D10 cache → D11 queue
Tier 4  PLATFORM       D14 cloud → D15 containers/IaC → D16 CI/CD, D17 secrets
Tier 5  CROSS-CUTTING  D13 obs, D18 security, D19 eval, D20 cost, D21 failure, D22 repo
```

- **Deliberation budget shifted in v2:** scale is a Tier-0 input, so D2 and D15 — cheap calls in v1 — got re-deliberated. The graph didn't change; the *inputs* did. That's the lesson: decision structure is stable, decisions aren't.
- **Decision order ≠ build order.** D19 (eval) is decided 19th, built ~first in Phase 4 — baseline before refactor. D22 decided last, used first.
- **Gate for every entry:** reasoning must cite an NFR or an upstream decision, or it's taste — rejected.

---

## Decision 1: Primary database
**Question:** System-of-record for sessions, chat history (now **4.5M msg-pairs/day**), audit, ingestion-job state.
**Options:** SQLite (N — single-writer) · **Postgres 16 (RDS Multi-AZ)** · MySQL (no pgvector-class ecosystem; weaker JSONB/partitioning ergonomics) · MongoDB (no strength PG lacks here) · DynamoDB (Y-capable: serverless write scale, TTL retention — loses on relational audit queries + local-dev parity + access-pattern lock-in).
**Decision:** **Postgres 16 on RDS Multi-AZ** (SQLAlchemy 2 async + Alembic). Chat history **partitioned by day**; GDPR 30-day retention = nightly `DROP PARTITION` — deletion that is provable, fast, and vacuum-free. Aurora named as the growth path.
**Reasoning:** Peak write load ≈ 350 inserts/sec of small rows — comfortably inside vanilla Postgres. Relational queries needed for audit/compliance. One engine, solo ops.
**Trade-offs:** Partition discipline is ours; write 10× ⇒ Aurora or KV split for history.
**Reversibility:** Hard (data gravity). Flip-trigger: sustained write p95 >20ms or partition ops pain.

## Decision 2: Vector database *(FLIPPED from v1 pgvector)*
**Question:** What serves hybrid retrieval at **350 RPS reads** over ~100k chunks at 99.9%?
**Options:** pgvector (v1 pick — right at ≤50 RPS; at 350 RPS ANN+FTS contends with the system-of-record and couples read-scaling to RDS) · **Qdrant self-hosted** · Pinecone (per-query pricing ≈ $1k+/mo at this volume; no self-host story) · OpenSearch (real BM25, but JVM cluster or ~$700+/mo managed — heavy for 100k chunks) · Milvus (etcd+MinIO sprawl — built for billions, absurd here) · FAISS (current demo/ — in-process, no replication/filtering: fails availability structurally) · Chroma (dev-grade).
**Decision:** **Qdrant, 3-replica StatefulSet on EKS** (snapshots to S3; Qdrant Cloud as managed fallback), behind the same `VectorStorePort` interface v1 defined. Native hybrid (dense+sparse) + payload filtering + replication.
**Reasoning:** The scale pressure is **read throughput, not corpus size** — replicas answer it directly; per-query fees don't survive 350 RPS; keeping retrieval load off the primary DB protects D1's write path. Gap-fill: operating a stateful service on K8s is a named audit gap.
**Trade-offs:** We operate it (backups, upgrades); sparse quality slightly below OpenSearch BM25 (eval verifies adequacy).
**Reversibility:** Moderate — port seam + 100k-chunk re-index ≈ minutes. **Flip-DOWN trigger:** if real load ≤50 RPS, pgvector is the better call (v1 was not wrong — it answered different numbers).

## Decision 3: RAG paradigm *(survives)*
**Question:** Naive (current `k=1`), advanced, or agentic — for grounded medical Q&A.
**Options:** Naive (N — coin-flip retrieval on a medical corpus) · **Advanced RAG** · Agentic/corrective loops (N at runtime — N× LLM calls kill TTFT p95 2.0s *and* $0.0005/q at 350 RPS; encyclopedia Q&A is single-hop) · long-context stuffing (no citation granularity; cost scales with corpus).
**Decision:** **Advanced RAG:** condense (conversation-aware) → hybrid retrieve top-20 → cross-encoder rerank → top-4 token-budgeted context with citations → no-answer threshold → single streamed generation. HyDE/multi-query remain eval-gated flags, OFF (latency).
**Reasoning:** Serves faithfulness ≥0.85 + TTFT + unit cost simultaneously; determinism is a medical-domain requirement, not a preference.
**Trade-offs:** Multi-hop questions underserved — measured in eval, documented limitation.
**Reversibility:** Easy — composable stages.

## Decision 4: LLM provider & tiering *(REVISED v2.1 — user pushback: self-host primary)*
**Question:** Which models answer, and what happens when they fail — at 350 RPS and 99.9%.
**Options:** hosted tiered multi-provider (v2 draft pick — cheapest ops, weakest privacy story) · OpenAI/Anthropic direct · Bedrock-only · **self-hosted 8B default + hosted escalation & fallback** · fully self-hosted incl. 70B (N — 70B needs 2–4× A100/H100-class ≈ $15–30k/mo before traffic; indefensible).
**Decision:** **Default: self-hosted `Llama-3.1-8B-Instruct` on vLLM** (AWQ/FP8-quantized, L4/A10G class; weights pinned to a HF snapshot hash, mirrored to S3). **Escalation tier (hosted):** Groq 70B / Bedrock Claude Haiku for low-retrieval-confidence or long/complex queries. **Failure chain (failure-domain-honest):** vLLM → SGLang (engine-level failover, same pool — D12) → **hosted leg (Groq/Bedrock — the infra-independent outage leg)** → cache serve → degraded banner. Per-leg circuit breakers; model IDs + weights config-pinned; prompts harmonized + eval'd per leg.
**Reasoning:** (1) **User directive under operating principle 11** — inference serving is the #1 unclosed audit gap; this project is where it closes. (2) **The medical vertical genuinely strengthens self-hosting:** the primary path keeps health queries entirely in-box — "your health questions never leave our infrastructure" is a product differentiator, and the GDPR/DPA burden shrinks to the escalated/fallback minority (documented). (3) **Economics stated honestly:** portfolio scale ⇒ a 24/7 GPU is ~$260–700/mo, mitigated by scale-to-zero + spot + ephemeral windows; 10M-MAU design scale ⇒ fleet ≈ $15–40k/mo vs ~$17k hosted — **a premium, accepted and named**, bought for privacy + control + skill demonstration, not hidden behind fake savings claims.
**Trade-offs:** GPU fleet ops land on a team of 1 (pedagogically the point — operationally the risk, named); TTFT now depends on our batch/queue tuning, not a provider SLA; hosted legs still need DPA for the queries they see.
**Reversibility:** Easy — the adapter seam makes hosted-primary a config flip. **Flip-back triggers:** GPU spend >1.5× hosted-equivalent for 2 consecutive months, TTFT p95 >2.0s at load after tuning, or ops burden displacing feature work.

## Decision 4b: Serving venue strategy
**Question:** Where does the self-hosted model actually run — and can more than one venue be live at once?
**Context:** D12 v2.1 picked the *engines* (vLLM primary, SGLang second) but assumed a single GPU venue. Recon found a local RTX 3060 (12GB, compute 8.6, Docker GPU passthrough already configured), while AWS G-instance quotas need 24–48h human approval — making a single-venue choice both premature and unnecessarily limiting. **Correction (later in the same spike):** the local card was then found unable to run vLLM at all under WSL2 — see below, this reshapes the table.
**Options:** single venue (v2.1 assumption — simplest, but couples all serving to one failure domain) · local-only ($0, but consumer card, not production-representative — and, as it turned out, not viable at all) · cloud-only (representative, but metered and quota-gated, and painful for the 50-restart debugging S13 needs) · **multi-venue with config-selected primary + ordered failover**.
**Decision:** **Multi-venue.** All venues expose an **OpenAI-compatible API**, so one `OpenAICompatModel` adapter with a configurable `base_url` serves every one of them behind the existing `ModelPort` seam:

| Venue | Failure domain | Role | Cost |
|---|---|---|---|
| `local` | Developer machine (RTX 3060, WSL2) | ❌ **not a serving venue** — vLLM's V1 engine cannot initialize under WSL2 (`UVA is not available`; `docs/gpu-venue.md` §3 — a platform wall, not a tuning knob). Excluded from `SERVING_FALLBACK_CHAIN` entirely; the card is repurposed for S5/S6 embedder/reranker GPU work instead | $0 (unused for serving) |
| `runpod` | Third-party GPU cloud (L4/A10) | **primary** — dev iteration *and* production-representative serving (local can no longer carry the free-iteration role) | ~$0.40–0.80/hr |
| `aws` | AWS us-east-1 (g6 spot) | AWS-depth gap closure; Terraform target | ~$0.50–0.80/hr |
| `groq` | Hosted API | Always-available floor | per-token |

Config: `SERVING_PRIMARY` defaults to `runpod` (not `local`); `SERVING_FALLBACK_CHAIN` is the ordered failover list over `runpod`/`aws`/`groq`; per-venue `VLLM_{RUNPOD,AWS}_URL`. Circuit breaker + health check per leg.
**Reasoning:** **This corrects a real weakness in v2.1.** The recorded senior correction on D12 was that SGLang cannot be outage protection because it shares vLLM's GPU pool and failure domain. Multi-venue supplies what that chain lacked: **three genuinely independent failure domains** — that claim survives local's removal, since `runpod`/`aws`/`groq` are still three unrelated infrastructures. It also resolves the sequencing conflict for the *cloud* legs — RunPod gives quota-free iteration now, AWS gives the Terraform-matching benchmark once quota lands — instead of forcing a choice between them. Marginal cost is low because the port seam already exists.
**Trade-offs accepted:** larger config surface; **eval must run per-leg** (already required by D4 — venues may differ in quantization, so answers can drift); TTFT budgets are per-venue (network adds 50–200ms on cloud legs); ~+0.5 session in S13; **S13 dev iteration is no longer free** — the original "$0 local debugging" premise is gone, so the earliest rented GPU session now absorbs that role and its cost.
**Reversibility:** Easy — set `SERVING_FALLBACK_CHAIN` to a single venue and it degenerates to the v2.1 design.

## Decision 5: Embedding model *(REVISED v2.1 — user pushback: bge-large)*
**Question:** Which embedding model — baked into D2's collection *and* on the hot path at 350 RPS.
**Options:** MiniLM (mediocre) · bge-small-en-v1.5 (v2 draft — MiniLM speed class, quality ↑ free) · **bge-large-en-v1.5 (1024d)** · OpenAI/Cohere APIs (N — hot-path coupling, and queries would leave the box: doubly wrong given D4's privacy story) · fine-tuned embeddings (no labeled pairs — No).
**Decision:** **bge-large-en-v1.5 (1024-dim), served from `apps/ml-service`.** Serving plan: ONNX int8 on CPU pods first (~15–40ms/query); if retrieval p95 breaks 250ms at load, move embedding to the GPU pool with strict isolation from vLLM (no contention with generation). `embedding_version` in collection metadata; re-embed pipeline (100k chunks ≈ ~1 hr CPU / minutes GPU).
**Reasoning:** User directive: maximum retrieval quality. Cost check at this corpus: vector memory 100k × 1024d × 4B ≈ **0.4 GB — trivial**; the only real price is hot-path compute (335M vs 33M params ≈ ~10×), carried by ml-service scaling. **Eval checkpoint retained (senior correction):** the D19 baseline indexes bge-small *and* bge-large side-by-side (re-index is cheap) — if large's lift is <~2 points on golden-set retrieval metrics, the latency bought nothing and the flip-down is recorded as measured evidence, not opinion.
**⚠ DECISION GATE (updated):** dimension **1024** freezes before the first Qdrant collection is created.
**Trade-offs:** ~3–8× hot-path embedding compute; slightly higher Qdrant RAM per replica; expected lift is modest because the reranker already recovers much of small-model retrieval error.
**Reversibility:** Moderate — version column + small corpus; flip-down to bge-small = re-index + config change.

## Decision 6: Orchestration framework *(REVISED v2.1 — user pushback: LCEL)*
**Options:** LangChain prebuilt chains (current `RetrievalQA` — deprecated, opaque: N) · custom thin pipeline (v2 draft — maximum control, zero framework tax) · **LCEL over self-authored runnables** · LlamaIndex (second framework) · LangGraph (no graph to run — D3).
**Decision:** **LCEL as the composition layer — under three binding constraints:** (1) **every stage is a self-authored async function** (`condense → embed → retrieve → fuse → rerank → build_context → generate`) wrapped as `RunnableLambda`/custom `Runnable`, Pydantic contracts between stages; (2) **prebuilt chains are banned** (`RetrievalQA`-class opacity is exactly how demo's `k=1` shipped unexamined) — enforced by a lint rule blocking those imports; (3) **span-per-stage stays mandatory** — Langfuse's native LangChain callback handler + OTel spans; streaming via `astream_events` v2 → SSE.
**Reasoning:** User directive, plus two honest points in LCEL's favor: Langfuse's LC integration makes tracing nearly free (cheaper than hand-wiring callbacks), and LCEL fluency is a named market signal in your positioning docs. The v2-draft objection (hot-path opacity) is neutralized by the constraints: LCEL supplies `|`-composition, batching, and streaming plumbing — never hidden logic.
**Trade-offs:** `langchain-core` version churn (pinned + Renovate); latency debugging through runnable indirection is one layer worse than plain functions.
**Reversibility:** Easy — constraint (1) makes unwrapping to plain functions mechanical.

## Decision 7: Backend *(survives — re-anchored to concurrency)*
**Options:** Flask (N — sync WSGI: 2,100 concurrent SSE streams ⇒ 2,100 workers; architecturally dead) · **FastAPI** · Litestar (fine, no marginal win, off-inventory) · Node/Go (wrong language for the ML glue, team of 1).
**Decision:** **FastAPI + uvicorn (ASGI)**, REST `/api/v1/*` + SSE streaming; Pydantic v2 at every boundary; lifespan singletons (kills demo's rebuild-chain-per-request); strict async discipline — all I/O async, CPU-bound work lives in `apps/ml-service`.
**Reasoning:** **~2,100 concurrent open streams at peak** is the binding NFR — ASGI holds thousands of streams per pod; sync Flask cannot. SSE over WebSocket: one-way flow, simpler at every hop (LB, CDN, client).
**Reversibility:** Moderate — the API contract is the stable boundary.

## Decision 8: Frontend & streaming UX *(survives)*
**Options:** Jinja SSR (N — no streaming/cancel/citations) · HTMX+SSE (production-legit, weak rich-client state + portfolio signal) · **Next.js App Router (TS, Tailwind, shadcn/ui)** · Vite SPA (no SSR) · Streamlit (barred client-facing).
**Decision:** **Next.js**: fetch + ReadableStream SSE consumption, **AbortController** stop button, token-by-token render, citation chips with source popovers, disclaimer banner, degraded/no-answer states. Deployed as a container behind CloudFront — at this posture the frontend rides our infra, not Vercel.
**Reasoning:** Streaming UX *is* the perceived-latency NFR; citations are a functional requirement; inventory-known and the strongest hiring signal of the frontend options.
**Reversibility:** Easy — API is the contract.

## Decision 9: Authentication & authorization *(admin leg FLIPPED)*
**Options:** none (N) · **anonymous server-side sessions + OIDC-gated admin** · Clerk/Auth0 accounts (out of scope v1; Clerk = documented v2 seam) · Cognito user accounts (same scope objection).
**Decision:** **Anonymous signed sessions** (HTTP-only SameSite cookie, Redis-backed, stable secret from Secrets Manager — kills the `os.urandom(24)` restart bug) + per-session/per-IP quotas. **Admin/ops surfaces (`/admin/*`, Grafana, ArgoCD) behind Cognito OIDC; service-to-service via IRSA** (no static keys).
**Reasoning:** Quotas + GDPR deletion need an identity *handle*, not a signup wall (funnel-killer for anonymous health queries); at 10M-exposure the privileged surfaces get real federated auth + audit — hashed static keys (v1) don't rotate or attribute.
**Reversibility:** Easy — session middleware is where accounts plug in later.

## Decision 10: Caching *(semantic layer FLIPPED ON, guarded)*
**Options:** none (N — leaves the biggest cost lever unpulled) · exact-only (safe, ~5–10% hits on paraphrase-heavy health queries) · **exact + guarded-semantic + embedding cache on Redis (ElastiCache Multi-AZ)** · Memcached/in-proc (no vector ops / replica drift) · + provider prompt caching (n/a on Groq; applies on Bedrock legs).
**Decision:** Four layers: **(1) exact/normalized response cache** (TTL 24h; key = `sha256(normalized_query + prompt_v + index_v + model_id)`); **(2) semantic cache ON** — guard: cosine ≥0.97 **and** identical top-3 retrieved chunk IDs **and** only high-confidence, non-refusal, PII-free answers; promoted from v1's OFF only because the eval suite can now *prove* zero false hits on golden+adversarial sets before enablement; **(3) query-embedding cache**; **(4) CloudFront edge** for static + cacheable GETs. Invalidation stays version-key composition — bump a version, old entries go cold; no manual purges.
**Reasoning:** Projected 25–35% combined hit rate ≈ **$4–6k/mo** at full load + cached p95 200ms NFR. The medical rule survives: *correctness outranks hit rate* — hence the double guard, and refusals/low-confidence answers are never cached.
**Trade-offs:** Threshold-tuning burden; hit rate deliberately left on the table.
**Reversibility:** Easy — cache-aside; deleting the layer breaks nothing but the bill.

## Decision 11: Queue & async work *(FLIPPED from Celery)*
**Options:** FastAPI BackgroundTasks (N — dies with pod) · Celery+Redis (v1 pick — known, prefork; loses on broker-shares-cache blast radius + no DLQ story) · ARQ (async loop poor fit for CPU-bound embed) · **SQS + DLQ + KEDA-scaled worker** · Kafka/Kinesis (streaming machinery at 1 PDF/week — vetoed, resume-driven) · Temporal/Step Functions (workflow engines without a workflow).
**Decision:** **SQS (+DLQ) + plain async worker pods, KEDA-scaled on queue depth.** Tasks idempotent (content-hash keyed); **index alias swaps only on completed ingestion** — half-ingested corpora never serve (carried from v1 D21). LocalStack shims local dev.
**Reasoning:** Durable buffer + DLQ + **queue-depth autoscaling is the Package-1 signature pattern** on the platform D15 now justifies; SQS is ops-free where Celery adds a broker to babysit. Volume is tiny — managed-and-boring wins.
**Trade-offs:** LocalStack friction locally.
**Reversibility:** Easy — thin task seam.

## Decision 12: Inference serving *(REVISED v2.1 — user pushback: vLLM + SGLang)*
**Question:** How the self-hosted default model is served — and what each engine is *for*.
**The v2 fleet arithmetic (carried, still honest):** demand = 4.5M q/day ≈ avg 15.6k output tok/s, **peak 105k tok/s**. vLLM Llama-8B ≈ 1.5–2.5k tok/s per A10G/L4 ⇒ peak-provisioned ~50 GPUs ≈ $35–40k/mo; realistic autoscaled fleet ~20–30 ≈ $15–25k/mo vs hosted ≈ $17k/mo — the premium is owned by D4's reasoning (privacy + control + gap closure).
**Options:** hosted APIs (v2 draft pick — retained as the *outage leg*) · **vLLM** · **SGLang** · TGI (no edge over either here) · TensorRT-LLM/Triton (max perf, max engineering — flip destination at real fleet scale) · SageMaker endpoints (managed premium that hides exactly the ops being learned).
**Decision:** **vLLM = primary engine** — continuous batching, PagedAttention, AWQ/FP8 quant, **prefix caching ON** (the system prompt is shared by every request). **SGLang = second engine with two explicit jobs:** (1) **benchmarked alternative** — same model, same GPU class, k6-driven comparison (tokens/s, TTFT, p95-under-concurrency, structured-output speed) published as a portfolio artifact; (2) **engine-level failover** behind the same adapter (covers engine bugs/OOM regressions). **Senior correction, recorded:** SGLang shares vLLM's failure domain — same GPU pool, same cluster, same weights — so it is **not** outage protection; infra-independent protection is the hosted leg. Deployment: EKS GPU node group, one engine live + one warm-or-zero per env; DCGM + engine metrics; HPA on queue depth/GPU utilization.
**Reasoning:** User directive — run both engines to close the serving gap completely. Legitimate, and the benchmark converts "I deployed two engines" into *measured evidence* ("vLLM vs SGLang at 8B on L4, here are my numbers"), which is interview gold per your positioning docs.
**Trade-offs:** Two serving stacks to patch; benchmark honesty needs identical conditions (documented harness); GPU capacity planning is now ours — Little's Law sizing lands in Phase 3.
**Reversibility:** Easy — both engines sit behind one adapter; hosted-primary remains a config flip.

## Decision 13: Observability *(FLIPPED to self-hosted + sampling)*
**Options:** CloudWatch-only (partial) · Datadog (excellent, ~$2–5k+/mo at this cardinality — vetoed by cost NFR) · ELK (JVM ops solo) · LangSmith/managed-LLM-obs (per-trace pricing × 4.5M/day + data egress vs GDPR) · **OTel → self-hosted Prometheus + Grafana + Loki + Alertmanager + Langfuse (ClickHouse-backed)**.
**Decision:** **OTel SDK, span per pipeline stage** (attrs: TTFT, tokens, cost, cache-hit, no-answer, refusal, scores) → self-hosted stack on EKS. **Sampling policy: 1–5% head-sample + 100% tail-sample of errors and >p95-slow requests.** `structlog` JSON → stdout → Loki; **no raw query text in logs**. Alerts: **SLO burn-rate (fast 14.4×/1h, slow 6×/6h)**, TTFT p95 breach, no-answer-rate spike (cheapest retrieval-regression proxy), spend thresholds → Alertmanager → Slack. Dev = compose profile of the same stack. **GPU plane (v2.1):** DCGM exporter → GPU utilization/memory dashboards; vLLM/SGLang engine metrics (tokens/s, TTFT, running/waiting batch depth, KV-cache utilization) become first-class SLO inputs alongside the RED metrics.
**Reasoning:** 99.9% is unenforceable without burn-rate alerting; 4.5M traces/day at 100% sampling makes observability its own cost center (Phase-1 flip row 8) — sampling keeps it ≤~2% of infra spend; per-query cost attribution feeds D20.
**Reversibility:** Easy-moderate — OTel is vendor-neutral by design; that's why it's first.

## Decision 14: Cloud & core services *(survives, hardened)*
**Options:** AWS · Azure (Document Intelligence genuinely best-in-class — not needed, Gale PDFs are clean text) · GCP (no differentiator here) · PaaS/neoclouds (thin enterprise story).
**Decision:** **AWS us-east-1, multi-AZ**: EKS · RDS Postgres Multi-AZ · ElastiCache Redis Multi-AZ · S3 (corpus, artifacts, TF state) · SQS+DLQ · **CloudFront + AWS WAF** (edge, TLS, bot rules — un-deferred per D18) · Secrets Manager · ECR · Route 53 · Cognito · Bedrock (D4 fallback). NAT is permanent in the prod design; portfolio envs remain ephemeral (`terraform destroy` discipline).
**Reasoning:** Your AWS-depth strategy + boring-managed-everything for solo ops; every line answers an NFR (SLO ⇒ multi-AZ; abuse ⇒ WAF; DPA ⇒ Bedrock adjacency).
**Reversibility:** Hard — data + IAM gravity; IaC softens.

## Decision 15: Containers, orchestration, IaC *(FLIPPED — the headline change)*
**Options:** App Runner (current demo — SSE/stream limits, no pattern surface) · ECS Fargate (v1 steady pick; genuinely simpler — recorded as the honest scale-down alt) · **EKS multi-AZ + Helm + ArgoCD + Terraform** · GKE/AKS (off-strategy) · Kustomize (Helm chosen: chart ecosystem + values-per-env) · CDK/Pulumi (Terraform is inventory + market default).
**Decision:** **EKS (managed node groups, multi-AZ) as THE platform**: HPA on custom metrics (concurrent streams, not just CPU), **KEDA** (SQS depth → workers), PodDisruptionBudgets, NetworkPolicies (default-deny), IRSA per service. **GPU node group (v2.1):** dedicated managed node group (g6/g5 class — L4/A10G), taints + tolerations so only serving pods land there, NVIDIA device plugin, spot-preferred in staging, **scale-to-zero off-hours** for the serving engines with documented warm-up behavior. **Helm** charts (app) + community charts (Qdrant, Prometheus, Langfuse); **ArgoCD app-of-apps** GitOps; **Argo Rollouts** canary. **Terraform modules:** `network`, `eks`, `data` (RDS/ElastiCache/S3/SQS), `observability`, `app`. Images: multi-stage (uv builder → slim runtime), non-root, read-only rootfs, pinned digests, HEALTHCHECK, `.dockerignore` (kills the 27MB-artifacts-in-image bug). **Local: kind runs the same manifests daily ($0); cloud staging is an ephemeral window (≤$200 burst budget).**
**Reasoning:** v1's split (ECS steady + EKS window) was the $30-ceiling compromise; **the 10M design needs what only K8s primitives express here** — stream-aware HPA, queue-driven KEDA, PDBs for zero-downtime drains, IRSA least-privilege — *and* production K8s is your #1 audit gap (principle 11: gap-driven, named as such). The wallet survives via kind-local + ephemeral-staging, not by pretending EKS is cheap.
**Trade-offs:** Highest-complexity choice in the log; control-plane + baseline node cost during windows.
**Reversibility:** Moderate — containers port; manifests/IaC are the sunk cost.

## Decision 16: CI/CD *(survives + progressive delivery)*
**Options:** Jenkins (demo's path — self-hosted ops tax, already evidenced there; retired) · **GitHub Actions** · GitLab CI (repo is GitHub).
**Decision:** **GH Actions:** ruff+mypy → unit → integration (compose: PG/Redis/Qdrant/LocalStack) → **RAGAS eval gate, BLOCKING** (20-sample smoke on PR; full set nightly + pre-deploy) → multi-stage build → **Trivy scan FAILS on HIGH/CRITICAL** (fixes demo's `|| true` theater) → gitleaks + pip-audit → push ECR (SHA+semver, never bare `:latest`) → **ArgoCD sync staging → Argo Rollouts canary to prod (10%→50%→100%) with auto-rollback on SLO metrics** → smoke. **CI identity: GitHub OIDC → IAM role — zero long-lived keys.** Migrations: expand-migrate-contract so rollbacks never fight schema.
**Reasoning:** The eval gate is the package-defining pattern; canary + metric-driven rollback is what 43.8 min/month of error budget demands of a deploy process; `:latest`-only tagging (demo) made rollback impossible — tags are the rollback mechanism.
**Reversibility:** Easy.

## Decision 17: Secrets & configuration *(FLIPPED from SSM)*
**Options:** `.env` (current — N: no rotation/audit, one `COPY . .` from leaking, which demo's Dockerfile literally does) · SSM SecureString (v1 pick — $0, manual rotation; stays for dev/non-secret config) · **Secrets Manager + External Secrets Operator** · Vault (a project unto itself solo) · SOPS (rotation/audit weaker).
**Decision:** **AWS Secrets Manager (managed rotation, 90-day) + ESO syncing into K8s** (manifests stay secret-free) + **SSM Parameter Store for non-secret config**; app config via `pydantic-settings` — **typed, fail-fast at boot** (no more silent-`None` API keys); per-env Helm `values-{env}.yaml`; local `.env` gitignored with documented parity; gitleaks pre-commit + CI.
**Reasoning:** GDPR-real audit posture + RDS/provider-key rotation stop being "quarterly manual runbook" items at this exposure; $0.40/secret/mo is noise against the v2 cost base. Fail-fast config converts D21's "config missing" from runtime incident to deploy-time error.
**Reversibility:** Easy.

## Decision 18: Security posture *(WAF un-deferred; core carries)*
**Threat → mitigation (LLM-specific first):**
| Threat | Mitigation |
|---|---|
| Prompt injection (user) | Instruction-hierarchy prompt; answers must cite; **toolless by design** (D3 — nothing to hijack); adversarial suite in CI |
| Indirect injection via corpus | Retrieved text framed data-not-instructions; operator-only uploads (provenance); injection strings in golden set |
| Jailbreak → personal medical advice | Refusal policy + output pattern filter (dosage-like regexes) + refusal-correctness ≥95% CI gate |
| PII in logs/traces | Hash+length only in app logs; Langfuse = the one sanctioned store (access-controlled, 30-day retention, sampled) |
| Cost/DoS abuse | **CloudFront + AWS WAF (rate rules, bot control)** + per-IP/session Redis token buckets + token budgets + D20 breaker |
| Data exfil via provider | DPA review; Bedrock leg for enterprise terms; no PII forwarded in prompts |
| Supply chain | uv lockfile, Trivy, pip-audit, gitleaks, Dependabot, pinned digests |
| Container/runtime | Non-root, read-only rootfs, slim base, **NetworkPolicies default-deny**, IRSA least-privilege |
| Session hijack | HTTP-only SameSite signed cookies; stable secret in Secrets Manager |
| Killed by design | FAISS pickle `allow_dangerous_deserialization` (gone with D2); raw exception text to users (RFC 7807 envelope) |
**Still deferred with reasons:** mTLS/mesh (single cluster, solo — flip: multi-service compliance mandate); ML-grade PII detection (Presidio) behind regex layer v1.
**Reasoning:** Anonymous × medical × 10M ⇒ output-side safety and edge abuse defense are first-class, not hardening afterthoughts.

## Decision 19: Evaluation *(survives — the build-first rule stands)*
**Options:** manual (N) · **RAGAS + custom metrics + calibrated LLM-judge, CI-gated** · DeepEval (pytest ergonomics — named alt) · promptfoo (prompt-diff regression — adjunct) · Garak/PyRIT (red-team adjuncts).
**Decision:** **Build the harness BEFORE the refactor; baseline the current demo pipeline** — the before/after delta is the portfolio's before/after comparison. Golden set versioned in-repo, upsized for v2: **~150 curated Gale Q&A** (stratified: definitions/symptoms/treatment-info/cross-topic) + **~50 adversarial safety** (diagnosis, dosage, emergency, injection) + **~15 out-of-corpus** (must say don't-know). Metrics: RAGAS faithfulness/relevancy/context-precision/recall + citation-coverage, refusal-correctness, no-answer precision. **Blocking thresholds: faithfulness ≥0.85, relevancy ≥0.80, refusal ≥95%, don't-know precision ≥90%.** Judge: Groq-70B, calibrated once vs ~20 human labels (agreement reported); judge prompts versioned. CI: 20-sample smoke on PR; full nightly + pre-deploy. Online: **1% sampled scoring** via Langfuse traces + UI thumbs → weekly job; drift alerts. True online A/B: honestly deferred until real traffic exists.
**Reasoning:** The medical NFR makes eval the top quality control; eval-gated deploys are your #1 audit-gap fill.
**Reversibility:** Easy — datasets are the compounding asset.

## Decision 20: Cost controls *(survives — numbers re-anchored)*
**Decision:** Per-request: context token budget at `build_context` + max output 350–512. Per-session: daily token quota (Redis). Per-IP: rate limit (+ WAF edge rules). **Global: real-time spend counter (tokens × price table) → soft alert 50%, hard breaker 100% flips `CACHE_ONLY_MODE`** — degraded banner, zero provider calls. Full-load guardrails: **~$830/day** pro-rata alert line vs the $25k/mo ceiling; portfolio ~$2/day. CloudWatch billing alarms as the lagging backstop (~8h lag — the app counter is the real-time guard). Cost/query panel from D13 attrs. **GPU spend (v2.1):** GPU-hours tracked as a first-class spend line — utilization dashboard + scale-to-zero policy enforcement; an idle GPU is now the single biggest waste vector in the system (a 24/7 forgotten g6.xlarge ≈ $600/mo — more than the entire v1 infra budget). **Kill switch:** env flag + admin endpoint, chaos-tested in Phase 5.
**Reasoning:** Ceilings are real only if something *enforces* them; at 10M-scale a runaway loop or scrape is a five-figure event, not a surprise line item.
**Reversibility:** Easy — thresholds are config.

## Decision 21: Failure modes & degradation *(survives — matrix updated for v2 components)*
| Failure | Detection | Behavior | User experience |
|---|---|---|---|
| vLLM engine crash / OOM regression | health probe, error rate | → SGLang engine (same pool — D12) | transparent |
| GPU node / pool loss | node health, pending pods | → **hosted leg (Groq/Bedrock — infra-independent)** | transparent |
| Cold start after scale-to-zero | queue depth + warm-up probe | hosted leg absorbs while engine warms; min-replicas during peak hours | slight delay |
| Hosted escalation leg 429/outage | breaker | skip escalation — answer with 8B + cache; log quality dip | transparent |
| All serving legs down | breaker chain open | **cache-only mode** (exact+semantic) | banner: "answers may be limited" — never a raw 500 |
| Qdrant slow/down | 300ms timeout, 1 retry, breaker | cached / honest don't-know path; readiness flips | degraded |
| Reranker (ml-service) down | health check | skip rerank — hybrid-fusion order passthrough (quality dip logged, not outage) | none |
| Redis down | ping | cache bypass (fail-open); **rate limiting falls back to in-pod token bucket** (fail-closed-enough) | slower |
| Postgres down | readiness probe | chat continues stateless; history/persist disabled; audit buffered + replayed | maintenance notice |
| SQS backlog | depth alert | ingestion delayed (non-user-facing); KEDA scales; DLQ after N retries | none |
| Worker dies mid-ingest | stale-job alert | idempotent re-run; **alias swap only on completion** | none |
| Empty/low-confidence retrieval | score floor | honest "I don't have reliable information" + rephrase hint — **never generate ungrounded** | by design |
| Token budget exceeded | context builder | drop lowest-ranked chunks first; citations stay consistent | none |
| SSE client disconnect | server-side cancel | provider stream aborted — spend stops | n/a |
| Malicious input | guardrails | typed refusal + quota decrement | refusal message |
**Error-budget arithmetic that shapes all of this:** at 350 RPS, **~2 minutes of hard 500s ≈ the entire month's 99.9% budget.** Chaos drills (Phase 5): kill provider, kill Redis, kill Qdrant — top 3 by likelihood × blast radius.

## Decision 22: Repo structure *(survives + ml-service)*
**Options:** polyrepo (×N ops solo — N) · flat single app (couples deploys — N) · **uv-workspace monorepo**.
**Decision:**
```
P5-Medical-Chatbot/
├── apps/
│   ├── api/            # FastAPI: routes, SSE, middleware, degradation policies
│   ├── ml-service/     # bge embeddings + cross-encoder reranker (CPU pods)  ← NEW v2
│   ├── worker/         # SQS consumer: load→chunk→embed→upsert (alias swap)
│   └── web/            # Next.js
├── packages/
│   ├── core/           # pipeline stages, prompts/ (versioned), schemas, ports (vector/model)
│   └── eval/           # golden sets, RAGAS runners, adversarial suites, judge prompts
├── infra/
│   ├── terraform/      # network, eks, data, observability, app
│   └── k8s/            # Helm charts + ArgoCD apps (+ Rollouts)
├── .github/workflows/  # ci, eval-gate, cd
├── tests/              # unit, integration, e2e, load (k6), chaos
├── docs/               # DECISION_LOG.md (v1), DECISION_LOG_V2.md, runbooks/, architecture
└── demo/               # read-only reference until end-of-life
```
**Why ml-service is new:** CPU-bound embed/rerank inside the API's async event loop violates D7's discipline (one blocked loop = every open SSE stream stalls); a separate CPU-pod service scales on its own HPA and keeps the API pods pure-async I/O.
**Reversibility:** Moderate — cheap now, dear after Phase 4; decided last, used first.

---

# Decision summary v2 — at a glance (DRAFT, pending sign-off)

| # | Decision | Available options | Pick (v2) | Why (NFR anchor) | Prod-grade? | Fills audit gap? | Reversibility & flip-trigger | Δ v1 | Notes (cost / new tool) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Primary DB | SQLite / Postgres / MySQL / MongoDB / DynamoDB | **Postgres 16 RDS Multi-AZ, day-partitioned** | 350 writes/s trivial; audit SQL; retention = DROP PARTITION (GDPR-provable) | ✅ | SQL + partition ops | Hard · flip: write p95 >20ms → Aurora/KV split | upgraded | Partitioning = new pattern for you |
| 2 | Vector DB | pgvector / Qdrant / Pinecone / OpenSearch / Milvus / FAISS / Chroma | **Qdrant ×3 replicas (EKS), S3 snapshots** | 350 RPS reads off the system-of-record; native hybrid+filter; no per-query fees | ✅ | **Stateful svc on K8s** | Moderate · flip-DOWN to pgvector ≤50 RPS | **FLIP** | Course-known; port seam kept |
| 3 | RAG paradigm | naive / advanced / agentic / corrective / long-context | **Advanced: hybrid→rerank→threshold→cite** | Single LLM call fits TTFT 2.0s + $0.0005/q; medical determinism | ✅ | Advanced retrieval | Easy · HyDE/multi-query = eval-gated flags | — | Agentic = Package-2 project |
| 4 | LLM & tiering | hosted tiered / self-host 8B + hosted esc. / full self-host | **Self-host Llama-8B (vLLM) → hosted 70B esc. → hosted outage leg → cache** | Gap directive + queries never leave the box; premium named, not hidden | ✅ | **#1 gap: serving** | Easy · flip-back: GPU >1.5× hosted 2mo, TTFT p95 >2s | **v2.1** | ⚠ GPU $260–700/mo if 24/7 → scale-to-zero |
| 5 | Embeddings | MiniLM / bge-small / bge-large / OpenAI / Cohere / fine-tuned | **bge-large-en-v1.5 (1024d), ONNX int8 CPU → GPU if p95 breaks** | Max quality; memory trivial (0.4GB); hot-path compute is the only real price | ✅ | Embedding ops | ⚠ Mod · dim **1024** freezes at first collection | **v2.1** | Baseline eval vs bge-small; flip-down if lift <2pts |
| 6 | Orchestration | prebuilt chains / custom-thin / LCEL-constrained / LlamaIndex / LangGraph | **LCEL over self-authored runnables; prebuilt chains banned (lint-enforced)** | LC fluency signal + Langfuse callback ≈ free tracing; opacity neutralized by constraints | ✅ | LCEL mastery | Easy · unwrap is mechanical | **v2.1** | Span-per-stage stays mandatory |
| 7 | Backend | Flask / FastAPI / Litestar / Node / Go | **FastAPI ASGI + SSE** | **2,100 concurrent streams** ⇒ async or die; Pydantic boundaries | ✅ | Async at scale | Moderate | — | Lifespan singletons kill rebuild bug |
| 8 | Frontend | Jinja / HTMX / Next.js / Vite SPA / Streamlit | **Next.js App Router + TS** | Streaming/cancel/citations = the latency NFR made visible | ✅ | Streaming UX | Easy | — | Container behind CloudFront |
| 9 | Auth | none / anon+OIDC-admin / Clerk / Cognito accounts | **Anon signed sessions + Cognito OIDC admin + IRSA** | Quota+deletion identity sans signup; privileged surfaces get federated auth | ✅ | AuthZ design | Easy · Clerk = v2 seam | **FLIP** (admin leg) | Kills `os.urandom` restart bug |
| 10 | Caching | none / exact-only / +semantic / Memcached / in-proc | **Redis 4-layer; semantic ON w/ double guard** | 25–35% hits ≈ **$4–6k/mo** + cached p95 200ms; correctness outranks hit rate | ✅ | **Cost engineering** | Easy · version-key invalidation | **FLIP** (semantic ON) | Guard: ≥0.97 ∧ same top-3 ∧ eval-proven |
| 11 | Queue | BackgroundTasks / Celery / ARQ / SQS+KEDA / Kafka / Temporal | **SQS+DLQ + KEDA-scaled idempotent workers** | Durable+DLQ, queue-depth autoscale = Package-1 pattern; volume tiny ⇒ boring wins | ✅ | Event-driven scaling | Easy | **FLIP** | NEW: KEDA; LocalStack for dev |
| 12 | Inference serving | hosted / vLLM / SGLang / TGI / TensorRT-Triton / SageMaker | **vLLM primary + SGLang (benchmark + engine failover); hosted = outage leg** | Both engines = gap closed with *measured* evidence (published benchmark) | ✅ | **#1 gap: serving** | Easy · one adapter, hosted-primary = config flip | **v2.1** | ⚠ SGLang ≠ outage fallback (same failure domain) |
| 13 | Observability | CW-only / Datadog / ELK / LangSmith / OTel+Prom+Grafana+Loki+Langfuse | **OTel + self-hosted stack + Langfuse, SAMPLED** | 99.9% needs burn-rate alerts; 4.5M traces/day needs a sampling policy | ✅ | **Top gap: obs/SLO** | Easy-mod · OTel vendor-neutral | **FLIP** (self-host+sampling) | NEW: Langfuse, Loki, OTel |
| 14 | Cloud | AWS / Azure / GCP / PaaS | **AWS us-east-1 multi-AZ + CloudFront/WAF** | AWS-depth strategy; SLO ⇒ multi-AZ; abuse ⇒ WAF; DPA ⇒ Bedrock | ✅ | AWS depth | Hard | hardened | NAT permanent in design; envs ephemeral |
| 15 | Containers/IaC | App Runner / ECS / EKS+Helm+ArgoCD / GKE / Kustomize / CDK | **EKS multi-AZ + Helm + ArgoCD + Rollouts + TF; kind local** | Stream-aware HPA, KEDA, PDB, IRSA — only K8s expresses the 350-RPS design; #1 gap, named | ✅ | **Top gap: prod K8s** | Moderate · ECS = honest scale-down alt | **FLIP** | Wallet: kind $0 + ephemeral windows ≤$200 |
| 16 | CI/CD | Jenkins / GH Actions / GitLab | **GHA: eval gate + Trivy-fail + OIDC + canary rollback** | Error budget demands metric-driven canary; tags = rollback mechanism | ✅ | Eval-gated CD | Easy | +Rollouts | Fixes demo's `\|\| true` + `:latest` |
| 17 | Secrets/config | .env / SSM / Secrets Manager+ESO / Vault / SOPS | **Secrets Manager + ESO + pydantic-settings fail-fast** | GDPR audit + managed rotation; $0.40/secret = noise at v2 cost base | ✅ | Secrets ops | Easy | **FLIP** | NEW: ESO; SSM keeps non-secret config |
| 18 | Security | posture (per-threat) | Injection hierarchy · toolless · refusal filter · PII-free logs · **WAF+bot** · RFC 7807 | Anonymous × medical × 10M ⇒ output safety + edge defense first-class | ✅ | **Gap: AI security** | Additive | WAF un-deferred | Mesh/mTLS still deferred, reasoned |
| 19 | Evaluation | manual / RAGAS+judge / DeepEval / promptfoo / Garak | **RAGAS golden-215 + calibrated judge, CI-blocking, built FIRST** | Faithfulness ≥0.85, refusal ≥95% enforced by machinery; before/after = before/after comparison | ✅ | **#1 gap: eval** | Easy · datasets compound | upsized | NEW: RAGAS |
| 20 | Cost controls | observe-only / enforced / +LiteLLM gateway | **Enforced: budgets, quotas, spend breaker → CACHE_ONLY, kill switch** | $0.001/q + $25k/mo real only if enforced; runaway = five-figure event | ✅ | Cost engineering | Easy | re-anchored | $830/day alert line at full load |
| 21 | Failure modes | fail-fast / degradation ladder / multi-region | **Degradation ladder per dependency (matrix)** | 2 min of 500s ≈ month's 99.9% budget; never ungrounded medical answer | ✅ | Resilience design | Easy | matrix updated | Chaos drills top-3 in Phase 5 |
| 22 | Repo structure | polyrepo / flat / monorepo | **uv-workspace monorepo + apps/ml-service** | Atomic cross-cutting commits solo; CPU work off the async loop | ✅ | Packaging discipline | Moderate | +ml-service | Decided last, used first |

**New-for-you tools in v2.1 (each gets a 5-min primer at first use in Phase 4):** KEDA (D11/15), External Secrets Operator, Langfuse + OTel + Loki, RAGAS, Argo Rollouts, k6 (Phase 5), bge/reranker serving, **vLLM + SGLang (D12 — now primary serving engines, hands-on)**, DCGM GPU monitoring, GPU node groups/taints/device-plugin on EKS.
