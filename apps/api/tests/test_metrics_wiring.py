"""Metrics must be OBSERVED, not merely defined.

INFRA-5: four metrics were declared in metrics.py, re-exported from observability/__init__,
referenced in the Grafana dashboard — and never written:

    medbot_tokens_total          no caller anywhere
    medbot_ttft_seconds          computed in rag.py, carried on Answer, never observed
    medbot_venue_circuit_state   record_circuit() had no caller
    medbot_request_cost_usd      observed only `if cost_usd:` - so never, when self-hosting

Every one of them scraped cleanly as 0 or absent, so Prometheus was healthy, Grafana was
healthy, and the headline latency NFR was simply not being measured. Same shape as the
Langfuse defect (I4.3): complete machinery, no call site.

These tests assert the CALL, because that is the part that was missing.
"""

from __future__ import annotations

from typing import Any

import pytest
from medapi.observability import REGISTRY
from medapi.observability.metrics import record_answer


def value(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels or None) or 0.0


def test_ttft_is_observed_on_the_streaming_path() -> None:
    """The p50 0.8s / p95 2.0s NFR is unmeasurable if this never fires."""
    before = value("medbot_ttft_seconds_count", venue="local-sglang")
    record_answer(
        "grounded", total_ms=1500.0, cost_usd=0.0, ttft_ms=420.0, venue="local-sglang"
    )
    assert value("medbot_ttft_seconds_count", venue="local-sglang") == before + 1


def test_ttft_is_attributed_to_a_venue() -> None:
    """A chain serves the same endpoint from a local GPU and a hosted API, whose latencies
    differ by an order of magnitude. Unlabelled, `TTFT p95` averages whichever venues
    happened to answer - so the headline NFR moves when the CHAIN shifts rather than when
    performance does, and no query can name the slow leg."""
    before = value("medbot_ttft_seconds_count", venue="groq")
    record_answer("grounded", total_ms=900.0, cost_usd=0.0, ttft_ms=310.0, venue="groq")
    assert value("medbot_ttft_seconds_count", venue="groq") == before + 1


def test_answers_without_a_venue_are_labelled_none_not_empty() -> None:
    """A refusal generates nothing, so it has no venue. It still needs a label VALUE:
    an absent series and a zero are different claims, and this module has already been
    burned twice by conflating them."""
    before = value("medbot_request_duration_seconds_count", outcome="refused", venue="none")
    record_answer("refused", total_ms=12.0, cost_usd=0.0)
    assert (
        value("medbot_request_duration_seconds_count", outcome="refused", venue="none")
        == before + 1
    )


def test_ttft_is_not_faked_on_the_non_streaming_path() -> None:
    """There is no 'first token' without a stream. Substituting total_ms would redefine
    the SLI while still looking like data."""
    before = value("medbot_ttft_seconds_count", venue="local-sglang")
    record_answer(
        "grounded", total_ms=1500.0, cost_usd=0.0, ttft_ms=None, venue="local-sglang"
    )
    assert value("medbot_ttft_seconds_count", venue="local-sglang") == before


def test_zero_cost_is_recorded_not_skipped() -> None:
    """Self-hosted venues cost $0. Skipping the observation left the cost panel empty in
    the ONE configuration this project actually runs."""
    before = value("medbot_request_cost_usd_count", venue="local-sglang")
    record_answer("grounded", total_ms=900.0, cost_usd=0.0, venue="local-sglang")
    assert value("medbot_request_cost_usd_count", venue="local-sglang") == before + 1


@pytest.mark.asyncio
async def test_failover_records_tokens_and_circuit_state() -> None:
    """FailoverModel is the only place that knows BOTH the usage and the venue."""
    from medapi.adapters.failover import FailoverModel, VenueLeg

    from medcore.schema import Completion, Message, Usage

    class _Model:
        model_id = "test-model"

        async def complete(self, **_: Any) -> Completion:
            return Completion(
                text="ok", model_id="test-model",
                usage=Usage(prompt_tokens=100, completion_tokens=25),
            )

        async def stream(self, **_: Any) -> Any:  # pragma: no cover
            raise NotImplementedError

        async def health(self) -> bool:
            return True

    leg = VenueLeg(name="local-vllm", model=_Model())
    before = value("medbot_tokens_total", direction="prompt", venue="local-vllm")

    await FailoverModel([leg]).complete(
        messages=[Message(role="user", content="hi")], max_tokens=16, temperature=0.0
    )

    assert value("medbot_tokens_total", direction="prompt", venue="local-vllm") == before + 100
    assert value("medbot_tokens_total", direction="completion", venue="local-vllm") >= 25
    # 0 == closed. A gauge never written reads as absent, not as healthy.
    assert value("medbot_venue_circuit_state", venue="local-vllm") == 0


def test_reranker_degradation_is_metered_not_only_logged() -> None:
    """A degradation that publishes no signal is indistinguishable from working.

    RERANK_TIMEOUT was 2.0s against a reranker p95 of 2.425s, so the fallback fired on
    well over 5% of queries - serving fusion order instead of reranked order - while every
    dashboard stayed green, because the only evidence was a log line.
    """
    from medapi.observability.metrics import degradations_total

    before = value("medbot_degradations_total", component="reranker", reason="unavailable")
    degradations_total.labels(component="reranker", reason="unavailable").inc()
    after = value("medbot_degradations_total", component="reranker", reason="unavailable")
    assert after == before + 1


def test_timeouts_exceed_measured_p95() -> None:
    """A timeout below the p95 of what it guards makes the degraded path the normal path.

    Pinned as a test because the numbers are MEASURED (medbot_stage_duration_seconds on
    CPU ml-service), not chosen, and the next person to 'tidy' them needs to know that.
    """
    from medcore.config import get_settings

    s = get_settings()
    assert s.rerank_timeout > 2.425, "rerank timeout must exceed the measured rerank p95"
    assert s.embed_timeout > 2.35, "embed timeout must exceed the measured embed p95"


@pytest.mark.asyncio
async def test_cache_hit_records_its_own_latency_not_the_one_it_avoided() -> None:
    """The cache is the largest latency lever in the system; it must not report itself
    as a regression.

    short_circuit() passed `cached.timings.total_ms` - the ORIGINAL generation time -
    into the request-duration histogram on every hit. A 40ms cache hit was therefore
    recorded as an 11-second request, and it compounded: the more traffic the cache
    served, the WORSE p95 looked. request p95 was inflated by answers that were never
    generated on that request.
    """
    from types import SimpleNamespace

    from medapi.serving import short_circuit

    from medcore.schema import Answer, AnswerKind, Citation, StageTimings

    slow = Answer(
        kind=AnswerKind.GROUNDED,
        text="cached answer [1].",
        citations=[Citation(chunk_id="c1", source="Gale", snippet="x")],
        # The generation this hit AVOIDED took 11 seconds.
        timings=StageTimings(total_ms=11_000.0),
        cache_hit=True,
    )

    class _Cache:
        async def get(self, _q: str) -> Answer:
            return slow

    svc = SimpleNamespace(cache=_Cache())
    pre = SimpleNamespace(log=SimpleNamespace(info=lambda *a, **k: None))

    before = value("medbot_request_duration_seconds_sum", outcome="grounded") or 0.0
    # A STANDALONE question, not the old "q" placeholder. One-word text is now classified
    # as context-dependent and bypasses the cache entirely (INFRA-5), so "q" would return
    # before the lookup and this test would assert nothing about cache latency at all.
    result = await short_circuit("What is cirrhosis?", svc, pre)  # type: ignore[arg-type]
    after = value("medbot_request_duration_seconds_sum", outcome="grounded") or 0.0

    assert result is slow
    # The observation must be the cache lookup (milliseconds), never the replayed 11s.
    assert after - before < 1.0, "cache hit re-observed the generation time it avoided"
    # The replayed timings stay ON the answer - they describe how the content was made.
    assert slow.timings.total_ms == 11_000.0


def test_refusals_are_metered_by_category() -> None:
    """`answers_total{kind="refused"}` cannot tell an emergency from a dosage question.

    That blindness is how the self-harm rule shipped broken (I7.1): every gerund phrasing
    fell through the guardrail into retrieval and came back as a no_answer, and no counter
    anywhere moved to say a safety rule had stopped matching.
    """
    before = value("medbot_refusals_total", category="self_harm")
    record_answer("refused", total_ms=12.0, refusal_category="self_harm")
    assert value("medbot_refusals_total", category="self_harm") == before + 1


def test_the_two_no_answer_paths_are_counted_separately() -> None:
    """They cost different money: the retrieval gate never calls the model, while a model
    abstention has already read ~1,000 prompt tokens to say "I don't know"."""
    gate = value("medbot_no_answers_total", path="retrieval_gate")
    paid = value("medbot_no_answers_total", path="model_abstained")

    record_answer("no_answer", total_ms=90.0, no_answer_path="retrieval_gate")
    record_answer("no_answer", total_ms=900.0, no_answer_path="model_abstained")

    assert value("medbot_no_answers_total", path="retrieval_gate") == gate + 1
    assert value("medbot_no_answers_total", path="model_abstained") == paid + 1


def test_a_grounded_answer_touches_neither_safety_counter() -> None:
    """No spurious refusal or decline: these panels drive safety review, so a false
    positive is worse than a missing one."""
    r = value("medbot_refusals_total", category="dosage")
    n = value("medbot_no_answers_total", path="retrieval_gate")
    record_answer("grounded", total_ms=1000.0, cost_usd=0.0)
    assert value("medbot_refusals_total", category="dosage") == r
    assert value("medbot_no_answers_total", path="retrieval_gate") == n
