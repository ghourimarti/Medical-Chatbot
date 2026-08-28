"""Superseded Qdrant collections must be pruned, and the LIVE one must never be.

I3.7: a re-ingest builds `gale_live_vN`, repoints the alias, and left every predecessor
behind forever - five stale copies of a 7,080-chunk corpus at ~29MB each, growing on a
schedule nobody watches. Storage is the visible cost; the real one is that
`GET /collections` stops answering the question the D11 alias exists to answer, which is
"which collection is actually live?".
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from medapi.adapters.vector_store import QdrantVectorStore


class _Client:
    def __init__(self, names: list[str]) -> None:
        self.names = list(names)
        self.deleted: list[str] = []
        self.fail_on: set[str] = set()

    async def get_collections(self) -> Any:
        return SimpleNamespace(collections=[SimpleNamespace(name=n) for n in self.names])

    async def delete_collection(self, name: str) -> None:
        if name in self.fail_on:
            raise RuntimeError("qdrant said no")
        self.deleted.append(name)
        self.names.remove(name)


def _store(names: list[str], live: str | None) -> tuple[QdrantVectorStore, _Client]:
    store = QdrantVectorStore.__new__(QdrantVectorStore)
    client = _Client(names)
    store._client = client  # type: ignore[attr-defined]

    async def resolve(_alias: str) -> str | None:
        return live

    store.resolve_alias = resolve  # type: ignore[method-assign]
    return store, client


ALL = [
    "gale_live_v1787322511",
    "gale_live_v1787322512",
    "gale_live_v1787322513",
    "gale_live_v1787322516",  # live
]


@pytest.mark.asyncio
async def test_keeps_one_previous_version_for_rollback() -> None:
    """Rollback must stay a single alias operation with no re-ingest. That is the whole
    reason the alias indirection exists, so exactly one predecessor survives."""
    store, client = _store(ALL, "gale_live_v1787322516")
    removed = await store.prune_superseded("gale_live", keep=1)

    assert "gale_live_v1787322516" not in client.deleted, "deleted the LIVE collection"
    assert "gale_live_v1787322513" in client.names, "no rollback target left"
    assert sorted(removed) == ["gale_live_v1787322511", "gale_live_v1787322512"]


@pytest.mark.asyncio
async def test_never_deletes_the_live_collection() -> None:
    store, client = _store(ALL, "gale_live_v1787322511")  # oldest is live
    await store.prune_superseded("gale_live", keep=0)
    assert "gale_live_v1787322511" in client.names
    assert client.deleted, "nothing else was pruned"


@pytest.mark.asyncio
async def test_unresolvable_alias_deletes_nothing() -> None:
    """If we cannot tell what is live, deleting is how a re-index becomes an outage."""
    store, client = _store(ALL, None)
    removed = await store.prune_superseded("gale_live", keep=1)
    assert removed == []
    assert client.deleted == []


@pytest.mark.asyncio
async def test_unrelated_collections_are_untouched() -> None:
    """Only versioned siblings of THIS alias are candidates."""
    names = [*ALL, "some_other_index", "gale_live_backup"]
    store, client = _store(names, "gale_live_v1787322516")
    await store.prune_superseded("gale_live", keep=1)
    assert "some_other_index" in client.names
    assert "gale_live_backup" in client.names


@pytest.mark.asyncio
async def test_a_failed_delete_does_not_abort_the_rest() -> None:
    """Housekeeping runs after a successful swap; one stubborn collection must not
    strand the others or fail the ingest that just succeeded."""
    store, client = _store(ALL, "gale_live_v1787322516")
    client.fail_on = {"gale_live_v1787322511"}
    removed = await store.prune_superseded("gale_live", keep=1)
    assert removed == ["gale_live_v1787322512"]
    assert "gale_live_v1787322511" in client.names
