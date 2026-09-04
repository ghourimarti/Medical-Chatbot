"""Structured logging with PII redaction.

Health questions are sensitive, so raw query text can't go into application logs, but
production still has to be debuggable. So: log everything about a request (stage latencies,
token counts, cache hits, refusal reasons, a stable query fingerprint) and never the query
itself. Langfuse is the one sanctioned store for content, access-controlled and sampled,
under the 30-day retention policy.

Redaction is a structlog processor rather than a convention, because a convention is one
careless `logger.info(f"query: {q}")` away from an incident. A processor can't be
forgotten; a review guideline can.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sys
from typing import Any

import structlog

# Keys whose values must never reach a log sink, regardless of who logs them.
SENSITIVE_KEYS = frozenset(
    {
        "question", "query", "prompt", "answer", "text", "content", "message",
        "context", "passage", "chunk_text", "user_input",
    }
)

# Belt-and-braces patterns for values that slip through under an innocuous key.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "<email>"),
    (re.compile(r"\bgsk_[A-Za-z0-9]{10,}\b"), "<groq-key>"),
    (re.compile(r"\b(sk|hf)_[A-Za-z0-9]{10,}\b"), "<api-key>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"), "<ip>"),
)


def fingerprint(text: str) -> str:
    """Stable 12-char hash: lets you correlate repeats of the same question across logs
    without ever storing the question. Enough to answer 'is this one query looping?'."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def redact_processor(
    _logger: Any, _name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Replace sensitive values with a fingerprint; scrub patterns everywhere else."""
    for key in list(event_dict):
        value = event_dict[key]
        if key.lower() in SENSITIVE_KEYS and isinstance(value, str):
            event_dict[key] = f"<redacted:{fingerprint(value)}:{len(value)}chars>"
        elif isinstance(value, str):
            for pattern, replacement in _PATTERNS:
                value = pattern.sub(replacement, value)
            event_dict[key] = value
    return event_dict


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    """JSON to stdout, never to a file.

    Writing to `logs/` inside the container is invisible to `kubectl logs`, lost on pod
    restart, and needs a sidecar to ship. Stdout is the only log destination a container
    should know about; collection is the platform's job.
    """
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,  # request-scoped fields, no plumbing
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_processor,  # last before rendering, so nothing can bypass it
    ]
    processors.append(
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[level.upper()]
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    return structlog.get_logger(name)
