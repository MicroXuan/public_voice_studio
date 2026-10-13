from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from backend.app.coordinator import (
    QueueCapacityError,
    SynthesisCoordinator,
    UnknownVoiceError,
)
from backend.app.job_store import ActiveJobError, JobStore
from backend.app.models import JobState, SynthesisRequest, VoiceOption
from backend.app.quota import HourlyLimitError, InMemoryQuotaStore


NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
VOICE = VoiceOption(
    short_name="zh-CN-XiaoxiaoNeural",
    friendly_name="Xiaoxiao",
    local_name="晓晓",
    locale="zh-CN",
    gender="Female",
)


class FakeCatalog:
    async def get(self, short_name):
        return VOICE if short_name == VOICE.short_name else None


class BlockingSynthesizer:
    def __init__(self):
        self.release = asyncio.Event()
        self.started = 0
        self.finished = 0
        self.active = 0
        self.max_active = 0
        self.two_started = asyncio.Event()

    async def synthesize(self, request, output_path, *, on_progress=None):
        self.started += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        if self.started >= 2:
            self.two_started.set()
        if on_progress:
            await on_progress(40)
        try:
            await self.release.wait()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"mp3")
            self.finished += 1
        finally:
            self.active -= 1


def request(voice=VOICE.short_name):
    return SynthesisRequest(text="公共语音服务测试", voice=voice)


def coordinator(tmp_path, *, hourly_limit=100):
    synth = BlockingSynthesizer()
    quota = InMemoryQuotaStore(
        hourly_limit=hourly_limit,
        daily_character_limit=100_000,
    )
    jobs = JobStore(tmp_path, clock=lambda: NOW)
    service = SynthesisCoordinator(
        catalog=FakeCatalog(),
        quota=quota,
        jobs=jobs,
        synthesizer=synth,
        worker_count=2,
        queue_maxsize=8,
        clock=lambda: NOW,
    )
    return service, synth, quota, jobs


async def wait_for_state(jobs, job_id, state, timeout=2):
    async with asyncio.timeout(timeout):
        while (await jobs.get(job_id)).state is not state:
            await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_two_jobs_execute_and_next_eight_queue(tmp_path):
    service, synth, _, jobs = coordinator(tmp_path)
    await service.start()
    try:
        first = await service.submit("client-0", request())
        second = await service.submit("client-1", request())
        await synth.two_started.wait()
        queued = [
            await service.submit(f"client-{index}", request())
            for index in range(2, 10)
        ]

        with pytest.raises(QueueCapacityError):
            await service.submit("client-10", request())

        assert synth.max_active == 2
        assert (await jobs.get(first.id)).state is JobState.RUNNING
        assert (await jobs.get(second.id)).state is JobState.RUNNING
        states = [(await jobs.get(item.id)).state for item in queued]
        assert all(state is JobState.QUEUED for state in states)

        synth.release.set()
        await wait_for_state(jobs, queued[-1].id, JobState.COMPLETED)
        assert synth.max_active == 2
        assert synth.finished == 10
    finally:
        synth.release.set()
        await service.stop()


@pytest.mark.asyncio
async def test_same_client_duplicate_is_rejected_and_quota_refunded(tmp_path):
    service, synth, _, jobs = coordinator(tmp_path, hourly_limit=2)
    await service.start()
    try:
        first = await service.submit("same", request())
        with pytest.raises(ActiveJobError):
            await service.submit("same", request())

        synth.release.set()
        await wait_for_state(jobs, first.id, JobState.COMPLETED)
        replacement = await service.submit("same", request())
        await wait_for_state(jobs, replacement.id, JobState.COMPLETED)
    finally:
        synth.release.set()
        await service.stop()


@pytest.mark.asyncio
async def test_unknown_voice_is_rejected_before_quota_consumption(tmp_path):
    service, synth, _, jobs = coordinator(tmp_path, hourly_limit=1)
    await service.start()
    try:
        with pytest.raises(UnknownVoiceError):
            await service.submit("client", request("unknown"))

        accepted = await service.submit("client", request())
        synth.release.set()
        await wait_for_state(jobs, accepted.id, JobState.COMPLETED)
        with pytest.raises(HourlyLimitError):
            await service.submit("client", request())
    finally:
        synth.release.set()
        await service.stop()


@pytest.mark.asyncio
async def test_queue_rejection_refunds_quota_and_discards_active_slot(tmp_path):
    service, synth, _, jobs = coordinator(tmp_path, hourly_limit=1)
    await service.start()
    try:
        await service.submit("client-0", request())
        await service.submit("client-1", request())
        await synth.two_started.wait()
        queued = [
            await service.submit(f"client-{index}", request())
            for index in range(2, 10)
        ]

        with pytest.raises(QueueCapacityError):
            await service.submit("retry-client", request())

        synth.release.set()
        await wait_for_state(jobs, queued[-1].id, JobState.COMPLETED)
        retried = await service.submit("retry-client", request())
        await wait_for_state(jobs, retried.id, JobState.COMPLETED)
    finally:
        synth.release.set()
        await service.stop()
