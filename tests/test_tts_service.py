from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.app.models import SynthesisRequest
from backend.app.tts_service import (
    EdgeTTSService,
    SynthesisEmptyAudioError,
    SynthesisStorageError,
    SynthesisUnavailableError,
)


class FakeCommunicate:
    def __init__(self, chunks, *, error: Exception | None = None):
        self.chunks = chunks
        self.error = error

    async def stream(self):
        for chunk in self.chunks:
            await asyncio.sleep(0)
            yield chunk
        if self.error:
            raise self.error


def request(**overrides):
    values = {
        "text": "你好，欢迎使用小宣 Voice Studio。",
        "voice": "zh-CN-XiaoxiaoNeural",
        "rate": 12,
        "pitch": -8,
        "volume": 5,
    }
    values.update(overrides)
    return SynthesisRequest(**values)


@pytest.mark.asyncio
async def test_streams_audio_in_order_and_atomically_renames(tmp_path):
    captured = {}

    def factory(**kwargs):
        captured.update(kwargs)
        return FakeCommunicate(
            [
                {"type": "audio", "data": b"first-"},
                {"type": "WordBoundary", "offset": 1},
                {"type": "audio", "data": b"second"},
            ]
        )

    output = tmp_path / "job.mp3"
    progress = []
    await EdgeTTSService(communicator_factory=factory).synthesize(
        request(), output, on_progress=progress.append
    )

    assert captured == {
        "text": "你好，欢迎使用小宣 Voice Studio。",
        "voice": "zh-CN-XiaoxiaoNeural",
        "rate": "+12%",
        "pitch": "-8Hz",
        "volume": "+5%",
    }
    assert output.read_bytes() == b"first-second"
    assert not (tmp_path / "job.mp3.part").exists()
    assert progress == sorted(progress)
    assert all(1 <= value <= 95 for value in progress)


@pytest.mark.asyncio
async def test_signed_zero_controls_are_explicit(tmp_path):
    captured = {}

    def factory(**kwargs):
        captured.update(kwargs)
        return FakeCommunicate([{"type": "audio", "data": b"mp3"}])

    await EdgeTTSService(communicator_factory=factory).synthesize(
        request(rate=0, pitch=0, volume=0), tmp_path / "zero.mp3"
    )

    assert captured["rate"] == "+0%"
    assert captured["pitch"] == "+0Hz"
    assert captured["volume"] == "+0%"


@pytest.mark.asyncio
async def test_empty_audio_is_rejected_and_partial_file_removed(tmp_path):
    service = EdgeTTSService(
        communicator_factory=lambda **_: FakeCommunicate(
            [{"type": "WordBoundary", "offset": 1}]
        )
    )
    output = tmp_path / "empty.mp3"

    with pytest.raises(SynthesisEmptyAudioError):
        await service.synthesize(request(), output)

    assert not output.exists()
    assert not (tmp_path / "empty.mp3.part").exists()


@pytest.mark.asyncio
async def test_network_failure_is_mapped_without_upstream_details(tmp_path):
    service = EdgeTTSService(
        communicator_factory=lambda **_: FakeCommunicate(
            [], error=OSError("secret upstream hostname")
        )
    )

    with pytest.raises(SynthesisUnavailableError) as caught:
        await service.synthesize(request(), tmp_path / "network.mp3")

    assert "secret upstream hostname" not in str(caught.value)
    assert not (tmp_path / "network.mp3.part").exists()


@pytest.mark.asyncio
async def test_cancellation_removes_partial_file_and_propagates(tmp_path):
    started = asyncio.Event()

    class BlockingCommunicate:
        async def stream(self):
            yield {"type": "audio", "data": b"partial"}
            started.set()
            await asyncio.Event().wait()

    output = tmp_path / "cancel.mp3"
    task = asyncio.create_task(
        EdgeTTSService(communicator_factory=lambda **_: BlockingCommunicate()).synthesize(
            request(), output
        )
    )
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert not output.exists()
    assert not (tmp_path / "cancel.mp3.part").exists()


@pytest.mark.asyncio
async def test_filesystem_write_failure_is_mapped(monkeypatch, tmp_path):
    service = EdgeTTSService(
        communicator_factory=lambda **_: FakeCommunicate(
            [{"type": "audio", "data": b"mp3"}]
        )
    )

    def fail_open(*args, **kwargs):
        raise OSError("disk detail")

    monkeypatch.setattr(Path, "open", fail_open)

    with pytest.raises(SynthesisStorageError) as caught:
        await service.synthesize(request(), tmp_path / "disk.mp3")
    assert "disk detail" not in str(caught.value)
