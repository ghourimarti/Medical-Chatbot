# Serving-engine benchmark (S14, D12)

> Harness: `tests/load/engine_benchmark.js` (k6). Works against any OpenAI-compatible
> endpoint, so venues and engines are compared under identical load.
> Reproduce: `make bench-groq` · `make bench-local` · `make bench-sglang`

## Why a separate harness from `scripts/bench_venue.py`

| Tool | Measures | Answers |
|---|---|---|
| `bench_venue.py` (S3b) | **Sequential** TTFT / TPOT | "What does one request cost when nothing else is happening?" |
| `engine_benchmark.js` (S14) | **Concurrent** throughput + latency under ramp | "What happens when requests overlap?" |

Continuous batching, KV-cache pressure, and admission queueing only appear under
concurrency — and that is exactly where vLLM and SGLang differ. Measured sequentially the
two engines look nearly identical, which is why the S3b numbers alone cannot settle D12.

**Load model:** `ramping-arrival-rate` (open model), not ramping VUs. A closed model with
fixed VUs silently *reduces* offered load as latency rises, hiding saturation completely —
the classic load-testing mistake. An open model keeps sending, which is how real traffic
behaves.

## Result 1 — hosted free tiers cannot be load-benchmarked

| Run | Peak rate | Requests | Failed | tok/s (successful) |
|---|---:|---:|---:|---:|
| Groq, default ramp | 20 RPS | 810 | **91.4%** | 189 |
| Groq, reduced ramp | 3 RPS | 169 | **66.9%** | 204 |
| Groq, single request | — | 1 | **0%** | — |

A lone request returns 200, so this is **429 rate limiting, not an outage**. Groq's free
tier allows roughly **30 requests/minute (~0.5 RPS)**.

```
Groq free tier   ~0.5 RPS
Phase-1 NFR peak  350   RPS
gap               ~700x
```

**This empirically confirms the D4 analysis** made during Phase 2: *"at 350 RPS, provider
rate limits are a contract negotiation, not a config value."* It was an assertion then; it
is a measurement now. Serving 350 RPS from a hosted venue is a **procurement** problem
before it is an engineering one.

Two consequences:
1. **Hosted venues are benchmarked for latency, not throughput.** Their ceiling is quota.
   The S3b sequential numbers (TTFT 163 ms, 182 tok/s) remain the meaningful hosted figures.
2. **The engine comparison must run on self-hosted GPUs**, where capacity is ours to
   saturate. This is not a workaround — it is the only setting in which "which engine
   batches better?" is even a well-posed question.

The threshold correctly failed the run (k6 exit 99). The benchmark is a **gate**, not a
report: a run that quietly reported 189 tok/s while discarding 91% of requests would be
worse than no benchmark at all.

## Result 2 — sequential venue latency (from S3b, for reference)

| Venue | TTFT p50 | TTFT p95 | tok/s | TPOT |
|---|---:|---:|---:|---:|
| local RTX 3060 · vLLM · Qwen2.5-7B-AWQ | **37 ms** | 39 ms | 63.5 | 14.9 ms |
| hosted Groq · llama-3.1-8b | 163 ms | 228 ms | **181.7** | 1.2 ms |

Crossover ≈ 9 output tokens: local wins time-to-first-token (no network hop), Groq wins
completion time for anything longer.

## Result 3 — vLLM vs SGLang, head to head ✅

Identical model (`Qwen/Qwen2.5-7B-Instruct-AWQ`), identical GPU (RTX 3060, 12 GB), identical
ramp (peak 12 RPS), identical prompts. Engines run **sequentially** — a 12 GB card fits one
7B model at a time — within the same session to hold thermal state roughly constant.

| Metric | vLLM 0.27.1 | SGLang | Winner |
|---|---:|---:|:--|
| Requests | 484 | 485 | — |
| Failed | **0.00%** | **0.00%** | tie |
| Latency median | 511 ms | 528 ms | vLLM (+3%) |
| **Latency p95** | 902 ms | **735 ms** | **SGLang (−18%)** |
| **Latency p99** | **1034 ms** | 2504 ms | **vLLM (−59%)** |
| Throughput / request | **58.0 tok/s** | 51.8 tok/s | **vLLM (+12%)** |
| Tokens generated | 14,537 | 11,657 | — |

### The finding that matters: the tail inverts

SGLang is **better at p95** and **2.4× worse at p99**. A comparison stopping at median and
p95 would have chosen SGLang; adding p99 reverses the conclusion. Since SLOs are written
against tail latency (Phase-1: TTFT p95 ≤ 2.0 s, and a 43.8-min monthly error budget that a
2.5 s stall erodes), **the p99 column decides this**.

### Recommendation for this project: **vLLM**

1. Better p99 (1034 ms vs 2504 ms) — the number the SLO is written against.
2. Higher sustained throughput (+12%).
3. Already integrated, measured (S3b), and running with a known WSL2 workaround.

SGLang remains valuable as the **engine-level failover leg** (D12): it is genuinely
production-capable here — zero failures, better p95 — so switching engines is a real
mitigation for a vLLM-specific bug or OOM regression, which is exactly the role D12
assigned it.

### Caveats — what these numbers are NOT

1. **Token counts differ by ~20%** (14,537 vs 11,657) at the same `max_tokens=128` and
   request count, so the engines stopped generating differently. Per-request tok/s
   normalises for time but not for stopping behaviour, so treat the throughput delta as
   indicative rather than exact.
2. **WSL2 forces `pin_memory=False`** (S3b) — both engines are handicapped equally, but
   neither figure is native-Linux representative.
3. **Consumer GPU, INT4 quantization.** An L4/A100 with FP8 would change absolute numbers
   and could change the ordering; batching behaviour is hardware-sensitive.
4. **Sequential runs**, not simultaneous — unavoidable on one GPU, and the reason both were
   run back-to-back rather than on different days.

Any *published* claim should be labelled "RTX 3060 / WSL2 / INT4 / 12 RPS", never
generalised. Re-running on a native-Linux cloud GPU (Track D) is the path to a
production-representative comparison.

## Superseded — pending section (kept for the reproduction commands)

**Status: harness ready, not yet run.** Requires both engines serving the same model on
the same GPU:

```bash
# vLLM (weights already cached in the vllm-hf-cache volume, so startup is fast)
docker run --rm -d --gpus all --ipc=host -e VLLM_USE_V2_MODEL_RUNNER=0 -e HF_TOKEN \
  -v vllm-hf-cache:/root/.cache/huggingface -p 1110:8000 --name vllm-local \
  vllm/vllm-openai:latest --model Qwen/Qwen2.5-7B-Instruct-AWQ \
  --gpu-memory-utilization 0.80 --max-model-len 8192
make bench-local

# SGLang — requires a new ~10GB image pull, and the GPU must be free first
docker run --rm -d --gpus all --ipc=host -v vllm-hf-cache:/root/.cache/huggingface \
  -p 1111:30000 --name sglang-local lmsysorg/sglang:latest \
  python3 -m sglang.launch_server --model-path Qwen/Qwen2.5-7B-Instruct-AWQ \
  --host 0.0.0.0 --port 30000 --mem-fraction-static 0.80
make bench-sglang
```

**Constraint to plan around:** a 12 GB consumer GPU fits **one** 7B model at a time, so the
engines must be benchmarked sequentially, not side by side. Comparability therefore depends
on identical model, prompt, ramp, and thermal state — the harness fixes the first three;
the fourth argues for running both within the same session.

**Known caveat for the local venue (S3b):** WSL2 forces `pin_memory=False`, so local
figures are inherently below native-Linux performance. Any *published* engine comparison
belongs on a native-Linux cloud GPU (RunPod/AWS, Track D) — the local run establishes the
method and a relative baseline, not headline numbers.
