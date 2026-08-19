"""Database schema (D1).

THE DESIGN DECISION: `messages` is RANGE-partitioned by day.

At the Phase-1 target of 4.5M message-pairs/day, a 30-day retention policy expressed as
`DELETE FROM messages WHERE created_at < now() - interval '30 days'` would delete ~135M
rows per run: long locks, table bloat, and heavy autovacuum pressure. Dropping a whole
day's partition is near-instant, lock-light, and returns disk immediately.

That turns GDPR retention from an operational burden into a cron one-liner — which is the
entire reason D1 chose Postgres partitioning over a naive schema.

⚠ POSTGRES CONSTRAINT: a partitioned table's PRIMARY KEY must contain the partition key.
So `messages` is keyed on (id, created_at), not id alone. This is not stylistic — Postgres
rejects the table otherwise.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class ChatSession(Base):
    """An anonymous session (D9). No account, no PII beyond a hashed client fingerprint —
    the id exists so quotas can be enforced and a delete request can be honored."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Hashed, never raw: an IP is personal data under GDPR (D18).
    client_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (Index("ix_sessions_last_seen", "last_seen_at"),)


class Message(Base):
    """One chat turn. Partitioned by day — see module docstring.

    `content` holds health questions and answers, which are sensitive by nature. It lives
    here because the feature requires it, is never written to application logs (D18), and
    is bounded by the 30-day partition retention.
    """

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, default=utcnow
    )
    session_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Assistant turns only: grounded | no_answer | refused | degraded (medcore.AnswerKind).
    # Persisting it makes "how often do we abstain?" a SQL query rather than a log grep.
    kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        Index("ix_messages_session_created", "session_id", "created_at"),
        # Partition key MUST be part of the PK on a partitioned table.
        {"postgresql_partition_by": "RANGE (created_at)"},
    )

    # NOTE: deliberately NO foreign key to sessions. ON DELETE CASCADE across partitions
    # would defeat the DROP-PARTITION retention strategy (the whole point of D1's design).
    # Referential integrity for history is enforced in the repository layer instead.
