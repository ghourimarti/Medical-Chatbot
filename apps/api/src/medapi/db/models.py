"""Database schema.

`messages` is RANGE-partitioned by day. At 4.5M message-pairs/day, a 30-day retention
policy written as `DELETE FROM messages WHERE created_at < now() - interval '30 days'`
deletes ~135M rows per run: long locks, bloat, heavy autovacuum. Dropping a day's partition
is near-instant, lock-light, and gives the disk back immediately, which turns retention
into a cron one-liner.

Note the Postgres constraint that follows from this: a partitioned table's primary key has
to contain the partition key, so `messages` is keyed on (id, created_at) rather than id
alone. Postgres rejects the table otherwise.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class ChatSession(Base):
    """An anonymous session. No account, no PII beyond a hashed client fingerprint;
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
    # Hashed, never raw: an IP is personal data.
    client_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (Index("ix_sessions_last_seen", "last_seen_at"),)


class Message(Base):
    """One chat turn. Partitioned by day, see the module docstring.

    `content` holds health questions and answers, which are sensitive by nature. It's here
    because the feature needs it, never goes to application logs, and is bounded by the
    30-day partition retention.
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
    # Nullable and un-keyed: rows written before conversations existed have none, and a FK
    # would bring back the cascade that DROP PARTITION can't tolerate. session_id stays
    # alongside it, since the two answer different questions ("this visitor's transcript"
    # vs "this thread").
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __table_args__ = (
        Index("ix_messages_session_created", "session_id", "created_at"),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        # Partition key has to be part of the PK on a partitioned table.
        {"postgresql_partition_by": "RANGE (created_at)"},
    )

    # No foreign key to sessions on purpose: ON DELETE CASCADE across partitions would
    # defeat the DROP-PARTITION retention strategy. Referential integrity for history is
    # enforced in the repository layer instead.


class User(Base):
    """A signed-in identity.

    The auth provider's subject and nothing else: no email, no name, no avatar. Clerk
    already holds the profile, and copying it here would buy a PII store to defend, a
    deletion obligation, and a breach surface, in exchange for fields this product never
    reads.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # The `sub` claim from the identity provider. Unique, because two rows for one human
    # would silently split their history in half.
    auth_subject: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Conversation(Base):
    """A named thread. Owned by a user when signed in, by a session when anonymous.

    Both owner columns exist at once on purpose. An anonymous conversation records the
    session that created it, and when that visitor signs in their conversations are claimed
    by setting user_id. Without that seam, signing in orphans everything asked beforehand,
    and the conversation someone just had is usually why they signed up.

    The CHECK makes an ownerless conversation impossible rather than just unlikely.
    """

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # CASCADE is safe here because conversations isn't partitioned, unlike messages where
    # a cascade would defeat the retention design.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # server_default as well as default, so rows inserted by the raw DDL path or a future
    # migration get FALSE from the database and not only from Python.
    pinned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "user_id IS NOT NULL OR session_id IS NOT NULL",
            name="conversations_have_an_owner",
        ),
        Index("ix_conversations_user_updated", "user_id", "updated_at"),
        Index("ix_conversations_session_updated", "session_id", "updated_at"),
    )
