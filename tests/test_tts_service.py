from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.app import tts_service
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


def test_long_text_splits_at_sentence_boundaries_without_changing_text():
    source = "".join(f"第{i}段内容" + "甲" * 45 + "。" for i in range(20))

    parts = tts_service.split_for_parallel_synthesis(source)

    assert len(parts) == 4
    assert "".join(parts) == source
    assert all(part.endswith("。") for part in parts)
    assert max(map(len, parts)) - min(map(len, parts)) <= 60


def test_text_without_safe_breaks_stays_in_one_piece():
    source = "甲" * 1_000
    assert tts_service.split_for_parallel_synthesis(source) == [source]


@pytest.mark.asyncio
async def test_long_parts_run_concurrently_but_audio_is_joined_in_text_order(tmp_path):
    source = "".join(marker + "甲" * 240 + "。" for marker in "ABCD")
    started = 0
    all_started = asyncio.Event()

    class DelayedCommunicate:
        def __init__(self, text):
            self.text = text

        async def stream(self):
            nonlocal started
            started += 1
            if started == 4:
                all_started.set()
            await all_started.wait()
            await asyncio.sleep((4 - "ABCD".index(self.text[0])) * 0.001)
            yield {"type": "audio", "data": self.text[0].encode()}

    service = EdgeTTSService(communicator_factory=lambda **kwargs: DelayedCommunicate(kwargs["text"]))
    output = tmp_path / "ordered.mp3"
    progress = []

    async with asyncio.timeout(1):
        await service.synthesize(request(text=source), output, on_progress=progress.append)

    assert output.read_bytes() == b"ABCD"
    assert progress == sorted(progress)
    assert progress[-1] == 95


@pytest.mark.asyncio
async def test_parallel_failure_cancels_other_parts_and_removes_partial_file(tmp_path):
    source = "".join(marker + "甲" * 240 + "。" for marker in "ABCD")
    cancelled = asyncio.Event()

    class FailingCommunicate:
        def __init__(self, text):
            self.text = text

        async def stream(self):
            if self.text.startswith("A"):
                await asyncio.sleep(0)
                raise OSError("upstream detail")
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
            yield {"type": "audio", "data": b"unreachable"}

    service = EdgeTTSService(communicator_factory=lambda **kwargs: FailingCommunicate(kwargs["text"]))
    output = tmp_path / "failed.mp3"

    async with asyncio.timeout(1):
        with pytest.raises(SynthesisUnavailableError):
            await service.synthesize(request(text=source), output)

    assert cancelled.is_set()
    assert not output.exists()
    assert not output.with_suffix(".mp3.part").exists()


@pytest.mark.asyncio
async def test_parallel_stream_limit_is_shared_between_jobs(tmp_path):
    source = "".join(marker + "甲" * 240 + "。" for marker in "ABCD")
    active = 0
    maximum_active = 0
    four_started = asyncio.Event()
    release = asyncio.Event()

    class BlockingCommunicate:
        def __init__(self, text):
            self.text = text

        async def stream(self):
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            if active == 4:
                four_started.set()
            try:
                await release.wait()
                yield {"type": "audio", "data": self.text[0].encode()}
            finally:
                active -= 1

    service = EdgeTTSService(communicator_factory=lambda **kwargs: BlockingCommunicate(kwargs["text"]))
    first = tmp_path / "first.mp3"
    second = tmp_path / "second.mp3"

    async with asyncio.timeout(1):
        jobs = [
            asyncio.create_task(service.synthesize(request(text=source), output))
            for output in (first, second)
        ]
        await four_started.wait()
        await asyncio.sleep(0)
        assert maximum_active == 4
        release.set()
        await asyncio.gather(*jobs)

    assert first.read_bytes() == b"ABCD"
    assert second.read_bytes() == b"ABCD"
    assert maximum_active == 4
