"""Typed errors and the RFC 7807 problem envelope.

Two rules live here: users never see internal exception text, and failures carry
`retryable` / `degradable` flags so the degradation ladder branches on types rather than
string-matching provider error messages.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

PROBLEM_BASE_URI = "https://p5-medical-chatbot/problems"


class ProblemDetail(BaseModel):
    """RFC 7807. `detail` is public and safe; internals go to the logs, never here."""

    model_config = ConfigDict(frozen=True)

    type: str
    title: str
    status: int
    detail: str
    instance: str | None = None


class MedbotError(Exception):
    """Base for all domain failures."""

    status: int = 500
    title: str = "Internal Server Error"
    slug: str = "internal-error"
    public_detail: str = "An unexpected error occurred."
    retryable: bool = False
    degradable: bool = False

    def __init__(self, internal_message: str = "", *, cause: Exception | None = None) -> None:
        self.internal_message = internal_message or self.title
        self.__cause__ = cause
        super().__init__(self.internal_message)

    def to_problem(self, instance: str | None = None) -> ProblemDetail:
        return ProblemDetail(
            type=f"{PROBLEM_BASE_URI}/{self.slug}",
            title=self.title,
            status=self.status,
            detail=self.public_detail,
            instance=instance,
        )


class ConfigError(MedbotError):
    status, title, slug = 500, "Configuration Error", "config-error"
    public_detail = "The service is misconfigured."


class RetrievalError(MedbotError):
    status, title, slug = 503, "Retrieval Unavailable", "retrieval-unavailable"
    public_detail = "Knowledge retrieval is temporarily unavailable."
    retryable = True
    degradable = True


class RerankerError(MedbotError):
    """Non-fatal: skip reranking, serve fusion order, log the quality dip."""

    status, title, slug = 503, "Reranker Unavailable", "reranker-unavailable"
    public_detail = "Answer quality is temporarily reduced."
    retryable = True
    degradable = True


class ProviderError(MedbotError):
    status, title, slug = 502, "Model Provider Error", "provider-error"
    public_detail = "The answering model is temporarily unavailable."
    retryable = True
    degradable = True


class AllProvidersDownError(MedbotError):
    status, title, slug = 503, "Service Degraded", "service-degraded"
    public_detail = "Answers are limited right now. Please try again shortly."
    degradable = True


class QuotaExceededError(MedbotError):
    status, title, slug = 429, "Quota Exceeded", "quota-exceeded"
    public_detail = "You have reached your request limit. Please try again later."


class GuardrailRefusal(MedbotError):
    """A product behaviour rather than a failure. It is an exception only so the pipeline
    can short-circuit; the API renders it as a normal refused Answer."""

    status, title, slug = 200, "Refused", "guardrail-refusal"
    public_detail = (
        "I can't provide personal medical advice. Please consult a healthcare provider. "
        "If this is an emergency, contact your local emergency services."
    )
