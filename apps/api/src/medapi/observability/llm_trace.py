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

import time as _time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from contextvars import ContextVar
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
            # NOTE: the export timeout is deliberately NOT passed here. The SDK resolves it
            # as `timeout or int(os.environ["LANGFUSE_TIMEOUT"])`, so an explicit argument
            # SHADOWS the environment variable - two knobs for one setting, with the
            # invisible one winning. It is set in .env as LANGFUSE_TIMEOUT instead, which
            # also means it can be changed with a container restart rather than a rebuild.
            #
            # Why it needs raising at all: the SDK default is 5s, and it loses spans
            # SILENTLY rather than erroring. Symptom: a trace arriving with its ROOT and
            # none of its children, plus
            # "Failed to export span batch ... Read timed out (read timeout=5s)" in the
            # logs. The root and the children go in different batches, so a slow ingest
            # drops the interesting half and leaves a trace that looks like the old flat
            # one - a regression that is indistinguishable from the bug it replaced.
            # Langfuse v3 fans a write out to Postgres, ClickHouse and S3/MinIO, so a
            # burst is legitimately slower than a single request suggests: measured 0.15s
            # idle, past 5s under batch load on this box.
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
        _emit_tree(
            question=question,
            answer_text=answer_text,
            kind=kind,
            prompt_version=prompt_version,
            prompt_sha=prompt_sha,
            model_id=model_id,
            contexts=contexts,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            timings=timings,
            cache_hit=cache_hit,
            venue=venue,
        )
    except Exception:  # noqa: BLE001 (see docstring)
        return


# Pipeline stages in execution order, with the Langfuse observation type that describes
# each one. The types are not decoration: Langfuse groups, filters and charts on them, so
# a retrieval step typed `span` is invisible to every retrieval-quality view.
# There is no "reranker" type, and `span` is the honest choice rather than mislabelling
# rerank as retrieval - it consumes candidates, it does not fetch them.
_STAGES: tuple[tuple[str, str, str], ...] = (
    ("embed_ms", "embed", "embedding"),
    ("retrieve_ms", "retrieve", "retriever"),
    ("rerank_ms", "rerank", "span"),
)

_MS_TO_NS = 1_000_000


def _emit_tree(
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
    venue: str | None,
) -> None:
    """Build the trace as a TREE: one root with a child observation per pipeline stage.

    Previously this emitted a single flat observation, with the per-stage durations packed
    into `metadata` as `embed_ms`, `retrieve_ms`, `rerank_ms`. Everything was technically
    recorded, and none of it was usable: Langfuse charts, sorts, filters and compares on
    OBSERVATIONS, so timings living inside one node's metadata cannot be grouped, ranked or
    tracked over time. The trace also showed as "Unnamed trace / 0.00s", because nothing
    named the root and the single observation was opened and closed back-to-back after the
    work had already finished - so it described a duration of zero for a 4-second request.

    A LangChain app gets this shape for free: its callback handler emits one observation per
    Runnable. This pipeline is hand-written, so the tree is built explicitly. That is also
    why it is WORTH building - every node here is a real stage, not framework plumbing.

    TIMING, stated precisely because the limitation is real: the SDK exposes `end_time` but
    not `start_time`, so each child is opened now and closed at now + its measured duration.
    Per-stage DURATIONS are therefore exact and the Tree view is correct, but the Timeline
    view renders the stages as starting together rather than in sequence. Durations answer
    "which stage was slow", which is the question this tree exists for. Reaching into the
    private OTel tracer would fix the timeline at the cost of depending on a private API in
    the one module that is designed to fail silently - a bad trade (see the warning below).

    WARNING, learned the hard way: every failure in here is swallowed, because a broken
    tracer must not fail a medical answer. That means a wrong method name does not raise -
    it silently stops all tracing and looks exactly like a healthy system with nothing to
    report. After changing anything here, verify by COUNTING observations, never by the
    absence of errors:
        GET /api/public/traces/{id}  ->  expect a root plus one child per stage
    """
    stage_total = sum(v for _, v in _present(timings) if v)
    root_ms = timings.get("total_ms") or stage_total

    root = _CLIENT.start_observation(
        as_type="chain",
        name="rag_answer",
        input={"question": question, "n_contexts": len(contexts)},
        metadata={
            "prompt_version": prompt_version,
            # The exact prompt revision behind this answer. Without it a quality
            # regression cannot be attributed to a prompt change.
            "prompt_sha": prompt_sha[:12],
            "model_id": model_id,
            "venue": venue,
            "cache_hit": cache_hit,
        },
    )
    started = _time.time_ns()

    for key, name, as_type in _STAGES:
        duration = timings.get(key)
        # A missing stage is SIGNAL, not an omission: a cache hit skips all of them, and a
        # retrieval-gated no_answer never reaches generate. The absent node is the evidence.
        if not duration:
            continue
        now = _time.time_ns()
        child = root.start_observation(as_type=as_type, name=name)
        if name == "retrieve":
            child.update(output={"n_contexts": len(contexts)})
        child.end(end_time=now + int(duration * _MS_TO_NS))

    generate_ms = timings.get("generate_ms")
    if generate_ms:
        now = _time.time_ns()
        # `model`, `usage_details` and `cost_details` belong on the GENERATION node, not on
        # the root: Langfuse's cost-per-model, tokens/sec and spend-over-time views read
        # those fields from generation observations specifically. On any other type they
        # are inert, which is how 318 traces once charted as zero spend.
        gen = root.start_observation(
            as_type="generation",
            name="generate",
            model=model_id,
            input={"n_contexts": len(contexts)},
            output={"answer": answer_text},
            usage_details={
                "input": prompt_tokens,
                "output": completion_tokens,
                "total": prompt_tokens + completion_tokens,
            },
            cost_details={"total": round(cost_usd, 6)},
            metadata={"venue": venue, "kind": kind},
        )
        gen.end(end_time=now + int(generate_ms * _MS_TO_NS))

    root.update(output={"answer": answer_text, "kind": kind})
    root.end(end_time=started + int((root_ms or 0) * _MS_TO_NS))


def _present(timings: dict[str, float | None]) -> list[tuple[str, float]]:
    return [(k, v) for k, v in timings.items() if k != "total_ms" and v]



# ── The pipeline tree ──────────────────────────────────────────────────────────────────
#
# `rag_trace()` opens the ROOT, and every LCEL Runnable the chain executes becomes a child
# of it automatically via `langchain_handler()`. That is what turns one flat node into the
# nested guard -> condense -> embed -> retrieve -> rerank -> build_context -> generate tree.
#
# WHY THE ROOT NEEDS AN EXPLICIT trace_id, which is the non-obvious part:
# this SDK is built on OpenTelemetry, and the API is already OTel-instrumented for Jaeger.
# Left alone, Langfuse attaches its root to whatever OTel span is ambient - the FastAPI
# request span, which belongs to a DIFFERENT TracerProvider that Langfuse never saw. The
# trace then has a parent Langfuse cannot name, and the UI renders exactly what it knows:
# "Unnamed trace". Passing a fresh trace_id detaches from the ambient span and makes
# `rag_answer` the root, which is also what supplies the trace name.


def new_trace_id() -> str | None:
    if not _ENABLED or _CLIENT is None:
        return None
    try:
        return str(_CLIENT.create_trace_id())
    except Exception:  # noqa: BLE001
        return None


@contextmanager
def rag_trace(question: str, *, n_history: int = 0) -> Iterator[Any]:
    """Open the root observation. Yields it, or None when tracing is off.

    Never raises and never swallows the caller's exception: the pipeline must behave
    identically whether or not Langfuse is reachable.
    """
    if not _ENABLED or _CLIENT is None:
        yield None
        return
    root = None
    cm = None
    try:
        trace_id = _CLIENT.create_trace_id()
        cm = _CLIENT.start_as_current_observation(
            trace_context={"trace_id": trace_id},
            as_type="chain",
            name="rag_answer",
            input={"question": question, "n_history": n_history},
        )
        # start_as_current_observation returns a CONTEXT MANAGER; the observation is what
        # __enter__() hands back. Keeping the manager and calling start_observation() on it
        # raises AttributeError - which this module swallows by design, so the root was
        # created (the manager does that on entry) while every child silently vanished.
        # The visible symptom was a correctly named trace containing exactly one node,
        # indistinguishable from the flat trace this code replaced.
        root = cm.__enter__()
    except Exception:  # noqa: BLE001
        root = None
        cm = None
    token = _ROOT.set(root)
    try:
        yield root
    finally:
        _ROOT.reset(token)
        if cm is not None:
            with suppress(Exception):
                cm.__exit__(None, None, None)



# The root of the trace currently being built, so `stage()` can attach to it without every
# pipeline stage having to thread the object through its signature.
#
# A ContextVar, NOT a module global: concurrent requests each build their own tree, and a
# global would let one request's stages land under another's root. asyncio copies the
# context per task, so each request sees its own value.
_ROOT: ContextVar[Any] = ContextVar("langfuse_root", default=None)


@contextmanager
def stage(name: str, as_type: str = "span") -> Iterator[None]:
    """Record one pipeline stage as a child observation of the current trace root.

    This is deliberately NOT Langfuse's LangChain CallbackHandler. That handler does
    `import langchain` purely to read `__version__` and then imports everything it needs
    from `langchain_core`, which is already a dependency - so using it would mean adding
    the full `langchain` package, at a major version that conflicts with the pinned
    `langchain-core>=0.3,<1`, to satisfy a version check. The tree is the goal, not the
    handler; this produces the same shape with no new dependency, and every node is a real
    stage of THIS pipeline rather than framework plumbing (RunnableSequence,
    RunnableParallel, RunnableAssign) that describes LangChain more than it describes us.
    """
    root = _ROOT.get()
    if root is None:
        yield
        return
    child = None
    try:
        child = root.start_observation(as_type=as_type, name=name)
    except Exception:  # noqa: BLE001 - a tracer must never fail a medical answer
        child = None
    try:
        yield
    finally:
        if child is not None:
            with suppress(Exception):
                child.end()


def langchain_handler() -> Any:
    """The LangChain callback handler, or None.

    Returning None rather than raising keeps `config={"callbacks": [...]}` construction at
    the call site free of conditionals - an empty list is a valid config.
    """
    if not _ENABLED:
        return None
    try:
        from langfuse.langchain import CallbackHandler

        return CallbackHandler()
    except Exception:  # noqa: BLE001
        return None


def emit_generation(
    root: Any,
    *,
    model_id: str | None,
    venue: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
    duration_ms: float | None,
    output_text: str,
    kind: str,
    n_contexts: int,
) -> None:
    """Attach the LLM call as a GENERATION child of the root.

    It must be a child of `root` rather than a fresh observation carrying its own
    trace_context: Langfuse treats an explicit trace_context as a TRACE-LEVEL write, so a
    second one renames the whole trace after `generate_llm`. Measured, not assumed.

    `model`, `usage_details` and `cost_details` live here and not on the root because the
    cost-per-model, tokens/sec and spend-over-time views read them from GENERATION
    observations specifically; on any other type they are inert.
    """
    if root is None:
        return
    try:
        gen = root.start_observation(
            as_type="generation",
            name="generate",
            model=model_id,
            input={"n_contexts": n_contexts},
            output={"answer": output_text},
            usage_details={
                "input": prompt_tokens,
                "output": completion_tokens,
                "total": prompt_tokens + completion_tokens,
            },
            cost_details={"total": round(cost_usd, 6)},
            metadata={"venue": venue, "kind": kind},
        )
        if duration_ms:
            gen.end(end_time=_time.time_ns() + int(duration_ms * 1_000_000))
        else:
            gen.end()
    except Exception:  # noqa: BLE001
        return


def close_root(root: Any, *, answer_text: str, kind: str, **metadata: Any) -> None:
    """Record the outcome on the root so the trace list shows the answer, not just a name."""
    if root is None:
        return
    with suppress(Exception):
        root.update(
            output={"answer": answer_text, "kind": kind},
            metadata={k: v for k, v in metadata.items() if v is not None},
        )


def flush() -> None:
    """Drain buffered events at shutdown so the last requests before a rollout are not lost."""
    if _ENABLED and _CLIENT is not None:
        try:
            _CLIENT.flush()
        except Exception:  # noqa: BLE001
            return
