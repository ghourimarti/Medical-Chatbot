"""Identity verification (S20b, D24).

THE RULE THIS MODULE EXISTS TO ENFORCE: a token that is PRESENT but INVALID is a 401 — it
is never quietly downgraded to "anonymous".

Downgrading is the tempting behaviour because it keeps the product working, and it is
wrong twice over. It hides an attack (a forged token looks exactly like a signed-out
visitor), and it confuses an honest user whose session expired: they stay signed in
visually, their conversations vanish, and nothing explains why. Absent token means
anonymous; broken token means broken.

Verification is behind a Protocol so the endpoints are testable without a Clerk account,
which is the difference between "this is written" and "this is proven".
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx
import jwt
from jwt import PyJWKClient

from medapi.observability import get_logger
from medcore.errors import MedbotError

logger = get_logger("medapi.auth")


class InvalidToken(MedbotError):
    status, title, slug = 401, "Not Authenticated", "invalid-token"
    public_detail = "Your sign-in has expired or is not valid. Please sign in again."


class AuthVerifier(Protocol):
    """Returns the verified subject for a token, or raises InvalidToken."""

    async def subject(self, token: str) -> str: ...

    @property
    def enabled(self) -> bool: ...


class DisabledVerifier:
    """No identity provider configured: accounts are simply off.

    Presenting a token to a service with no verifier is a client error, not a silent
    anonymous downgrade — the client believes it is authenticated and must be told it is
    not, or it will render a signed-in UI over anonymous data.
    """

    enabled = False

    async def subject(self, token: str) -> str:
        raise InvalidToken("authentication is not configured on this deployment")


class ClerkVerifier:
    """Verifies a Clerk-issued RS256 JWT against the provider's JWKS.

    The JWKS client caches keys and refetches on an unknown `kid`, which is what makes key
    ROTATION a non-event: a rotated key produces one cache miss rather than an outage.

    Signature alone is not enough. `iss` is checked because a validly-signed token from a
    DIFFERENT Clerk instance is still not a token for this application, and algorithms are
    pinned to RS256 so a token claiming `alg: none` — or HS256 signed with the public key —
    cannot be accepted. Both are classic JWT bypasses that a naive `jwt.decode` allows.
    """

    enabled = True

    def __init__(
        self,
        jwks_url: str,
        *,
        issuer: str | None = None,
        audience: str | None = None,
        leeway_seconds: int = 30,
    ) -> None:
        self._client = PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)
        self._issuer = issuer
        self._audience = audience
        # Clocks drift between the issuer and this machine; without leeway a freshly issued
        # token can appear to be from the future and be rejected on arrival.
        self._leeway = leeway_seconds

    async def subject(self, token: str) -> str:
        try:
            key = self._client.get_signing_key_from_jwt(token).key
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self._issuer,
                audience=self._audience,
                leeway=self._leeway,
                options={
                    "require": ["exp", "sub"],
                    "verify_aud": self._audience is not None,
                    "verify_iss": self._issuer is not None,
                },
            )
        except Exception as exc:
            # Never echo the library's message to the caller: it distinguishes "expired"
            # from "bad signature" from "wrong issuer", which is a probing oracle. The
            # detail goes to the log, where an operator can use it.
            logger.warning("token_rejected", reason=type(exc).__name__)
            raise InvalidToken(f"token rejected: {exc}", cause=exc) from exc

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise InvalidToken("token has no usable subject")
        return subject


def build_verifier(settings: Any) -> AuthVerifier:
    """Config decides whether accounts exist at all. Absent JWKS URL => accounts off, and
    the anonymous product keeps working unchanged (D24 sequencing)."""
    url = getattr(settings, "clerk_jwks_url", None)
    if not url:
        return DisabledVerifier()
    return ClerkVerifier(
        url,
        issuer=getattr(settings, "clerk_issuer", None) or None,
        audience=getattr(settings, "clerk_audience", None) or None,
    )


def bearer_token(authorization: str | None) -> str | None:
    """Extract a Bearer token, or None when the header is absent.

    A malformed Authorization header returns None rather than raising: it is
    indistinguishable from a client that simply is not signed in, and treating a typo as an
    attack helps nobody.
    """
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


async def jwks_reachable(url: str, timeout: float = 3.0) -> bool:
    """Used by readiness reporting, not by request handling. A JWKS outage must not take
    the anonymous product down — it only means new sign-ins cannot be verified."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            return (await client.get(url)).status_code == 200
    except Exception:
        return False
