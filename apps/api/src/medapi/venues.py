"""Serving-venue registry.

Turns `SERVING_CHAIN=local,runpod,aws,groq` into an ordered list of failover legs.

Two rules keep it honest:

  1. A venue with no URL is skipped, not an error. The chain can name venues whose accounts
     don't exist yet, so configuration and provisioning proceed independently and nobody
     edits code when a GPU finally appears.

  2. An empty resulting chain is a STARTUP failure, not a runtime surprise. A service that
     boots with no way to answer would pass its liveness probe and fail every request
     (D17 fail-fast).
"""

from __future__ import annotations

import logging
from typing import NamedTuple

from medapi.adapters.failover import CircuitBreaker, FailoverModel, VenueLeg
from medapi.adapters.openai_compat import OpenAICompatModel
from medcore.config import Settings

logger = logging.getLogger("medapi.venues")

KNOWN_VENUES = ("local", "runpod", "aws", "groq", "openai")

# The GPU venues — the ones that run our own weights, and therefore the ones where the
# ENGINE is a choice. Hosted APIs have no engine of ours to pick.
GPU_VENUES = ("local", "runpod", "aws")
ENGINES = ("vllm", "sglang")


class ChainLeg(NamedTuple):
    """One entry of SERVING_CHAIN, after parsing. `engine` is None for hosted venues."""

    venue: str
    engine: str | None

    @property
    def label(self) -> str:
        return f"{self.venue}-{self.engine}" if self.engine else self.venue


def _venue_config(settings: Settings, leg: ChainLeg) -> tuple[str, str, str | None]:
    """(base_url, model_id, api_key) for a venue. Empty base_url => not configured.

    GPU venues honour `serving_engine`. It used to be declared in Settings and read
    nowhere: `vllm_local_url` was hardcoded, so `SERVING_ENGINE=sglang` kept serving vLLM.
    A knob that promises a capability nothing implements is worse than no knob, because
    people believe it.

    SGLang is an engine within a venue, never a venue of its own; see the note in
    Settings: two engines on one GPU do not cross a failure domain.
    """
    venue = leg.venue
    if venue in GPU_VENUES:
        engine = leg.engine or settings.serving_engine
        return (
            getattr(settings, f"{engine}_{venue}_url"),
            getattr(settings, f"{engine}_{venue}_model"),
            None,
        )
    if venue == "groq":
        return (
            settings.groq_base_url,
            settings.groq_default_model,
            settings.groq_api_key.get_secret_value(),
        )
    if venue == "openai":
        # No key => empty base_url => the leg is SKIPPED like any unconfigured venue,
        # rather than added and then failing 401 on the first real question.
        key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
        return (settings.openai_base_url if key else "", settings.openai_fallback_model, key)
    raise ValueError(f"unknown venue {venue!r}; known: {KNOWN_VENUES}")


def parse_chain(raw: str) -> list[ChainLeg]:
    """`local-vllm,local-sglang,openai,groq` -> ordered legs.

    An entry is `venue` or `venue-engine`. A bare GPU venue inherits SERVING_ENGINE, so
    every chain written before engine suffixes existed keeps its exact meaning.
    """
    legs: list[ChainLeg] = []
    for raw_entry in raw.split(","):
        entry = raw_entry.strip().lower()
        if not entry:
            continue
        venue, _, engine = entry.partition("-")
        engine = engine or ""
        if venue not in KNOWN_VENUES:
            raise ValueError(
                f"unknown venue {venue!r} in SERVING_CHAIN entry {entry!r}; "
                f"known: {KNOWN_VENUES}"
            )
        if engine and engine not in ENGINES:
            raise ValueError(
                f"unknown engine {engine!r} in SERVING_CHAIN entry {entry!r}; known: {ENGINES}"
            )
        if engine and venue not in GPU_VENUES:
            # Naming an engine for a hosted API asks for something that cannot be
            # delivered. Silently ignoring it would leave the operator believing they
            # had chosen something.
            raise ValueError(
                f"venue {venue!r} is a hosted API and has no engine to choose, but "
                f"SERVING_CHAIN entry {entry!r} names one. Use plain {venue!r}."
            )
        legs.append(ChainLeg(venue=venue, engine=engine or None))

    # Preserve order, drop exact duplicates. `local-vllm` and `local-sglang` are NOT
    # duplicates: same box, different engine, and an engine fault is what that pair covers.
    seen: set[ChainLeg] = set()
    ordered: list[ChainLeg] = []
    for leg in legs:
        if leg not in seen:
            seen.add(leg)
            ordered.append(leg)
    return ordered


def build_failover_model(settings: Settings) -> FailoverModel:
    legs: list[VenueLeg] = []
    for leg in parse_chain(settings.serving_chain):
        venue = leg.venue
        base_url, model_id, api_key = _venue_config(settings, leg)
        if not base_url:
            # Name the ENGINE when one applies. Otherwise `SERVING_ENGINE=sglang` with only
            # vLLM URLs set drops every GPU venue and quietly serves from the hosted API —
            # the operator asked for self-hosted SGLang and got Groq, with a log line that
            # said "not configured" and never mentioned the engine that caused it.
            if venue in GPU_VENUES:
                engine = leg.engine or settings.serving_engine
                # Name the engine AND where it came from. "no sglang URL" alone leaves an
                # operator hunting: with per-leg engines the answer is either their own
                # `local-sglang` entry or the SERVING_ENGINE default, and those are fixed
                # in different places.
                source = (
                    f"SERVING_CHAIN entry {leg.label!r}"
                    if leg.engine
                    else f"SERVING_ENGINE={settings.serving_engine}"
                )
                logger.warning(
                    "leg %s SKIPPED: no %s URL set (engine chosen by %s). "
                    "Set %s_%s_URL, or drop the leg from SERVING_CHAIN.",
                    leg.label, engine, source, engine.upper(), venue.upper(),
                )
            else:
                logger.info("leg %s not configured (no URL/key); skipping", leg.label)
            continue
        legs.append(
            VenueLeg(
                name=leg.label,
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
            f"SERVING_CHAIN={settings.serving_chain!r} (default engine "
            f"{settings.serving_engine!r}) produced no usable legs. Every entry was "
            "skipped for want of a URL or key, so the service could answer nothing."
        )
    logger.info("serving chain: %s", " -> ".join(leg.name for leg in legs))
    return FailoverModel(legs)
