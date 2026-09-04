"""The streaming and non-streaming endpoints must enforce the same controls.

Why this file exists
--------------------
`query_stream()` shipped with none of the cross-cutting controls `query()` had: no rate
limiting, no kill switch, no cache, no spend accounting, no history, no session. Measured
against the running service before the fix:

    /api/v1/query          ->  200 x20, then 429 x5     (limit enforced)
    /api/v1/query/stream   ->  200 x25                  (no limit at all)

The browser only ever calls the streaming endpoint, so in practice the deployed rate limit
could be bypassed by using the default path. Nothing caught it because every test and the
eval harness exercised `answer()` / `query()`.

These tests are written to fail if the two paths EVER diverge again — they assert the same
behaviour against both, rather than testing the streaming handler in isolation, because a
test that only knows about one endpoint is what let the gap exist.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from medapi.conversations import ConversationNotFound
from medapi.routes import router

from medcore.errors import MedbotError, QuotaExceededError
from medcore.schema import (
    Answer,
    AnswerKind,
    Citation,
    DoneEvent,
    Message,
    SourcesEvent,
    StageTimings,
    Usage,
)

BOTH_ENDPOINTS = ["/api/v1/query", "/api/v1/query/stream"]
GROUNDED = Answer(
    kind=AnswerKind.GROUNDED,
    text="Cirrhosis is scarring of the liver [1].",
    citations=[Citation(chunk_id="c1", source="Gale", page=42, snippet="scar", score=0.9)],
    model_id="stub",
    usage=Usage(prompt_tokens=10, completion_tokens=5),
    timings=StageTimings(total_ms=12.0),
)


class _Limiter:
    """Allows `limit` calls, then raises — the same contract the real limiter has."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.calls = 0

    async def check(self, key: str, *, scope: str, limit: int, window_seconds: int) -> None:
        # Count only the per-session minute bucket so the assertion is about one dimension.
        if scope != "minute":
            return
        self.calls += 1
        if self.calls > self.limit:
            raise QuotaExceededError("over limit")


class _Cache:
    def __init__(self, hit: Answer | None = None) -> None:
        self.hit = hit
        self.written: list[Answer] = []

    async def get(self, question: str) -> Answer | None:
        return self.hit

    async def set(self, question: str, answer: Answer) -> None:
        self.written.append(answer)


class _History:
    enabled = True

    def __init__(self) -> None:
        self.turns: list[dict[str, Any]] = []

    async def record_turn(self, session_id: UUID, **kw: Any) -> None:
        self.turns.append({"session_id": session_id, **kw})

    async def load_thread(
        self, session_id: UUID, conversation_id: UUID | None
    ) -> list[Message]:
        """Condense reads the THREAD, not the whole session: a session is a browser
        identity, a conversation is a train of thought, and only the second gives a
        pronoun its referent."""
        return await self.load(session_id)

    async def load(self, session_id: UUID) -> list[Message]:
        """Both query routes read history now, to condense follow-ups before retrieval.
        The double returns nothing: these tests assert stream/non-stream PARITY, and a
        double that invented turns would make the two paths differ for a reason that has
        nothing to do with what is under test."""
        return []


class _Pipeline:
    async def answer(self, question: str, history: Any = None) -> Answer:
        return GROUNDED

    async def stream_answer(self, question: str, history: Any = None):  # noqa: ANN201 - async generator
        yield SourcesEvent(citations=GROUNDED.citations)
        yield DoneEvent(
            kind=GROUNDED.kind,
            text=GROUNDED.text,
            citations=GROUNDED.citations,
            model_id=GROUNDED.model_id,
            usage=GROUNDED.usage,
            timings=GROUNDED.timings,
        )


class _Conversations:
    """Stands in for ConversationService with the SAME three outcomes preflight relies on.

    `owned` is the set of threads this caller may write to; `broken` simulates Postgres
    being unreachable, which must degrade rather than authorise.
    """

    def __init__(self, owned: set[UUID] | None = None, broken: bool = False) -> None:
        self.owned = owned or set()
        self.broken = broken
        self.enabled = True

    async def resolve_user(self, token: str | None) -> UUID | None:
        return None

    async def resolve_thread(self, caller: Any, conversation_id: UUID | None) -> UUID | None:
        if conversation_id is None or self.broken:
            return None
        if conversation_id not in self.owned:
            raise ConversationNotFound("not yours")
        return conversation_id


def build_client(
    *,
    limit: int = 20,
    cache_hit: Answer | None = None,
    llm_enabled: bool = True,
    conversations: Any = None,
) -> tuple[TestClient, SimpleNamespace]:
    sid = uuid4()
    services = SimpleNamespace(
        settings=SimpleNamespace(
            rate_limit_per_minute=limit,
            rate_limit_per_day=10_000,
            rate_limit_ip_per_minute=10_000,
            rate_limit_ip_per_day=10_000,
            trusted_proxy_hops=0,
            corpus_version="v1",
            index_version="v1",
        ),
        sessions=SimpleNamespace(
            resolve=lambda request: (sid, True),
            attach=lambda response, s: response.set_cookie("medbot_sid", str(s)),
            client_hash=lambda request, trusted_proxy_hops: None,
        ),
        limiter=_Limiter(limit),
        cache=_Cache(cache_hit),
        kill_switch=SimpleNamespace(llm_enabled=_const(llm_enabled)),
        spend=SimpleNamespace(
            state=_const_state(), record=_record, state_for=lambda t: _OK, total_today=_const(0.0)
        ),
        history=_History(),
        pipeline=_Pipeline(),
        conversations=conversations,
    )
    app = FastAPI()
    app.include_router(router)

    @app.exception_handler(MedbotError)
    async def _handler(request, exc: MedbotError):  # noqa: ANN202
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=exc.status, content=exc.to_problem().model_dump())

    app.state.services = services
    return TestClient(app), services


class _OKState:
    value = "ok"


_OK = _OKState()


def _const(value: Any):  # noqa: ANN202
    async def _f(*a: Any, **k: Any) -> Any:
        return value

    return _f


def _const_state():  # noqa: ANN202
    async def _f() -> Any:
        return _OK

    return _f


async def _record(amount: float) -> float:
    return amount


def _post(client: TestClient, path: str, **extra: Any) -> Any:
    body = {"question": "What is cirrhosis?", "stream": path.endswith("stream"), **extra}
    return client.post(path, json=body)


# THE REGRESSION: rate limiting must apply to BOTH paths.
@pytest.mark.parametrize("path", BOTH_ENDPOINTS)
def test_rate_limit_applies_to_both_endpoints(path: str) -> None:
    client, _ = build_client(limit=3)
    codes = [_post(client, path).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200], f"{path}: allowed requests were rejected"
    assert codes[3:] == [429, 429], (
        f"{path}: quota NOT enforced — this is the exact hole S10.6a closed "
        f"(streaming returned 25x 200 against a 20/min limit)"
    )


@pytest.mark.parametrize("path", BOTH_ENDPOINTS)
def test_quota_rejection_is_a_real_http_status(path: str) -> None:
    """A 429 must be an HTTP status with an RFC 7807 body, NOT an in-band SSE error.
    Once a stream has started the status line is already 200 and the client has to
    special-case a second failure channel."""
    client, _ = build_client(limit=1)
    _post(client, path)
    rejected = _post(client, path)
    assert rejected.status_code == 429
    assert "event:" not in rejected.text, "quota failure was delivered in-band, not as a status"


# The other controls, asserted on both paths.
@pytest.mark.parametrize("path", BOTH_ENDPOINTS)
def test_session_cookie_is_set_on_both(path: str) -> None:
    client, _ = build_client()
    assert "medbot_sid" in _post(client, path).cookies, f"{path}: no session cookie"


@pytest.mark.parametrize("path", BOTH_ENDPOINTS)
def test_history_is_recorded_on_both(path: str) -> None:
    client, services = build_client()
    _post(client, path)
    assert len(services.history.turns) == 1, f"{path}: the answer was never persisted"
    assert services.history.turns[0]["question"] == "What is cirrhosis?"


@pytest.mark.parametrize("path", BOTH_ENDPOINTS)
def test_grounded_answer_is_cached_on_both(path: str) -> None:
    client, services = build_client()
    _post(client, path)
    assert len(services.cache.written) == 1, f"{path}: nothing written to the response cache"


@pytest.mark.parametrize("path", BOTH_ENDPOINTS)
def test_cache_hit_short_circuits_both(path: str) -> None:
    client, services = build_client(cache_hit=GROUNDED)
    response = _post(client, path)
    assert response.status_code == 200
    # A cache hit must not be re-written, and must not persist a duplicate history turn.
    assert services.cache.written == []
    if path.endswith("stream"):
        # Delivered through the SAME event sequence so the client keeps one code path.
        assert "event: sources" in response.text
        assert "event: done" in response.text
        assert "event: token" not in response.text


@pytest.mark.parametrize("path", BOTH_ENDPOINTS)
def test_kill_switch_degrades_on_both(path: str) -> None:
    """With generation disabled both paths must return DEGRADED — never an error, and
    never a normal answer. Before the kill switch did nothing at all for browser
    traffic, so a cost incident could not actually be stopped."""
    client, _ = build_client(llm_enabled=False)
    response = _post(client, path)
    assert response.status_code == 200
    if path.endswith("stream"):
        terminal = json.loads(response.text.strip().split("data: ")[-1])
        assert terminal["kind"] == AnswerKind.DEGRADED.value
    else:
        assert response.json()["kind"] == AnswerKind.DEGRADED.value


# — a READ must not mint a session.
def test_history_read_does_not_mint_a_session() -> None:
    """Found via an intermittently-failing browser test.

    /session/history used to resolve-and-attach unconditionally, so a first-time visitor
    loading the page raced their own first question: both requests arrive cookie-less, both
    mint a session, and whichever Set-Cookie lands last orphans the other session history.

    A visitor with no session has no history by definition, so there is nothing to mint a
    session for. Only a write establishes one.
    """
    client, _ = build_client()
    response = client.get("/api/v1/session/history")

    assert response.status_code == 200
    assert response.json()["messages"] == []
    assert response.json()["session_id"] is None
    assert "medbot_sid" not in response.cookies, (
        "a read minted a session cookie — this is the race that orphans history"
    )


def test_history_read_still_serves_an_established_session() -> None:
    """The fix must not break the case it exists for: once a query has established a
    session, the transcript has to come back."""
    client, services = build_client()
    client.post("/api/v1/query", json={"question": "What is cirrhosis?", "stream": False})
    assert len(services.history.turns) == 1


# — conversation_id is caller-supplied, so BOTH paths must authorise it.
#
# The failure this prevents is a WRITE-side IDOR, which is worse than the read-side one:
# a thread is prompt context, so appending a turn to a stranger's conversation puts text
# of the attacker's choosing into what that person's next request sends to the model.
@pytest.mark.parametrize("path", BOTH_ENDPOINTS)
def test_an_unowned_thread_is_rejected_on_both_endpoints(path: str) -> None:
    client, svc = build_client(conversations=_Conversations(owned={uuid4()}))
    response = _post(client, path, conversation_id=str(uuid4()))

    # 404 as a REAL status line, on the streaming path too. The check runs before the
    # StreamingResponse is constructed; once bytes are on the wire the status is already
    # 200 and the only way left to report the refusal is in-band.
    assert response.status_code == 404, f"{path}: unowned thread was accepted"
    assert svc.history.turns == [], f"{path}: wrote a turn into a thread it did not own"


@pytest.mark.parametrize("path", BOTH_ENDPOINTS)
def test_an_owned_thread_is_persisted_on_both_endpoints(path: str) -> None:
    mine = uuid4()
    client, svc = build_client(conversations=_Conversations(owned={mine}))
    assert _post(client, path, conversation_id=str(mine)).status_code == 200
    assert [t["conversation_id"] for t in svc.history.turns] == [mine], path


@pytest.mark.parametrize("path", BOTH_ENDPOINTS)
def test_an_unverifiable_thread_still_answers_on_both_endpoints(path: str) -> None:
    """a database outage costs history, not the ability to answer.

    "Cannot prove ownership" must resolve to "write no thread", never to "allow" — the
    answer is still served, and nothing lands in anyone's conversation."""
    client, svc = build_client(conversations=_Conversations(broken=True))
    assert _post(client, path, conversation_id=str(uuid4())).status_code == 200
    assert [t["conversation_id"] for t in svc.history.turns] == [None], path


@pytest.mark.parametrize("path", BOTH_ENDPOINTS)
def test_no_thread_is_still_valid_on_both_endpoints(path: str) -> None:
    """D24 sequencing: the anonymous single-thread path predates conversations and must
    keep working with no thread at all."""
    client, svc = build_client(conversations=_Conversations())
    assert _post(client, path).status_code == 200
    assert [t["conversation_id"] for t in svc.history.turns] == [None], path
