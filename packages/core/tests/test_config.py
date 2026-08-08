import pytest
from pydantic import SecretStr, ValidationError

from medcore.config import EMBEDDING_DIM, Settings


def _settings(**over: object) -> Settings:
    """Hermetic: _env_file=None ignores any real .env so tests don't depend on the machine."""
    base: dict[str, object] = {"groq_api_key": "gsk_test_key"}
    base.update(over)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


def test_missing_required_key_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    """D17: a missing GROQ_API_KEY must raise at construction, not boot a broken app."""
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
    """DECISION GATE C: version-key composition (D10). Bumping any version changes the key."""
    s = _settings(prompt_version="v2", corpus_version="v3", index_version="v4")
    ns = s.cache_namespace
    assert "pv2" in ns and "cv3" in ns and "iv4" in ns
    assert _settings(prompt_version="v1").cache_namespace != s.cache_namespace


def test_secret_is_not_exposed_in_repr() -> None:
    s = _settings(groq_api_key="gsk_super_secret")
    assert "gsk_super_secret" not in repr(s)
    assert isinstance(s.groq_api_key, SecretStr)
    assert s.groq_api_key.get_secret_value() == "gsk_super_secret"


def test_settings_are_frozen() -> None:
    s = _settings()
    with pytest.raises(ValidationError):
        s.retrieval_top_k = 99  # type: ignore[misc]
