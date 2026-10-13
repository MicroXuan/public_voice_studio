from __future__ import annotations

from dataclasses import fields

from backend.app.config import Settings


def test_settings_defaults_are_safe_for_public_free_tier(monkeypatch):
    for name in (
        "MAX_TEXT_CHARS",
        "HOURLY_REQUEST_LIMIT",
        "DAILY_CHARACTER_LIMIT",
        "SYNTHESIS_WORKERS",
        "QUEUE_MAXSIZE",
        "AUDIO_RETENTION_SECONDS",
        "CORS_ORIGINS",
        "TURNSTILE_SECRET_KEY",
        "TURNSTILE_SITE_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings.from_env()

    assert settings.max_text_chars == 5_000
    assert settings.hourly_request_limit == 10
    assert settings.daily_character_limit == 50_000
    assert settings.synthesis_workers == 2
    assert settings.queue_maxsize == 8
    assert settings.audio_retention_seconds == 3_600
    assert "http://localhost:5173" in settings.cors_origins
    assert "http://127.0.0.1:5173" in settings.cors_origins
    assert settings.turnstile_secret_key is None
    assert settings.turnstile_site_key is None


def test_settings_parse_overrides_and_normalize_origins(monkeypatch):
    monkeypatch.setenv("MAX_TEXT_CHARS", "4321")
    monkeypatch.setenv("HOURLY_REQUEST_LIMIT", "7")
    monkeypatch.setenv("DAILY_CHARACTER_LIMIT", "12000")
    monkeypatch.setenv("SYNTHESIS_WORKERS", "3")
    monkeypatch.setenv("QUEUE_MAXSIZE", "4")
    monkeypatch.setenv("AUDIO_RETENTION_SECONDS", "900")
    monkeypatch.setenv(
        "CORS_ORIGINS",
        " https://voice.example.com, http://localhost:5173,https://voice.example.com ,, ",
    )
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "secret-value")
    monkeypatch.setenv("TURNSTILE_SITE_KEY", "site-value")

    settings = Settings.from_env()

    assert settings.max_text_chars == 4321
    assert settings.hourly_request_limit == 7
    assert settings.daily_character_limit == 12000
    assert settings.synthesis_workers == 3
    assert settings.queue_maxsize == 4
    assert settings.audio_retention_seconds == 900
    assert settings.cors_origins == (
        "https://voice.example.com",
        "http://localhost:5173",
    )
    assert settings.turnstile_secret_key == "secret-value"
    assert settings.turnstile_site_key == "site-value"


def test_secret_fields_are_hidden_from_repr(monkeypatch):
    monkeypatch.setenv("CLIENT_IDENTITY_SECRET", "identity-secret")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "turnstile-secret")

    rendered = repr(Settings.from_env())

    assert "identity-secret" not in rendered
    assert "turnstile-secret" not in rendered
    hidden = {
        field.name
        for field in fields(Settings)
        if field.name in {"client_identity_secret", "turnstile_secret_key"}
        and field.repr is False
    }
    assert hidden == {"client_identity_secret", "turnstile_secret_key"}


def test_deployment_environment_names_take_precedence(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://official.example")
    monkeypatch.setenv("CORS_ORIGINS", "https://legacy.example")
    monkeypatch.setenv("IP_HASH_SECRET", "deployment-secret")
    monkeypatch.setenv("CLIENT_IDENTITY_SECRET", "legacy-secret")

    settings = Settings.from_env()

    assert settings.cors_origins == ("https://official.example",)
    assert settings.client_identity_secret == "deployment-secret"
