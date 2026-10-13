"""Bounded synthesis admission and worker coordination."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from backend.app.job_store import JobRecord, JobStore
from backend.app.models import SynthesisRequest
from backend.app.quota import InMemoryQuotaStore, QuotaReservation
from backend.app.tts_service import SpeechSynthesizer, SynthesisError
from backend.app.voice_catalog import VoiceCatalog


class UnknownVoiceError(ValueError):
    pass


class QueueCapacityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _WorkItem:
    job: JobRecord
    request: SynthesisRequest
    reservation: QuotaReservation


class SynthesisCoordinator:
    def __init__(
        self,
        *,
        catalog: VoiceCatalog,
        quota: InMemoryQuotaStore,
        jobs: JobStore,
        synthesizer: SpeechSynthesizer,
        worker_count: int = 2,
        queue_maxsize: int = 8,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._catalog = catalog
        self._quota = quota
        self._jobs = jobs
        self._synthesizer = synthesizer
        self._worker_count = worker_count
        self._queue: asyncio.Queue[_WorkItem] = asyncio.Queue(maxsize=queue_maxsize)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._admission_lock = asyncio.Lock()
        self._workers: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        if self._workers:
            return
        self._workers = [
            asyncio.create_task(self._worker(), name=f"tts-worker-{index + 1}")
            for index in range(self._worker_count)
        ]

    async def stop(self) -> None:
        workers, self._workers = self._workers, []
        for worker in workers:
            worker.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)

        while True:
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            try:
                await self._jobs.discard_queued(item.job.id)
                await self._quota.refund(item.reservation)
            finally:
                self._queue.task_done()

    async def submit(self, client_key: str, request: SynthesisRequest) -> JobRecord:
        async with self._admission_lock:
            if await self._catalog.get(request.voice) is None:
                raise UnknownVoiceError("所选语音不存在，请刷新语音列表")

            snapshot = await self._quota.reserve(
                client_key, len(request.text), self._clock()
            )
            try:
                job = await self._jobs.create(client_key)
            except Exception:
                await self._quota.refund(snapshot.reservation)
                raise

            item = _WorkItem(job, request, snapshot.reservation)
            try:
                self._queue.put_nowait(item)
            except asyncio.QueueFull as exc:
                await self._jobs.discard_queued(job.id)
                await self._quota.refund(snapshot.reservation)
                raise QueueCapacityError("当前生成队列已满，请稍后重试") from exc
            return job

    async def _worker(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                await self._jobs.start(item.job.id)

                async def on_progress(value: int) -> None:
                    await self._jobs.update_progress(item.job.id, value)

                output_path = self._jobs.output_dir / f"{item.job.id}.mp3"
                await self._synthesizer.synthesize(
                    item.request,
                    output_path,
                    on_progress=on_progress,
                )
                await self._jobs.complete(item.job.id, output_path)
            except asyncio.CancelledError:
                await self._jobs.fail(item.job.id, "服务已重启，请重新提交")
                await self._quota.refund(item.reservation)
                raise
            except SynthesisError:
                await self._jobs.fail(item.job.id, "生成失败，请稍后重试")
                await self._quota.refund(item.reservation)
            except Exception:
                await self._jobs.fail(item.job.id, "生成失败，请稍后重试")
                await self._quota.refund(item.reservation)
            finally:
                self._queue.task_done()
