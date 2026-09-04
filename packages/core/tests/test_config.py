import pytest
from pydantic import SecretStr, ValidationError

from medcore.config import EMBEDDING_DIM, Settings


def _settings(**over: object) -> Settings:
    """Hermetic: _env_file=None ignores any real .env so tests don't depend on the machine."""
    base: dict[str, object] = {"groq_api_key": "gsk_test_key"}
    base.update(over)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


def test_missing_required_key_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    """a missing GROQ_API_KEY must raise at construction, not boot a broken app."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_embedding_dim_is_frozen_at_1024() -> None:
    """DECISION GATE B: the dimension baked into the Qdrant collection."""
    assert EMBEDDING_DIM == 1024
    assert _settings().embedding_dim == 1024
    with pytest.raises(ValidationError):
        _settings(embedding_dim=384)  # any other dim must be rejected


def test_cache_namespace_composes_all_versions() -> None:
    """DECISION GATE C: version-key composition. Bumping any version changes the key."""
    s = _settings(prompt_version="v2", corpus_version="v3", index_version="v4")
    ns = s.cache_namespace
    assert "pv2" in ns and "cv3" in ns and "iv4" in ns
    assert _settings(prompt_version="v1").cache_namespace != s.cache_namespace


def test_secret_is_not_exposed_in_repr() -> None:
    s = _settings(groq_api_key="gsk_super_secret")
    assert "gsk_super_secret" not in repr(s)
    assert isinstance(s.groq_api_key, SecretStr)
    assert s.groq_api_key.get_secret_value() == "gsk_super_secret"


def test_dev_session_secret_is_refused_outside_local() -> None:
    """A default secret that works everywhere is a default secret that reaches production.
    Local stays frictionless; every other environment must supply a real value."""
    assert _settings(environment="local").session_secret.get_secret_value()  # local is fine
    for env in ("dev", "staging", "prod"):
        with pytest.raises(ValidationError, match="SESSION_SECRET must be set"):
            _settings(environment=env, secure_cookies=True)


def test_insecure_cookies_are_refused_outside_local() -> None:
    with pytest.raises(ValidationError, match="SECURE_COOKIES must be true"):
        _settings(environment="prod", session_secret="a-real-secret", secure_cookies=False)


def test_real_secret_and_secure_cookies_pass_in_prod() -> None:
    s = _settings(
        environment="prod",
        session_secret="a-real-secret",
        secure_cookies=True,
        redis_url="redis://prod-cache:6379/0",
        database_url="postgresql+asyncpg://u:p@prod-db:5432/medbot",
    )
    assert s.is_production


def test_missing_redis_is_rejected_outside_local() -> None:
    """An empty REDIS_URL is a valid local convenience but a silent production
    hazard: caching turns off and quotas fall back to PER-REPLICA in-process counters, so
    the effective limit becomes N x the configured one. Failing at startup beats
    discovering it from a bill or an abuse incident."""
    with pytest.raises(ValidationError, match="REDIS_URL"):
        _settings(
            environment="prod",
            session_secret="a-real-secret",
            secure_cookies=True,
            redis_url="",
            database_url="postgresql+asyncpg://u:p@prod-db:5432/medbot",
        )


def test_local_still_runs_without_redis() -> None:
    """The guard must not make local development require infrastructure."""
    assert _settings(environment="local", redis_url="", database_url="").redis_url == ""


def test_missing_database_is_rejected_outside_local() -> None:
    """Same silent-degradation shape as REDIS_URL: an empty DATABASE_URL disables history
    and the service still answers, so nothing looks wrong. But Postgres is the only system
    of record, so there is no audit trail and no deletion path without it. Found when a
    chaos drill stopped a database the app was not actually using."""
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        _settings(
            environment="prod",
            session_secret="a-real-secret",
            secure_cookies=True,
            redis_url="redis://prod-cache:6379/0",
            database_url="",
        )


def test_settings_are_frozen() -> None:
    s = _settings()
    with pytest.raises(ValidationError):
        s.retrieval_top_k = 99  # type: ignore[misc]


def test_cache_namespace_includes_the_collection() -> None:
    """Found by accident: pointing the service at a different, empty collection still
    returned fully cited answers, because the cache key never mentioned which index had
    produced them. Version-key composition only worked if an operator remembered to bump
    INDEX_VERSION alongside the collection — a convention whose failure mode is silent and
    wrong. Now the invalidation is automatic."""
    a = _settings(qdrant_collection="gale_v1")
    b = _settings(qdrant_collection="gale_v2")
    assert a.cache_namespace != b.cache_namespace
    assert "gale_v1" in a.cache_namespace

def test_retired_serving_vars_are_rejected_not_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """`extra="ignore"` makes a renamed setting fail silently: SERVING_PRIMARY=local
    reads like it selects the GPU venue and does nothing, so the symptom ("my vLLM box is
    idle") appears far from the cause. Renamed vars must be an error, not a no-op."""
    for retired in ("SERVING_PRIMARY", "SERVING_FALLBACK_CHAIN"):
        monkeypatch.setenv(retired, "local")
        with pytest.raises(ValidationError, match="retired serving env var"):
            _settings()
        monkeypatch.delenv(retired)


def test_serving_chain_is_the_supported_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SERVING_PRIMARY", raising=False)
    monkeypatch.delenv("SERVING_FALLBACK_CHAIN", raising=False)
    assert _settings(serving_chain="local,groq").serving_chain == "local,groq"
