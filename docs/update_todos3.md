PHASE 0 — Recon ✅

    ✅ P0.1 Read repo, map stack and data flow
    ✅ P0.2 Baseline report
    ✅ P0.3 Package mapping → Package 1 + medical wrapper

PHASE 1 — Requirements & NFRs ✅

    ✅ P1.1 Functional scope
    ✅ P1.2 NFRs @ 10M MAU (350 RPS peak · TTFT p50 800ms/p95 2.0s · retrieval p95 250ms · 99.9% SLO · ≤$0.001/q)
    ✅ P1.3 Out-of-scope list

PHASE 2 — Decision Log ✅

    ✅ P2.1 Dependency graph
    ✅ P2.2 22 decisions + D4b multi-venue
    ✅ P2.3 At-a-glance summary table
    ✅ P2.4 Saved as docs/DECISION_LOG_V2.md (v2.1 after user pushback on D4/D5/D6/D12)

PHASE 3 — Transformation Plan ✅

    ✅ P3.1 19 risk-front-loaded steps
    ✅ P3.2 v1.2 — D4b sub-steps, parallel tracks, S10 deferred
    ✅ P3.3 v1.3 — phases 6–9 split, vendor-portability principle

PHASE 4 — Execution 🔄 14 / 20

    ✅ S1 Eval harness + golden-90 + baseline [D19]

        ✅ S1a Scaffolding
        ✅ S1b Seed set
        ✅ S1c DemoTarget adapter
        ✅ S1d judge + metrics + meta-eval
        ✅ S1e Runner + CLI
        ✅ S1f golden-90 curated from corpus + docs/BASELINE.md

    ✅ S2 medcore contracts + CI shell [D22, D17, D16]

        ✅ S2.1 schema (typed Answer)
        ✅ S2.2 errors (RFC 7807) 
        ✅ S2.3 config (Gate B/C)
        ✅ S2.4 ports.py
        ✅ S2.5 S2.5 prompt registry prompts.py
        ✅ S2.6 CI + Makefile + .env.example

    ✅ S3 Thin slice [D2, D5, D6, D7]

        ✅ S3.1 Adapters
        ✅ S3.2 LCEL pipeline
        ✅ S3.3 Routes + lifespan
        ✅ S3.4 reindex
        ✅ S3.5 integration test (caught UUID bug)
        ✅ S3b.6 measured (local 37ms / Groq 163ms TTFT)
        ✅ S3b.7 docs/gpu-venue.md

    ✅ S3b GPU venue spike [D12, D4b]

        ✅ S3b.0 Recon
        ✅ S3b.1 Disk
        ✅ S3b.2 Passthrough
        ✅ S3b.3 Model choice
        ✅ S3b.4 Image
        ✅ S3b.5 server up (UVA + token + no-resume solved)
        ✅ S3b.6 Measured
        ✅ S3b.7 gpu-venue.md

    ✅ S4 SSE + cancellation + RFC 7807 [D7, D21]

        ✅ S4.1 Event contract
        ✅ S4.2 Shared prep chain
        ✅ S4.3 Handlers
        ✅ S4.4 SSE route
        ✅ S4.5 cancellation test (caught GC-close bug)

    ✅ S5 ml-service [D5, D22, D7]

        ✅ S5.1 Package
        ✅ S5.2 Backends
        ✅ S5.3 Schema
        ✅ S5.4 Routes
        ✅ S5.5 HTTP Clients
        ✅ S5.6 Wiring
        ✅ S5.7 Docker
        ✅ S5.8 measured (embed 120ms, rerank 155ms)
        ✅ S5.9 ONNX backends — measured refutation; smaller reranker is the 8× lever

    🔄 S6 Hybrid + rerank + eval delta [D3, D5] — 11 / 12

        ✅ S6.1 Reranker + sigmoid
        ✅ S6.2 BM25 encoder
        ✅ S6.3 Hybrid + RRF
        ✅ S6.4 rerank stage + degradation
        ✅ S6.5 PipelineTarget + answer_verbose
        ✅ S6.6 full-corpus re-index (7,080 chunks)
        ✅ S6.7 Latency decision
        ✅ S6.8 metric bug fixed + both runs rescored
        ✅ S6.9 compare + rescore (13 tests)
        ✅ S6.10 Money chart
        ✅ S6.11 thresholds BLOCKING — --gate, Make targets, eval-gate.yaml
        ⏳ S6.12 Faithfulness re-run — blocked on Groq judge quota

    ✅ S7 Postgres [D1, D9]

        ✅ S7.1 Engine
        ✅ S7.2 Partitions
        ✅ S7.3 anonymous sessions
        ✅ S7.4 retention job (DROP PARTITION)
        ✅ S7.5 deletion-actually-deletes test
        ✅ S7.6 Repository
        ✅ S7.7 Cookie + wiring

    ✅ S8 Redis caches + quotas [D10, D20]

        ✅ S8.1 Compose
        ✅ S8.2 Response cache
        ✅ S8.3 Embedding cache
        ✅ S8.4 Quotas
        ✅ S8.5 Fail-open / fail-safe
        ✅ S8.6 Semantic cache OFF-flagged

    ✅ S9 Worker + SQS + alias swap [D11]

        ✅ S9.1 Alias support
        ✅ S9.2 medworker
        ✅ S9.3 Verify-then-swap
        ✅ S9.4 SQS consumer
        ✅ S9.5 Retention scheduler
        ✅ S9.6 CLI
        ✅ S9.7 Tests

    ⏸️ S10 Next.js UI [D8] — DEFERRED by you

    ✅ S11 Observability [D13]

        ✅ S11.1 structlog → stdout
        ✅ S11.2 PII redaction
        ✅ S11.3 RED metrics per stage
        ✅ S11.4 /metrics
        ✅ S11.5 Route instrumentation
        ✅ S11.6 Burn-rate alerts
        ✅ S11.7 Prometheus + Grafana compose
        ✅ S11.8 OTel + Langfuse — delivered in S15.6

    ✅ S12 Security guardrails [D18]

        ✅ S12.1 Pre-retrieval input guardrail
        ✅ S12.2 Category-specific refusals
        ✅ S12.3 Output dosage filter
        ✅ S12.4 Injection suite
        ✅ S12.5 20/20 refused, 0 false refusals
        ✅ S12.6 Pipeline short-circuit

    🔄 S13 Multi-venue serving [D4, D4b, D12] — 5 / 9

        ✅ S13.1 OpenAICompatModel
        ✅ S13.2 Venue registry
        ✅ S13.3 Local venue
        ✅ S13.4 Groq venue
        ⏸️ S13.5 RunPod venue — Track D
        ⏸️ S13.6 AWS venue — Track D
        ⏸️ S13.7 SGLang leg
        ✅ S13.8 Failover + breaker proven (2438 ms → 93 ms)
        ⏸️ S13.9 Cross-venue parity — Groq quota

    ✅ S14 k6 engine benchmark [D12]

        ✅ S14.1 Harness
        ✅ S14.2 Custom metrics
        ✅ S14.3 NFR thresholds
        ✅ S14.4 Venue-tunable ramp
        ✅ S14.5 Make targets + doc
        ✅ S14.6a vLLM — 12 RPS, 0% fail, 58 tok/s, p99 1034 ms
        ✅ S14.6b SGLang — 12 RPS, 0% fail, 51.8 tok/s, p99 2504 ms → vLLM recommended

    ✅ S15 Helm + kind [D15] — 6 / 6

        ✅ S15.1 Chart scaffold — Chart.yaml, values.yaml, _helpers.tpl
        ✅ S15.2 API deployment + Service + HPA + PDB
        ✅ S15.3 ml-service + worker + missing worker Dockerfile
        ✅ S15.4 Secrets + config + ServiceAccount + NetworkPolicy + values-kind
        ✅ S15.5 kind cluster up — 3 nodes, chart installs green, 21 objects
        ✅ S15.6 OTel + Langfuse + Collector tail sampling (absorbed S11.8)

    🔄 S16 Terraform + plan [D14, D15] — 6 / 7

        ✅ S16.1 Provider + backend — pinned versions, S3 + native lockfile
        ✅ S16.2 VPC + networking — 3 AZs, EKS discovery tags
        ✅ S16.3 EKS — CPU pool + tainted GPU pool, IRSA enabled
        ✅ S16.4 RDS with PITR — enforced by variable validation (P5.4.10)
        ✅ S16.5 ElastiCache + SQS with DLQ
        ✅ S16.6 IAM least-privilege — worker-only SQS, no wildcards
        ⏳ S16.7 terraform plan proof — blocked on AWS credentials (Track D)

    ✅ S18 Cost controls + kill switch [D20]

        ✅ S18.1 Token pricing table — pricing.py
        ✅ S18.2 Per-request + daily budget accounting — budget.py
        ✅ S18.3 Kill switch wired into routes + deps
        ✅ S18.4 Redis-backed counters, fail-safe on Redis loss
        ✅ S18.5 Config surface in medcore.config
        ✅ S18.6 test_budget.py

    🔄 S19 Golden-215 + calibration [D19, D10] — 4 / 5

        ✅ S19.0 Judge identity re-pinned → judge_v2 (Groq removed llama-3.3-70b)
        ✅ S19.1 Expand golden set 90 → 215 — v2 assembled (150/50/15), v1 superset verified
        ✅ S19.2 Judge calibration vs human labels — harness + κ + 36-row sheet; awaiting your labels
        ✅ S19.3 Threshold re-tune — 3 defects found, docs/THRESHOLDS.md

            ✅ S19.3a Safety scoring split 3-way — abstain (safe) no longer scored as unsafe
            ✅ S19.3b unsafe_answer_rate invariant added, gated at 0.00, direction-aware gates
            ✅ S19.3c Guardrail overfit found — 20/20 on its own cases, 11/30 (37%) on unseen
            ✅ S19.3d Guardrail rewritten — recall 0.620 → 1.000, false refusals 4/150 → 0
            ✅ S19.3e Root cause fixed — tests were pinned to golden_core_v1, repointed to v2
            ✅ S19.3f REFUSAL_MARKERS gap — own refusals scored `answered`; would have red-lined CI
            ✅ S19.3g Thresholds re-derived from measured noise + grid realizability
        ✅ S19.4 Semantic cache go/no-go — NO-GO, measured; docs/SEMANTIC_CACHE.md

            ✅ S19.4a Found the claim false — no SemanticCache exists; docstring corrected
            ✅ S19.4b D10 premise refuted — "aspirin adult/child" = 0.8235, not "closer than 0.95"
            ✅ S19.4c Exp A golden set — 23,005 pairs, max 0.8541, zero ≥ 0.95
            ✅ S19.4d Exp B adversarial — 15 clinical minimal pairs, danger ceiling 0.9133
            ✅ S19.4e Exp C paraphrase — useful floor; only 1/12 hits at the configured 0.97
            ✅ S19.4f Decision — safe threshold is inert, useful threshold has 0.007 margin
            ✅ S19.4g Pinned in config comment + 2 regression tests

PHASE 6 — Local & kind validation ⏳ 0 / 7 (cost $0)

    ⏳ P6.1 Docker images — api / ml-service / worker, multi-stage, non-root, Trivy-clean
    ⏳ P6.1a Strip CUDA from CPU-only images — 3.4 GB dead weight MEASURED; prerequisite for S17.1
    ⏳ P6.2 docker compose full-stack end-to-end smoke
    ⏳ P6.3 kind cluster created; Helm chart installs green
    ⏳ P6.4 Probes, HPA, ConfigMap/Secret wiring verified in-cluster
    ⏳ P6.5 In-cluster failure drills — pod kill, rollout restart, node drain
    ⏳ P6.6 terraform plan reviewed (no apply) — same blocker as S16.7

    ⏳ S17 CI/CD + eval gate proof [D16] — 0 / 7 — gated on P6.1a

        ⏳ S17.1 Build + push images — needs P6.1a (runner disk ~14 GB < 8.8 GB × 3)
        ⏳ S17.2 Unit + integration stages
        ⏳ S17.3 Eval gate blocking proof
        ⏳ S17.4 Load smoke in CI
        ⏳ S17.5 Security scan stage
        ⏳ S17.6 Deploy to dev
        ⏳ S17.7 Promotion workflow

PHASE 5 — Hardening ✅ 5 / 5

    ✅ P5.1 Secrets · dependency · license audit

        ✅ P5.1.1 Secret scan — tree, full git history, pattern grep → clean
        ✅ P5.1.2 pip-audit → 13 findings
        ✅ P5.1.3 Upgrade aiohttp + pypdf → 4 fixed
        ✅ P5.1.4 Exploitability assessment → 9 not reachable
        ✅ P5.1.5 Confirm ragas 0.4.3 is latest → pin is forced
        ✅ P5.1.6 Delete dead code — model.py, reindex.py
        ✅ P5.1.7 License audit — no copyleft; Gale corpus flagged
        ✅ P5.1.8 docs/SECURITY_AUDIT.md + make audit

    ✅ P5.2 Load test

        ✅ P5.2.1 system_load.js harness, 3 tiers
        ✅ P5.2.2 Tier A cache → 310 RPS, p99 6 ms
        ✅ P5.2.3 Tier C guardrails → 6 ms/refusal
        ✅ P5.2.4 Tier B full pipeline → 2 RPS, rerank 54%
        ✅ P5.2.5 Fix rate-limit bypass
        ✅ P5.2.6 Fix process death (BlockingConnectionPool)
        ✅ P5.2.7 Fix log amplification
        ✅ P5.2.8 Fix empty venue errors
        ✅ P5.2.9 Fix silent Redis-off
        ✅ P5.2.10 Correction — unattributed_ms
        ✅ P5.2.11 docs/LOAD_TEST.md + 3 make targets

    ✅ P5.3 Chaos drills

        ✅ P5.3.1 Drill harness — stop/start only
        ✅ P5.3.2 Provider drill → 503, RTO 64.8 s
        ✅ P5.3.3 Redis drill → fixed 20.4 s → 4.7 s
        ✅ P5.3.4 Qdrant drill → fixed 500 → 503
        ✅ P5.3.5 Postgres drill → withdrawn, re-run in P5.4.2
        ✅ P5.3.6 Empty index = fault, not abstention
        ✅ P5.3.7 Harness false-pass fixed
        ✅ P5.3.8 Pass criterion corrected
        ✅ P5.3.9 docs/CHAOS_DRILLS.md + make chaos

    ✅ P5.4 Backup / restore drill

        ✅ P5.4.1 State classification — 1 of 3 is a system of record
        ✅ P5.4.2 Re-run Postgres chaos drill properly → +3.5 s finding
        ✅ P5.4.3 Fix — DATABASE_URL required outside local
        ✅ P5.4.4 Fix — test suite no longer drops the dev database
        ✅ P5.4.5 Extract shared Breaker → circuit.py
        ✅ P5.4.6 Postgres dump + restore verified — RTO 0.5 s
        ✅ P5.4.7 Qdrant snapshot + restore verified — RTO 3.5 s
        ✅ P5.4.8 Measure re-index → snapshot is 390× faster
        ✅ P5.4.9 Redis — prove no-backup is correct
        ✅ P5.4.10 RPO analysis → PITR is a Phase 8 requirement
        ✅ P5.4.11 docs/BACKUP_RESTORE.md + make backup-drill

    ✅ P5.5 Runbooks · alerts · cost thresholds · log retention

        ✅ P5.5.1 Runbook — provider outage
        ✅ P5.5.2 Runbook — Redis / Postgres / Qdrant outages
        ✅ P5.5.3 Runbook — index rebuild and alias rollback
        ✅ P5.5.4 Fix — errors_total was declared but never emitted
        ✅ P5.5.5 Fix — 429s were burning the availability budget
        ✅ P5.5.6 Add dependency_circuit_state metric
        ✅ P5.5.7 Six new alerts, thresholds traced to measurements
        ✅ P5.5.8 promtool validation — 15 rules
        ✅ P5.5.9 Runbook anchor links verified against alerts
        ✅ P5.5.10 Cost threshold review — $5/day flagged
        ✅ P5.5.11 Log retention + PII policy
        ✅ P5.5.12 docs/RUNBOOKS.md

PHASE 7 — Real managed Kubernetes ⏳ 0 / 12 (DigitalOcean first, vendor-portable)

    ⏳ P7.1 Vendor selection + cost model committed to repo
    ⏳ P7.2 Cluster provisioned via Terraform (never click-ops)
    ⏳ P7.3 Container registry + image push pipeline
    ⏳ P7.4 Data tier — managed Postgres + Redis
    ⏳ P7.5 Ingress-nginx + cert-manager + TLS + DNS
    ⏳ P7.6 Secrets management — External Secrets or vendor store
    ⏳ P7.7 App tier deployed; GPU venue connected per D4b
    ⏳ P7.8 Observability live — Prometheus, Grafana, alerts firing
    ⏳ P7.9 Load test against the real cluster — HPA actually scaling
    ⏳ P7.10 Chaos drills against the real cluster — node/pod failure
    ⏳ P7.11 Real cost measurement — $ per 1k queries
    ⏳ P7.12 Teardown runbook + terraform destroy verified

PHASE 8 — AWS EKS ⏳ 0 / 8 (portability proof + AWS-depth gap)

    ⏳ P8.1 G-instance / EKS quota approved (Track D)
    ⏳ P8.2 Terraform — VPC + EKS + managed node groups (HCL written in S16, never applied)
    ⏳ P8.3 IRSA — least privilege (HCL written in S16, never applied)
    ⏳ P8.4 RDS with PITR + ElastiCache + SQS (HCL written in S16, never applied)
    ⏳ P8.5 Same charts via values-aws.yaml — diff must be config-only
    ⏳ P8.6 GPU node group for self-hosted vLLM venue
    ⏳ P8.7 Cost comparison — DOKS vs EKS, measured
    ⏳ P8.8 Portability findings written up

PHASE 9 — Portfolio ⏳ 0 / 6

    ⏳ P9.1 Architecture diagram
    ⏳ P9.2 README rewrite
    ⏳ P9.3 Before/after metrics story (money chart)
    ⏳ P9.4 Findings writeup — every measurement that refuted an assumption
    ⏳ P9.5 Demo video / screenshots
    ⏳ P9.6 Interview talking points + senior-vs-junior table

TRACK D — user-side async ⏳ 1 / 5

    ⏳ D.1 AWS quota request
    ⏳ D.2 RunPod account
    ✅ D.3 HF token
    ⏳ D.4 DigitalOcean account + apply $200 credit
    ⏳ D.5 cgroup v2 in WSL2 — unblocks newer kind node images
