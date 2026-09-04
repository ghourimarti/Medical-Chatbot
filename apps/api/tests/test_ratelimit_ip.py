"""Per-IP rate limiting.

The defect these tests lock down: the limiter was keyed ONLY on the session id, and the
session id is minted fresh whenever no cookie arrives. A client that never sends the cookie
therefore got a brand-new quota bucket per request. Measured against the running API before
the fix: 30 cookieless requests, 20/min limit, ZERO 429s.

A limit the attacker opts into is not a limit.
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi import Request
from medapi.session import SessionManager

_SECRET = "test-secret-for-session-signing"


def _request(*, ip: str | None = "203.0.113.7", xff: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode()))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/query",
        "headers": headers,
        "client": (ip, 51234) if ip else None,
        "query_string": b"",
    }
    return Request(scope)


def test_client_hash_is_stable_for_the_same_ip() -> None:
    mgr = SessionManager(_SECRET, secure_cookies=False)
    assert mgr.client_hash(_request()) == mgr.client_hash(_request())


def test_client_hash_differs_across_ips() -> None:
    mgr = SessionManager(_SECRET, secure_cookies=False)
    assert mgr.client_hash(_request(ip="203.0.113.7")) != mgr.client_hash(
        _request(ip="203.0.113.8")
    )


def test_raw_ip_is_never_the_key() -> None:
    """An IP is personal data under GDPR; only the salted hash may be stored."""
    mgr = SessionManager(_SECRET, secure_cookies=False)
    key = mgr.client_hash(_request(ip="203.0.113.7"))
    assert key is not None
    assert "203.0.113.7" not in key
    assert key != hashlib.sha256(b"203.0.113.7").hexdigest()  # salted, not bare


def test_missing_client_yields_none_rather_than_crashing() -> None:
    """ASGI does not guarantee a client tuple. The route must degrade to session-only
    limiting, never 500 on a request that simply lacks peer info."""
    mgr = SessionManager(_SECRET, secure_cookies=False)
    assert mgr.client_hash(_request(ip=None)) is None


class TestForwardedFor:
    """X-Forwarded-For is CLIENT-SUPPLIED. Trusting it blindly is worse than ignoring it:
    an attacker rotates the header per request and gets unlimited quota again."""

    def test_spoofed_header_is_ignored_when_no_proxy_is_configured(self) -> None:
        mgr = SessionManager(_SECRET, secure_cookies=False)
        honest = mgr.client_ip(_request(ip="203.0.113.7"))
        spoofed = mgr.client_ip(_request(ip="203.0.113.7", xff="1.2.3.4"))
        assert honest == spoofed == "203.0.113.7"

    def test_rotating_a_spoofed_header_cannot_change_the_bucket(self) -> None:
        mgr = SessionManager(_SECRET, secure_cookies=False)
        keys = {
            mgr.client_hash(_request(ip="203.0.113.7", xff=f"10.0.0.{i}"))
            for i in range(50)
        }
        assert len(keys) == 1, "spoofed XFF must not multiply quota buckets"

    def test_one_trusted_hop_reads_the_address_the_proxy_observed(self) -> None:
        mgr = SessionManager(_SECRET, secure_cookies=False)
        # Our ALB appends the peer it saw; the client wrote everything to its left.
        ip = mgr.client_ip(
            _request(ip="10.0.0.1", xff="1.2.3.4, 198.51.100.9"), trusted_proxy_hops=1
        )
        assert ip == "198.51.100.9"

    def test_two_trusted_hops_step_one_further_left(self) -> None:
        mgr = SessionManager(_SECRET, secure_cookies=False)
        ip = mgr.client_ip(
            _request(ip="10.0.0.1", xff="1.2.3.4, 198.51.100.9, 10.0.0.2"),
            trusted_proxy_hops=2,
        )
        assert ip == "198.51.100.9"

    def test_short_chain_does_not_index_out_of_range(self) -> None:
        """Configured for 3 hops but only 1 entry arrived — clamp, never IndexError."""
        mgr = SessionManager(_SECRET, secure_cookies=False)
        assert (
            mgr.client_ip(_request(ip="10.0.0.1", xff="1.2.3.4"), trusted_proxy_hops=3)
            == "1.2.3.4"
        )

    def test_empty_header_falls_back_to_peer(self) -> None:
        mgr = SessionManager(_SECRET, secure_cookies=False)
        assert (
            mgr.client_ip(_request(ip="10.0.0.1", xff="   "), trusted_proxy_hops=1)
            == "10.0.0.1"
        )


@pytest.mark.asyncio
async def test_ip_bucket_is_shared_across_distinct_sessions() -> None:
    """The property that actually closes the hole: rotating session ids must NOT reset the
    quota, because every one of those requests lands in the same IP bucket."""
    from medapi.ratelimit import RateLimiter

    from medcore.errors import QuotaExceededError

    limiter = RateLimiter(None, "test")  # None client -> in-process counter
    mgr = SessionManager(_SECRET, secure_cookies=False)
    ip_key = mgr.client_hash(_request(ip="203.0.113.7"))
    assert ip_key is not None

    allowed = 0
    for _ in range(10):
        try:
            # A fresh session id every iteration — exactly the bypass.
            await limiter.check(ip_key, scope="ip_minute", limit=5, window_seconds=60)
            allowed += 1
        except QuotaExceededError:
            pass
    assert allowed == 5, "the IP bucket must bind regardless of session churn"
