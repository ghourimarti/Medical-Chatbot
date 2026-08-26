"""S20: users, conversations, and the anonymous-to-signed-in seam (D24, D25).

Runs against a real Postgres; skips if unreachable. The CHECK constraint and the FK cascade
are half the design, and neither exists in SQLite — testing this against a fake would verify
the ORM and nothing about the schema.

The dedicated `_test` database and its guard exist because this fixture drops every table.
See test_db.py for the incident that produced that rule.
"""

from __future__ import annotations

import uuid

import pytest
from medapi.db.engine import build_engine, build_session_factory, session_scope
from medapi.db.repository import (
    ConversationRepository,
    MessageRepository,
    UserRepository,
)
from medapi.db.schema_sql import DROP_ALL, INITIAL_DDL
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

DB_NAME = "medbot_test"
ADMIN_DSN = "postgresql+asyncpg://medbot:medbot@localhost:5001/postgres"
DSN = f"postgresql+asyncpg://medbot:medbot@localhost:5001/{DB_NAME}"


def _assert_disposable(dsn: str) -> None:
    name = dsn.rsplit("/", 1)[-1].split("?")[0]
    if not name.endswith("_test"):
        raise RuntimeError(f"refusing destructive DDL against {name!r}: must end in '_test'")


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


@pytest.fixture
async def engine() -> AsyncEngine:  # type: ignore[misc]
    _assert_disposable(DSN)
    if not await _ensure_db() or not await _reachable(DSN):
        pytest.skip("Postgres unreachable; `docker compose up -d postgres`")
    eng = build_engine(DSN, pool_size=2, max_overflow=2)
    async with eng.begin() as conn:
        # Split on ';': asyncpg prepares each statement and cannot run several at once.
        # test_db.py does the same — copying its fixture from memory instead of reading it
        # is exactly how this was missed.
        for stmt in DROP_ALL.strip().split(";"):
            if stmt.strip():
                await conn.execute(text(stmt))
        for ddl in INITIAL_DDL:
            await conn.execute(text(ddl))
        # messages is partitioned: without a partition covering today, every insert fails.
        from medapi.db.partitions import ensure_future_partitions

        await ensure_future_partitions(conn, days_ahead=2)
    yield eng
    await eng.dispose()


# ---------------------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------------------
async def test_user_upsert_is_idempotent(engine: AsyncEngine) -> None:
    """One human, one row. Two rows for one subject would split their history in half, and
    nothing would report an error — the user would simply find half their conversations."""
    factory = build_session_factory(engine)
    async with session_scope(factory) as s:
        first = await UserRepository(s).upsert("clerk|user_abc")
        first_id = first.id
    async with session_scope(factory) as s:
        again = await UserRepository(s).upsert("clerk|user_abc")
        assert again.id == first_id


async def test_users_store_no_pii_beyond_the_subject(engine: AsyncEngine) -> None:
    """Data minimisation (D18): the table must not grow an email or name column without a
    deliberate decision, because each one is a deletion obligation and a breach surface."""
    async with engine.connect() as conn:
        cols = {
            r[0]
            for r in (
                await conn.execute(
                    text("SELECT column_name FROM information_schema.columns "
                         "WHERE table_name = 'users'")
                )
            ).all()
        }
    assert cols == {"id", "auth_subject", "created_at", "last_seen_at"}, cols


# ---------------------------------------------------------------------------------------
# Ownership — the security property
# ---------------------------------------------------------------------------------------
async def test_a_conversation_cannot_be_ownerless(engine: AsyncEngine) -> None:
    factory = build_session_factory(engine)
    async with session_scope(factory) as s:
        with pytest.raises(ValueError, match="needs an owner"):
            await ConversationRepository(s).create(user_id=None, session_id=None)

    # And the database refuses it too, so a future caller bypassing the repository cannot
    # create one either. Belt and braces on an invariant that is invisible once violated.
    async with engine.begin() as conn:
        with pytest.raises(IntegrityError):
            await conn.execute(
                text("INSERT INTO conversations (id) VALUES (:i)"), {"i": str(uuid.uuid4())}
            )


async def test_one_user_cannot_read_anothers_conversation(engine: AsyncEngine) -> None:
    factory = build_session_factory(engine)
    async with session_scope(factory) as s:
        users, convos = UserRepository(s), ConversationRepository(s)
        alice = await users.upsert("clerk|alice")
        bob = await users.upsert("clerk|bob")
        hers = await convos.create(user_id=alice.id, session_id=None, title="Alice thread")
        await s.flush()

        assert await convos.owned_by(hers.id, user_id=alice.id, session_id=None) is not None
        # Not "forbidden" — indistinguishable from "does not exist", so the endpoint cannot
        # be used to discover whether someone else's conversation id is real.
        assert await convos.owned_by(hers.id, user_id=bob.id, session_id=None) is None


async def test_a_session_cannot_read_a_claimed_conversation(engine: AsyncEngine) -> None:
    """Once a conversation belongs to an account, the session cookie that created it must
    no longer open it. Otherwise a shared browser leaks a signed-in user's history to
    whoever uses the machine next."""
    factory = build_session_factory(engine)
    sid = uuid.uuid4()
    # Mutate in one session, verify in ANOTHER — which is what actually happens: the claim
    # is one request and the next read is a different one. Verifying in the same session
    # would also fight the identity map, since claim_for_user issues a bulk UPDATE that
    # does not refresh already-loaded objects.
    async with session_scope(factory) as s:
        convos = ConversationRepository(s)
        user = await UserRepository(s).upsert("clerk|carol")
        convo = await convos.create(user_id=None, session_id=sid)
        await s.flush()
        assert await convos.owned_by(convo.id, user_id=None, session_id=sid) is not None
        convo_id, user_id = convo.id, user.id

    async with session_scope(factory) as s:
        await ConversationRepository(s).claim_for_user(session_id=sid, user_id=user_id)

    async with session_scope(factory) as s:
        convos = ConversationRepository(s)
        assert await convos.owned_by(convo_id, user_id=None, session_id=sid) is None
        assert await convos.owned_by(convo_id, user_id=user_id, session_id=None) is not None


# ---------------------------------------------------------------------------------------
# The sign-in seam
# ---------------------------------------------------------------------------------------
async def test_signing_in_claims_the_anonymous_conversation(engine: AsyncEngine) -> None:
    """The conversation someone just had is usually the reason they signed up. Losing it at
    the moment of sign-in is the worst possible time to lose it."""
    factory = build_session_factory(engine)
    sid = uuid.uuid4()
    async with session_scope(factory) as s:
        convos = ConversationRepository(s)
        await convos.create(user_id=None, session_id=sid, title="before sign-in")
        await s.flush()

        user = await UserRepository(s).upsert("clerk|dave")
        claimed = await convos.claim_for_user(session_id=sid, user_id=user.id)
        assert claimed == 1

        mine = await convos.list_for_owner(user_id=user.id, session_id=None)
        assert [c.title for c in mine] == ["before sign-in"]


async def test_claiming_never_steals_an_already_claimed_conversation(
    engine: AsyncEngine,
) -> None:
    """THE SECURITY CASE. Two accounts on one shared browser: the second sign-in must not
    re-assign the first account's conversations. Without `user_id IS NULL` in the predicate
    this is a cross-account data leak wearing the costume of a merge."""
    factory = build_session_factory(engine)
    sid = uuid.uuid4()
    async with session_scope(factory) as s:
        users, convos = UserRepository(s), ConversationRepository(s)
        first = await users.upsert("clerk|first")
        second = await users.upsert("clerk|second")

        convo = await convos.create(user_id=None, session_id=sid, title="shared browser")
        await s.flush()
        assert await convos.claim_for_user(session_id=sid, user_id=first.id) == 1
        convo_id, first_id, second_id = convo.id, first.id, second.id

    async with session_scope(factory) as s:
        # Second person signs in on the same machine. Nothing may transfer.
        assert await ConversationRepository(s).claim_for_user(
            session_id=sid, user_id=second_id
        ) == 0

    async with session_scope(factory) as s:
        convos = ConversationRepository(s)
        assert (await convos.owned_by(convo_id, user_id=first_id, session_id=None)) is not None
        assert (await convos.owned_by(convo_id, user_id=second_id, session_id=None)) is None


# ---------------------------------------------------------------------------------------
# Deletion — provable, not merely claimed
# ---------------------------------------------------------------------------------------
async def test_deleting_a_conversation_removes_its_messages_and_says_how_many(
    engine: AsyncEngine,
) -> None:
    factory = build_session_factory(engine)
    sid = uuid.uuid4()
    async with session_scope(factory) as s:
        convos, msgs = ConversationRepository(s), MessageRepository(s)
        convo = await convos.create(user_id=None, session_id=sid)
        await s.flush()
        for role, content in (("user", "q"), ("assistant", "a")):
            await msgs.add(
                session_id=sid, role=role, content=content, conversation_id=convo.id
            )
        await s.flush()

        assert await convos.delete(convo) == 2


async def test_account_deletion_removes_messages_before_the_cascade(
    engine: AsyncEngine,
) -> None:
    """Messages carry no foreign key — deliberately, since a cascade across partitions would
    defeat DROP PARTITION. So deleting a user must remove messages EXPLICITLY and FIRST:
    once the cascade takes the conversations, their messages are unreachable orphans that
    only the 30-day partition drop would clear, which is not a deletion anyone would accept.
    """
    factory = build_session_factory(engine)
    sid = uuid.uuid4()
    async with session_scope(factory) as s:
        users, convos, msgs = UserRepository(s), ConversationRepository(s), MessageRepository(s)
        user = await users.upsert("clerk|erin")
        convo = await convos.create(user_id=user.id, session_id=sid)
        await s.flush()
        await msgs.add(session_id=sid, role="user", content="q", conversation_id=convo.id)
        await s.flush()

        assert await convos.delete_for_user(user.id) == 1
        assert await users.delete(user.id) == 1

    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM conversations")) == 0
        assert await conn.scalar(text("SELECT count(*) FROM messages")) == 0


async def test_anonymous_history_still_works_unchanged(engine: AsyncEngine) -> None:
    """D24 sequencing: adding accounts must not disturb the anonymous path. A message with
    no conversation is legal and still readable by session."""
    factory = build_session_factory(engine)
    sid = uuid.uuid4()
    async with session_scope(factory) as s:
        msgs = MessageRepository(s)
        await msgs.add(session_id=sid, role="user", content="anonymous question")
        await s.flush()
        history = await msgs.history(sid)
        assert [m.content for m in history] == ["anonymous question"]
