"""Conversation service and endpoints (S20b, D24/D25).

Mirrors HistoryService: the repository is wrapped so callers never touch a session, and a
missing database means the feature is OFF rather than an error — accounts are additive, and
nothing here may take the anonymous product down (D21).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from medapi.auth import bearer_token
from medapi.db.engine import session_scope
from medapi.db.repository import ConversationRepository, MessageRepository, UserRepository
from medapi.observability import get_logger
from medcore.errors import MedbotError

logger = get_logger("medapi.conversations")
router = APIRouter()


class ConversationNotFound(MedbotError):
    """404 for a conversation that does not exist OR that the caller does not own.

    ONE error for both cases, deliberately. Distinguishing them turns the endpoint into an
    oracle: an attacker enumerating ids learns which ones are real by whether they get 403
    or 404. The owner sees no difference, and a prober learns nothing.
    """

    status, title, slug = 404, "Not Found", "conversation-not-found"
    public_detail = "That conversation does not exist."


class AccountsDisabled(MedbotError):
    status, title, slug = 503, "Accounts Unavailable", "accounts-disabled"
    public_detail = "Saved conversations are not available on this deployment."


@dataclass(slots=True)
class Caller:
    """Who is asking. `session_id` always exists; `user_id` only when signed in."""

    session_id: uuid.UUID
    user_id: uuid.UUID | None

    @property
    def signed_in(self) -> bool:
        return self.user_id is not None


class ConversationService:
    def __init__(self, factory: Any, verifier: Any) -> None:
        self._factory = factory
        self._verifier = verifier

    @property
    def enabled(self) -> bool:
        return self._factory is not None

    async def resolve_user(self, token: str | None) -> uuid.UUID | None:
        """Verify a bearer token and map it to a local user id.

        No token means anonymous. An INVALID token raises (401) rather than falling back to
        anonymous: a forged token must not look like a signed-out visitor, and an expired
        one must tell the user rather than silently emptying their sidebar.
        """
        if token is None:
            return None
        subject = await self._verifier.subject(token)
        if self._factory is None:
            raise AccountsDisabled("no database configured")
        async with session_scope(self._factory) as s:
            user = await UserRepository(s).upsert(subject)
            return user.id

    async def list_owned(self, caller: Caller) -> list[dict[str, Any]]:
        if self._factory is None:
            return []
        async with session_scope(self._factory) as s:
            rows = await ConversationRepository(s).list_for_owner(
                user_id=caller.user_id, session_id=caller.session_id
            )
            return [_serialize(c) for c in rows]

    async def create(self, caller: Caller, title: str | None) -> dict[str, Any]:
        if self._factory is None:
            raise AccountsDisabled("no database configured")
        async with session_scope(self._factory) as s:
            convo = await ConversationRepository(s).create(
                user_id=caller.user_id,
                # The session is recorded even when signed in: it is what a later
                # `claim` would match on, and it keeps an audit trail of where a
                # conversation was started.
                session_id=caller.session_id,
                title=title,
            )
            await s.flush()
            return _serialize(convo)

    async def messages(self, caller: Caller, conversation_id: uuid.UUID) -> list[dict[str, str]]:
        if self._factory is None:
            raise ConversationNotFound("history disabled")
        async with session_scope(self._factory) as s:
            convo = await ConversationRepository(s).owned_by(
                conversation_id, user_id=caller.user_id, session_id=caller.session_id
            )
            if convo is None:
                raise ConversationNotFound(f"conversation {conversation_id} not owned by caller")
            msgs = await MessageRepository(s).history_for_conversation(conversation_id)
            return [{"role": m.role, "content": m.content} for m in msgs]

    async def rename(
        self, caller: Caller, conversation_id: uuid.UUID, title: str
    ) -> dict[str, Any]:
        if self._factory is None:
            raise ConversationNotFound("history disabled")
        async with session_scope(self._factory) as s:
            repo = ConversationRepository(s)
            convo = await repo.owned_by(
                conversation_id, user_id=caller.user_id, session_id=caller.session_id
            )
            if convo is None:
                raise ConversationNotFound(f"conversation {conversation_id} not owned by caller")
            return _serialize(await repo.rename(convo, title))

    async def delete(self, caller: Caller, conversation_id: uuid.UUID) -> int:
        if self._factory is None:
            raise ConversationNotFound("history disabled")
        async with session_scope(self._factory) as s:
            repo = ConversationRepository(s)
            convo = await repo.owned_by(
                conversation_id, user_id=caller.user_id, session_id=caller.session_id
            )
            if convo is None:
                raise ConversationNotFound(f"conversation {conversation_id} not owned by caller")
            # Returns the message count, same audit property as the session delete: a
            # control that claims success without evidence fails an audit.
            return await repo.delete(convo)

    async def resolve_thread(
        self, caller: Caller, conversation_id: uuid.UUID | None
    ) -> uuid.UUID | None:
        """Authorise a caller-supplied conversation id for WRITING, before any work runs.

        Three outcomes, and the difference between them is the whole point:

        * owned          -> the id, and the turn is appended to that thread
        * not owned      -> ConversationNotFound (404). Never 403, same oracle argument as
                            the read path: a prober must not learn which ids are real.
        * cannot verify  -> None, and the turn is written WITHOUT a thread.

        The third case is the one worth being careful about. If Postgres is unreachable we
        cannot prove ownership, and "cannot prove" must never resolve to "allow" — but it
        must not 500 either, because D21 says a database outage costs history, not the
        ability to answer. Dropping the thread satisfies both: nothing is written into
        anyone's conversation, and the question is still answered.
        """
        if conversation_id is None or self._factory is None:
            return None
        try:
            async with session_scope(self._factory) as s:
                convo = await ConversationRepository(s).owned_by(
                    conversation_id, user_id=caller.user_id, session_id=caller.session_id
                )
        except Exception:
            logger.warning("thread_unverifiable", exc_info=True)
            return None
        if convo is None:
            raise ConversationNotFound(f"conversation {conversation_id} not owned by caller")
        return conversation_id

    async def claim(self, caller: Caller) -> int:
        """Transfer this session's anonymous conversations to the signed-in user (D25)."""
        if self._factory is None or caller.user_id is None:
            return 0
        async with session_scope(self._factory) as s:
            return await ConversationRepository(s).claim_for_user(
                session_id=caller.session_id, user_id=caller.user_id
            )


def _serialize(convo: Any) -> dict[str, Any]:
    return {
        "id": str(convo.id),
        "title": convo.title,
        "created_at": convo.created_at.isoformat(),
        "updated_at": convo.updated_at.isoformat(),
        # Whether it is bound to an account yet. The UI uses this to show that an anonymous
        # thread will be kept if the visitor signs in.
        "claimed": convo.user_id is not None,
    }


# ── HTTP ───────────────────────────────────────────────────────────────────────────────
def _services(request: Request) -> Any:
    return request.app.state.services


async def _caller(request: Request, response: Response) -> Caller:
    svc = _services(request)
    session_id, _ = svc.sessions.resolve(request)
    svc.sessions.attach(response, session_id)
    user_id = await svc.conversations.resolve_user(
        bearer_token(request.headers.get("authorization"))
    )
    return Caller(session_id=session_id, user_id=user_id)


class CreateBody(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class RenameBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)


@router.get("/api/v1/conversations")
async def list_conversations(request: Request, response: Response) -> dict[str, Any]:
    caller = await _caller(request, response)
    svc = _services(request)
    return {
        "enabled": svc.conversations.enabled,
        "signed_in": caller.signed_in,
        "conversations": await svc.conversations.list_owned(caller),
    }


@router.post("/api/v1/conversations", status_code=201)
async def create_conversation(
    body: CreateBody, request: Request, response: Response
) -> dict[str, Any]:
    caller = await _caller(request, response)
    return await _services(request).conversations.create(caller, body.title)


@router.get("/api/v1/conversations/{conversation_id}/messages")
async def conversation_messages(
    conversation_id: uuid.UUID, request: Request, response: Response
) -> dict[str, Any]:
    caller = await _caller(request, response)
    return {
        "conversation_id": str(conversation_id),
        "messages": await _services(request).conversations.messages(caller, conversation_id),
    }


@router.patch("/api/v1/conversations/{conversation_id}")
async def rename_conversation(
    conversation_id: uuid.UUID, body: RenameBody, request: Request, response: Response
) -> dict[str, Any]:
    caller = await _caller(request, response)
    return await _services(request).conversations.rename(caller, conversation_id, body.title)


@router.delete("/api/v1/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: uuid.UUID, request: Request, response: Response
) -> dict[str, Any]:
    caller = await _caller(request, response)
    deleted = await _services(request).conversations.delete(caller, conversation_id)
    logger.info("conversation_deleted", messages=deleted)
    return {"conversation_id": str(conversation_id), "deleted_messages": deleted}


@router.post("/api/v1/auth/claim")
async def claim_conversations(request: Request, response: Response) -> dict[str, Any]:
    """Called by the client immediately after sign-in.

    The session id comes from the cookie and is never a parameter, so a caller cannot claim
    a session they do not hold.
    """
    caller = await _caller(request, response)
    claimed = await _services(request).conversations.claim(caller)
    logger.info("conversations_claimed", claimed=claimed, signed_in=caller.signed_in)
    return {"claimed": claimed, "signed_in": caller.signed_in}
