from medcore.errors import (
    AllProvidersDownError,
    GuardrailRefusal,
    MedbotError,
    ProviderError,
    QuotaExceededError,
    RerankerError,
    RetrievalError,
)


def test_problem_detail_never_leaks_internal_message() -> None:
    secret = "psycopg2 connection failed: password=hunter2 host=10.0.0.5"
    err = RetrievalError(secret)
    problem = err.to_problem(instance="/api/v1/query")
    assert secret not in problem.detail
    assert problem.detail == RetrievalError.public_detail
    assert problem.status == 503
    assert problem.type.endswith("/retrieval-unavailable")
    assert problem.instance == "/api/v1/query"
    assert err.internal_message == secret  # preserved for logs only


def test_degradation_flags_drive_the_ladder() -> None:
    """D21 branches on types, not on provider error strings."""
    assert ProviderError().retryable and ProviderError().degradable
    assert RerankerError().degradable
    assert AllProvidersDownError().degradable
    assert not QuotaExceededError().retryable
    assert not QuotaExceededError().degradable


def test_quota_is_429_and_refusal_is_not_an_error_status() -> None:
    assert QuotaExceededError().status == 429
    assert GuardrailRefusal().status == 200  # a product behavior, not a failure


def test_cause_chaining_preserved() -> None:
    root = ValueError("boom")
    err = ProviderError("upstream 502", cause=root)
    assert err.__cause__ is root
    assert isinstance(err, MedbotError)
