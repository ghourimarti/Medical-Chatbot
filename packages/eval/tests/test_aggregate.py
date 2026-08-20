"""S6.12a: an aggregate without its n is an anecdote, not a measurement."""

from medeval.aggregate import aggregate_scores, applicable_counts, coverage_line
from medeval.schema import CaseResult


def _case(cid: str, category: str, **scores: float | None) -> CaseResult:
    return CaseResult(
        case_id=cid, category=category, scores=dict(scores), answer="a", n_contexts=1,
        latency_ms=10.0,
    )


def test_coverage_exposes_a_thin_metric() -> None:
    """The exact defect found in S6.12: 1 of 60 qa cases scored, published as a headline.
    The mean is arithmetically fine; without n it is uninterpretable."""
    results = [
        _case(f"qa-{i:03d}", "qa", faithfulness=0.95 if i == 1 else None)
        for i in range(1, 61)
    ]
    agg, cov = aggregate_scores(results)
    assert agg["faithfulness"] == 0.95  # the misleading number
    assert cov["faithfulness"] == 1  # ...now carries the n that makes it readable
    assert coverage_line("faithfulness", cov, applicable_counts(results)) == "1/60"


def test_full_coverage_reads_as_full() -> None:
    results = [_case(f"qa-{i:03d}", "qa", faithfulness=0.8) for i in range(1, 61)]
    agg, cov = aggregate_scores(results)
    assert agg["faithfulness"] == 0.8
    assert coverage_line("faithfulness", cov, applicable_counts(results)) == "60/60"


def test_applicable_counts_are_category_scoped() -> None:
    """faithfulness applies to qa only; refusal to safety only. Coverage must be judged
    against what a metric COULD score, not against the whole set."""
    results = (
        [_case(f"qa-{i:03d}", "qa", faithfulness=0.9) for i in range(1, 4)]
        + [_case(f"safety-{i:03d}", "safety", refusal_correctness=1.0) for i in range(1, 3)]
        + [_case("ooc-001", "ooc", dont_know_correctness=1.0)]
    )
    app = applicable_counts(results)
    assert app["faithfulness"] == 3
    assert app["refusal_correctness"] == 2
    assert app["dont_know_correctness"] == 1
    _, cov = aggregate_scores(results)
    assert coverage_line("refusal_correctness", cov, app) == "2/2"


def test_latency_and_error_rate_still_computed() -> None:
    results = [_case("qa-001", "qa"), _case("qa-002", "qa")]
    results[1] = results[1].model_copy(update={"error": "boom"})
    agg, cov = aggregate_scores(results)
    assert agg["error_rate"] == 0.5
    assert cov["error_rate"] == 2
    assert agg["latency_p50_ms"] == 10.0
