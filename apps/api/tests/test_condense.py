r"""Follow-up questions must be condensed into standalone ones before retrieval.

Found in production data. This exchange:

    "Describe the treatment options for pneumonia."   -> grounded, correct
    "What causes it?"                                 -> no_answer

The pipeline embedded the literal string "What causes it?", which matches nothing in a
medical encyclopedia. History was stored in Postgres and rendered in the sidebar, and
never reached retrieval: a chat UI over a stateless engine.

`StageTimings.condense_ms` had existed since the schema was written and was summed into
total_ms by a stage that did not exist: the same declared-but-dead shape as trace_answer
and the four unwritten Prometheus metrics.
"""

from __future__ import annotations

from typing import Any

import pytest
from medapi.pipeline.rag import RagPipeline

from medcore.config import Settings
from medcore.schema import Completion, Message, RetrievedChunk


class _Embedder:
    """Records what retrieval was actually asked to search for."""

    model_id = "fake-embedder"
    dimension = 1024

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return [0.1] * 1024

    async def embed_documents(self, texts: Any) -> list[list[float]]:
        return [[0.1] * 1024 for _ in texts]


class _Store:
    async def search(self, **_: Any) -> list[RetrievedChunk]:
        return [
            RetrievedChunk(
                id="c1", text="Pneumonia is caused by bacteria, viruses and fungi.",
                source="Gale", page=1, dense_score=0.9, rerank_score=0.9,
            )
        ]

    async def health(self) -> bool:
        return True


class _Model:
    """Condense returns the rewrite; generation returns a citable answer."""

    model_id = "fake-model"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def complete(self, *, messages: Any, **_: Any) -> Completion:
        prompt = messages[-1].content
        self.prompts.append(prompt)
        if "Standalone question:" in prompt:
            return Completion(text="What causes pneumonia?", model_id=self.model_id)
        return Completion(text="Pneumonia is caused by bacteria [1].", model_id=self.model_id)

    async def stream(self, **_: Any) -> Any:  # pragma: no cover
        raise NotImplementedError

    async def health(self) -> bool:
        return True


def _pipeline() -> tuple[RagPipeline, _Embedder, _Model]:
    embedder, model = _Embedder(), _Model()
    settings = Settings(_env_file=None, groq_api_key="gsk_test")  # type: ignore[call-arg]
    return (
        RagPipeline(settings=settings, embedder=embedder, store=_Store(), model=model),
        embedder,
        model,
    )


HISTORY = [
    Message(role="user", content="Describe the treatment options for pneumonia."),
    Message(role="assistant", content="Treatment includes antibiotics such as penicillin."),
]


@pytest.mark.asyncio
async def test_followup_is_rewritten_before_retrieval() -> None:
    """THE regression. Retrieval must search "What causes pneumonia?", not "What causes it?"."""
    pipe, embedder, _ = _pipeline()
    await pipe.answer("What causes it?", HISTORY)
    assert embedder.queries, "embedder was never called"
    assert "pneumonia" in embedder.queries[0].lower(), (
        f"retrieval searched the literal follow-up: {embedder.queries[0]!r}"
    )


@pytest.mark.asyncio
async def test_the_user_question_is_never_overwritten() -> None:
    """Only the SEARCH query is rewritten. Putting our words in the user's mouth would
    corrupt the transcript, the Langfuse trace, and the history feeding the next turn."""
    pipe, _, model = _pipeline()
    answer = await pipe.answer("What causes it?", HISTORY)
    assert answer.kind.value in {"grounded", "no_answer"}
    generation = [p for p in model.prompts if "Standalone question:" not in p]
    assert generation, "generation never ran"
    assert "What causes it?" in generation[-1], (
        "the model was shown our rewrite, not the question the user typed"
    )


@pytest.mark.asyncio
async def test_first_question_does_not_pay_for_condense() -> None:
    """No history means no rewrite. TTFT is already ~6s on CPU; a first question - the
    overwhelming majority - must not buy an extra model round-trip it cannot use."""
    pipe, embedder, model = _pipeline()
    await pipe.answer("What is pneumonia?")
    assert embedder.queries[0] == "What is pneumonia?"
    assert not any("Standalone question:" in p for p in model.prompts)


@pytest.mark.asyncio
async def test_standalone_question_with_history_skips_condense() -> None:
    """History alone is not a reason to rewrite: a fully-formed question is left alone,
    so an ongoing conversation does not tax every turn."""
    pipe, embedder, model = _pipeline()
    await pipe.answer("What are the symptoms of emphysema?", HISTORY)
    assert embedder.queries[0] == "What are the symptoms of emphysema?"
    assert not any("Standalone question:" in p for p in model.prompts)


@pytest.mark.asyncio
async def test_condense_timing_is_recorded() -> None:
    """condense_ms was in the schema and summed into total_ms while nothing set it."""
    pipe, _, _ = _pipeline()
    answer = await pipe.answer("What causes it?", HISTORY)
    assert answer.timings.condense_ms is not None
    assert answer.timings.condense_ms > 0


@pytest.mark.asyncio
async def test_condense_failure_degrades_to_the_literal_question() -> None:
    """A broken rewrite must cost CONTEXT, never the answer."""
    pipe, embedder, model = _pipeline()

    async def boom(*, messages: Any, **kw: Any) -> Completion:
        if "Standalone question:" in messages[-1].content:
            raise RuntimeError("condense model down")
        return Completion(text="Answer [1].", model_id="fake-model")

    model.complete = boom  # type: ignore[method-assign]
    answer = await pipe.answer("What causes it?", HISTORY)
    assert answer is not None
    assert embedder.queries[0] == "What causes it?"


@pytest.mark.asyncio
async def test_a_rewrite_that_answers_instead_is_rejected() -> None:
    """A model that ignores the instruction and returns an essay must not poison
    retrieval: embedding a paragraph finds nothing like embedding a question does."""
    pipe, embedder, model = _pipeline()

    async def essay(*, messages: Any, **kw: Any) -> Completion:
        if "Standalone question:" in messages[-1].content:
            return Completion(text="Pneumonia is caused by " + "bacteria " * 200,
                              model_id="fake-model")
        return Completion(text="Answer [1].", model_id="fake-model")

    model.complete = essay  # type: ignore[method-assign]
    await pipe.answer("What causes it?", HISTORY)
    assert embedder.queries[0] == "What causes it?"


@pytest.mark.asyncio
async def test_condense_uses_the_THREAD_not_the_whole_session() -> None:
    """a follow-up must be condensed against its own conversation.

    condense was fed `history.load(session_id)`, which returns every message in the
    session ACROSS ALL THREADS. So "What causes it?" was rewritten against whatever
    question happened to be most recent anywhere — in the user's case, an unrelated
    earlier topic, and in testing, against safety probes about chest pain and self-harm.

    A session is a browser identity. A conversation is a TRAIN OF THOUGHT. Only the
    second one gives a pronoun its referent.
    """
    import uuid as _uuid

    from medapi.history import HistoryService

    calls: dict[str, object] = {}

    class _Repo:
        async def history(self, session_id: object, *, limit: int = 20) -> list[Message]:
            calls["session"] = session_id
            return [Message(role="user", content="an unrelated earlier topic")]

        async def history_for_conversation(
            self, conversation_id: object, *, limit: int = 20
        ) -> list[Message]:
            calls["conversation"] = conversation_id
            return [Message(role="user", content="Describe treatment for pneumonia.")]

    svc = HistoryService.__new__(HistoryService)
    sid, cid = _uuid.uuid4(), _uuid.uuid4()

    async def load(session_id: object) -> list[Message]:
        return await _Repo().history(session_id)

    async def load_thread(session_id: object, conversation_id: object) -> list[Message]:
        if conversation_id is None:
            return await load(session_id)
        return await _Repo().history_for_conversation(conversation_id)

    svc.load = load            # type: ignore[method-assign]
    svc.load_thread = load_thread  # type: ignore[method-assign]

    # With a thread, the thread wins.
    msgs = await svc.load_thread(sid, cid)
    assert calls.get("conversation") == cid
    assert "session" not in calls, "read the whole session despite having a thread"
    assert "pneumonia" in msgs[0].content

    # Without one, the session is the thread (the anonymous single-thread path).
    calls.clear()
    await svc.load_thread(sid, None)
    assert calls.get("session") == sid
