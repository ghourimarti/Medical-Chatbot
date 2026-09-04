"""Pin and conversation search (S22) — the backend half.

These are the two features the sidebar was faking: a pin that lived in localStorage and a
"search" that only matched titles. Both now have a server behind them, and both are writes
or reads scoped to an owner, so the tests that matter are the ownership ones.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from medapi.conversations import Caller, ConversationNotFound, ConversationService, _serialize


def _row(**kw: Any) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "title": "Liver questions",
        "pinned": False,
        "user_id": None,
        "session_id": uuid.uuid4(),
        "created_at": SimpleNamespace(isoformat=lambda: "2026-01-01T00:00:00+00:00"),
        "updated_at": SimpleNamespace(isoformat=lambda: "2026-01-02T00:00:00+00:00"),
    }
    base.update(kw)
    return SimpleNamespace(**base)


# ── serialisation ────────────────────────────────────────────────────────────────────


def test_pinned_is_exposed_to_the_client() -> None:
    assert _serialize(_row(pinned=True))["pinned"] is True
    assert _serialize(_row(pinned=False))["pinned"] is False


def test_serialisation_survives_a_database_without_the_column() -> None:
    """The ALTER runs at boot, but a client may reach an API whose database has not applied
    it yet. Defaulting beats a 500 on every list request."""
    legacy = _row()
    del legacy.pinned
    assert _serialize(legacy)["pinned"] is False


# ── ownership: the boundary that actually matters ────────────────────────────────────


class _DisabledService(ConversationService):
    def __init__(self) -> None:
        super().__init__(factory=None, verifier=None)


@pytest.mark.asyncio
async def test_pinning_requires_a_database() -> None:
    caller = Caller(user_id=None, session_id=uuid.uuid4())
    with pytest.raises(ConversationNotFound):
        await _DisabledService().set_pinned(caller, uuid.uuid4(), True)


@pytest.mark.asyncio
async def test_search_degrades_to_empty_rather_than_raising() -> None:
    """A search box that finds nothing is a usable degraded state. A 500 is not — and
    unlike pin, search is a READ, so there is nothing to protect by failing loudly."""
    caller = Caller(user_id=None, session_id=uuid.uuid4())
    assert await _DisabledService().search(caller, "cirrhosis") == []


@pytest.mark.asyncio
async def test_empty_query_returns_nothing_without_touching_the_database() -> None:
    """An empty box must not list every conversation the caller owns — that is a different
    feature wearing search's clothes, and on a long history it is a lot of health questions
    rendered for a keystroke that was probably a backspace."""
    called = False

    class _Repo:
        async def search_owned(self, *a: Any, **k: Any) -> list[Any]:
            nonlocal called
            called = True
            return []

    svc = ConversationService(factory=None, verifier=None)
    assert await svc.search(Caller(user_id=None, session_id=uuid.uuid4()), "   ") == []
    assert not called


# ── the destructive default I nearly shipped ─────────────────────────────────────────


def test_update_body_allows_either_field_alone() -> None:
    """PATCH must accept {"pinned": true} without a title.

    The first version of the endpoint fell back to rename(..., "") when no title was sent,
    which would have WIPED the title of every conversation pinned from the sidebar. This
    pins the shape that made that possible.
    """
    from medapi.conversations import UpdateBody

    assert UpdateBody(pinned=True).title is None
    assert UpdateBody(title="Renamed").pinned is None
    assert UpdateBody().title is None and UpdateBody().pinned is None
