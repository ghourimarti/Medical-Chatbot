"""Data access. The ONLY module that emits SQL for application data (D1).

Keeping SQL behind repositories is what makes the D1 "Reversibility: Hard" honest — a move
to Aurora or a history split touches these methods and nothing else.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from medapi.db.models import ChatSession, Message, utcnow
from medcore.schema import Message as ChatMessage


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def touch(self, session_id: uuid.UUID, *, client_hash: str | None = None) -> ChatSession:
        """Create-or-update. Upsert rather than select-then-insert: two concurrent requests
        from one browser would otherwise race and violate the PK."""
        stmt = (
            insert(ChatSession)
            .values(id=session_id, client_hash=client_hash)
            .on_conflict_do_update(index_elements=["id"], set_={"last_seen_at": utcnow()})
            .returning(ChatSession)
        )
        return (await self._s.execute(stmt)).scalar_one()

    async def get(self, session_id: uuid.UUID) -> ChatSession | None:
        return await self._s.get(ChatSession, session_id)


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(
        self,
        *,
        session_id: uuid.UUID,
        role: str,
        content: str,
        kind: str | None = None,
        model_id: str | None = None,
    ) -> Message:
        msg = Message(
            session_id=session_id, role=role, content=content, kind=kind, model_id=model_id
        )
        self._s.add(msg)
        await self._s.flush()
        return msg

    async def history(self, session_id: uuid.UUID, *, limit: int = 20) -> list[ChatMessage]:
        """Most recent `limit` turns, oldest-first for prompt construction."""
        stmt = (
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        rows: Sequence[Message] = (await self._s.execute(stmt)).scalars().all()
        return [
            ChatMessage(role="user" if r.role == "user" else "assistant", content=r.content)
            for r in reversed(rows)
        ]

    async def delete_session_messages(self, session_id: uuid.UUID) -> int:
        """GDPR right-to-erasure (D18). Returns rows actually removed.

        Returning the count is deliberate: a delete endpoint that reports success without
        proving anything was removed is exactly the kind of compliance control that passes
        review and fails an audit.
        """
        result = await self._s.execute(delete(Message).where(Message.session_id == session_id))
        # rowcount exists on CursorResult at runtime; the generic Result stub lacks it.
        return int(getattr(result, "rowcount", 0) or 0)

    async def count(self, session_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(Message).where(Message.session_id == session_id)
        return int((await self._s.execute(stmt)).scalar_one())
