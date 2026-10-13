"""Optional Cloudflare Turnstile verification behind a small adapter."""

from __future__ import annotations

from typing import Protocol

import httpx


TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


class HumanVerifier(Protocol):
    async def verify(self, token: str | None, remote_ip: str) -> bool: ...


class DisabledHumanVerifier:
    async def verify(self, token: str | None, remote_ip: str) -> bool:
        del token, remote_ip
        return True


class TurnstileHumanVerifier:
    def __init__(
        self,
        secret_key: str,
        *,
        client=None,
        timeout: float = 3.0,
    ) -> None:
        self._secret_key = secret_key
        self._client = client
        self._timeout = timeout

    async def verify(self, token: str | None, remote_ip: str) -> bool:
        if not token:
            return False
        data = {
            "secret": self._secret_key,
            "response": token,
            "remoteip": remote_ip,
        }
        try:
            if self._client is not None:
                response = await self._client.post(
                    TURNSTILE_VERIFY_URL, data=data, timeout=self._timeout
                )
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        TURNSTILE_VERIFY_URL, data=data, timeout=self._timeout
                    )
            payload = response.json()
            return isinstance(payload, dict) and payload.get("success") is True
        except (httpx.HTTPError, ValueError, TypeError):
            return False


def build_human_verifier(
    *, secret_key: str | None, client=None, timeout: float = 3.0
) -> HumanVerifier:
    if not secret_key:
        return DisabledHumanVerifier()
    return TurnstileHumanVerifier(secret_key, client=client, timeout=timeout)
