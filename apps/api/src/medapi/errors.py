"""RFC 7807 exception handlers (D18, D21).

Two rules enforced here:
  1. Users never see internal exception text. demo/ renders `f"Error : {str(e)}"`
     straight into the page; this replaces that with a safe, typed envelope.
  2. The catch-all matters most. Handling only known exceptions leaves the one
     unhandled path — the one that leaks a stack trace to a browser — wide open.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from medapi.observability.metrics import errors_total
from medcore.errors import MedbotError, ProblemDetail

logger = logging.getLogger("medapi.errors")

PROBLEM_JSON = "application/problem+json"


def problem_response(problem: ProblemDetail) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(exclude_none=True),
        media_type=PROBLEM_JSON,
    )


async def medbot_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, MedbotError)
    logger.warning(
        "domain error: %s | path=%s | retryable=%s degradable=%s",
        exc.internal_message,
        request.url.path,
        exc.retryable,
        exc.degradable,
    )
    # P5.5: this counter was DECLARED and exported but never incremented anywhere, so the
    # availability SLO's error-budget burn alert — which sums
    # medbot_errors_total{degradable="false"} — could never fire from that term. An alert
    # wired to a metric nobody emits is worse than no alert: it occupies the slot where a
    # working one would go, and it reports healthy forever.
    #
    # `slug` is the label to group by: it is the stable, public problem-type identifier
    # (retrieval-unavailable, service-degraded, quota-exceeded), so alerts written against
    # it survive class renames.
    errors_total.labels(
        error_type=exc.slug,
        degradable=str(exc.degradable).lower(),
        status=str(exc.status),
    ).inc()
    return problem_response(exc.to_problem(instance=request.url.path))


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all. A correlation id goes to the client so a user can quote it in a
    support request, while the actual cause stays in logs only."""
    correlation_id = uuid.uuid4().hex[:12]
    logger.exception("unhandled error [%s] at %s", correlation_id, request.url.path)
    # degradable="false": an unhandled exception is a BUG, and it must count against the
    # availability budget. Handled degradation (a venue failing over) must not.
    errors_total.labels(error_type="unhandled", degradable="false", status="500").inc()
    return problem_response(
        ProblemDetail(
            type="https://p5-medical-chatbot/problems/internal-error",
            title="Internal Server Error",
            status=500,
            detail=f"An unexpected error occurred. Reference: {correlation_id}",
            instance=request.url.path,
        )
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(MedbotError, medbot_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
