"""Dynamic, provider-neutral catalog of every voice exposed by edge-tts."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Protocol

import edge_tts

from backend.app.models import VoiceOption


class VoiceCatalogUnavailableError(RuntimeError):
    """Raised when no usable voice catalog has ever been loaded."""


class VoiceProvider(Protocol):
    async def list_voices(self) -> list[dict[str, object]]: ...


class EdgeVoiceProvider:
    async def list_voices(self) -> list[dict[str, object]]:
        return await edge_tts.list_voices()


def _read(item: dict[str, object], *names: str) -> str:
    for name in names:
        value = item.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ValueError(f"Voice entry is missing {names[0]}")


def _normalize(item: dict[str, object]) -> VoiceOption:
    return VoiceOption(
        short_name=_read(item, "ShortName", "short_name"),
        friendly_name=_read(item, "FriendlyName", "friendly_name"),
        local_name=_read(item, "LocalName", "local_name"),
        locale=_read(item, "Locale", "locale"),
        gender=_read(item, "Gender", "gender"),
    )


class VoiceCatalog:
    def __init__(
        self,
        provider: VoiceProvider,
        *,
        ttl_seconds: float = 3_600,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._provider = provider
        self._ttl_seconds = ttl_seconds
        self._clock = clock or time.monotonic
        self._lock = asyncio.Lock()
        self._cached: tuple[VoiceOption, ...] | None = None
        self._expires_at = 0.0

    async def list(self, force_refresh: bool = False) -> tuple[VoiceOption, ...]:
        now = self._clock()
        if not force_refresh and self._cached is not None and now < self._expires_at:
            return self._cached

        async with self._lock:
            now = self._clock()
            if not force_refresh and self._cached is not None and now < self._expires_at:
                return self._cached
            try:
                raw = await self._provider.list_voices()
                normalized = tuple(
                    sorted(
                        (_normalize(item) for item in raw),
                        key=lambda voice: (
                            voice.locale.casefold(),
                            voice.local_name.casefold(),
                            voice.short_name.casefold(),
                        ),
                    )
                )
                if not normalized:
                    raise ValueError("Voice provider returned an empty catalog")
            except Exception as exc:
                if self._cached is not None:
                    return self._cached
                raise VoiceCatalogUnavailableError("语音目录暂时不可用") from exc

            self._cached = normalized
            self._expires_at = now + self._ttl_seconds
            return normalized

    async def get(self, short_name: str) -> VoiceOption | None:
        return next(
            (voice for voice in await self.list() if voice.short_name == short_name),
            None,
        )
