"""Chat history persistence with graceful degradation (D1, D9, D21).

Every method here is FAIL-SOFT by design. D21 specifies "Postgres down => chat continues
stateless": losing history is a degraded experience, losing the ability to answer is an
outage. Persistence is a side effect of answering, never a precondition for it.

Centralising that policy here — rather than scattering try/except through the routes —
means there is exactly one place where the degradation rule can be read, tested, or
changed. `disabled` (no DATABASE_URL) and `failing` (Postgres down) take the same path,
so local dev without a database exercises the same code that production falls back to.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from medapi.circuit import Breaker
from medapi.db.engine import session_scope
from medapi.db.repository import MessageRepository, SessionRepository
from medapi.logthrottle import ThrottledLogger
from medcore.schema import AnswerKind, Message

logger = logging.getLogger("medapi.history")
_throttled = ThrottledLogger()


class HistoryService:
    """Persistence facade. `factory=None` means history is disabled entirely."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession] | None,
        *,
        max_turns: int = 20,
        failure_threshold: int = 5,
        cooldown_seconds: float = 10.0,
    ) -> None:
        self._factory = factory
        self._max_turns = max_turns
        # Same breaker as Redis and the venue chain (P5.4). Measured with Postgres stopped:
        # request latency went 5.0s -> 8.5s, because history is read once and written once
        # per request and each call paid a full connection timeout before degrading
        # correctly. Degrading twice per request is still two timeouts.
        self._breaker = Breaker(
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown_seconds,
            name="postgres",
        )

    @property
    def enabled(self) -> bool:
        return self._factory is not None

    @property
    def circuit_open(self) -> bool:
        return self._breaker.is_open

    async def load(self, session_id: uuid.UUID) -> list[Message]:
        """Prior turns, oldest-first. Returns [] on any failure — a fresh conversation is
        a far better outcome than a 500."""
        if self._factory is None or self._breaker.is_open:
            return []
        try:
            async with session_scope(self._factory) as s:
                result = await MessageRepository(s).history(session_id, limit=self._max_turns)
        except Exception:
            self._breaker.record_failure()
            _throttled.warning(
                "history-load", "history load failed; continuing statelessly", exc_info=True
            )
            return []
        self._breaker.record_success()
        return result

    async def record_turn(
        self,
        session_id: uuid.UUID,
        *,
        question: str,
        answer_text: str,
        kind: AnswerKind,
        model_id: str | None,
        client_hash: str | None = None,
    ) -> bool:
        """Persist one user/assistant exchange. Returns whether it was stored.

        Both messages are written in ONE transaction: a user turn saved without its
        assistant reply would render as a conversation the system ignored.
        """
        if self._factory is None or self._breaker.is_open:
            return False
        try:
            async with session_scope(self._factory) as s:
                await SessionRepository(s).touch(session_id, client_hash=client_hash)
                repo = MessageRepository(s)
                await repo.add(session_id=session_id, role="user", content=question)
                await repo.add(
                    session_id=session_id,
                    role="assistant",
                    content=answer_text,
                    kind=kind.value,
                    model_id=model_id,
                )
            self._breaker.record_success()
            return True
        except Exception:
            self._breaker.record_failure()
            _throttled.warning(
                "history-write", "history write failed; answer still served", exc_info=True
            )
            return False

    async def clear(self, session_id: uuid.UUID) -> int:
        """GDPR erasure (D18). Returns rows actually deleted.

        Unlike load/record, failure here is NOT swallowed: a delete that silently fails
        while reporting success is a compliance violation, not a degraded experience.

        It also deliberately IGNORES the circuit breaker (P5.4). The breaker exists to stop
        paying timeouts on best-effort work; an erasure request is not best-effort. Skipping
        it because a breaker is open would report success without deleting anything — the
        exact failure this method is written to prevent.
        """
        if self._factory is None:
            return 0
        async with session_scope(self._factory) as s:
            return await MessageRepository(s).delete_session_messages(session_id)
