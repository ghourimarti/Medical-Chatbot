"""Shared circuit breaker.

Third use in this codebase, which is what justifies extracting it: the venue chain
(`adapters/failover.py`), Redis (`redis_guard.py`), and Postgres history (`history.py`).

The property all three share is the one the P5.3 drills measured: **a remote dependency
that is DOWN costs a full timeout on every call, and fail-open is implemented per call.**
Degrading correctly ten times in a row still costs ten timeouts. Redis measured 2.0s ->
20.4s that way; Postgres measured 5.0s -> 8.5s.

Fail-open handles the failure. The breaker is what stops you paying for it repeatedly.
"""

from __future__ import annotations

import time

from medapi.logthrottle import ThrottledLogger

_throttled = ThrottledLogger()


class Breaker:
    """Closed -> (threshold failures) -> Open -> (cooldown) -> one probe -> Closed or Open."""

    def __init__(
        self, *, failure_threshold: int, cooldown_seconds: float, name: str = "dependency"
    ) -> None:
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._name = name
        self._failures = 0
        self._opened_at: float | None = None
        # Publish CLOSED at construction, before anything has failed.
        #
        # A labelled Gauge does not exist in Prometheus until `.labels()` is first called,
        # so publishing only on a state CHANGE meant a dependency that had never broken had
        # no series at all - and "no series" renders identically to "this was never
        # instrumented". The Grafana panel read `No data` whether Redis was perfectly
        # healthy or the metric had been deleted, which makes it useless as a health signal
        # in exactly the situation you would reach for it.
        #
        # The venue breakers never had this problem because FailoverModel republishes every
        # leg on every request. This is the same guarantee, paid once at startup.
        self._publish(is_open=False)

    def _publish(self, *, is_open: bool) -> None:
        # Imported lazily so `circuit.py` stays usable in tests without the metrics
        # registry, and so a metrics failure can never break the degradation path itself.
        try:
            from medapi.observability.metrics import record_dependency_circuit

            record_dependency_circuit(self._name, is_open=is_open)
        except Exception:  # pragma: no cover - observability must never break serving
            pass

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self._cooldown:
            # Half-open: admit exactly one probe. Seeding failures at threshold-1 means a
            # failed probe re-opens immediately instead of needing a fresh streak — without
            # that, a permanently dead dependency would let one slow call through every
            # cooldown *and* reset progress toward re-opening.
            self._opened_at = None
            self._failures = self._threshold - 1
            self._publish(is_open=False)
            return False
        return True

    def record_success(self) -> None:
        was_open = self._opened_at is not None or self._failures > 0
        self._failures = 0
        self._opened_at = None
        if was_open:
            self._publish(is_open=False)

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            self._opened_at = time.monotonic()
            self._publish(is_open=True)
            _throttled.warning(
                f"circuit-{self._name}",
                f"{self._name} circuit OPEN after {self._failures} failures; "
                f"skipping for {self._cooldown:.0f}s",
            )
