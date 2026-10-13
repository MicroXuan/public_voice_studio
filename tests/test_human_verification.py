from __future__ import annotations

import httpx
import pytest

from backend.app.human_verification import (
    DisabledHumanVerifier,
    TurnstileHumanVerifier,
    build_human_verifier,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return FakeResponse(self.payload)


@pytest.mark.asyncio
async def test_disabled_verifier_accepts_without_a_token():
    verifier = build_human_verifier(secret_key=None)

    assert isinstance(verifier, DisabledHumanVerifier)
    assert await verifier.verify(None, "203.0.113.1") is True


@pytest.mark.asyncio
async def test_turnstile_posts_only_required_verification_fields():
    client = FakeClient({"success": True, "hostname": "voice.example.com"})
    verifier = TurnstileHumanVerifier("private-secret", client=client, timeout=2.5)

    assert await verifier.verify("browser-token", "203.0.113.8") is True
    assert client.calls == [
        (
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            {
                "data": {
                    "secret": "private-secret",
                    "response": "browser-token",
                    "remoteip": "203.0.113.8",
                },
                "timeout": 2.5,
            },
        )
    ]


@pytest.mark.asyncio
async def test_missing_token_and_provider_timeout_fail_closed():
    timeout = httpx.ReadTimeout("provider detail")
    verifier = TurnstileHumanVerifier(
        "private-secret", client=FakeClient(error=timeout), timeout=1.0
    )

    assert await verifier.verify(None, "203.0.113.8") is False
    assert await verifier.verify("token", "203.0.113.8") is False


@pytest.mark.asyncio
async def test_provider_error_details_are_not_exposed():
    client = FakeClient({"success": False, "error-codes": ["secret-input-response"]})
    verifier = TurnstileHumanVerifier("private-secret", client=client)

    assert await verifier.verify("bad-token", "203.0.113.8") is False
    assert not hasattr(verifier, "last_error")
