"""Measure TTFT and throughput of any OpenAI-compatible LLM endpoint (Decision 4b).

Every serving venue in this project speaks the same protocol — local vLLM, SGLang,
RunPod, AWS, and Groq — so one tool compares them all on equal terms. That is the
practical payoff of the D12 adapter seam, applied to measurement.

Usage:
  # local vLLM (S3b spike)
  uv run python scripts/bench_venue.py --base-url http://localhost:1110/v1 \
      --model Qwen/Qwen2.5-7B-Instruct-AWQ --runs 5

  # hosted Groq, same command shape
  uv run python scripts/bench_venue.py --base-url https://api.groq.com/openai/v1 \
      --model llama-3.1-8b-instant --api-key $GROQ_API_KEY --runs 5

Metrics:
  TTFT      time to first streamed token — what the user perceives (Phase 1 NFR: p50 800ms)
  TPOT      time per output token after the first (steady-state decode speed)
  tok/s     output tokens / total generation time
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request

# A prompt shaped like our real RAG workload: system prompt + retrieved context + question.
_CONTEXT = (
    "[1] (source: Gale Encyclopedia of Medicine, p.78)\n"
    "Abscess - A pus-filled area with definite borders. Bacterial infection of the CNS can "
    "result in abscesses and empyemas. Abscesses have fixed boundaries, but empyemas lack "
    "definable shape.\n\n"
    "[2] (source: Gale Encyclopedia of Medicine, p.79)\n"
    "A lumbar puncture and analysis of the cerebrospinal fluid can help diagnose an epidural "
    "abscess; however, the procedure can be dangerous in some patients.\n"
)
_SYSTEM = (
    "You are a medical information assistant. Answer only from the CONTEXT provided, "
    "citing passage numbers in square brackets. Be concise."
)
_QUESTION = "What is an abscess and how does it differ from an empyema?"


def _request(
    base_url: str, model: str, api_key: str | None, max_tokens: int, stream: bool
) -> urllib.request.Request:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"CONTEXT:\n{_CONTEXT}\nQUESTION:\n{_QUESTION}"},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "stream": stream,
    }
    # A User-Agent is mandatory in practice: hosted providers behind Cloudflare
    # (Groq among them) return 403 to bare urllib requests without one.
    headers = {"Content-Type": "application/json", "User-Agent": "medbot-bench/0.1"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )


def measure_stream(
    base_url: str, model: str, api_key: str | None, max_tokens: int
) -> tuple[float, float, int, str]:
    """Return (ttft_s, total_s, n_chunks, text)."""
    req = _request(base_url, model, api_key, max_tokens, stream=True)
    t0 = time.perf_counter()
    ttft = -1.0
    chunks = 0
    parts: list[str] = []
    with urllib.request.urlopen(req, timeout=180) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data: "):
                continue
            body = line[6:]
            if body == "[DONE]":
                break
            try:
                delta = json.loads(body)["choices"][0]["delta"].get("content")
            except (json.JSONDecodeError, KeyError, IndexError):
                continue
            if not delta:
                continue
            if ttft < 0:
                ttft = time.perf_counter() - t0
            chunks += 1
            parts.append(delta)
    return ttft, time.perf_counter() - t0, chunks, "".join(parts)


def measure_usage(
    base_url: str, model: str, api_key: str | None, max_tokens: int
) -> tuple[int, int]:
    """Non-streaming call to read exact prompt/completion token counts."""
    req = _request(base_url, model, api_key, max_tokens, stream=False)
    with urllib.request.urlopen(req, timeout=180) as resp:
        usage = json.loads(resp.read())["usage"]
    return int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True, help="e.g. http://localhost:1110/v1")
    ap.add_argument("--model", required=True)
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--max-tokens", type=int, default=200)
    ap.add_argument("--label", default=None, help="venue name for the report")
    args = ap.parse_args()

    label = args.label or args.base_url
    print(f"venue: {label}\nmodel: {args.model}\n")

    try:
        prompt_tok, completion_tok = measure_usage(
            args.base_url, args.model, args.api_key, args.max_tokens
        )
    except urllib.error.URLError as e:
        raise SystemExit(f"endpoint unreachable: {e}") from e
    print(f"token accounting: prompt={prompt_tok} completion={completion_tok}")

    print("warmup...", flush=True)
    measure_stream(args.base_url, args.model, args.api_key, args.max_tokens)

    ttfts: list[float] = []
    totals: list[float] = []
    rates: list[float] = []
    text = ""
    for i in range(1, args.runs + 1):
        ttft, total, chunks, text = measure_stream(
            args.base_url, args.model, args.api_key, args.max_tokens
        )
        rate = chunks / total if total > 0 else 0.0
        ttfts.append(ttft)
        totals.append(total)
        rates.append(rate)
        print(f"  run {i}: TTFT {ttft * 1000:7.1f} ms | total {total:5.2f} s | {rate:6.1f} tok/s")

    def p(vals: list[float], q: float) -> float:
        s = sorted(vals)
        return s[min(len(s) - 1, int(q * len(s)))]

    denom = max(1, completion_tok - 1)
    tpot_ms = [
        (tot - tt) / denom * 1000 for tt, tot in zip(ttfts, totals, strict=True)
    ]
    ttft_p50 = statistics.median(ttfts) * 1000
    ttft_p95 = p(ttfts, 0.95) * 1000
    print(f"\n--- {label} ---")
    print(f"TTFT   p50 {ttft_p50:.0f} ms   p95 {ttft_p95:.0f} ms")
    print(f"total  p50 {statistics.median(totals):.2f} s    p95 {p(totals, 0.95):.2f} s")
    print(f"tok/s  mean {statistics.fmean(rates):.1f}")
    print(f"TPOT   mean {statistics.fmean(tpot_ms):.1f} ms/token")
    print(f"\nsample answer:\n{text[:400]}")


if __name__ == "__main__":
    main()
