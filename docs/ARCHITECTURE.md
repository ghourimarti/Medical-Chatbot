# Architecture

Diagrams are Mermaid so they live in git and change in the same commit as the code. A PNG
would be stale within a week and nobody would know.

## 1. Request path

The ordering is the design. Everything cheap and deterministic happens before anything
expensive or probabilistic.

```mermaid
flowchart TD
    U[Browser] -->|SSE| BFF[Next.js BFF<br/>allowlist proxy]
    BFF -->|server-minted token| API[FastAPI<br/>RFC 7807 · SSE · quotas]

    API --> G{Input guardrail<br/>D18}
    G -->|refuse + redirect| R[["REFUSED<br/>~6 ms · 0 tokens"]]
    G -->|allow| C{Response cache<br/>grounded answers only}
    C -->|hit| H[["cached answer"]]
    C -->|miss| E[embed<br/>bge-large-en-v1.5 · 1024d]

    E --> RET[Qdrant hybrid retrieval<br/>dense + BM25 · server-side RRF]
    RET --> RR[Cross-encoder rerank<br/>sigmoid + no-answer threshold]
    RR -->|below threshold| NA[["NO_ANSWER<br/>honest abstention"]]
    RR -->|above| GEN[Generate<br/>failover chain]
    GEN --> OG{Output guardrail<br/>dosage filter}
    OG -->|dose detected| R
    OG -->|clean| A[["GROUNDED<br/>+ citations"]]

    style R fill:#7f1d1d,color:#fff
    style NA fill:#78350f,color:#fff
    style A fill:#14532d,color:#fff
    style H fill:#14532d,color:#fff
```

**Why the guardrail is first.** It is a rule engine, not a model — so there is nothing to
prompt-inject, it costs no GPU and no tokens, and a refusal returns in ~6 ms. Putting safety
after retrieval would make it depend on retrieval *failing*, which is exactly the accident
that measured `refusal_correctness` at 0.50 in S6.

**Why the output guardrail exists too.** Defence in depth: S10.2b found the input rules can
pass a question whose *answer* still contains a dosing schedule. It runs on both the
buffered and the streaming path — it originally ran only on the buffered one, which is not
the path the browser uses.

## 2. Failure domains

The failover chain is ordered by **independent failure domain**, which is what makes it real
outage protection.

```mermaid
flowchart LR
    API[FastAPI] --> FM[FailoverModel<br/>circuit breaker per leg]
    FM --> L1[local GPU<br/>vLLM or SGLang]
    FM --> L2[RunPod<br/>3rd-party GPU cloud]
    FM --> L3[AWS<br/>own account]
    FM --> L4[Groq<br/>hosted API]

    subgraph one["ONE failure domain — not redundancy"]
        L1
    end

    style one stroke-dasharray: 5 5
```

`SERVING_ENGINE` selects vLLM **or** SGLang *within* a GPU venue. SGLang is deliberately not
its own chain entry: two engines on one GPU die together, so chaining them would sell
redundancy that does not exist (D12 v2.1). A test enforces it.

Every leg speaks the same OpenAI-compatible protocol, so one adapter serves all four and a
venue with no URL is skipped rather than erroring — configuration and provisioning proceed
independently. Measured failover: **2438 ms → 93 ms** once the breaker trips.

## 3. Ingestion — never a half-built index

```mermaid
sequenceDiagram
    participant S as SQS
    participant W as Worker
    participant Q as Qdrant
    participant A as API

    A->>Q: query alias gale_live (always)
    S->>W: ingest job
    W->>Q: create gale_live_v2
    W->>Q: embed + upsert chunks
    W->>Q: VERIFY count + spot-check
    alt verification fails
        W->>Q: drop gale_live_v2
        Note over W: alias untouched — readers unaffected
    else verification passes
        W->>Q: repoint alias atomically
        Note over A: next query sees v2, mid-flight queries finish on v1
    end
```

Readers never see a partially-ingested corpus, and a bad ingest is a no-op rather than an
outage. Rollback is repointing the alias back — measured at **3.5 s**, against **390×**
longer to rebuild from source.

## 4. Deployment — one chart, three targets

```mermaid
flowchart TD
    CH[infra/k8s/medbot<br/>ONE Helm chart]
    CH --> K[values-kind.yaml<br/>local · $0]
    CH --> D[values-do.yaml<br/>DigitalOcean · Phase 7]
    CH --> E[values-aws.yaml<br/>EKS · Phase 8]

    subgraph "must differ ONLY here"
        K
        D
        E
    end
```

The portability claim is falsifiable on purpose: if moving vendors requires a change outside
`values-<vendor>.yaml` and `infra/terraform/<vendor>/`, the claim failed. Phase 8 exists to
test it rather than to assert it.

## 5. Package boundaries

```mermaid
flowchart BT
    subgraph core["packages/core · medcore"]
        SC[schema · typed Answer]
        CFG[config · fail-fast]
        PT[ports · protocols]
        PR[prompts · versioned]
    end

    API[apps/api · medapi] --> core
    ML[apps/ml-service · medml] --> core
    WK[apps/worker] --> core
    EV[packages/eval · medeval] --> core

    core -.->|imports ZERO vendor SDKs| X((  ))
    style X fill:none,stroke:none
```

`medcore` defines `EmbedderPort`, `VectorStorePort`, `RerankerPort`, `ModelPort` as protocols
and imports no vendor SDK. Qdrant, sentence-transformers and the LLM clients live behind
adapters in `apps/api/src/medapi/adapters/`, so swapping any one of them touches a single
file — and the eval harness can run the pipeline in-process against the same contracts.

## Key invariants

| Invariant | Enforced by |
|---|---|
| A grounded answer cannot exist without a citation | typed `Answer` refuses construction |
| Only grounded answers are cacheable | `Answer.is_cacheable` |
| Cache invalidation is version-key composition, never manual purge | `Settings.cache_namespace` |
| Nothing outside `medcore.config` reads `os.environ` | lint + review |
| Redis or Postgres loss degrades, never fails, the service | readiness excludes them deliberately |
| A dose in the output is a safety failure regardless of wording | output guardrail + scorer veto |
