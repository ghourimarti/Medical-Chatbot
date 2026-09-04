"""Token pricing and cost attribution.

Self-hosted venues cost $0 per token. Their cost is GPU-hours: time-based, incurred whether
you serve one request or a million. Hosted APIs are the mirror image, $0 idle and linear in
tokens.

Modelling both as cost-per-token would make the local GPU look free, when a forgotten 24/7
g6.xlarge (~$600/month) is the largest waste vector here. So per-token cost is 0 for
self-hosted and GPU spend is tracked separately as a time-based metric with a
scale-to-zero policy.

Prices are USD per 1M tokens and will drift. They're config, not truth: a wrong price gives
a wrong dashboard rather than a wrong answer, but it can trip the spend breaker wrongly,
so they carry a review date.
"""

from __future__ import annotations

from typing import NamedTuple

from medcore.schema import Usage

PRICES_REVIEWED = "2026-08"


class TokenPrice(NamedTuple):
    prompt_per_1m: float
    completion_per_1m: float


# Self-hosted: zero per-token cost by construction (see module docstring).
SELF_HOSTED = TokenPrice(0.0, 0.0)

PRICE_TABLE: dict[str, TokenPrice] = {
    # Groq (hosted, open-weight)
    "llama-3.1-8b-instant": TokenPrice(0.05, 0.08),
    "llama-3.3-70b-versatile": TokenPrice(0.59, 0.79),
    "openai/gpt-oss-20b": TokenPrice(0.10, 0.50),
    # OpenAI fallback leg
    "gpt-4o-mini": TokenPrice(0.15, 0.60),
    "gpt-4o": TokenPrice(2.50, 10.00),
    # Self-hosted models (local / runpod / aws): zero per token.
    "Qwen/Qwen2.5-7B-Instruct-AWQ": SELF_HOSTED,
    "meta-llama/Llama-3.1-8B-Instruct": SELF_HOSTED,
}

# An unknown model must not silently cost $0, which would hide spend from the breaker
# meant to catch it. Assume the most expensive tier we routinely use, and log it.
UNKNOWN_MODEL_PRICE = TokenPrice(0.59, 0.79)


def price_for(model_id: str) -> TokenPrice:
    if model_id in PRICE_TABLE:
        return PRICE_TABLE[model_id]
    # Vendor prefixes vary by venue ("groq/llama-3.1-8b-instant" vs bare); match the tail.
    tail = model_id.rsplit("/", 1)[-1]
    return PRICE_TABLE.get(tail, UNKNOWN_MODEL_PRICE)


def cost_usd(model_id: str, usage: Usage) -> float:
    p = price_for(model_id)
    return (
        usage.prompt_tokens * p.prompt_per_1m + usage.completion_tokens * p.completion_per_1m
    ) / 1_000_000


def is_self_hosted(model_id: str) -> bool:
    return price_for(model_id) == SELF_HOSTED
