"""Privacy-preserving client identity derived from the trusted request peer."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from starlette.requests import Request

from backend.app.config import Settings


class ClientIdentityResolver:
    def __init__(self, secret: str | bytes | None = None) -> None:
        if secret is None:
            self._secret = secrets.token_bytes(32)
        elif isinstance(secret, str):
            self._secret = secret.encode("utf-8")
        else:
            self._secret = secret

    @classmethod
    def from_settings(cls, settings: Settings) -> "ClientIdentityResolver":
        return cls(settings.client_identity_secret)

    def resolve(self, request: Request) -> str:
        # Proxy trust is configured at the ASGI server boundary. Reading only
        # request.client prevents arbitrary forwarding headers bypassing quotas.
        peer = request.client.host if request.client else "unknown-peer"
        return hmac.new(self._secret, peer.encode("utf-8"), hashlib.sha256).hexdigest()
