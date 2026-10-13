"""Environment-backed application settings."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
)


def _optional(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = int(raw)
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _origins_from_env() -> tuple[str, ...]:
    raw = os.getenv("CORS_ORIGINS")
    if raw is None:
        return DEFAULT_CORS_ORIGINS
    return tuple(dict.fromkeys(item.strip().rstrip("/") for item in raw.split(",") if item.strip()))


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable runtime settings with conservative public-service defaults."""

    app_name: str = "小宣 Voice Studio"
    environment: str = "development"
    max_text_chars: int = 10_000
    max_request_bytes: int = 64_000
    hourly_request_limit: int = 10
    daily_character_limit: int = 30_000
    synthesis_workers: int = 2
    queue_maxsize: int = 8
    audio_retention_seconds: int = 3_600
    voice_cache_ttl_seconds: int = 3_600
    output_dir: Path = Path("runtime/audio")
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    client_identity_secret: str | None = field(default=None, repr=False)
    turnstile_secret_key: str | None = field(default=None, repr=False)
    turnstile_site_key: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            app_name=os.getenv("APP_NAME", "小宣 Voice Studio").strip() or "小宣 Voice Studio",
            environment=os.getenv("ENVIRONMENT", "development").strip() or "development",
            max_text_chars=_positive_int("MAX_TEXT_CHARS", 10_000),
            max_request_bytes=_positive_int("MAX_REQUEST_BYTES", 64_000),
            hourly_request_limit=_positive_int("HOURLY_REQUEST_LIMIT", 10),
            daily_character_limit=_positive_int("DAILY_CHARACTER_LIMIT", 30_000),
            synthesis_workers=_positive_int("SYNTHESIS_WORKERS", 2),
            queue_maxsize=_positive_int("QUEUE_MAXSIZE", 8),
            audio_retention_seconds=_positive_int("AUDIO_RETENTION_SECONDS", 3_600),
            voice_cache_ttl_seconds=_positive_int("VOICE_CACHE_TTL_SECONDS", 3_600),
            output_dir=Path(os.getenv("OUTPUT_DIR", "runtime/audio")),
            cors_origins=_origins_from_env(),
            client_identity_secret=_optional("CLIENT_IDENTITY_SECRET"),
            turnstile_secret_key=_optional("TURNSTILE_SECRET_KEY"),
            turnstile_site_key=_optional("TURNSTILE_SITE_KEY"),
        )
