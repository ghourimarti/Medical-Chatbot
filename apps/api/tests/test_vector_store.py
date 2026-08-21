"""Vector-store adapter contracts (P6.3.5).

Read path and ingestion path have DIFFERENT rights over the collection: the API
may only verify, the worker may create. These tests pin that boundary.
"""

import pytest

# --- P6.3.5: the read path must verify, never create -------------------------------

class _FakeQdrant:
    """Minimal stand-in: records whether create_collection was ever called."""

    def __init__(self, *, exists: bool, points: int = 10, dim: int = 1024) -> None:
        self._exists, self._points, self._dim = exists, points, dim
        self.created = False

    async def collection_exists(self, name: str) -> bool:
        return self._exists

    async def get_collection(self, name: str):
        from types import SimpleNamespace

        return SimpleNamespace(
            points_count=self._points,
            config=SimpleNamespace(
                params=SimpleNamespace(vectors={"dense": SimpleNamespace(size=self._dim)})
            ),
        )

    async def create_collection(self, **kwargs) -> None:
        self.created = True
        self._exists = True


def _store(fake: _FakeQdrant):
    from medapi.adapters.vector_store import QdrantVectorStore

    s = QdrantVectorStore.__new__(QdrantVectorStore)
    s._client = fake            # type: ignore[attr-defined]
    s._collection = "gale_live"  # type: ignore[attr-defined]
    s._dimension = 1024          # type: ignore[attr-defined]
    return s


async def test_verify_refuses_to_create_a_missing_collection() -> None:
    """The API must never create `gale_live`: that name belongs to the D11 alias, and
    Qdrant forbids an alias sharing a name with a collection. Auto-creating it on a fresh
    cluster permanently blocks the zero-downtime swap."""
    fake = _FakeQdrant(exists=False)
    with pytest.raises(ValueError, match="does not create it"):
        await _store(fake).verify_collection()
    assert fake.created is False


async def test_verify_accepts_an_existing_collection() -> None:
    fake = _FakeQdrant(exists=True)
    await _store(fake).verify_collection()
    assert fake.created is False


async def test_ingestion_path_may_still_create() -> None:
    """Creation is legitimate for the worker — it knows what to put in the collection."""
    fake = _FakeQdrant(exists=False)
    await _store(fake).ensure_collection()
    assert fake.created is True


async def test_health_is_false_for_an_empty_index() -> None:
    """An empty index cannot answer anything, so readiness must not claim it can —
    the query path already treats zero candidates as a fault (P5.3.6)."""
    assert await _store(_FakeQdrant(exists=True, points=0)).health() is False
    assert await _store(_FakeQdrant(exists=True, points=7080)).health() is True
    assert await _store(_FakeQdrant(exists=False)).health() is False


# --- P6.5.4: readiness must mean "can answer a query" ------------------------------

async def test_readiness_fails_when_embedder_is_down() -> None:
    """With ml-service unreachable the API returned READY while every query 503'd.
    Embedding is the first step of retrieval, so an unreachable embedder is exactly as
    disqualifying as an unreachable index."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from medapi.routes import router

    class _Store:
        async def health(self) -> bool:
            return True

    class _Embedder:
        def __init__(self, ok: bool) -> None:
            self._ok = ok

        async def health(self) -> bool:
            return self._ok

    def _app(embedder_ok: bool) -> TestClient:
        from types import SimpleNamespace

        app = FastAPI()
        app.include_router(router)
        app.state.services = SimpleNamespace(store=_Store(), embedder=_Embedder(embedder_ok))
        return TestClient(app)

    r = _app(embedder_ok=False).get("/readyz")
    assert r.status_code == 503
    assert r.json()["checks"]["embedder"] is False
    assert r.json()["checks"]["vector_store"] is True  # the index was fine; the embedder was not

    r = _app(embedder_ok=True).get("/readyz")
    assert r.status_code == 200


# --- S10.2c: the PUBLIC status surface -------------------------------------------

async def test_public_status_reports_ok_degraded_and_unavailable() -> None:
    """The status page drives a user-facing banner, so its three states must be distinct
    and must never leak operator facts (spend, circuits, serving chain) — those live
    behind the key-gated /admin/status."""
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from medapi.routes import router

    class _Store:
        def __init__(self, ok: bool) -> None:
            self._ok = ok

        async def health(self) -> bool:
            return self._ok

    class _Embedder:
        async def health(self) -> bool:
            return True

    class _KillSwitch:
        def __init__(self, enabled: bool) -> None:
            self._enabled = enabled

        async def llm_enabled(self) -> bool:
            return self._enabled

    def _client(*, store_ok: bool, generation: bool) -> TestClient:
        app = FastAPI()
        app.include_router(router)
        app.state.services = SimpleNamespace(
            store=_Store(store_ok),
            embedder=_Embedder(),
            kill_switch=_KillSwitch(generation),
            settings=SimpleNamespace(corpus_version="v1", index_version="v1"),
        )
        return TestClient(app)

    body = _client(store_ok=True, generation=True).get("/api/v1/status").json()
    assert body["status"] == "ok"
    assert body["corpus"] == {"version": "v1", "index_version": "v1"}

    # Kill switch / spend breaker tripped: answers still serve from cache, so this is
    # DEGRADED, not unavailable — the banner must say something different from an outage.
    assert _client(store_ok=True, generation=False).get("/api/v1/status").json()["status"] == (
        "degraded"
    )
    assert _client(store_ok=False, generation=True).get("/api/v1/status").json()["status"] == (
        "unavailable"
    )

    # No operator facts leak to the public surface.
    leaked = set(body) & {"spend_today_usd", "circuits", "serving_chain", "cache_namespace"}
    assert not leaked, f"public status leaked operator fields: {leaked}"
