# Eval delta — demo → pipeline

- before: `demo-20260710-111143-rescored` (90 cases, judge judge_v1(llama-3.3-70b-versatile, temp=0))
- after:  `pipeline-20260816-185249` (90 cases, judge judge_v1(llama-3.3-70b-versatile, temp=0))

| metric | before | after | delta | gate | status |
|---|---:|---:|---:|---:|:--|
| answer_relevancy | 0.8802 | 0.9028 | +0.0226 ✅ | 0.80 | **PASS** |
| answered | 0.9167 | 1 | +0.0833 ✅ | — |  |
| citation_presence | 0 | 0.9833 | +0.9833 ✅ | 1.00 | **FAIL** |
| completed | 1 | 1 | +0 → | — |  |
| context_precision | 0.7143 | 0.8056 | +0.0913 ✅ | — |  |
| context_recall | 0.6538 | 1 | +0.3462 ✅ | — |  |
| dont_know_correctness | 0.8 | 0.9 | +0.1 ✅ | 0.90 | **PASS** |
| error_rate | 0 | 0 | +0 → | — |  |
| faithfulness | 0.6634 | — | — | — | only in one run |
| latency_p50_ms | 2214 | 1.056e+04 | +8348 ⚠️ | — |  |
| latency_p95_ms | 2505 | 1.156e+04 | +9054 ⚠️ | — |  |
| refusal_correctness | 0.4 | 0.5 | +0.1 ✅ | 0.95 | **FAIL** |

**Gate result: ❌ FAIL**
Below threshold: citation_presence, refusal_correctness