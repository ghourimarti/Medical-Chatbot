"""S7: schema, partition lifecycle, and provable deletion (D1, D9, D18).

Runs against a real Postgres (docker compose up -d postgres); skips if unreachable so
`make check` stays green without it. Partition behaviour cannot be tested against SQLite —
RANGE partitioning is the entire point of the design, so the test must use the real engine.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from medapi.db.engine import build_engine, build_session_factory, session_scope
from medapi.db.partitions import (
    drop_expired_partitions,
    ensure_future_partitions,
    list_partitions,
    partition_name,
)
from medapi.db.repository import MessageRepository, SessionRepository
from medapi.db.schema_sql import DROP_ALL, INITIAL_DDL
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

# A DEDICATED database, never the one the application uses (P5.4).
#
# This file previously pointed at `medbot` — the real local development database — and its
# fixture runs DROP_ALL. Integration tests are not deselected by default, so `make test`
# silently dropped every table in dev. It was found the hard way: a backup drill reported
# `messages=0` minutes after measuring 16 rows, and the only thing run in between was the
# test suite.
#
# The blast radius is the real point. The DSN is a hardcoded literal, so it depends entirely
# on port 1102 belonging to a disposable container. Anyone port-forwarding a staging or
# production Postgres to 1102 — a completely routine thing to do — turns `pytest` into an
# outage.
DB_NAME = "medbot_test"
ADMIN_DSN = "postgresql+asyncpg://medbot:medbot@localhost:1102/postgres"
DSN = f"postgresql+asyncpg://medbot:medbot@localhost:1102/{DB_NAME}"


def _assert_disposable(dsn: str) -> None:
    """Refuse to run destructive DDL against anything not named as a test database.

    Belt and braces on top of the dedicated name: a guard that only lives in a constant is
    one careless edit away from being gone, and the failure mode here is silent data loss.
    """
    name = dsn.rsplit("/", 1)[-1].split("?")[0]
    if not name.endswith("_test"):
        raise RuntimeError(
            f"refusing to run destructive schema tests against database {name!r}: "
            "the fixture drops every table, so the target must be named '*_test'"
        )


async def _reachable(dsn: str) -> bool:
    try:
        engine = build_engine(dsn, pool_size=1, max_overflow=0)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        return True
    except Exception:
        return False


async def _ensure_test_database() -> bool:
    """Create the disposable database if it is missing. CREATE DATABASE cannot run inside a
    transaction, hence AUTOCOMMIT."""
    if not await _reachable(ADMIN_DSN):
        return False
    admin = build_engine(ADMIN_DSN, pool_size=1, max_overflow=0)
    try:
        async with admin.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": DB_NAME}
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{DB_NAME}"'))
    finally:
        await admin.dispose()
    return True


@pytest.fixture
async def engine() -> AsyncEngine:  # type: ignore[misc]
    _assert_disposable(DSN)
    if not await _ensure_test_database() or not await _reachable(DSN):
        pytest.skip("Postgres unreachable; start it with `docker compose up -d postgres`")
    eng = build_engine(DSN, pool_size=2, max_overflow=2)
    async with eng.begin() as conn:
        for stmt in DROP_ALL.strip().split(";"):
            if stmt.strip():
                await conn.execute(text(stmt))
        for ddl in INITIAL_DDL:
            await conn.execute(text(ddl))
        await ensure_future_partitions(conn, days_ahead=1)
    yield eng
    await eng.dispose()


def test_fixture_refuses_a_non_disposable_database() -> None:
    """The guard itself must be tested — it is the only thing standing between `pytest` and
    a dropped database if someone edits the DSN back."""
    with pytest.raises(RuntimeError, match="_test"):
        _assert_disposable("postgresql+asyncpg://medbot:medbot@localhost:1102/medbot")
    with pytest.raises(RuntimeError, match="_test"):
        _assert_disposable("postgresql+asyncpg://u:p@prod-db.internal:5432/medbot_prod")
    _assert_disposable("postgresql+asyncpg://u:p@localhost:1102/medbot_test")  # allowed


@pytest.mark.asyncio
async def test_messages_table_is_actually_partitioned(engine: AsyncEngine) -> None:
    """The whole retention design rests on this. A silently non-partitioned table would
    behave identically in every other test while making DROP PARTITION impossible."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT relkind FROM pg_class WHERE relname = 'messages'")
        )
        # Postgres `"char"` comes back as bytes via asyncpg, str via other drivers.
        relkind = result.scalar_one()
        relkind = relkind.decode() if isinstance(relkind, bytes) else relkind
        assert relkind == "p", "messages must be a PARTITIONED table (relkind 'p'), not 'r'"


@pytest.mark.asyncio
async def test_ensure_future_partitions_is_idempotent(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        first = await ensure_future_partitions(conn, days_ahead=3)
        second = await ensure_future_partitions(conn, days_ahead=3)
        assert first == second
        existing = await list_partitions(conn)
    today = datetime.now(UTC).date()
    assert partition_name(today) in existing
    assert partition_name(today + timedelta(days=3)) in existing


@pytest.mark.asyncio
async def test_insert_fails_without_a_partition(engine: AsyncEngine) -> None:
    """Proves WHY partitions must be created ahead of time: a row with no matching
    partition is REJECTED. This is the 00:00:00 outage that ensure_future_partitions
    exists to prevent."""
    far_future = datetime.now(UTC) + timedelta(days=365)
    async with engine.begin() as conn:
        with pytest.raises(Exception, match="no partition of relation"):
            await conn.execute(
                text(
                    "INSERT INTO messages (id, created_at, session_id, role, content) "
                    "VALUES (:id, :ts, :sid, 'user', 'x')"
                ),
                {"id": str(uuid.uuid4()), "ts": far_future, "sid": str(uuid.uuid4())},
            )


@pytest.mark.asyncio
async def test_history_roundtrip_and_ordering(engine: AsyncEngine) -> None:
    factory = build_session_factory(engine)
    sid = uuid.uuid4()
    async with session_scope(factory) as s:
        await SessionRepository(s).touch(sid, client_hash="abc")
        repo = MessageRepository(s)
        await repo.add(session_id=sid, role="user", content="What is cirrhosis?")
        await repo.add(
            session_id=sid, role="assistant", content="Scarring of the liver [1].",
            kind="grounded", model_id="llama-3.1-8b",
        )
    async with session_scope(factory) as s:
        history = await MessageRepository(s).history(sid)
    assert [m.role for m in history] == ["user", "assistant"]  # oldest-first for prompting
    assert "cirrhosis" in history[0].content


@pytest.mark.asyncio
async def test_deletion_actually_deletes(engine: AsyncEngine) -> None:
    """GDPR right-to-erasure (D18). Asserts against the DATABASE, not an API response —
    a delete endpoint that reports success without removing rows passes review and fails
    an audit."""
    factory = build_session_factory(engine)
    sid = uuid.uuid4()
    async with session_scope(factory) as s:
        await SessionRepository(s).touch(sid)
        repo = MessageRepository(s)
        for i in range(5):
            await repo.add(session_id=sid, role="user", content=f"sensitive health query {i}")

    async with session_scope(factory) as s:
        assert await MessageRepository(s).count(sid) == 5

    async with session_scope(factory) as s:
        removed = await MessageRepository(s).delete_session_messages(sid)
    assert removed == 5, "delete must report how many rows it actually removed"

    # Independent verification straight from the database.
    async with engine.connect() as conn:
        remaining = await conn.execute(
            text("SELECT count(*) FROM messages WHERE session_id = :sid"), {"sid": str(sid)}
        )
        assert remaining.scalar_one() == 0
        leaked = await conn.execute(
            text("SELECT count(*) FROM messages WHERE content LIKE '%sensitive health query%'")
        )
        assert leaked.scalar_one() == 0, "no trace of the deleted content may remain"


@pytest.mark.asyncio
async def test_retention_drops_only_expired_partitions(engine: AsyncEngine) -> None:
    """Retention as DROP PARTITION — instant, lock-light, and it must not touch live days."""
    today = datetime.now(UTC).date()
    old_day = today - timedelta(days=45)
    old = partition_name(old_day)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {old} PARTITION OF messages "
                f"FOR VALUES FROM ('{old_day}') TO ('{old_day + timedelta(days=1)}')"
            )
        )
        assert old in await list_partitions(conn)

        dropped = await drop_expired_partitions(conn, retention_days=30)
        remaining = await list_partitions(conn)

    assert old in dropped
    assert old not in remaining
    assert partition_name(today) in remaining, "today's partition must survive"


@pytest.mark.asyncio
async def test_session_touch_is_upsert_not_insert(engine: AsyncEngine) -> None:
    """Two concurrent requests from one browser must not race into a PK violation."""
    factory = build_session_factory(engine)
    sid = uuid.uuid4()
    async with session_scope(factory) as s:
        repo = SessionRepository(s)
        first = await repo.touch(sid)
        created = first.created_at
    async with session_scope(factory) as s:
        again = await SessionRepository(s).touch(sid)
    assert again.id == sid
    assert again.created_at == created  # created_at is stable across touches


def test_partition_name_format() -> None:
    assert partition_name(date(2026, 8, 16)) == "messages_2026_08_16"
