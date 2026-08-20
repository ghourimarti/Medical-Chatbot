# Eval delta — demo → pipeline

- before: `demo-20260710-111143-rescored` (90 cases, judge judge_v1(llama-3.3-70b-versatile, temp=0))
- after:  `pipeline-20260816-194331-rescored-rejudged` (90 cases, judge judge_v2(openai/gpt-oss-120b, temp=0))

> ⚠️ **JUDGE MISMATCH** — before was scored by `judge_v1(llama-3.3-70b-versatile, temp=0)`, after by `judge_v2(openai/gpt-oss-120b, temp=0)`. Judge-derived rows (answer_relevancy, context_precision, context_recall, faithfulness) are NOT comparable across judges; read them as two separate absolute measurements, not as a delta. Deterministic rows are unaffected.

> ⚠️ **THIN COVERAGE** — `pipeline-20260816-194331-rescored-rejudged` answer_relevancy n=1/60. Treat these as indicative only.

| metric | before | after | delta | gate | status |
|---|---:|---:|---:|---:|:--|
| answer_relevancy | 0.8802 | 0.9537 | +0.0735 ✅ | 0.85 | **PASS** |
| answered | 0.9167 | 1 | +0.0833 ✅ | 0.98 | **PASS** |
| citation_presence | 0 | 1 | +1 ✅ | 0.99 | **PASS** |
| completed | 1 | 1 | +0 → | — |  |
| context_precision | 0.7143 | — | — | — | only in one run |
| context_recall | 0.6538 | — | — | — | only in one run |
| dont_know_correctness | 0.8 | 0.9 | +0.1 ✅ | 0.9333 | **FAIL** |
| error_rate | 0 | 0 | +0 → | 0.01 | **PASS** |
| faithfulness | 0.6634 | — | — | — | only in one run |
| latency_p50_ms | 2214 | 1.036e+04 | +8142 ⚠️ | — |  |
| latency_p95_ms | 2505 | 1.184e+04 | +9340 ⚠️ | — |  |
| refusal_correctness | 0.4 | 0.7 | +0.3 ✅ | 0.9 | **FAIL** |
| unsafe_answer_rate | — | 0.05 | — | — | only in one run |

**Gate result: ❌ FAIL**
Below threshold: dont_know_correctness, refusal_correctness, unsafe_answer_rate