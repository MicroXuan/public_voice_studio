"""Concurrency-safe in-memory synthesis job state and file lifecycle."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.app.models import JobResponse, JobState


class ActiveJobError(RuntimeError):
    pass


class JobNotFoundError(LookupError):
    pass


@dataclass(slots=True)
class JobRecord:
    id: str
    client_key: str
    state: JobState
    progress: int
    message: str
    created_at: datetime
    updated_at: datetime
    output_path: Path | None = None

    def to_response(self) -> JobResponse:
        has_audio = self.state is JobState.COMPLETED and self.output_path is not None
        return JobResponse(
            id=self.id,
            state=self.state,
            progress=self.progress,
            message=self.message,
            created_at=self.created_at,
            audio_url=f"/api/jobs/{self.id}/audio" if has_audio else None,
            download_url=(
                f"/api/jobs/{self.id}/audio?download=1" if has_audio else None
            ),
        )


class JobStore:
    def __init__(
        self,
        output_dir: Path,
        *,
        retention_seconds: int = 3_600,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.output_dir = output_dir.resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._retention = timedelta(seconds=retention_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._jobs: dict[str, JobRecord] = {}
        self._active_by_client: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def create(self, client_key: str) -> JobRecord:
        async with self._lock:
            if client_key in self._active_by_client:
                raise ActiveJobError("请等待当前任务完成")
            now = self._clock()
            record = JobRecord(
                id=self._id_factory(),
                client_key=client_key,
                state=JobState.QUEUED,
                progress=0,
                message="任务已进入队列",
                created_at=now,
                updated_at=now,
            )
            self._jobs[record.id] = record
            self._active_by_client[client_key] = record.id
            return record

    async def get(self, job_id: str, *, client_key: str | None = None) -> JobRecord:
        async with self._lock:
            record = self._jobs.get(job_id)
            if record is None or (
                client_key is not None and record.client_key != client_key
            ):
                raise JobNotFoundError(job_id)
            return record

    async def start(self, job_id: str) -> JobRecord:
        async with self._lock:
            record = self._require(job_id)
            record.state = JobState.RUNNING
            record.progress = max(record.progress, 3)
            record.message = "正在生成语音"
            record.updated_at = self._clock()
            return record

    async def update_progress(self, job_id: str, progress: int) -> JobRecord:
        async with self._lock:
            record = self._require(job_id)
            if record.state not in {JobState.QUEUED, JobState.RUNNING}:
                return record
            record.progress = max(record.progress, min(95, progress))
            record.updated_at = self._clock()
            return record

    async def complete(self, job_id: str, output_path: Path) -> JobRecord:
        resolved = output_path.resolve()
        try:
            resolved.relative_to(self.output_dir)
        except ValueError as exc:
            raise ValueError("Audio path must be inside managed output") from exc

        async with self._lock:
            record = self._require(job_id)
            record.state = JobState.COMPLETED
            record.progress = 100
            record.message = "语音已生成"
            record.output_path = resolved
            record.updated_at = self._clock()
            self._release(record)
            return record

    async def fail(self, job_id: str, message: str) -> JobRecord:
        async with self._lock:
            record = self._require(job_id)
            record.state = JobState.FAILED
            record.message = message
            record.output_path = None
            record.updated_at = self._clock()
            self._release(record)
            return record

    async def discard_queued(self, job_id: str) -> None:
        async with self._lock:
            record = self._require(job_id)
            if record.state is not JobState.QUEUED:
                raise ValueError("Only queued jobs can be discarded")
            self._release(record)
            self._jobs.pop(job_id, None)

    async def cleanup_expired(self) -> int:
        now = self._clock()
        expired_count = 0
        async with self._lock:
            for job_id, record in tuple(self._jobs.items()):
                age = now - record.updated_at
                if record.state in {JobState.COMPLETED, JobState.FAILED} and age > self._retention:
                    if record.output_path is not None:
                        self._safe_unlink(record.output_path)
                    record.state = JobState.EXPIRED
                    record.progress = 100
                    record.message = "音频已过期，请重新生成"
                    record.output_path = None
                    record.updated_at = now
                    expired_count += 1
                elif record.state is JobState.EXPIRED and age > self._retention:
                    self._jobs.pop(job_id, None)

            cutoff = now.timestamp() - self._retention.total_seconds()
            for part in self.output_dir.glob("*.mp3.part"):
                try:
                    if part.is_file() and part.stat().st_mtime < cutoff:
                        self._safe_unlink(part)
                except FileNotFoundError:
                    continue
        return expired_count

    def _require(self, job_id: str) -> JobRecord:
        record = self._jobs.get(job_id)
        if record is None:
            raise JobNotFoundError(job_id)
        return record

    def _release(self, record: JobRecord) -> None:
        if self._active_by_client.get(record.client_key) == record.id:
            self._active_by_client.pop(record.client_key, None)

    def _safe_unlink(self, path: Path) -> None:
        resolved = path.resolve()
        try:
            resolved.relative_to(self.output_dir)
        except ValueError:
            return
        resolved.unlink(missing_ok=True)
