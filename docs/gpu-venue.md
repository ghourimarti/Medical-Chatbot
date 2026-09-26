# GPU Venue Spike — findings

> **Purpose:** de-risk self-hosted serving *before* integration, by proving vLLM runs
> on available hardware and measuring what it actually delivers. Timeboxed spike; the
> deliverable is this document.
> **Outcome: ✅ vLLM runs locally at $0, and the measured numbers beat our NFR targets by 20×.**
> Reproduce: `uv run python scripts/bench_venue.py --base-url <url> --model <id> --runs 5`

## 1. Venue: local RTX 3060 (WSL2 + Docker)

| Property | Value |
|---|---|
| GPU | NVIDIA GeForce RTX 3060, 12288 MiB |
| Compute capability | **8.6 (Ampere)** — AWQ/GPTQ INT4 ✅ · **FP8 ❌** (needs ≥8.9) |
| Driver / CUDA | 591.86 / 13.1 |
| Host RAM | 31.1 GB |
| Runtime | Docker Desktop (WSL2) with `nvidia-container-runtime` |
| Engine | vLLM **0.27.1**, `vllm/vllm-openai:latest` (9.11 GB pull / 30.8 GB on disk) |
| Model | `Qwen/Qwen2.5-7B-Instruct-AWQ` (INT4) |
| Config | `--gpu-memory-utilization 0.80 --max-model-len 8192` |
| VRAM in use | **8115 / 12288 MiB** — no OOM |
| Cost | **$0** |

Auto-selected by vLLM without manual flags: **Marlin kernel** for AWQ (the Ampere-optimized
path), **FlashAttention 2**, **prefix caching ON**, chunked prefill ON.

## 2. Measured performance (identical prompt, 5 runs + warmup)

Workload mirrors the real RAG shape: system prompt + 2 retrieved passages + question
(167 prompt tokens → 50 completion tokens).

| Venue | TTFT p50 | TTFT p95 | Output tok/s | TPOT | Total (50 tok) |
|---|---:|---:|---:|---:|---:|
| **Local RTX 3060 · vLLM · Qwen2.5-7B-AWQ** | **37 ms** | **39 ms** | 63.5 | 14.9 ms | 0.77 s |
| **Hosted Groq · llama-3.1-8b-instant** | 163 ms | 228 ms | **181.7** | **1.2 ms** | **0.24 s** |
| *NFR target (Phase 1)* | *800 ms* | *2000 ms* | — | — | — |

**Both venues beat the TTFT NFR by a wide margin** — local by ~20×, Groq by ~5× on p50.

### The trade-off, quantified
- **Local wins time-to-first-token** (37 ms vs 163 ms) — no network round trip.
- **Groq wins throughput by ~3×** (182 vs 63.5 tok/s) — LPU hardware.
- **Crossover ≈ 9 output tokens.** Beyond that, Groq's decode speed dominates:
  `37 + 14.9n` vs `163 + 1.2n`. For a typical 100-token medical answer, Groq completes in
  ~283 ms vs local ~1527 ms.

**Honest caveat:** the local TTFT excludes user network latency, because the benchmark ran on
the same machine as the server. In a real deployment the API is remote from the user either
way, so local's TTFT edge narrows to the *server-to-provider* hop it actually saves.

## 3. Blockers found and solved (the spike's real value)

| # | Blocker | Root cause | Fix |
|---|---|---|---|
| 1 | `RuntimeError: UVA is not available` at `init_device` | vLLM 0.27's **V2 Model Runner** allocates a UVA buffer needing `cudaHostRegister`, which **WSL2's GPU driver does not support** | `-e VLLM_USE_V2_MODEL_RUNNER=0` (falls back to the mature V1 runner) |
| 2 | Weight download stalled at ~0.4 MB/s | Unauthenticated HF Hub requests are rate-limited | `-e HF_TOKEN` passthrough |
| 3 | Restarts appeared to lose all progress | **`huggingface_hub` 1.27 does NOT resume across process restarts** — each attempt writes a new `.{uuid}.incomplete` and starts from byte 0. Four orphaned partials (~4.6 GB) accumulated. | **Never restart mid-download.** Budget one uninterrupted run. |
| 4 | `403 Forbidden` from Groq via `urllib` | Cloudflare rejects requests with no `User-Agent` | Set `User-Agent` in `scripts/bench_venue.py` |
| 5 | Qdrant rejected string point IDs | Qdrant requires uint or UUID ids | deterministic `uuid5` from content hash |

**Performance caveat for this venue:** vLLM logs `Using 'pin_memory=False' as WSL is detected.
This may slow down performance.` WSL2 cannot pin host memory, so **local is inherently slower
than native Linux**. This is an evidence-based reason the *published* benchmark should run
on a native-Linux cloud GPU.

## 4. What this venue is and isn't good for

**Good for:** development iteration (restart 50× for free), adapter/failover-chain
debugging, keeping health queries entirely in-box (privacy), proving the pattern at $0.

**Not good for:** published production-representative benchmarks — it's a consumer card,
INT4-only (no FP8), on WSL2 with `pin_memory=False`. Claims from this venue must be labeled
"RTX 3060 / WSL2 / INT4", never generalized to production hardware.

## 5. Decision 4b consequences

This spike confirms the multi-venue design is correct and worth building:

| Venue | Status | Role |
|---|---|---|
| `local` | ✅ **proven, measured** | Dev iteration, free debugging, privacy path |
| `groq` | ✅ **proven, measured** | Always-available hosted floor; highest throughput |
| `runpod` | ⏳ not yet exercised | Production-representative GPU, native Linux, no quota wait |
| `aws` | ⏳ quota request pending | AWS-depth gap closure; Terraform target |

Two of four venues are now measured with the **same tool on the same prompt** — which is
exactly the comparison D4b exists to enable.

## 6. Operational notes
- Start: `docker run --rm -it --gpus all --ipc=host -e VLLM_USE_V2_MODEL_RUNNER=0 -e HF_TOKEN -v vllm-hf-cache:/root/.cache/huggingface -p 1110:8000 --name vllm-local vllm/vllm-openai:latest --model Qwen/Qwen2.5-7B-Instruct-AWQ --gpu-memory-utilization 0.80 --max-model-len 8192`
- Weights live in the named volume **`vllm-hf-cache`** (do not delete — re-download is slow).
- ~4.6 GB of orphaned `.incomplete` files can be reclaimed later; harmless meanwhile.
- Llama-3.1-8B-Instruct-AWQ-INT4 is partially cached in the same volume for the swap.
