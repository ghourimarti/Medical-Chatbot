"""identity verification and the conversation endpoints.

Uses a STUB verifier rather than a Clerk account, so the authorisation rules are provable
today instead of "once someone configures an identity provider". That is the reason
AuthVerifier is a Protocol: the security properties are the part that must be tested, and
they do not depend on who issues the token.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from medapi.auth import InvalidToken, bearer_token
from medapi.conversations import Caller, ConversationNotFound, ConversationService
from medapi.conversations import router as conversations_router
from medapi.db.engine import build_engine, build_session_factory
from medapi.db.schema_sql import DROP_ALL, INITIAL_DDL
from sqlalchemy import text

from medcore.errors import MedbotError

pytestmark = pytest.mark.integration

DB_NAME = "medbot_test"
ADMIN_DSN = "postgresql+asyncpg://medbot:medbot@localhost:5001/postgres"
DSN = f"postgresql+asyncpg://medbot:medbot@localhost:5001/{DB_NAME}"


class StubVerifier:
    """Maps a token to a subject. Anything not in the map is rejected, exactly as a real
    verifier rejects a bad signature."""

    enabled = True

    def __init__(self, tokens: dict[str, str]) -> None:
        self._tokens = tokens

    async def subject(self, token: str) -> str:
        if token not in self._tokens:
            raise InvalidToken("stub: unknown token")
        return self._tokens[token]


class DisabledStub:
    enabled = False

    async def subject(self, token: str) -> str:
        raise InvalidToken("accounts are not configured")


async def _reachable(dsn: str) -> bool:
    try:
        engine = build_engine(dsn, pool_size=1, max_overflow=0)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        return True
    except Exception:
        return False


async def _ensure_db() -> bool:
    if not await _reachable(ADMIN_DSN):
        return False
    admin = build_engine(ADMIN_DSN, pool_size=1, max_overflow=0)
    try:
        async with admin.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            if not await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": DB_NAME}
            ):
                await conn.execute(text(f'CREATE DATABASE "{DB_NAME}"'))
    finally:
        await admin.dispose()
    return True


Factory = Callable[..., AsyncClient]


@pytest.fixture
async def app_factory() -> AsyncIterator[Factory]:
    if not DSN.endswith("_test"):
        raise RuntimeError("refusing destructive DDL against a non-test database")
    if not await _ensure_db() or not await _reachable(DSN):
        pytest.skip("Postgres unreachable; `docker compose up -d postgres`")
    engine = build_engine(DSN, pool_size=3, max_overflow=2)
    async with engine.begin() as conn:
        for stmt in DROP_ALL.strip().split(";"):
            if stmt.strip():
                await conn.execute(text(stmt))
        for ddl in INITIAL_DDL:
            await conn.execute(text(ddl))
        from medapi.db.partitions import ensure_future_partitions

        await ensure_future_partitions(conn, days_ahead=2)
    factory = build_session_factory(engine)

    # httpx.AsyncClient over an ASGI transport, NOT fastapi's TestClient.
    #
    # TestClient runs the app in its OWN event loop (an anyio BlockingPortal), while this
    # fixture built the asyncpg pool in pytest-asyncio's loop. An asyncpg connection belongs
    # to the loop that created it, so every DB call failed with "attached to a different
    # loop" / "unknown protocol state". Staying in one loop is the fix. Building the engine
    # inside the app's lifespan would also work, but it would test a wiring that production
    # does not use.
    def build(verifier: Any, session_id: uuid.UUID | None = None) -> AsyncClient:
        sid = session_id or uuid.uuid4()
        app = FastAPI()
        app.include_router(conversations_router)

        @app.exception_handler(MedbotError)
        async def _handler(request: Any, exc: MedbotError) -> JSONResponse:
            return JSONResponse(status_code=exc.status, content=exc.to_problem().model_dump())

        app.state.services = SimpleNamespace(
            sessions=SimpleNamespace(
                resolve=lambda request: (sid, True),
                attach=lambda response, s: response.set_cookie("medbot_sid", str(s)),
            ),
            conversations=ConversationService(factory, verifier),
        )
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    # The session factory is exposed so a test can build a ConversationService directly
    # instead of digging one out of client._transport.app — a private attribute that would
    # break on an httpx upgrade for no benefit.
    build.factory = factory  # type: ignore[attr-defined]
    yield build
    await engine.dispose()


def _auth(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


CONVOS = "/api/v1/conversations"


# The rule: present-but-invalid is 401, never a silent downgrade
async def test_an_invalid_token_is_401_not_anonymous(app_factory: Factory) -> None:
    """Downgrading a bad token to anonymous hides an attack (a forged token looks exactly
    like a signed-out visitor) AND confuses an honest user whose session expired: they stay
    signed in visually while their conversations vanish, with nothing to explain it."""
    async with app_factory(StubVerifier({"good": "clerk|alice"})) as client:
        got = await client.get(CONVOS, headers=_auth("forged"))
    assert got.status_code == 401


async def test_no_token_is_anonymous_and_works(app_factory: Factory) -> None:
    """D24 sequencing: anonymous chat never waits on an identity provider."""
    async with app_factory(StubVerifier({})) as client:
        body = (await client.get(CONVOS)).json()
    assert body["signed_in"] is False
    assert body["enabled"] is True


async def test_a_token_against_a_deployment_without_accounts_is_401(
    app_factory: Factory,
) -> None:
    """The client believes it is authenticated and must be told it is not, or it renders a
    signed-in UI over anonymous data."""
    async with app_factory(DisabledStub()) as client:
        got = await client.get(CONVOS, headers=_auth("anything"))
    assert got.status_code == 401


def test_a_malformed_authorization_header_is_treated_as_absent() -> None:
    # Indistinguishable from a client that is simply not signed in. Treating a typo as an
    # attack helps nobody.
    assert bearer_token(None) is None
    assert bearer_token("Basic abc") is None
    assert bearer_token("Bearer") is None
    assert bearer_token("Bearer   ") is None
    assert bearer_token("Bearer tok") == "tok"


# Ownership over HTTP
async def test_one_user_gets_404_not_403_for_anothers_conversation(
    app_factory: Factory,
) -> None:
    """404, never 403. Distinguishing them turns the endpoint into an oracle: an attacker
    enumerating ids learns which are real from the status code alone."""
    verifier = StubVerifier({"alice": "clerk|alice", "bob": "clerk|bob"})
    async with app_factory(verifier) as client:
        created = await client.post(CONVOS, json={"title": "hers"}, headers=_auth("alice"))
        assert created.status_code == 201
        cid = created.json()["id"]

        mine = await client.get(f"{CONVOS}/{cid}/messages", headers=_auth("alice"))
        theirs = await client.get(f"{CONVOS}/{cid}/messages", headers=_auth("bob"))
        removed = await client.delete(f"{CONVOS}/{cid}", headers=_auth("bob"))
        renamed = await client.patch(
            f"{CONVOS}/{cid}", json={"title": "mine now"}, headers=_auth("bob")
        )

    assert mine.status_code == 200
    assert theirs.status_code == 404
    assert removed.status_code == 404
    assert renamed.status_code == 404


async def test_a_user_only_lists_their_own(app_factory: Factory) -> None:
    verifier = StubVerifier({"alice": "clerk|alice", "bob": "clerk|bob"})
    async with app_factory(verifier) as client:
        await client.post(CONVOS, json={"title": "hers"}, headers=_auth("alice"))
        hers = (await client.get(CONVOS, headers=_auth("alice"))).json()
        his = (await client.get(CONVOS, headers=_auth("bob"))).json()

    assert [c["title"] for c in hers["conversations"]] == ["hers"]
    assert his["conversations"] == []


# The sign-in seam, end to end
async def test_signing_in_claims_the_anonymous_conversation(app_factory: Factory) -> None:
    """One browser: ask anonymously, then sign in. The conversation must survive — it is
    usually the reason the person signed up."""
    verifier = StubVerifier({"alice": "clerk|alice"})
    async with app_factory(verifier, session_id=uuid.uuid4()) as client:
        await client.post(CONVOS, json={"title": "before sign-in"})
        before = (await client.get(CONVOS, headers=_auth("alice"))).json()
        claimed = (await client.post("/api/v1/auth/claim", headers=_auth("alice"))).json()
        after = (await client.get(CONVOS, headers=_auth("alice"))).json()

    # Signed in, but nothing transferred yet: the thread is still the session's.
    assert before["conversations"] == []
    assert claimed == {"claimed": 1, "signed_in": True}
    assert [c["title"] for c in after["conversations"]] == ["before sign-in"]
    assert after["conversations"][0]["claimed"] is True


async def test_a_second_account_on_the_same_browser_claims_nothing(
    app_factory: Factory,
) -> None:
    """THE SECURITY CASE, over HTTP. A shared machine must not hand the first account's
    conversations to the second person who signs in."""
    verifier = StubVerifier({"first": "clerk|first", "second": "clerk|second"})
    async with app_factory(verifier, session_id=uuid.uuid4()) as client:
        await client.post(CONVOS, json={"title": "first person"})
        first = (await client.post("/api/v1/auth/claim", headers=_auth("first"))).json()
        second = (await client.post("/api/v1/auth/claim", headers=_auth("second"))).json()
        theirs = (await client.get(CONVOS, headers=_auth("second"))).json()

    assert first["claimed"] == 1
    assert second["claimed"] == 0
    assert theirs["conversations"] == []


async def test_claiming_while_anonymous_is_a_no_op(app_factory: Factory) -> None:
    async with app_factory(StubVerifier({})) as client:
        body = (await client.post("/api/v1/auth/claim")).json()
    assert body == {"claimed": 0, "signed_in": False}


# Deletion reports evidence
async def test_delete_reports_how_many_messages_it_removed(app_factory: Factory) -> None:
    async with app_factory(StubVerifier({"alice": "clerk|alice"})) as client:
        created = await client.post(CONVOS, json={"title": "x"}, headers=_auth("alice"))
        cid = created.json()["id"]
        body = (await client.delete(f"{CONVOS}/{cid}", headers=_auth("alice"))).json()
        gone = await client.get(f"{CONVOS}/{cid}/messages", headers=_auth("alice"))

    assert body["conversation_id"] == cid
    assert body["deleted_messages"] == 0  # none written yet, but the count is REPORTED
    assert gone.status_code == 404


# resolve_thread — the authorisation seam the QUERY path uses
#
# test_stream_parity.py proves both endpoints CALL this and honour its three outcomes, but
# it does so against a stub. These exercise the real service, because the interesting case
# — "the database is unreachable, so ownership cannot be proven" — is a property of this
# implementation and would not be caught by a stub that hardcodes the answer.
async def test_resolve_thread_accepts_a_thread_the_caller_owns(app_factory: Factory) -> None:
    async with app_factory(StubVerifier({"alice": "clerk|alice"})) as client:
        created = await client.post(CONVOS, json={"title": "mine"}, headers=_auth("alice"))
        cid = uuid.UUID(created.json()["id"])

    svc = ConversationService(app_factory.factory, StubVerifier({"alice": "clerk|alice"}))  # type: ignore[attr-defined]
    owner = Caller(session_id=uuid.uuid4(), user_id=await svc.resolve_user("alice"))
    stranger = Caller(session_id=uuid.uuid4(), user_id=None)

    assert await svc.resolve_thread(owner, cid) == cid
    # Same id, different caller: rejected, and by the SAME error the read path uses.
    with pytest.raises(ConversationNotFound):
        await svc.resolve_thread(stranger, cid)
    # No thread requested is always fine — the anonymous path.
    assert await svc.resolve_thread(owner, None) is None


async def test_resolve_thread_degrades_rather_than_authorising_when_the_db_is_down() -> None:
    """"Cannot prove ownership" must resolve to "write no thread", never to "allow".

    Failing OPEN here would be the worst kind of outage bug: a Postgres blip would turn
    every caller-supplied id into an authorised one, so the moment the database recovered
    the writes would already have landed in strangers' threads.
    """

    class _BrokenFactory:
        def __call__(self, *a: Any, **k: Any) -> Any:
            raise ConnectionRefusedError("postgres is down")

    svc = ConversationService(_BrokenFactory(), StubVerifier({}))
    caller = Caller(session_id=uuid.uuid4(), user_id=None)

    # Answers, does not raise, and authorises nothing.
    assert await svc.resolve_thread(caller, uuid.uuid4()) is None


# Accounts health is an OPERATOR fact
async def test_accounts_health_is_reported_without_touching_the_request_path() -> None:
    """Three independent facts, because they fail independently: identity can be
    unconfigured, storage can be down, and the JWKS can be unreachable while the other two
    are fine. Collapsing them into one boolean makes an outage unreadable — an operator
    seeing `accounts: false` cannot tell whether to fix Postgres or Clerk."""
    from types import SimpleNamespace

    from medapi.routes import _accounts_status

    off = await _accounts_status(
        SimpleNamespace(verifier=None, conversations=None, settings=SimpleNamespace())
    )
    assert off == {"enabled": False, "storage": False}
    # No JWKS probe when accounts are off: nothing to probe, and no network call to hang.
    assert "jwks_reachable" not in off

    partial = await _accounts_status(
        SimpleNamespace(
            verifier=StubVerifier({}),
            conversations=SimpleNamespace(enabled=False),
            settings=SimpleNamespace(),
        )
    )
    # Identity configured, storage gone. The signed-in product is broken; the anonymous one
    # is not, and this is the pair of booleans that says so.
    assert partial == {"enabled": True, "storage": False}


def test_readiness_never_depends_on_accounts() -> None:
    """/readyz must not consult the verifier. Failing readiness on a JWKS outage would take
    every pod out of the load balancer over a dependency the anonymous product never uses,
    and the autoscaler would then cycle healthy pods for the duration of someone else's
    incident."""
    import inspect

    from medapi.routes import _readiness_checks, public_status

    for fn in (_readiness_checks, public_status):
        source = inspect.getsource(fn)
        assert "verifier" not in source, f"{fn.__name__} reads accounts state"
        assert "jwks" not in source.lower(), f"{fn.__name__} probes the identity provider"
