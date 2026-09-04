"""Langfuse: LLM-level tracing.

An OTel span says "generate took 240ms". It can't tell you the answer was bad because
prompt v1 retrieved the wrong passage and the model hedged. Langfuse stores the LLM-shaped
facts instead: prompt version, retrieved context, completion, token counts, cost and
per-stage scores. That's what you need to debug answer quality rather than latency.

This is the one sanctioned store for prompt and completion content, access-controlled with
30-day retention. Logs, OTel spans and metrics carry fingerprints only. Quality debugging
genuinely needs the text, so the text lives in one auditable place instead of five.

With no keys configured every call is a no-op. The pipeline must never depend on an
observability backend being reachable.
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
    except Exception:  # noqa: BLE001 (a broken tracer must not take the service down)
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
    """Record one answered query. Never raises: a tracing failure can't fail a request.

    `contexts` and the raw question are included here and nowhere else. A faithfulness
    regression isn't debuggable without seeing what the model was shown.
    """
    if not _ENABLED or _CLIENT is None:
        return
    try:
        # A generation observation, not an event. An event has no model, usage or cost
        # fields, so Langfuse's LLM-specific charts (cost per model, tokens/sec, spend over
        # time) read zero across 318 traces while the real numbers sat one level down in
        # `metadata`, where none of those charts look.
        #
        # `model` and `usage_details` are what Langfuse aggregates on, so they're promoted
        # out of metadata. The metadata copy stays: it costs nothing and keeps every value
        # visible when reading a single trace.
        #
        # Note there is no `create_generation` on the v4 client. Calling one stopped all
        # tracing silently, because the AttributeError went into the except below that
        # exists so a broken tracer can't fail a medical answer. So a wrong method name
        # looks exactly like a healthy system with nothing to trace: check by counting
        # traces after a change, not by the absence of errors.
        # The observation is ended immediately: this records a completed call, so there is
        # no interval to leave open.
        _CLIENT.start_observation(
            as_type="generation",
            name="rag_answer",
            model=model_id,
            input={"question": question, "n_contexts": len(contexts)},
            output={"answer": answer_text, "kind": kind},
            usage_details={
                "input": prompt_tokens,
                "output": completion_tokens,
                "total": prompt_tokens + completion_tokens,
            },
            cost_details={"total": round(cost_usd, 6)},
            metadata={
                "prompt_version": prompt_version,
                # The exact prompt revision behind this answer. Without it a quality
                # regression can't be attributed to a prompt change.
                "prompt_sha": prompt_sha[:12],
                "model_id": model_id,
                "venue": venue,
                "cache_hit": cache_hit,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": round(cost_usd, 6),
                **{k: v for k, v in timings.items() if v is not None},
            },
        ).end()
    except Exception:  # noqa: BLE001 (see docstring)
        return


def flush() -> None:
    """Drain buffered events at shutdown so the last requests before a rollout are not lost."""
    if _ENABLED and _CLIENT is not None:
        try:
            _CLIENT.flush()
        except Exception:  # noqa: BLE001
            return
