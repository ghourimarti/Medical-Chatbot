"""Langfuse traces must be a TREE, not one flat node.

The previous version emitted a single observation with the stage durations packed into
`metadata`. Everything was recorded and none of it was usable: Langfuse charts, sorts and
filters on OBSERVATIONS, so timings inside one node's metadata cannot be grouped or
compared. The trace also rendered as "Unnamed trace / 0.00s" for a 4-second request.

These tests assert the STRUCTURE, because structure was the defect. They use a fake client
rather than a live Langfuse: the thing under test is what we ASK the SDK to build.

Note this module swallows every exception by design, so a wrong SDK method name silently
disables all tracing and looks identical to a healthy idle system. That is exactly why the
shape is pinned here instead of being eyeballed in the UI.
"""

from __future__ import annotations

from typing import Any

import pytest
from medapi.observability import llm_trace


class FakeObservation:
    def __init__(self, name: str, as_type: str, kwargs: dict[str, Any]) -> None:
        self.name = name
        self.as_type = as_type
        self.kwargs = kwargs
        self.children: list[FakeObservation] = []
        self.end_time: int | None = None
        self.updates: list[dict[str, Any]] = []

    def start_observation(self, *, name: str, as_type: str = "span", **kw: Any):
        child = FakeObservation(name, as_type, kw)
        self.children.append(child)
        return child

    def update(self, **kw: Any) -> FakeObservation:
        self.updates.append(kw)
        return self

    def end(self, *, end_time: int | None = None) -> FakeObservation:
        self.end_time = end_time
        return self


class FakeClient:
    def __init__(self) -> None:
        self.roots: list[FakeObservation] = []

    def start_observation(self, *, name: str, as_type: str = "span", **kw: Any):
        root = FakeObservation(name, as_type, kw)
        self.roots.append(root)
        return root


TIMINGS = {
    "embed_ms": 226.6,
    "retrieve_ms": 41.5,
    "rerank_ms": 1803.2,
    "generate_ms": 2400.0,
    "total_ms": 4471.3,
}


def emit(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> FakeObservation:
    client = FakeClient()
    monkeypatch.setattr(llm_trace, "_CLIENT", client)
    monkeypatch.setattr(llm_trace, "_ENABLED", True)
    payload: dict[str, Any] = {
        "question": "What is emphysema?",
        "answer_text": "Emphysema is a chronic respiratory disease [1].",
        "kind": "grounded",
        "prompt_version": "v1",
        "prompt_sha": "a" * 64,
        "model_id": "Qwen/Qwen2.5-7B-Instruct-AWQ",
        "contexts": ["c1", "c2", "c3", "c4"],
        "prompt_tokens": 984,
        "completion_tokens": 124,
        "cost_usd": 0.0,
        "timings": dict(TIMINGS),
        "cache_hit": False,
        "venue": "local-sglang",
    }
    payload.update(overrides)
    llm_trace.trace_answer(**payload)
    assert client.roots, "nothing was emitted at all"
    return client.roots[0]


def test_root_is_named_and_is_a_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    """'Unnamed trace' was the visible symptom of a root nobody named."""
    root = emit(monkeypatch)
    assert root.name == "rag_answer"
    assert root.as_type == "chain"


def test_every_stage_becomes_its_own_observation(monkeypatch: pytest.MonkeyPatch) -> None:
    root = emit(monkeypatch)
    assert [c.name for c in root.children] == ["embed", "retrieve", "rerank", "generate"]


def test_stage_types_are_semantic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Langfuse groups and charts on observation type: a retrieval step typed `span` is
    invisible to every retrieval-quality view."""
    types = {c.name: c.as_type for c in emit(monkeypatch).children}
    assert types == {
        "embed": "embedding",
        "retrieve": "retriever",
        "rerank": "span",
        "generate": "generation",
    }


def test_generation_carries_model_usage_and_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    """These fields are inert on any other observation type, which is how a populated
    trace can still chart as zero spend."""
    gen = next(c for c in emit(monkeypatch).children if c.name == "generate")
    assert gen.kwargs["model"] == "Qwen/Qwen2.5-7B-Instruct-AWQ"
    assert gen.kwargs["usage_details"] == {"input": 984, "output": 124, "total": 1108}
    assert "total" in gen.kwargs["cost_details"]


def test_durations_are_per_stage_not_cumulative(monkeypatch: pytest.MonkeyPatch) -> None:
    """The first attempt used a running cursor, so `retrieve` reported embed+retrieve.
    Each child must be closed relative to ITS OWN start."""
    root = emit(monkeypatch)
    spans = {c.name: c for c in root.children}
    # end_time is absolute ns; the gap to the root's start proves nothing accumulated.
    assert spans["retrieve"].end_time is not None
    assert spans["embed"].end_time is not None
    retrieve_ns = spans["retrieve"].end_time
    embed_ns = spans["embed"].end_time
    # retrieve (41ms) is far SHORTER than embed (226ms); under the cumulative bug its
    # end_time would have been the later of the two by ~41ms.
    assert retrieve_ns < embed_ns


def test_cache_hit_has_no_stage_children(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing stage is SIGNAL. A cache hit ran none of them, and the absent nodes are
    the evidence that no work and no spend occurred."""
    root = emit(monkeypatch, cache_hit=True, timings={"total_ms": 12.0})
    assert root.children == []


def test_retrieval_gated_no_answer_has_no_generate_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Declining before the model is the free path; the absent generation node is how you
    tell it apart from the model abstaining after paying full prompt cost."""
    timings = {"embed_ms": 210.0, "retrieve_ms": 40.0, "rerank_ms": 1700.0,
               "generate_ms": None, "total_ms": 1950.0}
    root = emit(monkeypatch, kind="no_answer", timings=timings, prompt_tokens=0,
                completion_tokens=0)
    assert [c.name for c in root.children] == ["embed", "retrieve", "rerank"]


def test_tracing_failure_cannot_break_answering(monkeypatch: pytest.MonkeyPatch) -> None:
    class Exploding:
        def start_observation(self, **_: Any) -> Any:
            raise RuntimeError("langfuse is down")

    monkeypatch.setattr(llm_trace, "_CLIENT", Exploding())
    monkeypatch.setattr(llm_trace, "_ENABLED", True)
    llm_trace.trace_answer(
        question="q", answer_text="a", kind="grounded", prompt_version="v1",
        prompt_sha="a" * 64, model_id="m", contexts=[], prompt_tokens=1,
        completion_tokens=1, cost_usd=0.0, timings=dict(TIMINGS), cache_hit=False,
    )


class FakeCM:
    """Mimics start_as_current_observation: a CONTEXT MANAGER whose __enter__ yields the
    observation. The distinction is the whole point of these tests."""

    def __init__(self, obs: FakeObservation) -> None:
        self.obs = obs
        self.exited = False

    def __enter__(self) -> FakeObservation:
        return self.obs

    def __exit__(self, *_: Any) -> None:
        self.exited = True


class FakeRootClient(FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.cms: list[FakeCM] = []

    def create_trace_id(self) -> str:
        return "t" * 32

    def start_as_current_observation(self, *, name: str, as_type: str = "span", **kw: Any):
        obs = FakeObservation(name, as_type, kw)
        self.roots.append(obs)
        cm = FakeCM(obs)
        self.cms.append(cm)
        return cm


def test_rag_trace_yields_the_observation_not_the_context_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bug this exists for: start_as_current_observation returns a CONTEXT MANAGER,
    and the observation is what __enter__() returns. Holding the manager makes every
    root.start_observation(...) raise AttributeError - which this module swallows by
    design, so the root appeared (the manager creates it on entry) and every child
    silently vanished. The trace looked correct and named, with exactly one node:
    indistinguishable from the flat trace the tree replaced."""
    client = FakeRootClient()
    monkeypatch.setattr(llm_trace, "_CLIENT", client)
    monkeypatch.setattr(llm_trace, "_ENABLED", True)
    with llm_trace.rag_trace("q") as root:
        assert isinstance(root, FakeObservation), f"got {type(root).__name__}"
        assert hasattr(root, "start_observation")


def test_stages_become_children_of_the_root(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeRootClient()
    monkeypatch.setattr(llm_trace, "_CLIENT", client)
    monkeypatch.setattr(llm_trace, "_ENABLED", True)
    with llm_trace.rag_trace("q") as root:
        for name, kind in (("guard", "guardrail"), ("embed", "embedding"),
                           ("retrieve", "retriever")):
            with llm_trace.stage(name, kind):
                pass
    assert [c.name for c in root.children] == ["guard", "embed", "retrieve"]
    assert [c.as_type for c in root.children] == ["guardrail", "embedding", "retriever"]


def test_context_manager_is_exited(monkeypatch: pytest.MonkeyPatch) -> None:
    """The root must be closed, or its latency never lands."""
    client = FakeRootClient()
    monkeypatch.setattr(llm_trace, "_CLIENT", client)
    monkeypatch.setattr(llm_trace, "_ENABLED", True)
    with llm_trace.rag_trace("q"):
        pass
    assert client.cms[0].exited


def test_stage_is_a_noop_without_a_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """Called outside a trace - a cache hit, a short-circuit - it must not raise."""
    monkeypatch.setattr(llm_trace, "_CLIENT", None)
    monkeypatch.setattr(llm_trace, "_ENABLED", False)
    with llm_trace.stage("embed", "embedding"):
        pass
