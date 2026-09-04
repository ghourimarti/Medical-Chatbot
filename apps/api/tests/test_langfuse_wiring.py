"""Langfuse must actually be CALLED, not merely importable.

llm_trace.py was complete, configured, enabled and verified reachable - and had
no caller anywhere in the codebase. Every container was healthy, the bootstrapped keys
authenticated with HTTP 200, and the trace list stayed empty. A unit test of trace_answer
in isolation would have passed throughout.

So these tests assert the WIRING, which is the part that was missing. They deliberately do
not test what the payload contains: that would re-test llm_trace and miss the point again.
"""

from __future__ import annotations

from typing import Any

import pytest
from medapi import serving

from medcore.schema import Answer, AnswerKind, Citation, StageTimings, Usage


def _grounded() -> Answer:
    return Answer(
        kind=AnswerKind.GROUNDED,
        text="Cirrhosis is scarring of the liver [1].",
        citations=[Citation(chunk_id="c1", source="Gale", page=202, snippet="scar tissue")],
        model_id="Qwen/Qwen2.5-7B-Instruct-AWQ",
        usage=Usage(prompt_tokens=120, completion_tokens=40, cost_usd=0.0),
        timings=StageTimings(embed_ms=20, retrieve_ms=30, rerank_ms=200, generate_ms=800,
                             total_ms=1050),
    )


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(serving.llm_trace, "is_enabled", lambda: True)
    monkeypatch.setattr(serving.llm_trace, "trace_answer", lambda **kw: calls.append(kw))
    return calls


def test_postflight_traces_the_answer(captured: list[dict[str, Any]]) -> None:
    """The regression that matters: postflight must reach Langfuse at all."""
    serving._trace_to_langfuse(_grounded(), question="What is cirrhosis?", pre=None)  # type: ignore[arg-type]
    assert len(captured) == 1, "postflight did not call Langfuse"
    assert captured[0]["model_id"] == "Qwen/Qwen2.5-7B-Instruct-AWQ"
    assert captured[0]["kind"] == "grounded"


def test_prompt_version_is_recorded(captured: list[dict[str, Any]]) -> None:
    """A trace without the prompt version cannot answer 'did the prompt edit cause this?'."""
    serving._trace_to_langfuse(_grounded(), question="q", pre=None)  # type: ignore[arg-type]
    assert captured[0]["prompt_version"] == "v1"
    assert len(captured[0]["prompt_sha"]) == 64


def test_disabled_tracer_is_not_called(monkeypatch: pytest.MonkeyPatch) -> None:
    """No credentials must mean no call, not a crash on every request."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(serving.llm_trace, "is_enabled", lambda: False)
    monkeypatch.setattr(serving.llm_trace, "trace_answer", lambda **kw: calls.append(kw))
    serving._trace_to_langfuse(_grounded(), question="q", pre=None)  # type: ignore[arg-type]
    assert calls == []


def test_tracing_failure_cannot_break_answering(monkeypatch: pytest.MonkeyPatch) -> None:
    """Observability must never be able to fail a medical answer."""
    def boom(**_: object) -> None:
        raise RuntimeError("langfuse is down")

    monkeypatch.setattr(serving.llm_trace, "is_enabled", lambda: True)
    monkeypatch.setattr(serving.llm_trace, "trace_answer", boom)
    # No pytest.raises: postflight runs after the answer is final, so an exception here
    # would turn a delivered answer into a 500.
    serving._trace_to_langfuse(_grounded(), question="q", pre=None)  # type: ignore[arg-type]
