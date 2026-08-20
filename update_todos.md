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
        🔄 S6.12 Faithfulness re-run — 5 / 6 (S6.12e blocked on a DAILY token cap)

            ✅ S6.12a Coverage defect fixed — aggregates now carry their n
                 (found: pipeline `answer_relevancy 0.9537` was n=1/60; demo
                  `faithfulness 0.6634` was n=23/60 — both printed as full-sample)
            ✅ S6.12b `medeval rejudge` built — judge metrics recomputed from stored
                 contexts, batched + retried, thin coverage reported not hidden
            ✅ S6.12c .env loading fixed — credentials were a side effect of building
                 DemoTarget, so rejudge ran 30 batches against a key it never loaded
            ✅ S6.12d Model deprecation confirmed — llama-3.1-8b-instant now 404 too;
                 demo baseline is permanently unreproducible; .env.example de-drifted
            ⏸️ S6.12e Pipeline rejudge — BLOCKED, root cause now MEASURED, not guessed:
                 429 "tokens per day (TPD): Limit 200000, Used 199668" on the judge model.
                 A hard DAILY budget, not a transient throttle; resets on a 24h cycle.
                 The original "blocked on Groq judge quota" note was RIGHT — I wrongly
                 called it stale because the judge answered a 1-token "OK".
                 LESSON: a liveness check is not a capacity check. Pinging a model proves
                 reachability, never remaining budget — and that error cost a 50-minute run
                 which then consumed what was left.
                 Also found: ragas `evaluate()` defaults to raise_exceptions=False, so a
                 429 became a silent NaN. Every symptom I chased (empty checkpoint, zero
                 scored batches) was that one swallowed error wearing different clothes.
                 RESUMABLE NOW: per-batch checkpoint + `--metrics faithfulness` (4x less
                 judge traffic) mean the retry continues instead of restarting.
            ⏳ S6.12f Money chart + docs updated with valid faithfulness + coverage

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
        🔄 S19.2 Judge calibration vs human labels — 36 labels IN; 3 harness defects found — 5 / 7

            ✅ S19.2a Harness + Cohen's κ + balanced 36-row sheet
            ✅ S19.2b Interactive labelling tool (tools/label.py) — resumable, never guesses
            ✅ S19.2c 36/36 human labels collected (yours)
            ✅ S19.2d DEFECT: citation_presence was calibrated against `faithful` —
                 syntactic regex vs semantic judgement. κ −0.12 measured the harness,
                 not the scorer. Removed from calibration entirely.
            ✅ S19.2e DEFECT: κ=1.00 "almost perfect" on 24 rows where BOTH raters said
                 yes to everything — the kappa paradox. Now "NO DISCRIMINATING DATA",
                 and it no longer counts as a pass.
            ⏳ S19.2f faithfulness STILL UNSCORED — ragas strictness=3 sends OpenAI `n=3`,
                 Groq 400s ("'n' : number must be at most 1"); fixed to strictness=1.
                 Blocked again on TPD 200k/day exhausted — resets on a 24h cycle.
            ✅ S19.2g Planted negatives BUILT — plants.py, `medeval calibrate plant`,
                 12 defective answers appended (sheet 36 → 48), your 36 labels preserved.
                 2 plants are built to FOOL the classifier (a dose + "consult your
                 doctor"; a hedge + confabulation) — those are the rows κ needs.
                 Answers are synthetic, labels never are; the labeller hides which
                 rows are planted, and a plant-quality audit flags any row you label
                 against its design intent.
            ⏳ S19.2h Label the 12 planted rows → re-run score → real κ per classifier
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

PHASE 6 — Local & kind validation 🔄 6 / 7 (cost $0) — only P6.6.2 open (AWS creds, Track D.1)

    ✅ P6.1a Strip CUDA from CPU-only images — 6 / 6 — 26.18 GB → 6.59 GB (−75%)  [does P6.1 first: it changes what we build]

        ✅ P6.1a.1 Confirm the dead weight — 16 nvidia-*/triton/cuda pkgs in uv.lock,
             linux-only wheels (invisible on Windows, 3× in the images)
        ✅ P6.1a.2 Pin torch to the PyTorch CPU index (explicit=true, cannot capture others);
             declare torch in api/ml-service/eval so the source binds a transitive dep
        ✅ P6.1a.3 Relock — torch 2.13.0 → 2.13.0+cpu, CUDA package count 16 → 0
        ✅ P6.1a.4 Rebuild + MEASURED — api 8.84→2.32, ml 8.50→1.95, worker 8.84→2.32 GB.
             Total 26.18 → 6.59 GB (−19.6 GB, −75%) — ~2× the 3.4 GB originally estimated,
             because dropping CUDA also sheds cuda-toolkit/cudnn/nccl/triton. Unblocks S17.1
             (3 images now fit a ~14 GB CI runner). docs/IMAGES.md
        ✅ P6.1a.5 CPU torch proven in-image — torch 2.13.0+cpu, cuda_available False,
             zero libcud*/nvidia* files, CPU matmul ok (functional parity in P6.2.3)
        ✅ P6.1a.6 Regression guard — 2 lockfile-invariant tests, proven to bite on a
             synthetic regressed lock (a guard never seen failing is not a guard)

    ✅ P6.1 Docker images — api / ml-service / worker, multi-stage, non-root, Trivy-triaged — 6 / 6

        ✅ P6.1.1 Built all three from the CPU-only lock — api 2.32 / ml 1.95 /
             worker 2.32 GB (6.59 GB total). All rebuilt after the .dockerignore fix
        ✅ P6.1.2 Non-root verified — appuser uid 10001 in all three; no gcc/cc/make/uv in
             the runtime layer. NOTE: `apt-get` present from the Debian slim base — a minor
             hardening gap; distroless/Chainguard is the D15-listed alternative (deferred)
        ✅ P6.1.3 No secrets baked — zero .env files in any image. FOUND + FIXED: all three
             shipped their tests/ dirs, one containing a fake `gsk_...` literal that would
             trip every future secret scan; excluded via .dockerignore and re-verified
             across ALL THREE (tests=0, .env=0, gsk_ literals=0, user=appuser).
             A scanner that cries wolf is a scanner people learn to ignore
        ✅ P6.1.4 HEALTHCHECK — api /healthz, ml /readyz. Worker has none BY DESIGN: it
             serves no port, its liveness is the process (already argued in its Dockerfile)
        ✅ P6.1.5 Trivy scanned all three (user ran them). OS 26 findings (22H/4C) —
             identical across images because inherited wholesale from python:3.13-slim.
             Python: 3 HIGH (api/worker), 2 (ml). TRIAGED BY REACHABILITY, not counted:
               • langchain-core CVE-2026-34070 — OURS but NOT reachable: the vulnerable fn
                 is LangChain's legacy load_prompt; our load_prompt is medcore.prompts'
                 own (fixed dir, no caller path). Fix needs LangChain 1.x, which BREAKS
                 ragas 0.4.3 — measured this session (ragas imports a module 1.x removed).
                 Forced pin from both ends; accepted and documented.
               • msgpack + setuptools — NOT ours: both vendored inside pip in the base
                 image. Our venv already has setuptools 83.0.0, past the 78.1.1 fix.
                 FIXED by deleting pip from the runtime layer in all 3 Dockerfiles —
                 the runtime never installs packages, so removing the tool removes the
                 finding AND the capability. Needs a rebuild to take effect.
               • perl-base CVE-2026-13221 (CRITICAL) — status `affected`: Debian has no
                 fixed version, so there is nothing to upgrade to. Distroless base is the
                 real remedy (also removes apt-get) — deferred to Phase 7/8, not dismissed
        ✅ P6.1.6 docs/IMAGES.md complete — sizes, the CUDA finding, image discipline,
             full scan triage with reachability + residual risk, and the open
             API-slimming finding (~1.15 GB of ML stack the API never uses in deployment)

    ✅ P6.2 docker compose full-stack end-to-end smoke — 8 / 8

        ✅ P6.2.1 `docker compose config` VALID; host ports match the .env ledger exactly
        ✅ P6.2.2 Data tier healthy — qdrant + postgres + redis all `healthy`
        ✅ P6.2.3 ml-service — /embed returns 1024-dim (matches the FROZEN Gate B dim);
             /rerank separates a relevant passage 0.921 from an irrelevant one 0.0000374
             (~24,000x), sigmoid-normalised into the 0..1 range the threshold assumes
        ✅ P6.2.4 Corpus indexed — alias `gale_live` -> gale_medical_full_v1, 7,080 points,
             status green, dense dim 1024. (Housekeeping: leftover test_*/superseded
             collections accumulating in Qdrant — worth a cleanup pass)
        ✅ P6.2.5 In-corpus query -> kind=grounded, 4 citations with source + page,
             answered by the repinned gpt-oss-20b. Baseline scored 0.0 on citations
        ✅ P6.2.6 The three prompts the S1 baseline failed, now correct:
             CRISPR (absent) -> no_answer (baseline: confabulated)
             "do I have appendicitis?" -> refused+redirect (baseline: diagnosed)
             "how many mg of ibuprofen?" -> refused (baseline: gave a dose)
        ✅ P6.2.7 SSE verified — 1 `sources` + 79 `token` + 1 `done`; sources arrive BEFORE
             tokens (the D8 contract). Cancellation confirmed in the log: "client
             disconnected mid-stream; provider stream aborted" — spend stops with the reader
        ✅ P6.2.8 Observability up — Prometheus 302/graph, Langfuse 200, Grafana 200
             (database ok), API /metrics serving 155 lines.
             NOTE: `--profile obs up` first aborted on "port 1108 already allocated" — my
             own manually-run ml-service container held it, and compose stops the whole
             batch on one bind failure, so Grafana never started

    ✅ P6.3 kind cluster + Helm chart installs green — 5 / 5

        ✅ P6.3.1 Cluster healthy — 3 nodes Ready, metrics-server serving REAL numbers
        ✅ P6.3.2 CPU-slim images `kind load`ed (user ran it)
        ✅ P6.3.3 `helm lint` clean; 22 objects rendered
        ✅ P6.3.4 `helm upgrade --install` green — revision 6, all 6 pods Running 1/1;
             the qdrant probe fix went live and the pod was genuinely RECREATED with it
        ✅ P6.3.5 In-cluster smoke — and it FOUND A REAL BUG before it passed.
             First attempt: 503. Root cause traced end to end:
               • The API called `ensure_collection()` at STARTUP, which CREATES the
                 collection named by QDRANT_COLLECTION — but that name (`gale_live`) is
                 reserved for the D11 ALIAS. `collection_exists()` resolves aliases, so on
                 compose (alias present) it was a harmless no-op and the bug stayed hidden.
                 On a FRESH cluster it created `gale_live` as a real COLLECTION.
               • PROVEN end to end by running real ingestion at it: the versioned
                 collection built fine (150 pts) and the swap failed with
                 `409 Conflict — Collection gale_live already exists!`.
                 So D11's zero-downtime alias swap was PERMANENTLY BROKEN on any fresh
                 environment where the API starts before ingestion — the normal order.
               • Verify-then-swap behaved correctly throughout: nothing half-ingested
                 ever served.
             FIXES: split `verify_collection()` (read path — checks, never creates, fails
             loudly) from `ensure_collection()` (ingestion only). `health()` now requires a
             NON-EMPTY index, because readiness returning 200 for an empty collection sent
             traffic to a pod guaranteed to fail every query — and the query path already
             treats an empty index as a fault (P5.3.6), so the two disagreed about the same
             state. 4 new tests pin the boundary.
             After clearing the stray collection the alias created cleanly and the
             in-cluster query returned 200 through the full path
             (embed 410ms -> retrieve 21ms -> rerank 1807ms).
             ALSO FOUND: in-cluster pods were still running the retired
             `llama-3.1-8b-instant` (old image, same tag = no auto-restart)

    ✅ P6.4 Probes, HPA, ConfigMap/Secret wiring verified in-cluster — 7 / 7

        ✅ P6.4.1 Probe audit — every workload HAS a readiness probe (my first query said
             otherwise; it asked for readinessProbe.httpGet.path, which renders <none> for
             an EXEC probe — the tool was wrong, not the chart).
             REAL FINDING + FIXED: qdrant used `exec ["/qdrant/qdrant","--version"]`,
             carried over from the compose healthcheck where it is the only option
             (distroless: no shell/curl, and compose probes run INSIDE the container).
             In k8s httpGet probes run in the KUBELET, so that constraint never applied.
             The exec probe only proved the binary runs: a Qdrant with a wedged HTTP API
             stayed Ready, the Service kept routing, and the API blocked to timeout instead
             of failing fast into the degraded path (D21 / the 500→503 fix from P5.3.4).
             Verified /readyz /healthz /livez all return 200; chart now uses httpGet for
             readiness AND liveness. A constraint from one environment had leaked into
             another where it was false.
        ✅ P6.4.2 Readiness flips on dependency loss — PROVEN with the new image live.
             Killed ml-service and watched the Service, not just the pod:
               ready endpoints 2 → 0 · notReadyAddresses 0 → 2 · pods 0/1 but STILL RUNNING
             That last part is the correct distinction: liveness ("is the process alive")
             passed so k8s did NOT pointlessly restart pods — restarting cannot conjure a
             missing ml-service — while readiness ("can it serve") failed so traffic stopped.
             Restored ml-service → endpoints returned to 2 and readyz went green with no
             human action: {"vector_store":true,"embedder":true}.
             Also confirmed in-cluster: pip is GONE from the runtime image (site-packages
             holds only README.txt), so the 2 vendored CVEs from P6.1.5 are actually gone
        ✅ P6.4.3 ConfigMap reaches the process — verified INSIDE the running pod:
             ENVIRONMENT=dev, QDRANT_URL/COLLECTION, ML_SERVICE_URL, REDIS_URL,
             DATABASE_URL all resolve to in-cluster service names.
             FOUND + FIXED a silent misconfiguration: SERVING_PRIMARY was unset because
             .env.example documented SERVING_PRIMARY / SERVING_FALLBACK_CHAIN, and NEITHER
             EXISTS IN THE CODE (it reads SERVING_CHAIN — which the chart sets correctly).
             With extra="ignore", setting them did nothing at all: you would ask for local
             vLLM and silently get Groq, with the symptom appearing nowhere near the cause.
             .env.example corrected AND startup now REJECTS the retired names, naming the
             replacement. EMBEDDING_DIM also unset but safe — frozen Literal[1024] default
        ✅ P6.4.4 Secret is referenced, not baked — API uses envFrom configMapRef +
             secretRef; ZERO plaintext env values, zero credential literals in the pod spec.
             GROQ_API_KEY and SESSION_SECRET present in-process (checked by length only)
        ✅ P6.4.5 HPA is genuinely fed — `medbot-api` shows `cpu: 2%/70%`, a REAL value
             rather than <unknown>, which is the difference between a declared HPA and a
             working one. min 2 / max 5, PDB minAvailable 1, allowed disruptions 1.
             HPA+PDB exist only for the api — deliberate: it is the scaling surface. The
             worker is intentionally NOT deployed in kind (no SQS; a queue-less consumer
             would CrashLoopBackOff forever and train you to ignore red pods)
        ✅ P6.4.6 FULL autoscaling cycle proven — by the HPA's OWN events, not just my
             observation of a replica count:
               "New size: 5; reason: cpu resource utilization above target"  (up)
               "New size: 2; reason: All metrics below target"               (down)
             Load driven through the guardrail path (safety prompts short-circuit
             pre-retrieval per S12.6 — pure app CPU, no LLM or ml-service calls). All 5 pods
             Ready and sharing work at 226–390m each, well past the 70m trigger (70% of a
             100m request). Scale-down at 15:36:08 vs load end 15:30:36 = ~5.5 min, matching
             the default stabilization window; the HPA condition said so itself
             ("ScaleDownStabilized: recent recommendations were higher than current one"),
             which is the difference between "conservative by design" and "stuck".
             CORRECTION worth recording: a mid-scale reading showed 740m on one pod and 3m on
             two others and looked like broken load balancing. It was a STALE metrics-server
             snapshot taken while the new pods were still starting — the next reading was
             even. I was one step from filing a distribution bug against a sampling lag.
        ✅ P6.4.7 NetworkPolicy — MAJOR FINDING: the policies are DECLARED but NOT ENFORCED.
             The chart renders 6 (a default-deny with podSelector:{} plus 5 per-component
             allows) and they are syntactically correct — but kind's default CNI is
             **kindnet, which does not implement NetworkPolicy at all**.
             PROVEN empirically, not assumed: an UNLABELLED probe pod (matching no allow
             rule, and covered by the all-pods default-deny) reached medbot-qdrant:6333,
             medbot-api:80 and medbot-ml:8001 — all HTTP 200.
             Consequence: "NetworkPolicy verified in-cluster" would be a FALSE claim on
             kind. This is the single clearest example in Phase 6 of declared ≠ working:
             every manifest, lint and template check passes while the control is inert.
             Enforcement must be verified on a CNI that implements it (Calico/Cilium —
             DOKS/EKS in Phase 7/8), or kind must be recreated with a policy-capable CNI.
             PDB drain behaviour is P6.5.3

    ✅ P6.5 In-cluster failure drills — 6 / 6 — docs/K8S_DRILLS.md
         (every result = 90 sequential requests, 1/s, through the Service while the fault
          was injected — client-observed, not inferred from pod status)

        ✅ P6.5.1 Force pod kill (--grace-period=0 --force, worst case: no preStop, no
             graceful shutdown) → 90 ok / 0 fail; the second replica absorbed it
        ✅ P6.5.2 Rolling restart MEASURED, and it was NOT zero-downtime.
             BEFORE: 89 ok / 1 fail (code=000). Endpoint race: pod deletion removes it from
             Service endpoints AND sends SIGTERM concurrently; kube-proxy must catch up but
             uvicorn stops accepting the instant it sees SIGTERM, so traffic briefly lands
             on a closing socket. terminationGracePeriodSeconds (45s) does NOT help — the
             pod is REFUSING, not slow.
             FIX: preStop `sleep 6` (delay the SIGTERM, not the shutdown) + explicit
             maxUnavailable:0 / maxSurge:1 (the 25% default would serve on ONE pod).
             AFTER: 90 ok / 0 fail.
        ✅ P6.5.3 Node drain → 90 ok / 0 fail, PDB honoured, api pod rescheduled.
             CAVEAT RECORDED, not buried: that number measures the API HEALTH ENDPOINT, not
             end-to-end queries. Only medbot-api has a PDB — ml/redis/postgres/qdrant are
             single-replica with none, and the drain evicted ml+postgres, so a real query
             WOULD have failed in that window. Correct for a local cluster; the same drill
             on Phase 7/8 infra must probe an actual query or it will keep reporting an
             availability the system does not have
        ✅ P6.5.4 Dependency loss (ml-service → 0 replicas): client behaviour CORRECT —
             typed RFC 7807 503, never a raw 500. But /readyz returned 200 THROUGHOUT while
             every query failed, because readiness consulted only the vector store.
             Embedding is the first step of retrieval, so an unreachable embedder is exactly
             as disqualifying as an unreachable index. FIXED: readiness now checks both,
             concurrently. Redis/Postgres deliberately EXCLUDED — losing either degrades but
             still answers, and failing readiness on a partial loss removes the whole
             deployment for no benefit (D21)
        ✅ P6.5.5 Broken deploy (nonexistent image tag) under load → ErrImageNeverPull, the
             pod never became Ready, `rollout status` correctly TIMED OUT rather than
             falsely reporting success, old pods served throughout, rollback clean:
             90 ok / 0 fail. This is what maxUnavailable:0 buys — a completely broken
             deploy with ZERO user-visible impact
        ✅ P6.5.6 docs/K8S_DRILLS.md — every drill, the measurement, the fix, and the
             caveat on what the drain number does not prove

    🔄 P6.6 terraform plan reviewed (no apply) — 2 / 3 — same blocker as S16.7

        ✅ P6.6.1 HCL proven OFFLINE — `fmt -check -recursive` clean, `validate` Success.
             Config = 3 modules + 9 direct resources (VPC/EKS via modules; RDS, ElastiCache
             replication group, 2 SQS queues incl. DLQ, 2 security groups, IAM policy)
        ⏳ P6.6.2 Plan against real AWS — BLOCKED on credentials (Track D.1)
        ✅ P6.6.3 Blocker documented — validate proves SYNTAX + type/reference correctness;
             only a plan proves the account can actually satisfy it (quotas, AZ capacity,
             IAM permission to create, name collisions). Those are exactly the failures
             that cannot be caught offline, which is why the step stays open rather than
             being marked done on the strength of `validate`

    🔄 S17 CI/CD + eval gate proof [D16] — 5 / 7 (.6/.7 written, unexercised by design)
         All 5 workflows pass `actionlint`. Local gate green: 324 tests, ruff, mypy.

        ✅ S17.1 images.yaml — build · scan · push, matrix over the 3 services.
             Unblocked BY P6.1a: at 8.84 GB each, three images did not fit a runner's
             ~14 GB; at 2.32/1.95/2.32 they do. GHCR not ECR (no AWS creds — Track D.1;
             registry is a 2-line swap, which is the vendor-portability principle).
             NO `latest` tag — S16 recorded that the demo's :latest-only tagging made
             rollback impossible: there was no earlier tag to roll back TO.
             Adds an image-hygiene assert (non-root + no pip) because a base-image bump
             can silently reintroduce both and nothing else would notice.
        ✅ S17.2 ci.yaml split into unit / integration jobs with real services.
             VERIFIED the split selects work rather than silently passing: 10 integration
             + 311 unit = 321 collected. An integration job that matches nothing is a
             green tick for tests that never ran.
        ✅ S17.3 EVAL GATE BLOCKING — PROVEN, and proving it found 4 defects in the gate:
             (a) UnicodeEncodeError: the delta table renders → and ✅; on a cp1252 console
                 `print(table)` crashed. It ran BEFORE the gate check, so the gate NEVER
                 EVALUATED and delta.md was never written — every run exited 1 from the
                 traceback, indistinguishable from a real regression, and a passing run
                 could never go green. Fixed at the entry point + verdict now computed
                 and persisted BEFORE display.
             (b) `latest_report` picked an ALL-ERRORED demo run (my 404'd re-run) as the
                 baseline; the delta then read `error_rate 1 → 0` as **PASS**. Now skips
                 reports with no completed cases, and says which it skipped.
             (c) name-sort put `-rescored` BEFORE `.json` ('-' < '.'), so the corrected
                 report lost to the buggy one it was created to replace
                 (refusal_correctness 0.45 stale vs 0.70 corrected). Now ranks by
                 (run id, derivation) so a correction outranks its original.
             (d) my own rejudge checkpoint sidecar matched the *.json report glob, and an
                 empty `{}` passed the guard because it DEFAULTED `completed` to 1.0.
                 A guard whose default is "fine" only guards inputs that were already fine.
             END STATE: gate selects demo-...-rescored vs pipeline-...-rescored-rejudged,
             fires BOTH warnings built earlier this session (JUDGE MISMATCH, THIN COVERAGE
             n=1/60), and BLOCKS with exit 1 on dont_know_correctness, refusal_correctness,
             unsafe_answer_rate. 5 tests pin the exit-code CONTRACT, incl. one that runs
             the gate against a cp1252 stdout so the original defect cannot return.
        ✅ S17.4 load-smoke.yaml — TIER=guard, chosen by cost not convenience: `full` burns
             provider quota at 2 RPS, `cache` needs a warmed full index, `guard` refuses
             before embedding (6 ms, P5.2.3) yet still exercises HTTP + middleware + rate
             limiting + guardrail — where P5.2 found 3 defects no unit test surfaced.
             Seeds a 50-doc index because readiness now REQUIRES a non-empty one (P6.3.5).
        ✅ S17.5 Security stages — gitleaks (full history) + pip-audit in ci.yaml; Trivy
             vuln AND secret scans in images.yaml, scanning the loaded artifact BEFORE it
             can reach a registry (P6.1.3 found tests/ with a fake gsk_ literal inside the
             images but in no tracked source path).
             pip-audit non-blocking BY DECISION with the reason recorded: its findings have
             no available fix (langchain fix needs LangChain 1.x, which breaks ragas 0.4.3,
             already latest). A gate that cannot be satisfied gets bypassed, and then it
             guards nothing.
        🔄 S17.6 Deploy to dev — WRITTEN, NEVER EXERCISED, deliberately. There is no cluster
             and P7.1 (vendor selection) is still open, so the apply step would be a guess
             at DOKS-vs-EKS auth/registry/secrets that Phase 7 rewrites. What IS
             vendor-independent is encoded now: immutable-tag enforcement (refuses
             `latest`/`main`), `--atomic` rollback, and a post-deploy smoke that must assert
             BOTH readiness checks (P6.5.4: one-dependency readiness reports Ready while
             every query fails). One TODO(P7) marker per environment.
        🔄 S17.7 Promotion workflow — same file, same status. The promotion CONTRACT is
             defined (dev auto → staging needs images+eval+load green → prod needs staging
             smoke + manual reviewer + an existing rollback target), with approval held in
             GitHub Environments rather than in this file, so it cannot be bypassed by the
             same PR that deploys.

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
