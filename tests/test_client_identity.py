from __future__ import annotations

import re

from starlette.requests import Request

from backend.app.client_identity import ClientIdentityResolver


def request_for(host: str, *, forwarded_for: str | None = None) -> Request:
    headers = []
    if forwarded_for:
        headers.append((b"x-forwarded-for", forwarded_for.encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "client": (host, 50000),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
        }
    )


def test_resolver_returns_deterministic_hmac_without_raw_address():
    resolver = ClientIdentityResolver(secret="fixed-secret")

    first = resolver.resolve(request_for("203.0.113.8"))
    second = resolver.resolve(request_for("203.0.113.8"))

    assert first == second
    assert "203.0.113.8" not in first
    assert re.fullmatch(r"[a-f0-9]{64}", first)


def test_resolver_uses_request_client_after_trusted_proxy_processing():
    resolver = ClientIdentityResolver(secret="fixed-secret")

    direct = resolver.resolve(request_for("198.51.100.24"))
    proxied = resolver.resolve(request_for("198.51.100.24", forwarded_for="192.0.2.99"))

    assert proxied == direct
    assert proxied != resolver.resolve(request_for("192.0.2.99"))


def test_random_process_secret_is_stable_for_one_resolver_only():
    request = request_for("203.0.113.9")
    resolver = ClientIdentityResolver()

    assert resolver.resolve(request) == resolver.resolve(request)
    assert resolver.resolve(request) != ClientIdentityResolver().resolve(request)


def test_missing_request_client_uses_non_identifying_fallback():
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
        }
    )

    identity = ClientIdentityResolver(secret="fixed-secret").resolve(request)

    assert re.fullmatch(r"[a-f0-9]{64}", identity)
