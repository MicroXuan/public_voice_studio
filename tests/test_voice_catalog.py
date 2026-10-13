from __future__ import annotations

import asyncio

import pytest

from backend.app.voice_catalog import (
    EdgeVoiceProvider,
    VoiceCatalog,
    VoiceCatalogUnavailableError,
)


RAW_VOICES = [
    {
        "ShortName": "ja-JP-NanamiNeural",
        "FriendlyName": "Nanami - Japanese",
        "LocalName": "七海",
        "Locale": "ja-JP",
        "Gender": "Female",
    },
    {
        "ShortName": "zh-CN-XiaoxiaoNeural",
        "FriendlyName": "Xiaoxiao - Chinese",
        "LocalName": "晓晓",
        "Locale": "zh-CN",
        "Gender": "Female",
    },
    {
        "ShortName": "en-US-GuyNeural",
        "FriendlyName": "Guy - English",
        "LocalName": "Guy",
        "Locale": "en-US",
        "Gender": "Male",
    },
]


class FakeProvider:
    def __init__(self, values=None):
        self.values = list(values or RAW_VOICES)
        self.calls = 0
        self.error: Exception | None = None
        self.gate: asyncio.Event | None = None

    async def list_voices(self):
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        return list(self.values)


@pytest.mark.asyncio
async def test_catalog_preserves_and_normalizes_every_upstream_voice():
    catalog = VoiceCatalog(FakeProvider())

    voices = await catalog.list()

    assert len(voices) == len(RAW_VOICES)
    assert [voice.short_name for voice in voices] == [
        "en-US-GuyNeural",
        "ja-JP-NanamiNeural",
        "zh-CN-XiaoxiaoNeural",
    ]
    xiaoxiao = voices[-1]
    assert xiaoxiao.friendly_name == "Xiaoxiao - Chinese"
    assert xiaoxiao.local_name == "晓晓"
    assert xiaoxiao.locale == "zh-CN"
    assert xiaoxiao.gender == "Female"


@pytest.mark.asyncio
async def test_catalog_accepts_snake_case_key_variants_and_gets_by_short_name():
    provider = FakeProvider(
        [
            {
                "short_name": "en-GB-SoniaNeural",
                "friendly_name": "Sonia - English",
                "local_name": "Sonia",
                "locale": "en-GB",
                "gender": "Female",
            }
        ]
    )
    catalog = VoiceCatalog(provider)

    voice = await catalog.get("en-GB-SoniaNeural")

    assert voice is not None
    assert voice.local_name == "Sonia"
    assert await catalog.get("missing") is None


@pytest.mark.asyncio
async def test_edge_provider_delegates_to_edge_tts(monkeypatch):
    calls = 0

    async def fake_list_voices():
        nonlocal calls
        calls += 1
        return RAW_VOICES

    monkeypatch.setattr("edge_tts.list_voices", fake_list_voices)

    assert await EdgeVoiceProvider().list_voices() == RAW_VOICES
    assert calls == 1


@pytest.mark.asyncio
async def test_concurrent_first_load_calls_provider_once():
    provider = FakeProvider()
    provider.gate = asyncio.Event()
    catalog = VoiceCatalog(provider)

    requests = [asyncio.create_task(catalog.list()) for _ in range(6)]
    await asyncio.sleep(0)

    assert provider.calls == 1
    provider.gate.set()
    results = await asyncio.gather(*requests)
    assert all(result == results[0] for result in results)
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_successful_catalog_is_cached_for_configured_ttl():
    now = [100.0]
    provider = FakeProvider()
    catalog = VoiceCatalog(provider, ttl_seconds=3_600, clock=lambda: now[0])

    first = await catalog.list()
    now[0] = 3_699.9
    second = await catalog.list()

    assert second is first
    assert provider.calls == 1

    now[0] = 3_700.1
    await catalog.list()
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_refresh_failure_returns_last_good_catalog():
    now = [0.0]
    provider = FakeProvider()
    catalog = VoiceCatalog(provider, ttl_seconds=10, clock=lambda: now[0])
    first = await catalog.list()
    provider.error = OSError("upstream unavailable")
    now[0] = 11

    assert await catalog.list() is first
    assert await catalog.list(force_refresh=True) is first
    assert provider.calls == 3


@pytest.mark.asyncio
async def test_first_load_failure_has_public_catalog_error():
    provider = FakeProvider()
    provider.error = OSError("private upstream detail")

    with pytest.raises(VoiceCatalogUnavailableError, match="语音目录暂时不可用") as caught:
        await VoiceCatalog(provider).list()

    assert "private upstream detail" not in str(caught.value)
