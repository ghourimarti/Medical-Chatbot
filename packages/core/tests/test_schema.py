import pytest
from pydantic import ValidationError

from medcore.schema import Answer, AnswerKind, Citation, QueryRequest, RetrievedChunk, Usage


def _citation() -> Citation:
    return Citation(chunk_id="c1", source="Gale", page=42, snippet="...", score=0.9)


def test_grounded_answer_requires_citation() -> None:
    with pytest.raises(ValidationError, match="must carry at least one citation"):
        Answer(kind=AnswerKind.GROUNDED, text="Cirrhosis is scarring of the liver.")


def test_grounded_answer_requires_text() -> None:
    with pytest.raises(ValidationError, match="must have text"):
        Answer(kind=AnswerKind.GROUNDED, text="   ", citations=[_citation()])


def test_refusal_must_not_cite_corpus() -> None:
    with pytest.raises(ValidationError, match="must not cite"):
        Answer(kind=AnswerKind.REFUSED, text="Consult a doctor.", citations=[_citation()])


def test_valid_grounded_answer() -> None:
    ans = Answer(
        kind=AnswerKind.GROUNDED, text="Scarring of the liver [1].", citations=[_citation()]
    )
    assert ans.is_grounded and ans.is_cacheable


@pytest.mark.parametrize("kind", [AnswerKind.NO_ANSWER, AnswerKind.REFUSED, AnswerKind.DEGRADED])
def test_only_grounded_answers_are_cacheable(kind: AnswerKind) -> None:
    """D10: a cache must never memorize a refusal, a don't-know, or a degraded response."""
    assert Answer(kind=kind, text="...").is_cacheable is False


def test_cache_hit_answer_is_not_recacheable() -> None:
    ans = Answer(
        kind=AnswerKind.GROUNDED, text="x [1]", citations=[_citation()], cache_hit=True
    )
    assert ans.is_cacheable is False


def test_effective_score_prefers_rerank_then_dense() -> None:
    chunk = RetrievedChunk(id="c", text="t", source="s", dense_score=0.4, rerank_score=0.8)
    assert chunk.effective_score == 0.8
    assert RetrievedChunk(id="c", text="t", source="s", dense_score=0.4).effective_score == 0.4
    assert RetrievedChunk(id="c", text="t", source="s").effective_score == 0.0


def test_usage_total_tokens() -> None:
    assert Usage(prompt_tokens=10, completion_tokens=5).total_tokens == 15


def test_query_request_enforces_size_cap() -> None:
    with pytest.raises(ValidationError):
        QueryRequest(question="x" * 2001)
    with pytest.raises(ValidationError):
        QueryRequest(question="")
    assert QueryRequest(question="What is asthma?").stream is True
