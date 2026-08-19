"""Anonymous session identity (D9).

The cookie carries ONLY a signed session id; all data lives in Postgres. That split
matters: cookies are size-limited (~4KB), client-modifiable, and sent on every request —
chat history belongs in a database, not in a header.

Fixes a concrete demo/ bug: it used `app.secret_key = os.urandom(24)`, so every process
restart invalidated all sessions, and any second replica invalidated them immediately. The
signing key is now configuration, which is what makes horizontal scaling possible at all.
"""

from __future__ import annotations

import hashlib
import uuid

from fastapi import Request, Response
from itsdangerous import BadSignature, URLSafeSerializer

COOKIE_NAME = "medbot_sid"
_SALT = "medbot-session-v1"


class SessionManager:
    def __init__(self, secret: str, *, secure_cookies: bool) -> None:
        self._serializer = URLSafeSerializer(secret, salt=_SALT)
        self._secure = secure_cookies

    def sign(self, session_id: uuid.UUID) -> str:
        return self._serializer.dumps(str(session_id))  # type: ignore[no-any-return]

    def unsign(self, token: str) -> uuid.UUID | None:
        try:
            return uuid.UUID(self._serializer.loads(token))
        except (BadSignature, ValueError, TypeError):
            return None  # tampered, stale-secret, or malformed: treat as a new visitor

    def resolve(self, request: Request) -> tuple[uuid.UUID, bool]:
        """Return (session_id, is_new). A forged or unreadable cookie yields a fresh id
        rather than an error — an anonymous chat must never 400 on a bad cookie."""
        token = request.cookies.get(COOKIE_NAME)
        if token:
            existing = self.unsign(token)
            if existing is not None:
                return existing, False
        return uuid.uuid4(), True

    def attach(self, response: Response, session_id: uuid.UUID) -> None:
        response.set_cookie(
            COOKIE_NAME,
            self.sign(session_id),
            httponly=True,  # unreadable to JS — mitigates XSS session theft (D18)
            samesite="lax",
            secure=self._secure,  # HTTPS-only outside local dev
            max_age=60 * 60 * 24 * 30,
            path="/",
        )

    @staticmethod
    def client_ip(request: Request, *, trusted_proxy_hops: int = 0) -> str | None:
        """The caller's real IP, accounting for reverse proxies.

        Behind an ALB/ingress, `request.client.host` is the PROXY's address — so every user
        on the planet shares one bucket and per-IP limiting becomes a global kill switch.
        The fix is `X-Forwarded-For`, but that header is client-supplied and trivially
        spoofed: an attacker sends `X-Forwarded-For: 1.2.3.4` and rotates it per request,
        which is *worse* than not having it.

        The resolution is to trust only as many entries as there are proxies we actually
        operate. XFF appends left-to-right, so with N trusted hops the last N entries were
        written by our own infrastructure and entry `-N` is the address our outermost proxy
        observed. Anything further left is attacker-controlled and ignored. Default 0 means
        "no proxy" — the header is not consulted at all (P5.2).
        """
        if trusted_proxy_hops > 0:
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                hops = [h.strip() for h in forwarded.split(",") if h.strip()]
                if hops:
                    # Clamp: fewer entries than configured hops means the chain is shorter
                    # than expected, so fall back to the leftmost value we can defend.
                    return hops[max(0, len(hops) - trusted_proxy_hops)]
        client = request.client
        return client.host if client is not None else None

    @classmethod
    def client_hash(cls, request: Request, *, trusted_proxy_hops: int = 0) -> str | None:
        """Salted hash of the client IP. An IP is personal data under GDPR (D18), so the
        raw value is never stored; the hash still supports per-client abuse detection."""
        ip = cls.client_ip(request, trusted_proxy_hops=trusted_proxy_hops)
        if ip is None:
            return None
        return hashlib.sha256(f"{_SALT}:{ip}".encode()).hexdigest()
