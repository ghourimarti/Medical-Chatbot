"""S7.7: session identity + fail-soft history (D9, D21, D18).

No database required — HistoryService's degradation path IS the code under test, and it is
the same path production takes when Postgres is down.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import Response
from medapi.history import HistoryService
from medapi.session import COOKIE_NAME, SessionManager

from medcore.schema import AnswerKind


class _FakeRequest:
    def __init__(self, cookies: dict[str, str] | None = None, host: str | None = "1.2.3.4"):
        self.cookies = cookies or {}
        self.client = type("C", (), {"host": host})() if host else None


def _manager(secret: str = "test-secret") -> SessionManager:
    return SessionManager(secret, secure_cookies=False)


# --- session identity ---------------------------------------------------------------


def test_new_visitor_gets_a_fresh_session() -> None:
    sid, is_new = _manager().resolve(_FakeRequest())  # type: ignore[arg-type]
    assert is_new and isinstance(sid, uuid.UUID)


def test_valid_cookie_round_trips() -> None:
    mgr = _manager()
    original = uuid.uuid4()
    token = mgr.sign(original)
    sid, is_new = mgr.resolve(_FakeRequest({COOKIE_NAME: token}))  # type: ignore[arg-type]
    assert sid == original and not is_new


def test_tampered_cookie_yields_a_new_session_not_an_error() -> None:
    """An anonymous chat must never 400 on a bad cookie — forged input degrades to
    'new visitor', which is both safe and invisible to the user."""
    mgr = _manager()
    sid, is_new = mgr.resolve(_FakeRequest({COOKIE_NAME: "not-a-valid-token"}))  # type: ignore[arg-type]
    assert is_new and isinstance(sid, uuid.UUID)


def test_cookie_signed_with_another_secret_is_rejected() -> None:
    """Key rotation invalidates sessions rather than trusting unverified ids."""
    token = _manager("secret-a").sign(uuid.uuid4())
    _, is_new = _manager("secret-b").resolve(_FakeRequest({COOKIE_NAME: token}))  # type: ignore[arg-type]
    assert is_new


def test_cookie_flags_are_hardened() -> None:
    mgr = SessionManager("s", secure_cookies=True)
    resp = Response()
    mgr.attach(resp, uuid.uuid4())
    header = resp.headers["set-cookie"].lower()
    assert "httponly" in header  # unreadable to JS (XSS mitigation, D18)
    assert "samesite=lax" in header
    assert "secure" in header


def test_client_ip_is_hashed_never_stored_raw() -> None:
    """An IP is personal data under GDPR (D18)."""
    h = SessionManager.client_hash(_FakeRequest(host="203.0.113.9"))  # type: ignore[arg-type]
    assert h is not None and len(h) == 64
    assert "203.0.113.9" not in h
    assert h == SessionManager.client_hash(_FakeRequest(host="203.0.113.9"))  # type: ignore[arg-type]
    assert h != SessionManager.client_hash(_FakeRequest(host="203.0.113.10"))  # type: ignore[arg-type]


def test_missing_client_is_tolerated() -> None:
    assert SessionManager.client_hash(_FakeRequest(host=None)) is None  # type: ignore[arg-type]


# --- fail-soft history --------------------------------------------------------------


@pytest.mark.asyncio
async def test_history_disabled_returns_empty_not_error() -> None:
    """No DATABASE_URL: the app must answer, just without memory (D21)."""
    svc = HistoryService(None)
    assert not svc.enabled
    assert await svc.load(uuid.uuid4()) == []


@pytest.mark.asyncio
async def test_record_turn_reports_false_when_disabled() -> None:
    svc = HistoryService(None)
    stored = await svc.record_turn(
        uuid.uuid4(), question="q", answer_text="a",
        kind=AnswerKind.GROUNDED, model_id="m",
    )
    assert stored is False  # honest about not persisting, rather than silently claiming success


@pytest.mark.asyncio
async def test_database_failure_degrades_load_instead_of_raising() -> None:
    """Postgres down => stateless chat, never a 500 (D21)."""

    class ExplodingFactory:
        def __call__(self) -> object:
            raise ConnectionError("postgres is down")

    svc = HistoryService(ExplodingFactory())  # type: ignore[arg-type]
    assert await svc.load(uuid.uuid4()) == []
    assert await svc.record_turn(
        uuid.uuid4(), question="q", answer_text="a",
        kind=AnswerKind.GROUNDED, model_id=None,
    ) is False


@pytest.mark.asyncio
async def test_clear_failure_propagates_rather_than_degrading() -> None:
    """Deliberate asymmetry: a failed DELETE must NOT report success. Losing history is a
    degraded experience; a silently failed erasure is a compliance violation (D18)."""

    class ExplodingFactory:
        def __call__(self) -> object:
            raise ConnectionError("postgres is down")

    with pytest.raises(ConnectionError):
        await HistoryService(ExplodingFactory()).clear(uuid.uuid4())  # type: ignore[arg-type]
