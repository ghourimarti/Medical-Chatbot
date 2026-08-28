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

PHASE 4 — Execution 🔄 17 / 22
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
               ⏸️ S6.12f Money chart + valid faithfulness — SCOPE NARROWED BY EVIDENCE.
                    Re-attempted the rejudge 2026-08-25: 17 min, batch-size 4, ZERO batches
                    completed. The checkpoint writes at every batch boundary, so 0 entries
                    proves 0 successful batches — every one 429'd through 3 attempts x 20s
                    backoff. Same signature as the prior run. Killed rather than spin: the
                    daily cap had already been drawn down by today's calibration run.
                    Confirmed by MEASUREMENT, not assumption — the checkpoint is the capacity
                    check that a liveness ping is not.
                    AND: even when the tokens exist, S6.12f can NEVER deliver a before/after
                    faithfulness DELTA. Already recorded in EVAL_S6_FINDINGS Defect 4 — Groq
                    retired both the baseline's generator (llama-3.1-8b-instant) and its judge
                    (llama-3.3-70b), and the 2026-07-10 report predates context persistence,
                    so 0.6634 has no reproduction path. Deliverable is the ABSOLUTE pipeline
                    faithfulness under judge_v2 vs the 0.85 gate. Deterministic metrics
                    (citations 0.000 -> 1.000) are judge-independent and carry the money chart.
                    FIX DESIGNED (not yet built) — see below.
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

    ✅ S10 Next.js UI [D8, D23–D27b] — 17 / 17
          ✅ S10.0 Recon — read the RUNNING contract, not the brief. Found 4 gaps: no CORS
               anywhere, no user/conversation model, no public status endpoint, and the
               refusal category computed then discarded
          ✅ S10.1 Decisions D23–D27b → docs/DECISION_LOG_S10.md. D23 BFF proxy (allowlist,
               not passthrough) · D24 Clerk, chosen by you over my Auth.js recommendation,
               accepted cost + flip-trigger recorded · D26 no TanStack · D27 tokens ·
               D27b two densities
          ✅ S10.2 Backend gap closure — refusal_category surfaced + public /api/v1/status
               🔴 S10.2b DEFECT: the output dosage guardrail — the code's own "last line of
                  defence" — ran ONLY in answer(). stream_answer() had no output check at
                  all, and the browser uses that path for every question. Hidden because
                  the eval harness calls answer_verbose() and test_streaming.py asserted
                  nothing about dosages. Pre-fix the regression test observed
                  kind=GROUNDED text="Take 500mg twice daily." — a dose delivered as a
                  cited medical answer. New client contract: done.text is AUTHORITATIVE
          ✅ S10.3 Skeleton + BFF proxy. STREAMING PROVEN, not assumed: mock upstream at a
               120ms cadence, tokens arrived 178/303/427/552/675/799ms — cadence preserved,
               no buffering. Allowlist blocks /admin, /metrics and traversal
          ✅ S10.4 Design system — 30 contrast pairs measured BEFORE styling anything (2
               tokens moved as a result)
               🔴 RefusalCategory drift: the TS union listed 5 of the backend 8, and the
                  missing `harmful` carries crisis-helpline copy — it would have rendered
                  as a routine amber refusal. check-contract.mjs now fails on any drift
               🟠 EmergencyCard hardcoded "This may be a medical emergency" for every
                  urgent category, so a self-harm disclosure got clinical-alarm framing.
                  Split into medical vs crisis voice
          ✅ S10.5 Chat core — sources-first streaming, discriminated-union state machine.
               Cancellation PROVEN end to end: client abort → BFF → API logs "client
               disconnected mid-stream; provider stream aborted" (spend actually stops)
          ✅ S10.6a 🔴 THE LARGEST FINDING. query_stream() enforced NONE of the
               cross-cutting controls query() had — no rate limiting, kill switch, cache,
               spend accounting, history or session. Measured, one session, 25 requests:
               /api/v1/query returned 429 after the 20th; /api/v1/query/stream returned
               25x 200. The deployed rate limit was bypassable by using the default
               endpoint, and the kill switch could not stop browser traffic during a cost
               incident. Fixed by EXTRACTION into medapi/serving.py — not duplication,
               which is what drifted in the first place. 14 parity tests assert every
               control on BOTH paths, proven to fail on the stream variant when reverted
          ✅ S10.6b Browser verification (Playwright pulled forward). Next.js injects its
               own role="alert" into every page, so a bare role query can never assert
               "no alert"; and prose is a poor test hook because the sr-only aria-live
               region duplicates it. data-answer-kind now carries the RESOLVED treatment
          ✅ S10.7 Citations — inline markers open their passage; an out-of-range marker
               ([9] with 3 passages) renders as PLAIN TEXT, never a link. Uncited-but-
               retrieved passages are labelled, not hidden
          ✅ S10.8 History · re-ask · retry · delete-my-data (reports rows removed)
               🔴 DEFECT: a READ was minting a session. GET /session/history resolved-and-
                  attached unconditionally, so a first-time visitor raced their own first
                  question — both cookie-less, both minting, whichever Set-Cookie landed
                  last orphaning the other session history. Symptom: history intermittently
                  missing, caught only because a browser test failed about one run in two
          ✅ S10.9 Designed failure states per CAUSE — 429 quota (deliberately NO retry
               button: retrying fails identically), 503 retrieval, 502 provider, degraded
               banner driven by /api/v1/status on mount. None of them use red
          ✅ S10.10 Six public pages + live status page + footer. /sources lists the topics
               VERIFIED absent from the corpus so a user can check the claim
               🔧 fixed `make web-preview`: the @echo note used BACKTICKS, which in a
                  Makefile recipe are command substitution — `pnpm start` actually ran from
                  the repo root (ERR_PNPM_NO_IMPORTER_MANIFEST_FOUND). Added web-stop for
                  EADDRINUSE. Third "comment that was not inert" this session
          ✅ S10.11 Transparency panel — and reading REAL responses (not the schema) found
               two ways a faithful rendering would lie: a cache hit returns the ORIGINAL
               generation timings (50ms request reporting total_ms 2054) and the ORIGINAL
               cost, which is what reuse AVOIDED, not what it spent. Both relabelled.
               $0 renders as "not billed per token", never "$0.00"
          ✅ S10.12 a11y · mobile · perf budget. axe: ZERO WCAG A/AA violations across 8
               routes, both themes, and an answered page
               🔴 a completed answer was NEVER ANNOUNCED: the only live region lived inside
                  the streaming view, and a cache hit has no streaming phase, so a
                  screen-reader user was told nothing. Persistent polite region added
               🟠 the skip link is unreachable by forward tabbing on the landing because
                  autoFocus starts inside the question box. KEPT deliberately, documented
          ✅ S10.13 Mocked-SSE client contract + CI split. The retracted-dose contract
               (done REPLACES streamed tokens) had NO browser test — now covered and proven
               to bite. @live tagging: 24 live · 35 CI-safe, verified against a GENUINELY
               dead backend, which caught a mis-scoped status test
               🔧 fixed output:"standalone" making `next start` unsupported, so `pnpm
                  preview` was an invalid combination that failed intermittently. Now
                  opt-in via BUILD_STANDALONE for the Docker build only
          ✅ S10.14 Dockerfile + web service in docker-compose.app.yaml. 409MB (API 2.32GB),
               non-root uid 10001, npm/npx/corepack stripped from the runtime
               🔴 .env.example documented NEXT_PUBLIC_API_URL that NOTHING reads — worse
                  than inert, since NEXT_PUBLIC_* is inlined into the browser bundle and so
                  implied the browser dials the API directly
               🟠 ERR_PNPM_IGNORED_BUILDS: a warning scrolled past locally is a hard failure
                  non-interactively; it would have broken the S10.13 CI workflow too
               🟠 corepack downloads whatever pnpm is LATEST, so the same commit built
                  differently on different days. packageManager now pinned
          ✅ S10.15 docs/FRONTEND.md — every file path and route in it verified to exist
               and return 200
               🔴 the project OWN env-drift guard fired on UPSTREAM_TIMEOUT_MS: correct,
                  but its scope only covered Python readers while the web tier now reads
                  .env too. Extended and re-proven to bite

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

    🔄 S13 Multi-venue serving [D4, D4b, D12] — 7 / 9
        ✅ S13.1 OpenAICompatModel
        ✅ S13.2 Venue registry
        ✅ S13.3 Local venue
        ✅ S13.4 Groq venue
        ⏸️ S13.5 RunPod venue — Track D
        ⏸️ S13.6 AWS venue — Track D
        ✅ S13.7b Chain contract RECONCILED — config.py documented `venue-engine` entries
             and called openai "a real chain venue"; venues.py rejected both. The config's
             OWN example `local-vllm,local-sglang,openai,groq` failed to parse. Another
             session landed ChainLeg + the openai venue mid-session; I updated the 8 tests
             that still asserted the old contract (did NOT touch venues.py while it was
             being written — racing it is how work gets lost).
             CORRECTED MY OWN S13.7 CLAIM: "two engines on one GPU do not cross a failure
             domain" was too absolute. local-vllm -> local-sglang covers an ENGINE fault
             (crash, OOM, bad build) and nothing when the GPU dies — a PARTIAL domain.
             Worth having, never sufficient; a hosted leg still belongs last.
             370 tests green. .env.example de-drifted.
        ✅ S13.7 SGLang leg — `serving_engine` was DEAD CONFIG: declared in Settings,
             read nowhere, `vllm_local_url` hardcoded, so SERVING_ENGINE=sglang silently
             served vLLM (same defect shape as semantic_cache_enabled in S19.4).
             GPU venues now resolve `{engine}_{venue}_url`; Groq ignores it (hosted API,
             no engine of ours to pick). SGLang is deliberately NOT a SERVING_CHAIN entry
             — two engines on one GPU are not independent failure domains (D12 v2.1).
             A missing engine URL is a WARNING naming the engine, never a silent downgrade
             to Groq. Found drift while wiring it: benchmark doc says :1111, live port
             scheme is :5010. 4 tests, .env.example documented.
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
        🔄 S19.2 Judge calibration vs human labels — 48 labels IN; 6 defects found — 9 / 10
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
            ✅ S19.2h 48/48 labelled → REAL κ at last (variance, not the paradox):
                 refusal_correctness 0.68 substantial · dont_know_correctness 0.60 moderate
            ✅ S19.2i DEFECT: a dose outranked politeness — "400mg every 6 hours… Consult
                 your doctor" scored a clean redirect. S12.3's dosage filter already caught
                 it; the scorer never asked. Now vetoes.
            ✅ S19.2j DEFECT: "I don't know, BUT here's the answer" scored as an honest
                 abstention. New `abstains_cleanly` requires admit-the-gap-AND-STOP.
            ✅ S19.2k DEFECT: calibration scored LOOKALIKES — calibrate.score called
                 contains_refusal/expresses_uncertainty while the gate runs classify_safety/
                 abstains_cleanly. It was certifying code the pipeline never executes.
                 Post-fix κ 0.85 / 1.00 — FITTED, not independent; plants now spent.
            ⏳ S19.2l faithfulness + answer_relevancy κ — still unmeasured (Groq TPD);
                 strictness=1 fix is in, needs the daily reset
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

    🔄 S17 CI/CD + eval gate proof [D16] — 5 / 7 (.6/.7 written, unexercised by design)
         FIRST REAL RUN (you pushed) — 3 workflows failed, and each failure was worth more
         than a green tick. actionlint-clean is NOT "will run":

         🔴 A1 THE SAFETY POLICY WAS NEVER IN GIT. `.gitignore` line `Prompts/` had no
              leading slash, so it matched a directory of that name at ANY depth — and on
              Windows, case-insensitively — silently swallowing
              packages/core/src/medcore/prompts/. CI: `prompt system_v1 not found;
              available: []`. The refusal rules, injection defence and citation
              requirement existed only on this machine; a fresh clone could not start, and
              D6's "prompts are versioned as code, reviewed like code" was false.
              Invisible locally because the files were there and every local run passed.
              FIXED: anchored to /Prompts/ and /demo/. Verified both directions —
              packages prompts now tracked, top-level folders still ignored.
         🔴 A2 `aquasecurity/trivy-action@0.28.0` does not exist (7-second failure).
              actionlint validates YAML and expressions; it cannot know whether a third
              party's version tag is real. FIXED to @0.35.0, confirmed via the releases API.
         🔴 A3 No corpus in CI: the Gale PDF is correctly untracked (27 MB, copyrighted,
              /demo/ ignored) so `medworker-ingest` has nothing to index — and MY OWN
              P6.3.5 readiness fix now REQUIRES a non-empty index, so the API cannot start.
              Blocks load-smoke and the nightly eval-gate. Needs a small committed fixture
              corpus (follow-up).

         💰 BILLING (repo is PRIVATE — every minute is billed):
              images    push-to-main → TAGS + manual only (3 × 2.3 GB builds per merge
                        paid for artifacts nobody deployed)
              load-smoke push → manual only (cannot pass until A3; was billing to fail
                        identically every time)
              eval-gate nightly cron DISABLED — it had failed every night on A3. A
                        scheduled job that always fails is worse than none: it trains you
                        to ignore the notification. Also costs a day of judge quota per run.
              ci        unchanged: ~2-3 min, and it is the one that caught A1.
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
    ✅ S20 Users + conversations schema [D24] — completed in another session
          ✅ auth.py — Clerk JWT verification against JWKS; DisabledVerifier when
               CLERK_JWKS_URL is empty (presenting a token to an unconfigured service is a
               client error, NOT a silent anonymous downgrade)
          ✅ conversations.py — 6 endpoints: list · create · messages · rename · delete ·
               auth/claim
          ✅ Caller(session_id, user_id) — a conversation is owned by the USER when signed
               in and by the anonymous SESSION otherwise, which is what lets the sidebar
               work with no account
          ✅ QueryRequest.conversation_id — caller-supplied and treated as UNTRUSTED;
               ownership verified in serving.preflight (the S10.6a extraction) before
               anything is written

    ✅ S21 Clerk auth + conversation sidebar [D24] — 8 / 8
          ✅ S21.1 Recon — read S20 real contract rather than the plan description.
               Decisive finding: list_owned matches on session_id when user_id is None, so
               the whole feature is buildable AND verifiable with no Clerk credentials
          ✅ S21.2 Verified the full lifecycle anonymously against the live API FIRST —
               create · ask-into-thread · messages · rename · claim (no-op while anonymous)
               (the running API container predated S20 files and 404d; rebuilt)
          ✅ S21.3 Proxy allowlist extended to its first DYNAMIC segment. Matched segment
               by segment against a UUID pattern, not a loose regex, which would have
               matched v1/conversations/../../admin/status. Verified admin, non-UUID and
               traversal all 404
          ✅ S21.4 Bearer token MINTED SERVER-SIDE from the verified session. `authorization`
               is deliberately absent from the forwarded headers, so a client cannot present
               a token of its choosing through the proxy
          ✅ S21.5 useConversations — optimistic rename (trivially reversible), NON-optimistic
               delete (it destroys stored health questions)
          ✅ S21.6 Sidebar — create · select · rename · delete-with-confirmation · anonymous
               notice that states the CONSEQUENCE ("saved to this browser") rather than
               dangling a signup prompt. Titles come from the user and are NEVER derived
               from the question: a thread auto-titled "Chest pain at night" is readable by
               anyone glancing at the screen. No red button (red is reserved, D27)
          ✅ S21.7 Clerk genuinely OPTIONAL — no publishable key means no provider, no Clerk
               JavaScript loaded, no sign-in button, matching the backend DisabledVerifier.
               One test fails if any Clerk network request is made
          ✅ S21.8 8 browser tests · env vars documented · 352 py + 68 browser green
          ⏳ sign-in / auth-claim UNVERIFIED — this machine has no Clerk credentials. The
               integration is built and the DISABLED path is fully covered; enabling needs
               NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY, CLERK_SECRET_KEY and CLERK_JWKS_URL
               (Track D)


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

INFRA — layered local stack ✅ (env + compose + Makefile restructure)
     ✅ I.1 .env / .env.example rewritten — every credential and port controllable, 5000-range
          ports sequenced by STARTUP order (data 5001-5005, app 5006-5010, obs 5011-5022),
          [live]/[infra]/[inert] tags, names generated FROM the Settings fields so nothing
          documented is silently unread. Real secrets preserved.
          🔴 FOUND: `VAR=   # comment` gives python-dotenv the COMMENT AS THE VALUE (a trailing
               comment is only stripped when a real value precedes it). VLLM_RUNPOD_URL,
               VLLM_AWS_URL, OPENAI_API_KEY, SQS_QUEUE_URL and HF_HOME all became non-empty
               garbage, so the failover chain believed two GPU venues were configured and the
               worker believed it had a queue. 13 comments moved above their line + a
               regression test whose premise I verified by simulation.
          🔴 FOUND: EMBEDDING_DIM cannot be set from env at all — Literal[1024] vs env strings.
               It broke 18 tests. Commented out with the reason; changing the dimension means
               a new collection and a full re-embed, not an env edit.
     ✅ I.2 docker-compose.yml split into three tiers — data / app / observability.
          app.yaml is deliberately NOT standalone (it depends_on data services); the worker is
          profile-gated because a queue-less consumer that restarts forever trains you to
          ignore red status (same reasoning as values-kind.yaml); no `web` placeholder because
          S10 is deferred and a container that cannot start is worse than an honest absence.
     ✅ I.3 Makefile: db / app / obs / up / upv / down / downv / worker / ps / logs / migrate /
          seed / urls. Project prefix for volume deletion is resolved AT RUNTIME because this
          repo's path contains spaces and `&` — the sample's warning applies here exactly.
          `migrate` pipes scripts/migrate.py over stdin rather than baking scripts/ into the
          image (P6.1 keeps images to what serves traffic).
     ✅ I.4 VERIFIED LIVE end-to-end in containers — kind=grounded, 4 citations, both
          readiness checks true. Steady-state timings embed ~250-390ms / retrieve ~10ms /
          rerank ~1.1s (rerank dominates, consistent with S5.9).
          🔴 FOUND: ml-service `--wait` timed out at ~355s while the service was seconds from
               ready. start_period (60s) is a GRACE window and must cover the WORST legitimate
               start — a cold boot downloads ~2.4GB of weights. Raised to 600s; a warm boot
               still reports healthy in ~15s because the window ends at the first pass.
          ⚠ UNVERIFIED: infra/postgres/init/ never executed — Postgres runs initdb.d only on an
               EMPTY volume and this one had data. The `langfuse` DB exists from an earlier
               session, so the script is correct-by-inspection but untested until a
               `make downv && make db` cycle.

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
          ✅ P6.4.7 NetworkPolicy — MAJOR FINDING: the policies are DECLARED but NOT    ENFORCED.
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

PHASE 7 — Real managed Kubernetes 🔄 1 / 12 (DigitalOcean first, vendor-portable)
     ✅ P7.1 Vendor selection + cost model — docs/VENDOR_SELECTION.md. DOKS COMMITTED
          (not just recommended), with the 4 criteria that would reverse it stated in
          advance so they are criteria, not rationalisations. This is the decision
          S17.6/S17.7 were blocked on.
          Cost model sized from the chart's ACTUAL requests (2.45 vCPU / 4.9 Gi at rest,
          7.5 / 15 at HPA max), not guessed: DOKS ≈ $121/mo vs EKS ≈ $245/mo.
          ~$105 of the gap is TWO line items with no DOKS equivalent — EKS control plane
          ~$73 and NAT gateway ~$32 (the most-forgotten line in an EKS estimate, billed
          hourly whether or not traffic flows).
          Finding: at portfolio scale $/query is an IDLE-CAPACITY number, not a throughput
          one — ~$40/1k queries at 100/day vs ~$0.02/1k saturated. Quoting the saturated
          figure would describe a machine that will never be busy.
          $200 DO credit ≈ 7-8 weeks on DOKS vs ~3.5 on EKS → teardown runbook (P7.12)
          matters. Prices labelled list-price-to-verify; the SHAPE survives price drift.
          Also corrected docs/DEPLOYMENT_PHASES.md — it still carried the S15.5 ESTIMATE
          of 3.4 GB CUDA; P6.1a MEASURED 6.5 GB per image. Estimate was half the truth.
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

PHASE 9 — Portfolio 🔄 5 / 6
     ✅ P9.1 Architecture diagram — docs/ARCHITECTURE.md, 5 MERMAID diagrams (render on
          GitHub, live in git, change in the same commit as the code — a PNG would be
          stale within a week and nobody would know). Request path · failure domains ·
          alias-swap ingestion · one-chart-three-vendors · package boundaries + an
          invariants table
     ✅ P9.2 README rewrite — README.md was EMPTY (0 lines), the first thing any reviewer
          opens. Leads with FINDINGS, not architecture. Carries a "proven vs built but
          unexercised" ledger so validated ≠ applied. Every caveat kept: the stale
          pre-guardrail safety row, the judge mismatch, answer_relevancy n=1/60, and the
          latency REGRESSION shown rather than hidden.
          Found + fixed drift while verifying: README said :1107, live scheme is :5007
     🔄 P9.3 Before/after metrics story — structure + delta table done and honest about
          its 3 caveats; the faithfulness row waits on S6.12e (daily judge cap)
     ✅ P9.4 Findings writeup — docs/FINDINGS.md, 19 measurements that refuted an
          assumption, with the through-line stated: THE MEASURING INSTRUMENT WAS WRONG
          MORE OFTEN THAN THE SYSTEM. Over half were a scorer/probe/test/config knob —
          every one of them green beforehand. Includes the two that refuted MY OWN
          recommendation (ONNX 0.95×, D10's aspirin premise at 0.8235)
     ✅ P9.5 Screenshots surfaced — 12 existed, generated by the e2e suite, presented
          NOWHERE. The four answer kinds now render in the README with the reason
          category-specific refusals beat one generic refusal. Cannot drift: the e2e
          suite regenerates them. (Demo VIDEO not made — needs a recorder + narration)
     ✅ P9.6 Interview talking points — docs/INTERVIEW.md: 60-second pitch, senior-vs-junior
          table (11 rows), 6 hard questions answered honestly, numbers to memorise, gaps
          to volunteer BEFORE they are found, and 5 questions to ask them

TRACK D — user-side async ⏳ 1 / 5

    ⏳ D.1 AWS quota request
    ⏳ D.2 RunPod account
    ✅ D.3 HF token
    ⏳ D.4 DigitalOcean account + apply $200 credit
    ⏳ D.5 cgroup v2 in WSL2 — unblocks newer kind node images

INFRA-2 — operability pass ✅ (engines, kind lifecycle, env, dashboards, verification)
     Requested as 11 items; every one verified LIVE rather than declared.

     ✅ I2.1 SERVING_CHAIN is now an ORDERED PREFERENCE LIST of `venue-engine` legs:
          `local-vllm,local-sglang,openai,groq`. Chosen over priority numbers because
          numbers split identity from order into two places that can disagree, and
          inserting a leg means renumbering the rest.
          🔴 FOUND: S13.7 had made SERVING_ENGINE an either/or SELECTOR — you could run
             vLLM OR SGLang, never "vLLM, and if the engine faults, SGLang". D12 v2.1 had
             actually asked for the second thing. SGLang is reachable as a failover leg now.
          🔴 FOUND: OPENAI_API_KEY was config NOTHING read (the dead-config shape again).
             `openai` is a real venue; no key = leg SKIPPED, never a runtime 401.
          ✅ The skip warning names WHERE the engine came from — your explicit
             `local-sglang` entry or the SERVING_ENGINE default are fixed in different
             places, so "no sglang URL" alone sent you hunting.

     ✅ I2.2 vLLM + SGLang in compose (docker-compose.gpu.yaml), GPU auto-detected.
          WSL2 UVA fix and HF_TOKEN carried over from S3b; ONE weights volume for both.
          ✅ `make downv` keeps weights AND images. Removing them is deliberate and
             separate: clean-images / clean-models / clean-all.
          ✅ INDEPENDENT control: vllm-up/-down/-upv/-downv, sglang-*. Each -up prints a
             5-part test guide (liveness → generation → browser → GPU/bench → "is the APP
             actually using it"). -downv warns the cache is SHARED before deleting it.
          ✅ `make webui` — Open WebUI on :5024, ChatGPT-style, model picker switches
             vLLM ↔ SGLang on the same prompt. Deliberately the UNGUARDED path: judging
             ENGINE quality there and PRODUCT quality on :5008 keeps a bad retrieval
             config from being blamed on the model.
          🔴 FOUND: the api container had no in-network engine URLs. localhost:5009 is
             unreachable from inside the API container, so the whole GPU half of the chain
             was dead from the app's view while looking perfectly configured from the host.

     ✅ I2.3 kind nodes now follow the stack lifecycle — the three stray containers you
          saw after `make down` were the cluster's nodes.
          up → start (or create) · down → STOP · downv → DELETE · upv → recreate,
          mirroring the preserve/destroy split the data volumes already use.
          TESTED: stop → 0 containers, start → 3 nodes Ready.
          🔴 FOUND: after a node restart kubectl fell back to localhost:8080
             ("current-context is not set") because kind reassigns the API-server host
             port. kind-start re-exports the kubeconfig.
          🔴 FOUND: the target claimed "still settling" while nodes were Ready —
             `kubectl wait` exits immediately on connection-refused instead of retrying.
          🔴 FOUND: `$(MAKE)` inside a shell conditional. GNU make executes those even
             under `-n`, so a DRY RUN of kind-start could have created a real cluster.

     ✅ I2.4 .env / .env.example rewritten — one boxed section per SERVICE, comments ABOVE
          every value, generated from ONE spec (scripts/gen_env.py) so they cannot drift.
          🔴 FOUND: my own first generation silently DROPPED 16 LIVE settings (rate
             limits, cache TTLs, circuit breakers) — they fell back to code defaults with
             nothing reporting it. Added a guard that FAILS if any Settings field is
             undocumented. A generator that can quietly delete configuration is worse than
             the two hand-edited files it replaced.
          🔴 FOUND: preserving values kept LANGFUSE_PUBLIC_KEY EMPTY, which silently
             disabled tracing while every container reported healthy. FILL_IF_EMPTY now
             covers local bootstrap identifiers — and deliberately excludes
             OPENAI_API_KEY / VLLM_RUNPOD_URL, where empty means "skip this leg".
          🔴 FOUND: the project's own env-drift guard looked for [infra] tags on the SAME
             line as the assignment, which the safer above-the-line layout broke. Guard
             now reads the comment block above.
          ✅ 25 genuinely inert keys dropped (Langfuse-v3 leftovers, *_DOCKER duplicates,
             the dead NEXT_PUBLIC_API_URL). Real secrets preserved; .env.bak kept.

     ✅ I2.5 Langfuse traces with ZERO manual steps — headless bootstrap creates the org,
          project and user and PINS the API keys to the .env values the app already sends.
          VERIFIED: authenticated with those keys, HTTP 200, project "Medical RAG Chatbot".

     ✅ I2.6 Grafana provisioned — datasource with a FIXED uid (so committed dashboards
          stay portable) + a 14-panel dashboard generated FROM the real metric names in
          metrics.py, not hand-written against remembered ones. Anonymous Viewer = no
          login, and Viewer rather than Admin so a stray click cannot edit a provisioned
          dashboard. VERIFIED: unauthenticated API call returned both datasources and the
          dashboard.

     ✅ I2.7 RedisInsight working, databases pre-registered by an idempotent seeder.
          VERIFIED BOTH BRANCHES: deleted the entry, seeder re-added it; ran again, it
          skipped. 🔴 FOUND: `connectionType` is a RESPONSE field — sending it made
          RedisInsight reject the payload with a bare 400 naming no field.
          🔴 FOUND: the script had CRLF endings, so busybox reported `set: illegal
             option -` — an error naming neither the file nor the cause. Added
             .gitattributes so it cannot recur on checkout.

     ✅ I2.8b 🔴 FOUND while verifying: OTEL_ENABLED=false and OTEL_ENDPOINT= (empty) in
          .env. Jaeger would have shown an EMPTY TRACE LIST FOREVER while every container
          reported healthy — the exact failure Jaeger was added to remove, reproduced one
          layer down. Both values predate there being anywhere to send traces, and
          --write-env faithfully preserved them. OTEL_ENDPOINT added to FILL_IF_EMPTY
          (an empty exporter endpoint is never a deliberate configuration), OTEL_ENABLED
          set true now that a trace backend exists.
          THE PATTERN, three times in one session: Langfuse keys blank, OTEL endpoint
          blank, RedisInsight seeded nothing — each one silent, each one green.

     ✅ I2.8 Jaeger added — and it was NEEDED: the OTel Collector exported traces to the
          `debug` exporter, i.e. its own stdout and nowhere else. The instrumentation and
          the tail-sampling policy were both real and the traces were unreadable — the
          same "declared but not working" shape found elsewhere. Its own config comment
          said "production exports to Tempo/Jaeger instead".
          Also cut verbosity detailed → basic: it printed every span body, which is the
          log-amplification failure P5.2.7 already had to fix once.
          Complements Langfuse: Langfuse = what the model saw and what it cost,
          Jaeger = where the 1.8 seconds went.

     ✅ I2.9  `make up`/`upv` print every service URL, no credentials (it scrolls past on
          every start and ends up in screen shares).
     ✅ I2.10 `make service_ls` — full inventory WITH credentials and connection strings,
          live/down markers, pgAdmin-ready. Both read .env through ONE script, so the
          board cannot drift from what compose published.
     ✅ I2.11 docs/VERIFY_STACK.md — per-component verification, UI and CLI, ordered by
          dependency, including the failure drills. Written around two habits this project
          keeps re-learning: a liveness check is not a capacity check, and "declared" is
          not "working".

     Gate: 370 tests pass, ruff clean, all four compose files validate.

INFRA-3 — first REAL run of the full stack (findings that only running produces)
     Everything below was found by starting all 16 containers and using them, after the
     API image was rebuilt to accept the new SERVING_CHAIN syntax.

     🔴 I3.1 `make up` reported FAILURE over a completely healthy stack.
          `docker compose up --wait` treats ANY container exit as a failure — including the
          one-shot redisinsight-seed that correctly exits 0 after seeding. A command that
          cries failure when nothing is wrong is worse than no check: it teaches you to
          ignore the exit code. Seeder moved behind a `seed` profile and invoked right
          after the stack is up.

     🔴 I3.2 TWO ENGINES ON ONE 12GB CARD IS A DEADLOCK, NOT A CONFIGURATION.
          vLLM asks 0.80 of the GPU, SGLang 0.45 — 125% of an RTX 3060. It did NOT fail
          fast: SGLang took memory while vLLM was mid-load and vLLM WEDGED at "Starting to
          load model" for 15 minutes with no error line. Stopping SGLang afterwards did not
          release it; the container had to be recreated.
          FIX: `make up` starts vLLM ONLY. SGLang is opt-in (`make sglang-up`) for
          benchmarking or a failover rehearsal, on a box with headroom.
          PROVEN AFTER: vLLM alone reports "Free memory on device (10.98/12.0 GiB)",
          init 51.77 s, "Application startup complete", and generates:
            "Name three symptoms of asthma" -> shortness of breath / chest tightness /
            coughing / wheezing (prompt=38, completion=21 tokens).

     🔴 I3.3 open-webui was in the `gpu` profile, so `make up` depended on pulling a
          chat-UI image that serves no traffic. A debugging convenience must never gate the
          stack coming up. Now `webui` profile only.

     🔴 I3.4 THREE SEPARATE OTEL DEFECTS, each of which alone made Jaeger useless:
          (a) OTEL_ENABLED=false and OTEL_ENDPOINT= empty — spans created, exported
              nowhere. Fixed; OTEL_ENDPOINT added to FILL_IF_EMPTY.
          (b) OTEL_SAMPLE_RATIO=0.05 head-sampling. The Collector does TAIL sampling and
              can only decide about traces it RECEIVES, so a 5% head sample silently
              disabled "keep 100% of errors and slow requests". Worse, it does not drop
              whole traces — it drops individual spans, leaving ORPHAN FRAGMENTS.
              Now 1.0: send everything, let the Collector decide. That is the entire
              reason tail_sampling is in otel-collector.yaml.
          (c) THE REAL ONE: `instrument_app(app)` was called inside `lifespan`.
              FastAPIInstrumentor adds ASGI middleware and Starlette FREEZES its middleware
              stack when the app starts, so instrumenting from lifespan silently does
              nothing — no HTTP request span is ever created.
              Invisible because the EXPLICIT stage spans still worked: Jaeger showed traces
              containing a lone `embed` (471ms) or a lone `rerank` (2003ms). That reads as a
              sampling artefact, not as missing instrumentation.
              A PARTIAL TRACE IS WORSE THAN NO TRACE, BECAUSE IT LOOKS LIKE DATA.
              Fixed by wiring configure_tracing + instrument_app in create_app(), before
              the server starts. 248 API tests green.

     ✅ I3.5 CORRECTION to an earlier claim of mine: I reported the host->collector OTLP
          hop as failing. It was not. The in-container path works (`jaeger services:
          ['medbot-api']`); my host-run API was the anomaly, not the deployment path.

     ✅ I3.6 The rebuilt API resolves the new chain correctly:
          "serving chain: local-vllm -> local-sglang -> groq"

     🟠 I3.7 OPEN: superseded Qdrant collections accumulate without bound. A re-ingest
          builds `gale_live_vN`, repoints the alias, and leaves the previous collection in
          place forever — six were present after a handful of runs. Keeping ONE previous
          version is deliberate and useful (rollback is a single alias operation), keeping
          all of them is a leak: ~29MB per abandoned full-corpus copy. The ingest worker
          should drop versions older than the last N. Not fixed in this pass.

---

## INFRA-4 — Langfuse actually traces (raised mid-session: "I have to enter credentials
## and then public key private key — that's harsh, can you do it automatic")

The complaint was about friction. The finding underneath it was that Langfuse had never
recorded a single trace, and nothing anywhere said so.

     ✅ I4.1 Bootstrap was NOT the problem, contrary to the obvious guess. The org, project
          and both API keys were being created headlessly from .env, and `curl -u pk:sk
          /api/public/projects` returned HTTP 200 with the medbot project. There was never
          any need to sign up, create a project, or copy a key. Verified before changing
          anything — the fix for a problem you have not reproduced is a guess.

     ✅ I4.2 DEFECT 1 — version skew. `langfuse/langfuse:2` server, SDK `langfuse>=4.14.4`.
          The v3+ SDK ships spans over OTLP to /api/public/otel; a v2 server does not
          implement that route. Every trace was discarded.
          Why it was invisible: container up, /api/public/health `{"status":"OK"}`, keys
          authenticating with HTTP 200 — three green checks over a dead pipeline. And
          llm_trace.py swallows exporter errors ON PURPOSE (D21: observability must never
          fail a medical answer), which is correct and also removes the last symptom.
          Fixed: server -> `langfuse/langfuse:3`, matching the SDK the code was written
          against (`create_event` is v3/v4 API, not v2).
          v3 splits ingestion from serving, so it needs clickhouse (columnar span store),
          minio (blob store for raw payloads), redis db 1 (queue) and langfuse-worker.
          WITHOUT THE WORKER THE UI STAYS EMPTY even though ingestion succeeds.
          All four images were already local — zero pulls.

     ✅ I4.3 DEFECT 2, and the one that actually mattered — `trace_answer()` HAD NO CALLER.
          `grep -rn trace_answer apps/` returned only its own definition. The module was
          complete, configured, enabled, reachable and dead. Even on a correct server it
          would have traced nothing.
          Wired into `postflight()`, deliberately: `answer_from_done()` exists so streaming
          and non-streaming run the SAME accounting path, and tracing only the
          non-streaming branch would under-report exactly the requests users make.
          Guarded with contextlib.suppress — postflight runs AFTER the answer is final, so
          an exception there converts a delivered medical answer into a 500.

     ✅ I4.4 Regression guard: apps/api/tests/test_langfuse_wiring.py asserts the CALL
          happens, not what the payload contains. A unit test of trace_answer passed
          throughout the outage; testing the payload again would miss the defect again.
          4 tests. Full API suite 257 passed.

     ✅ I4.5 ClickHouse auth, self-inflicted and worth recording: I set
          CLICKHOUSE_SKIP_USER_SETUP=1, which skips APPLYING CLICKHOUSE_PASSWORD, leaving
          `default` password-less while Langfuse connected with the password. It surfaced
          as "Authentication failed" AFTER 200+ Postgres migrations had succeeded, so it
          read as a Langfuse bug rather than a ClickHouse one.

     ✅ I4.6 The friction that CANNOT be removed, stated plainly rather than worked around:
          Langfuse has no anonymous/viewer mode (Grafana does). One sign-in is unavoidable.
          `make langfuse` prints the bootstrapped credentials, opens the tab, and says
          explicitly that no project creation and no key copying is needed.

     ✅ I4.7 docs/VERIFY_STACK.md now says to verify Langfuse by COUNTING TRACES, never by
          health check, with both zero-trace failure modes written out. Three green health
          signals over a dead pipeline is the lesson worth keeping.

     🔵 I4.8 HANDOVER (user runs docker builds): the serving.py wiring is source-only until
          the API image is rebuilt.
              docker build -f apps/api/Dockerfile -t medbot-api:0.1.0 .
              docker compose -f docker-compose.data.yaml -f docker-compose.app.yaml \
                up -d --force-recreate --no-deps api
          Then ask a question and confirm totalItems > 0.

---

## Readiness — INFRA-3 follow-up found while verifying the seeded index

     ✅ I3.8 /readyz returned 503, and then hung past 20s, while the SAME API answered a
          grounded question with 4 citations throughout. Root cause: the readiness checks
          had NO timeout. Right after the 7,080-chunk ingest, Qdrant was optimising into
          its segments and `get_collection` blocked.
          Why this is serious rather than cosmetic: Kubernetes defaults
          readinessProbe.timeoutSeconds to 1, so an unbounded check is not "slow", it is
          recorded as a FAILURE — and it would hit every replica simultaneously right
          after a re-index. That is precisely the D11 alias swap this design exists to
          make seamless.
          Fixed with a 2s bound per check plus a 30s last-known-good grace window. A
          timeout is a THIRD state, not False: slow and absent look identical in one call
          but demand opposite verdicts. A definite False still fails immediately, with no
          grace, or a genuinely broken pod would keep serving for the whole window.
          5 tests in apps/api/tests/test_readiness_timeout.py.

     ✅ I3.9 test_integration.py leaked its Qdrant collection on failure — `delete_collection`
          was a trailing statement, so an assertion raised straight past it. A stray
          `test_3cb6c7fd` collection was sitting in Qdrant as proof. Now try/finally.
          Same unbounded-growth shape as I3.7, and a test that leaks state on failure makes
          the NEXT failure harder to read.

     ✅ I3.10 Corpus seed completed: alias `gale_live` -> `gale_live_v1787322516`, 7,080
          points, status green, 7,080 indexed vectors. Verify-then-swap worked as designed.
          Note the seed embeds ON THE HOST: `make seed` runs locally, where
          ML_SERVICE_URL=http://ml-service:8001 does not resolve, so it silently loads
          models in-process instead of using the running ml-service (0.21% CPU throughout).
          It works; it is the slow path.

---

## INFRA-5 — engine selection + a brutal inspection pass

     ✅ I5.1 make up-vllm / up-sglang / up-vllm-sglang, plus ENGINE= as the manual knob.
          ENGINE couples the profile AND the chain deliberately: starting vLLM without
          putting it in SERVING_CHAIN (or listing it without starting it) is the commonest
          way to believe you are benchmarking a self-hosted engine while Groq answers
          every request. Two files, one decision.
          ENGINE=both splits VRAM 0.42/0.42 at 4k context - MEASURED, because 0.80+0.45 =
          125% of a 12 GB card wedged vLLM for 15 minutes with no error at all.
          `make which-engine` prints configured chain, resolved chain, and who actually
          answered, because guessing is not verification.

     ✅ I5.2 Two correctness bugs found while building it, neither cosmetic:
          (a) `docker compose up` with a different profile does NOT stop containers outside
              it, so switching vllm->sglang left BOTH running and oversubscribed the card.
              up now removes the engine it is not using; down/downv use ALL engine profiles
              regardless of the current ENGINE.
          (b) env_file WINS over shell interpolation. With SERVING_CHAIN only in .env, the
              export reached compose and never reached the container: `make up-sglang`
              would start SGLang and still be served by vLLM. SERVING_CHAIN is now an
              explicit `environment:` entry with a ${VAR:-default} fallback to .env.

     ✅ I5.3 scripts/inspect_stack.py — 59 checks across 7 sections, each reading a value
          that exists ONLY if the component did its job. Exit code = failure count.
          First run: 42 passed / 9 failed / 8 informational.

     ✅ I5.4 FOUR DEAD METRICS, same shape as the Langfuse defect: declared in metrics.py,
          re-exported from observability/__init__, referenced by the Grafana dashboard, and
          never written. Every one scraped cleanly as 0 or absent.
              medbot_tokens_total         no caller anywhere
              medbot_ttft_seconds         computed in rag.py, carried on Answer, never observed
              medbot_venue_circuit_state  record_circuit() had no caller
              medbot_request_cost_usd     guarded by `if cost_usd:` so self-hosted ($0) never recorded
          The TTFT one is the worst: it is the headline NFR (p50 0.8s / p95 2.0s) and it was
          not being measured at all, while Grafana showed a panel and Prometheus was healthy.
          Fixed: tokens + circuit state in FailoverModel (the only place that knows BOTH the
          usage and the venue); TTFT threaded through record_answer from Answer.timings,
          streaming-only so the SLI is not silently redefined; cost observed ALWAYS including
          0.0, because absent and zero are different answers on a spend dashboard.
          _publish_states writes EVERY leg, not just the one that moved: a gauge written only
          when a venue is touched leaves untouched legs reporting stale values forever.
          4 regression tests asserting the CALL. Full suite 411 passed.

     ✅ I5.5 docs/INSPECTION.md — 14 queries to run in the UI, and for each one what must
          appear in Langfuse / Grafana / Prometheus / Jaeger, why that is correct, and what
          a wrong reading means. Includes the two non-obvious "absence is the evidence"
          cases: a cache hit must produce NO Langfuse trace (nothing was generated), and a
          guardrail refusal must produce NO generate span (no spend occurred).

     ✅ I5.6 Confirmed from inside the running image that the earlier fixes are LIVE
          (_trace_to_langfuse, instrument_app, _READINESS_TIMEOUT all present). Langfuse
          holds real traces and Jaeger shows a 72-span tree with HTTP parent spans, so
          INFRA-3/INFRA-4 are verified end to end, not merely committed.

     🔵 I5.7 HANDOVER: the four metric fixes are source-only until the API image is rebuilt.
              docker build -f apps/api/Dockerfile -t medbot-api:0.1.0 .
              docker compose -f docker-compose.data.yaml -f docker-compose.app.yaml \
                up -d --force-recreate --no-deps api

---

## INFRA-6 — the inspection found real defects, including three in the inspector itself

Your run of scripts/inspect_stack.py produced 40 passed / 10 failed. Three of those
failures were MY bugs, and the rest were real.

     ✅ I6.1 CONFIRMED WORKING from your run, not from my assertion:
          - `make up-sglang` resolved SERVING_CHAIN=local-sglang,groq end to end; SGLang
            reachable, vLLM correctly absent. The env_file-vs-environment fix holds.
          - All four previously-dead metrics now report: tokens 3,040 labelled
            venue=local-sglang, venue breakers closed, cost/request $0.000095.
          - Langfuse 49 traces, Jaeger span trees with HTTP parents. INFRA-3/4 verified.

     ✅ I6.2 MY BUG - UnicodeDecodeError on every run. subprocess `text=True` decodes with
          the LOCALE codec (cp1252 on a Windows console) and `docker logs` carries UTF-8.
          It raised on a reader THREAD, so the traceback printed while the call still
          returned: the inspection looked fine while silently losing all docker output,
          which is why "resolved at boot" and container states were unreliable.
          Fixed with explicit encoding="utf-8", errors="replace".

     ✅ I6.3 MY BUG - redisinsight-seed reported as a stopped container. It is a ONE-SHOT
          job that exits 0 on success. This is the third time that same exit(0) has been
          read as failure in this project (it also broke `make up`). Now excluded by name.

     ✅ I6.4 MY BUG - reading Prometheus for counters the script had just incremented.
          Prometheus scrapes every 15s, so "grounded: 0" printed one line below a
          successful grounded probe. It also summed series from DEAD container instances,
          reporting 1 error that no longer existed anywhere in the running process.
          Fixed: counters now come from the API's own /metrics (real-time, this process
          only); Prometheus is used only for quantiles, which need history by definition.
          Also: histogram_quantile over an empty histogram returns NaN, and `nan <= 0.8`
          is False - so an SLI nobody had exercised rendered as a FAILED threshold. "Not
          measured" and "measured and bad" now print differently.
          Re-run after fixes: 46 passed / 3 failed.

     ✅ I6.5 REAL DEFECT - RERANK_TIMEOUT was 2.0s against a MEASURED reranker p95 of
          2.425s. A timeout below the p95 of the thing it guards makes the degraded path
          the NORMAL path: the cross-encoder was being skipped on well over 5% of queries,
          serving fusion order instead of reranked order. Rerank is the quality step the
          whole retrieval design rests on (S5.9), so this quietly undid it.
          Raised to 4.0s. EMBED_TIMEOUT 5.0 -> 8.0: p95 is 2.35s so it looks ample, but
          ml-service runs bge-large on CPU, concurrency serialises, and a burst of probes
          blew the 5s budget - a 503, correctly, since without a vector there is nothing
          to retrieve. The real fix is a GPU reranker; this stops the fallback being
          routine. Pinned by a test asserting each timeout exceeds its measured p95.

     ✅ I6.6 REAL DEFECT - the reranker fallback was LOGGED AND NEVER METERED. No counter,
          so it could not be graphed or alerted on, and combined with I6.5 the system was
          serving degraded answers as its normal mode with every dashboard green.
          Added medbot_degradations_total{component,reason}. This is the same rule the
          codebase already states for the dependency breakers: a fix that hides its own
          failure signal has to publish one.

     ✅ I6.7 REAL DEFECT - `ml-service /embed failed: ` logged with an EMPTY cause. httpx
          timeout exceptions carry no message, so str(e) was blank and the 503 explained
          nothing. During an incident that hides the one fact that matters: refused
          connection vs. too slow, which have opposite fixes. _describe() now falls back
          to the exception type name. Applied to both /embed and /rerank.

     ✅ I6.8 A claim of mine, corrected: I read `"\embed"` in ml_client.py and called it a
          backslash bug. The raw bytes are `"/embed"` - it was a rendering artefact in the
          search output. Checked before reporting; no such bug exists.

     🔵 I6.9 STILL OPEN and honestly red:
          - request p95 11.80s vs the 6s NFR. Not a bug, a hardware truth: bge-large
            embeddings AND a cross-encoder reranker on CPU cannot meet it. Either the
            reranker moves to GPU or the NFR is wrong for this box. Do not "fix" it by
            tightening timeouts again - that is what I6.5 was.
          - 5 superseded Qdrant collections (I3.7, ingest still does not prune).

     🔵 I6.10 HANDOVER: metrics + timeout + error-message fixes are source-only.
              docker build -f apps/api/Dockerfile -t medbot-api:0.1.0 .
              docker compose -f docker-compose.data.yaml -f docker-compose.app.yaml \
                up -d --force-recreate --no-deps api

---

## INFRA-7 — inspecting the user's real frontend session found a SAFETY defect

Read back from Postgres, not from a test: 14 refused / 6 no_answer / 3 grounded.

     🔴 I7.1 THE SERIOUS ONE. A real query at 13:06:
              "I have been thinking about hurting myself."
          returned kind=no_answer, text "I don't have reliable information on that in my
          reference material."
          Cause: the SELF_HARM rule was `\b(kill|harm|hurt)\s+(myself|my ?self)\b` - the
          BARE verb only. `\s` cannot follow the "t" of "hurting", so the gerund missed,
          the disclosure fell THROUGH the guardrail into retrieval, matched nothing, and
          came back as a generic no_answer. Also missed: "killing myself", "harming
          myself", "ending it all", "better off without me".
          The gerund is the MORE common phrasing of ideation, so the rule missed the
          majority case while passing every test ever written against the minority one -
          the same "fitted to its own examples" failure S19.3 already recorded for v1.
          Fixed with (?:ing|s|ed)? on the verb group plus the missing markers.

     ✅ I7.2 Same defect one word wider in INJECTION: exactly ONE modifier was allowed
          between verb and noun, so "ignore all instructions" matched while "ignore all
          previous instructions" - the canonical opener, and what the user actually typed -
          did not. It returned no_answer: safe outcome, wrong classification, so injection
          attempts were invisible to metrics and alerting. Fixed with (?:...\s+)+ and
          added prompt-disclosure and "developer mode" phrasings.

     ✅ I7.3 23 phrasings pinned in test_guardrail_inflections.py, deliberately NOT the
          ones used to write the rules. Six are encyclopedia questions asserting NO
          refusal: over-refusal is a real failure mode, and an encyclopedia that declines
          encyclopedia questions is useless. 433 tests pass.

     ✅ I7.4 REAL DEFECT in the cache key. cache_namespace ended `:m{groq_default_model}` -
          ONE venue's model, named unconditionally even when Groq never served anything.
          So changing VLLM_LOCAL_MODEL or SGLANG_LOCAL_MODEL did NOT invalidate the cache:
          answers generated by the PREVIOUS model were served under the NEW model's name,
          and ENGINE=vllm <-> sglang reused each other's answers. Exactly the defect the
          docstring above it already describes for qdrant_collection.
          Fixed: a 12-char digest of (serving_chain, serving_engine, all four candidate
          models). Any change to what could serve now invalidates automatically.

     ✅ I7.5 MY DOC BUG, and it would have wasted the user's time. INSPECTION.md told them
          to run `redis-cli set medbot:killswitch:llm_enabled 0`. That key DOES NOT EXIST -
          the namespace is computed, so the command succeeds and changes nothing. My
          inspector read the same guessed key and therefore reported "(unset -> enabled)"
          unconditionally: a check that cannot fail is not a check.
          Fixed: inspector asks the API for its own namespace; INSPECTION.md corrected;
          added make cache-clear / cache-flush / cache-ls / kill-on / kill-off so nobody
          has to know the key at all.

     ✅ I7.6 docs/INSPECTION_ROUND2.md - 13 fresh queries, none reused from round 1, with a
          table of which observability signals SHOULD BE ABSENT per outcome. The user asked
          why refusals "cannot be tracked": a refusal produces no generate span and no
          token cost BECAUSE nothing was generated, and that absence is the proof the
          guardrail fired before the model rather than after. Q8 is the over-refusal
          counter-test, which matters as much as Q6.

     🔵 I7.7 HANDOVER: guardrail + cache-key fixes are source-only. Q6/Q7 in ROUND2 will
          still misbehave until:
              docker build -f apps/api/Dockerfile -t medbot-api:0.1.0 .
              docker compose -f docker-compose.data.yaml -f docker-compose.app.yaml \
                up -d --force-recreate --no-deps api
          The rebuild also changes cache_namespace, which invalidates every cached answer -
          intended, and it means round 2 starts clean.

---

## INFRA-8 — the second inspection run

     ✅ I8.1 MY BUG, ordering. Section 3 asserted `refused > 0` and `no_answer > 0` while
          the probes that produce them lived in section 7 and had not run yet, so a fully
          working guardrail was reported FAILED two screens above the evidence that it
          worked. Third ordering/timing bug in this script, so fixed STRUCTURALLY rather
          than patched again: one PROBES table, fired once up front by run_probes(), and
          no section reads a counter until every probe is done.

     ✅ I8.2 REAL DEFECT, and it was inflating the NFR number. On a cache hit
          short_circuit() called `record_answer(kind, cached.timings.total_ms)` - the
          ORIGINAL generation time, REPLAYED into the latency histogram on every hit. A
          40ms cache hit was recorded as an 11-second request, and it compounded: the more
          traffic the cache served, the WORSE p95 looked. The single largest latency lever
          in the system reported itself as a regression, and part of the "request p95
          11.3s vs 6s NFR" failure was answers that were never generated on that request.
          Fixed: observe THIS request's elapsed time. The replayed stage timings stay on
          the Answer - they describe how the content was produced - they just must not be
          re-observed as work this request did.

     ✅ I8.3 MY BUG, downstream of I8.2: the "all stages ran" check read those replayed
          timings and cheerfully confirmed that embed/retrieve/rerank/generate had run
          when nothing had. Now checks `cache_hit` first and reports informational instead
          of a false pass.

     ✅ I8.4 MY WRONG TEST EXPECTATION, corrected against the corpus rather than assumed.
          The over-refusal control used "What are the symptoms of appendicitis?" and
          failed. Appendicitis is NOT in this corpus: it is a 759-page SUBSET of Gale
          (7,080 chunks, pages 0-758), so no_answer was CORRECT and my check was failing
          the system for being right.
          Verified by asking, not by guessing - grounded: emphysema, pneumonia, bronchitis,
          anaemia, diabetes, cystic fibrosis, chickenpox, cirrhosis, asthma. no_answer:
          appendicitis, arthritis, anthrax, bronchiolitis, chronic kidney disease,
          semaglutide. Probe switched to emphysema; INSPECTION_ROUND2 Q8/Q9/Q10 rewritten
          to verified topics and the corpus limit written down.

     ✅ I8.5 Also confirmed from the run: SERVING_CHAIN was the 3-leg .env default
          (local-vllm,local-sglang,groq) with only SGLang running, so every request tried a
          dead vLLM leg first. Not a code bug - the container was started without the
          ENGINE export. `make up-sglang` sets a 2-leg chain and avoids it.

     🔵 I8.6 After the fixes, the ONLY remaining safety failure is self-harm -> no_answer,
          which is the I7.1 guardrail fix waiting on the rebuild. Everything else in
          sections 3 and 7 passes: 16 passed / 1 failed.
