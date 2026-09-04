"""Two defects that were invisible from outside the system (INFRA-5).

Both were reported as UI problems — "the conversation saves but will not reload", and a
follow-up answering about the wrong condition — and both were in the request path.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from medapi.pipeline.rag import is_context_dependent
from medapi.serving import Preflight, record_short_circuit, short_circuit

from medcore.schema import Answer, AnswerKind, Citation, StageTimings, Usage


def _answer() -> Answer:
    return Answer(
        kind=AnswerKind.GROUNDED,
        text="Cirrhosis is scarring of the liver [1].",
        citations=[Citation(chunk_id="c1", source="Gale", page=202, snippet="scar tissue")],
        model_id="m",
        usage=Usage(prompt_tokens=10, completion_tokens=5),
        timings=StageTimings(total_ms=12.0),
    )


class _History:
    def __init__(self) -> None:
        self.turns: list[dict[str, Any]] = []

    async def record_turn(self, session_id: uuid.UUID, **kw: Any) -> None:
        self.turns.append({"session_id": session_id, **kw})


def _pre(conversation_id: uuid.UUID | None = None) -> Preflight:
    return Preflight(
        session_id=uuid.uuid4(),
        client_key="ip-hash",
        log=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None),
        conversation_id=conversation_id,
    )


# ── #0 · a cache hit is still a turn that happened ───────────────────────────────────


@pytest.mark.asyncio
async def test_cached_answer_is_recorded_in_history() -> None:
    """The whole defect: postflight is the only caller of record_turn, and a cache hit
    returns before it. Every cached answer vanished from the transcript."""
    history = _History()
    svc = SimpleNamespace(history=history)
    pre = _pre()

    await record_short_circuit(_answer(), question="What is cirrhosis?", svc=svc, pre=pre)

    assert len(history.turns) == 1
    assert history.turns[0]["question"] == "What is cirrhosis?"


@pytest.mark.asyncio
async def test_cached_answer_keeps_its_conversation() -> None:
    """The visible symptom. Without the conversation id the row is written against the
    session only, so the thread it was asked in stays empty and 'will not reload'."""
    history = _History()
    svc = SimpleNamespace(history=history)
    convo = uuid.uuid4()

    await record_short_circuit(_answer(), question="q", svc=svc, pre=_pre(convo))

    assert history.turns[0]["conversation_id"] == convo


# ── #4 · a follow-up must never be served from a shared cache ────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        "What causes it?",
        "What triggers it?",
        "why?",
        "and the treatment?",
        "How does it present?",
    ],
)
def test_followups_are_recognised(question: str) -> None:
    assert is_context_dependent(question), f"{question!r} would be cached under its literal text"


@pytest.mark.parametrize(
    "question",
    [
        "What is cirrhosis?",
        "Describe the treatment options for pneumonia.",
        "What are the symptoms of appendicitis in adults?",
    ],
)
def test_standalone_questions_still_use_the_cache(question: str) -> None:
    """The fast path must survive. If everything looked like a follow-up the fix would
    have quietly disabled the response cache entirely."""
    assert not is_context_dependent(question)


@pytest.mark.asyncio
async def test_followup_never_reaches_the_cache() -> None:
    """short_circuit must not even LOOK. Reading and discarding would still be a
    correctness bug the moment someone 'optimised' the discard away."""
    looked = False

    class _Cache:
        async def get(self, question: str) -> Answer | None:
            nonlocal looked
            looked = True
            return _answer()

    svc = SimpleNamespace(cache=_Cache(), spend=None)
    result = await short_circuit("What causes it?", svc, _pre())

    assert result is None, "a follow-up was served from cache"
    assert not looked, "the cache was consulted for a follow-up"


# ── #7 · an empty completion must not become a 500 ───────────────────────────────────


@pytest.mark.parametrize("text", ["", "   ", "\n\n"])
def test_empty_completion_is_relabelled_not_crashed(text: str) -> None:
    """`Answer` refuses a grounded answer with no text — correctly, since an uncited
    wordless answer is the thing the schema exists to prevent. The pipeline was handing it
    exactly that, turning a legitimate model behaviour (a reasoning model exhausting its
    budget on reasoning) into a ValidationError and a 500.

    Asserts the CONSTRUCTION rule rather than the pipeline branch: the branch is one `if`,
    while this is the invariant that made it necessary.
    """
    with pytest.raises(ValueError, match="must have text"):
        Answer(
            kind=AnswerKind.GROUNDED,
            text=text,
            citations=[Citation(chunk_id="c1", source="Gale", snippet="x")],
        )

    # The relabelled shape the pipeline now produces instead must be constructible.
    ok = Answer(kind=AnswerKind.NO_ANSWER, text="I don't have reliable information on that.")
    assert ok.kind is AnswerKind.NO_ANSWER
    assert not ok.citations, "a no_answer must not carry citations it did not use"
