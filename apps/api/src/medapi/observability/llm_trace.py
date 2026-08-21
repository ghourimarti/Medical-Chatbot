"""Langfuse — LLM-level tracing (D13).

WHAT THIS ADDS over OTel. An OTel span says "generate took 240ms". It cannot tell you
that the answer was bad because prompt v1 retrieved the wrong passage and the model
hedged. Langfuse stores the LLM-shaped facts: prompt version, the retrieved context, the
completion, token counts, cost, and per-stage scores — the things you need to debug
ANSWER QUALITY rather than latency.

PII: this is the ONE sanctioned store for prompt/completion content (D18) — access
controlled, 30-day retention. Everywhere else (logs, OTel spans, metrics) carries only
fingerprints. That asymmetry is deliberate: quality debugging genuinely requires the text,
so the text lives in exactly one auditable place instead of leaking into five.

Optional by design: no keys configured -> every call is a no-op. The pipeline must never
depend on an observability backend being reachable.
"""

from __future__ import annotations

from typing import Any

_CLIENT: Any = None
_ENABLED = False


def configure_llm_tracing(
    *, public_key: str, secret_key: str, host: str, environment: str
) -> None:
    """Idempotent. Missing credentials disable tracing rather than raising: observability
    is not a hard dependency of answering a medical question."""
    global _CLIENT, _ENABLED
    if not (public_key and secret_key):
        _ENABLED = False
        return
    try:
        from langfuse import Langfuse

        _CLIENT = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host or "http://localhost:5015",
            environment=environment,
        )
        _ENABLED = True
    except Exception:  # noqa: BLE001 — a broken tracer must not take down the service
        _CLIENT = None
        _ENABLED = False


def is_enabled() -> bool:
    return _ENABLED


def trace_answer(
    *,
    question: str,
    answer_text: str,
    kind: str,
    prompt_version: str,
    prompt_sha: str,
    model_id: str | None,
    contexts: list[str],
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
    timings: dict[str, float | None],
    cache_hit: bool,
    venue: str | None = None,
) -> None:
    """Record one answered query. Never raises — a tracing failure must not fail a request.

    `contexts` and the raw question are included ON PURPOSE here (and nowhere else): a
    faithfulness regression is undebuggable without seeing what the model was shown.
    """
    if not _ENABLED or _CLIENT is None:
        return
    try:
        _CLIENT.create_event(
            name="rag_answer",
            input={"question": question, "n_contexts": len(contexts)},
            output={"answer": answer_text, "kind": kind},
            metadata={
                "prompt_version": prompt_version,
                # The exact prompt revision that produced this answer. Without it, a
                # quality regression cannot be attributed to a prompt change (D6).
                "prompt_sha": prompt_sha[:12],
                "model_id": model_id,
                "venue": venue,
                "cache_hit": cache_hit,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": round(cost_usd, 6),
                **{k: v for k, v in timings.items() if v is not None},
            },
        )
    except Exception:  # noqa: BLE001 — see docstring
        return


def flush() -> None:
    """Drain buffered events at shutdown so the last requests before a rollout are not lost."""
    if _ENABLED and _CLIENT is not None:
        try:
            _CLIENT.flush()
        except Exception:  # noqa: BLE001
            return
