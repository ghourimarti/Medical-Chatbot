"""Caching layers (D10, D20).

At the Phase-1 target a 25-35% hit rate is worth ~$4-6k/month, which makes this an
economic component rather than an optimization. But the medical domain inverts the usual
priority: **a wrong cache hit is a patient-safety bug, not a stale page.** Three rules
follow, and the type system already carries two of them:

  1. Only GROUNDED answers are cacheable — never a refusal, no-answer, or degraded
     response. `Answer.is_cacheable` (S2) encodes this; the cache only has to respect it.
  2. Invalidation is VERSION-KEY COMPOSITION, never a manual purge. Keys are namespaced by
     prompt + corpus + index + model version (`Settings.cache_namespace`, S2 Gate C), so
     bumping any version makes every stale entry unreachable atomically.
  3. FAIL-OPEN. Redis down means slower and more expensive, never wrong or unavailable.

There is NO semantic cache. Only the two exact-match layers below ship, and S19.4 decided
against building the third — see docs/SEMANTIC_CACHE.md for the measurements.

(An earlier version of this docstring claimed the semantic cache "is implemented but ships
DISABLED". It never was: `semantic_cache_enabled` and `semantic_cache_threshold` exist in
Settings and are referenced nowhere else in the codebase. Corrected in S19.4 — a comment
that overstates what exists is worse than no comment, because it stops anyone looking.)

The same docstring also justified D10's guard by asserting that "aspirin dose adult" and
"aspirin dose child" sit closer than 0.95 in embedding space. Measured with the production
embedder (bge-large-en-v1.5, query prefix, L2-normalised): **0.8235**. The premise was
wrong, and the real obstacle turned out to be the opposite of the one feared — see
`packages/eval/tools/semantic_cache_probe.py`.
"""

from __future__ import annotations

import hashlib
import logging
import re
from array import array
from collections.abc import Sequence
from typing import Any

from medapi.logthrottle import ThrottledLogger
from medcore.schema import Answer

logger = logging.getLogger("medapi.cache")
_throttled = ThrottledLogger()

_WHITESPACE = re.compile(r"\s+")


def normalize_question(text: str) -> str:
    """Conservative normalization: case + whitespace only.

    Deliberately NOT stemming, stripping punctuation, or removing stop-words. In medical
    text those transformations merge genuinely distinct questions ("hepatitis B" vs
    "hepatitis C" survive; "is it X?" vs "is it not X?" would not survive stop-word
    removal). A lower hit rate is the correct trade here.
    """
    return _WHITESPACE.sub(" ", text.strip().lower())


class ResponseCache:
    """Exact-match answer cache. `client=None` disables it entirely."""

    def __init__(self, client: Any | None, namespace: str, ttl_seconds: int = 86_400) -> None:
        self._client = client
        self._ns = namespace
        self._ttl = ttl_seconds

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def key(self, question: str) -> str:
        digest = hashlib.sha256(normalize_question(question).encode()).hexdigest()
        return f"{self._ns}:ans:{digest}"

    async def get(self, question: str) -> Answer | None:
        if self._client is None:
            return None
        try:
            raw = await self._client.get(self.key(question))
        except Exception:
            _throttled.warning("cache-read", "cache read failed; serving uncached", exc_info=True)
            return None
        if not raw:
            return None
        try:
            answer = Answer.model_validate_json(raw)
        except Exception:
            _throttled.warning("cache-parse", "cache entry unparseable; ignoring", exc_info=True)
            return None
        return answer.model_copy(update={"cache_hit": True})

    async def set(self, question: str, answer: Answer) -> bool:
        """Store only if the answer is safe to replay. Returns whether it was stored."""
        if self._client is None or not answer.is_cacheable:
            return False
        try:
            await self._client.set(self.key(question), answer.model_dump_json(), ex=self._ttl)
            return True
        except Exception:
            _throttled.warning("cache-write", "cache write failed; continuing", exc_info=True)
            return False


class EmbeddingCache:
    """Query-embedding cache — small, safe, and pure upside.

    Embeddings are a deterministic function of (text, model), so unlike answers there is no
    correctness risk at all. Vectors are stored as packed float32 (~4KB for 1024 dims)
    rather than JSON (~20KB): a 5x memory difference at no cost in complexity.
    """

    def __init__(self, client: Any | None, namespace: str, ttl_seconds: int = 604_800) -> None:
        self._client = client
        self._ns = namespace
        self._ttl = ttl_seconds

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def key(self, text: str) -> str:
        digest = hashlib.sha256(normalize_question(text).encode()).hexdigest()
        return f"{self._ns}:emb:{digest}"

    async def get(self, text: str) -> list[float] | None:
        if self._client is None:
            return None
        try:
            raw = await self._client.get(self.key(text))
        except Exception:
            _throttled.warning("embcache-read", "embedding cache read failed", exc_info=True)
            return None
        if not raw:
            return None
        vec = array("f")
        vec.frombytes(raw if isinstance(raw, bytes) else bytes(raw))
        return list(vec)

    async def set(self, text: str, vector: Sequence[float]) -> bool:
        if self._client is None:
            return False
        try:
            await self._client.set(self.key(text), array("f", vector).tobytes(), ex=self._ttl)
            return True
        except Exception:
            _throttled.warning("embcache-write", "embedding cache write failed", exc_info=True)
            return False
