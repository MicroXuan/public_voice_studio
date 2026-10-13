"""Public API models shared by the service layers."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PublicModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class VoiceOption(PublicModel):
    short_name: str = Field(min_length=1)
    friendly_name: str = Field(min_length=1)
    local_name: str = Field(min_length=1)
    locale: str = Field(min_length=2)
    gender: str = Field(min_length=1)


class SynthesisRequest(PublicModel):
    text: str = Field(min_length=1, max_length=10_000)
    voice: str = Field(min_length=1, max_length=160)
    rate: int = Field(default=0, ge=-50, le=50)
    pitch: int = Field(default=0, ge=-50, le=50)
    volume: int = Field(default=0, ge=-50, le=50)
    turnstile_token: str | None = Field(default=None, max_length=2_048)

    @field_validator("text", "voice", mode="before")
    @classmethod
    def strip_required_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("turnstile_token", mode="before")
    @classmethod
    def normalize_optional_token(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class JobResponse(PublicModel):
    id: str = Field(min_length=1)
    state: JobState
    progress: int = Field(ge=0, le=100)
    message: str = Field(min_length=1, max_length=300)
    created_at: datetime
    audio_url: str | None = None
    download_url: str | None = None
