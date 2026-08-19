"""Serving-venue registry (D4b).

Turns `SERVING_CHAIN=local,runpod,aws,groq` into an ordered list of failover legs.

Two rules that keep this honest:

  1. A venue with no URL is SKIPPED, not an error. The chain can name venues whose
     accounts do not exist yet (RunPod, AWS), so configuration and provisioning proceed
     independently — nobody has to edit code when a GPU finally appears.

  2. An empty resulting chain is a STARTUP failure, not a runtime surprise. A service that
     boots with no way to answer would pass its liveness probe and fail every request
     (D17 fail-fast).
"""

from __future__ import annotations

import logging

from medapi.adapters.failover import CircuitBreaker, FailoverModel, VenueLeg
from medapi.adapters.openai_compat import OpenAICompatModel
from medcore.config import Settings

logger = logging.getLogger("medapi.venues")

KNOWN_VENUES = ("local", "runpod", "aws", "groq")


def _venue_config(settings: Settings, venue: str) -> tuple[str, str, str | None]:
    """(base_url, model_id, api_key) for a venue. Empty base_url => not configured."""
    if venue == "local":
        return settings.vllm_local_url, settings.vllm_local_model, None
    if venue == "runpod":
        return settings.vllm_runpod_url, settings.vllm_runpod_model, None
    if venue == "aws":
        return settings.vllm_aws_url, settings.vllm_aws_model, None
    if venue == "groq":
        return (
            settings.groq_base_url,
            settings.groq_default_model,
            settings.groq_api_key.get_secret_value(),
        )
    raise ValueError(f"unknown venue {venue!r}; known: {KNOWN_VENUES}")


def parse_chain(raw: str) -> list[str]:
    venues = [v.strip().lower() for v in raw.split(",") if v.strip()]
    unknown = [v for v in venues if v not in KNOWN_VENUES]
    if unknown:
        raise ValueError(f"unknown venues in SERVING_CHAIN: {unknown}; known: {KNOWN_VENUES}")
    # Preserve order, drop duplicates — a repeated venue would double its failure weight
    # in the chain without adding a failure domain.
    seen: set[str] = set()
    ordered: list[str] = []
    for venue in venues:
        if venue not in seen:
            seen.add(venue)
            ordered.append(venue)
    return ordered


def build_failover_model(settings: Settings) -> FailoverModel:
    legs: list[VenueLeg] = []
    for venue in parse_chain(settings.serving_chain):
        base_url, model_id, api_key = _venue_config(settings, venue)
        if not base_url:
            logger.info("venue %s not configured (no URL); skipping", venue)
            continue
        legs.append(
            VenueLeg(
                name=venue,
                model=OpenAICompatModel(
                    venue=venue,
                    base_url=base_url,
                    model_id=model_id,
                    api_key=api_key,
                    timeout=settings.groq_timeout,
                ),
                breaker=CircuitBreaker(
                    failure_threshold=settings.circuit_failure_threshold,
                    cooldown_seconds=settings.circuit_cooldown_seconds,
                ),
            )
        )
    if not legs:
        raise ValueError(
            f"SERVING_CHAIN={settings.serving_chain!r} produced no usable venues. "
            "Set at least one venue URL, or the service cannot answer anything."
        )
    logger.info("serving chain: %s", " -> ".join(leg.name for leg in legs))
    return FailoverModel(legs)
