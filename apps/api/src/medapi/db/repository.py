"""Data access. The ONLY module that emits SQL for application data (D1).

Keeping SQL behind repositories is what makes the D1 "Reversibility: Hard" honest — a move
to Aurora or a history split touches these methods and nothing else.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from medapi.db.models import ChatSession, Conversation, Message, User, utcnow
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
        conversation_id: uuid.UUID | None = None,
    ) -> Message:
        # conversation_id is OPTIONAL, not required. The anonymous single-thread path
        # predates conversations and must keep working unchanged (D24 sequencing: anonymous
        # chat never gets a signup wall), so a message without a thread is legal.
        msg = Message(
            session_id=session_id,
            role=role,
            content=content,
            kind=kind,
            model_id=model_id,
            conversation_id=conversation_id,
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

    async def history_for_conversation(
        self, conversation_id: uuid.UUID, *, limit: int = 50
    ) -> list[ChatMessage]:
        """One thread, oldest-first for prompt construction.

        Ownership is NOT checked here — the caller must have already resolved the
        conversation through ConversationRepository.owned_by. Splitting it that way means
        there is exactly one place that decides who may read a thread, rather than an
        authorisation check duplicated into every query that touches messages.
        """
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
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


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def upsert(self, auth_subject: str) -> User:
        """Create-or-touch by the provider's subject.

        Upsert rather than select-then-insert for the same reason SessionRepository.touch
        does it: a browser opening two tabs at once produces two concurrent first-requests,
        and select-then-insert loses that race and violates the unique constraint. Losing it
        would ALSO split one person's history across two user rows, which is silent and
        permanent.
        """
        stmt = (
            insert(User)
            .values(auth_subject=auth_subject)
            .on_conflict_do_update(
                index_elements=["auth_subject"], set_={"last_seen_at": utcnow()}
            )
            .returning(User)
        )
        return (await self._s.execute(stmt)).scalar_one()

    async def delete(self, user_id: uuid.UUID) -> int:
        """Account deletion. Conversations cascade; MESSAGES DO NOT — they have no foreign
        key, deliberately (a cascade across partitions would defeat DROP PARTITION). The
        caller must delete messages first; ConversationRepository.delete_for_user does."""
        result = await self._s.execute(delete(User).where(User.id == user_id))
        return int(getattr(result, "rowcount", 0) or 0)


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(
        self,
        *,
        user_id: uuid.UUID | None,
        session_id: uuid.UUID | None,
        title: str | None = None,
    ) -> Conversation:
        if user_id is None and session_id is None:
            # The database CHECK would catch this, but failing here names the caller rather
            # than surfacing an IntegrityError three frames away.
            raise ValueError("a conversation needs an owner: user_id or session_id")
        convo = Conversation(user_id=user_id, session_id=session_id, title=title)
        self._s.add(convo)
        await self._s.flush()
        return convo

    async def list_for_owner(
        self, *, user_id: uuid.UUID | None, session_id: uuid.UUID | None, limit: int = 50
    ) -> Sequence[Conversation]:
        """Most recently updated first.

        A signed-in user sees ONLY their own; an anonymous visitor sees only their session's.
        The two are never unioned: doing so would let anyone holding a session cookie read
        conversations that a signed-in account had already claimed.
        """
        stmt = select(Conversation).order_by(Conversation.updated_at.desc()).limit(limit)
        if user_id is not None:
            stmt = stmt.where(Conversation.user_id == user_id)
        elif session_id is not None:
            stmt = stmt.where(
                Conversation.session_id == session_id, Conversation.user_id.is_(None)
            )
        else:
            return []
        return (await self._s.execute(stmt)).scalars().all()

    async def owned_by(
        self,
        conversation_id: uuid.UUID,
        *,
        user_id: uuid.UUID | None,
        session_id: uuid.UUID | None,
    ) -> Conversation | None:
        """Fetch ONLY if the caller owns it.

        Every read and write of a conversation goes through this. Checking ownership in the
        query rather than after fetching means a missing row and a forbidden row are
        indistinguishable to the caller, which is also what stops the endpoint leaking
        whether someone else's conversation id exists.
        """
        # The ownership predicate is IN the query, not applied to a fetched row.
        #
        # The first version fetched by id and compared attributes in Python, which the
        # docstring above already claimed it did not — and the difference was not cosmetic:
        # after a claim expired the identity-map copy, reading convo.user_id triggered a
        # lazy refresh and raised MissingGreenlet. Filtering in SQL cannot go stale, cannot
        # lazy-load, and is the only version that actually matches the security claim.
        stmt = select(Conversation).where(Conversation.id == conversation_id)
        if user_id is not None:
            stmt = stmt.where(Conversation.user_id == user_id)
        elif session_id is not None:
            stmt = stmt.where(
                Conversation.user_id.is_(None), Conversation.session_id == session_id
            )
        else:
            return None
        return (await self._s.execute(stmt)).scalar_one_or_none()

    async def rename(self, convo: Conversation, title: str) -> Conversation:
        convo.title = title[:200]
        convo.updated_at = utcnow()
        await self._s.flush()
        return convo

    async def touch(self, conversation_id: uuid.UUID) -> None:
        """Bump updated_at so the sidebar orders by real activity, not creation time."""
        await self._s.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(updated_at=utcnow())
        )

    async def claim_for_user(self, *, session_id: uuid.UUID, user_id: uuid.UUID) -> int:
        """THE SIGN-IN SEAM (D25). Transfer this session's anonymous conversations to a user.

        `user_id IS NULL` in the predicate is load-bearing: without it, signing in would
        re-assign conversations that had ALREADY been claimed by a different account which
        happened to share this browser — a real scenario on a shared device, and a
        cross-account data leak rather than a merge.

        The session id comes from the request cookie and is never a parameter, so a caller
        cannot claim a session they do not hold.
        """
        result = await self._s.execute(
            update(Conversation)
            .where(Conversation.session_id == session_id, Conversation.user_id.is_(None))
            .values(user_id=user_id, updated_at=utcnow())
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def delete(self, convo: Conversation) -> int:
        """Delete a conversation AND its messages, returning the message count removed.

        Messages are deleted explicitly because they carry no foreign key. Reporting the
        count keeps the same audit property as the session delete: a control that claims
        success without evidence passes review and fails an audit.
        """
        result = await self._s.execute(
            delete(Message).where(Message.conversation_id == convo.id)
        )
        removed = int(getattr(result, "rowcount", 0) or 0)
        await self._s.delete(convo)
        await self._s.flush()
        return removed

    async def delete_for_user(self, user_id: uuid.UUID) -> int:
        """Account erasure: every message in every conversation the user owns.

        Runs BEFORE the user row is deleted. Once the cascade removes the conversations,
        their messages become unreachable orphans that only the 30-day partition drop would
        eventually clear — which is far too slow to call a deletion.
        """
        ids = (
            (await self._s.execute(select(Conversation.id).where(Conversation.user_id == user_id)))
            .scalars()
            .all()
        )
        if not ids:
            return 0
        result = await self._s.execute(
            delete(Message).where(Message.conversation_id.in_(ids))
        )
        return int(getattr(result, "rowcount", 0) or 0)
