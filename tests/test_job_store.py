from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from backend.app.job_store import ActiveJobError, JobNotFoundError, JobStore
from backend.app.models import JobState


NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_only_one_active_job_per_client_but_different_clients_can_run(tmp_path):
    store = JobStore(tmp_path, clock=lambda: NOW)
    first = await store.create("hash-a")
    second = await store.create("hash-b")

    with pytest.raises(ActiveJobError):
        await store.create("hash-a")

    assert first.client_key == "hash-a"
    assert second.client_key == "hash-b"
    assert first.state is JobState.QUEUED


@pytest.mark.asyncio
async def test_concurrent_create_is_atomic_for_one_client(tmp_path):
    store = JobStore(tmp_path, clock=lambda: NOW)
    results = await asyncio.gather(
        *(store.create("same-hash") for _ in range(10)),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, ActiveJobError) for result in results) == 9


@pytest.mark.asyncio
async def test_progress_is_monotonic_and_capped_until_completion(tmp_path):
    store = JobStore(tmp_path, clock=lambda: NOW)
    job = await store.create("hash-a")
    await store.start(job.id)

    assert (await store.update_progress(job.id, 72)).progress == 72
    assert (await store.update_progress(job.id, 30)).progress == 72
    assert (await store.update_progress(job.id, 100)).progress == 95

    audio = tmp_path / f"{job.id}.mp3"
    audio.write_bytes(b"audio")
    completed = await store.complete(job.id, audio)
    assert completed.state is JobState.COMPLETED
    assert completed.progress == 100


@pytest.mark.asyncio
async def test_terminal_and_discarded_jobs_release_the_client_slot(tmp_path):
    store = JobStore(tmp_path, clock=lambda: NOW)
    failed = await store.create("hash-a")
    await store.fail(failed.id, "生成失败，请稍后重试")
    assert (await store.create("hash-a")).state is JobState.QUEUED

    queued = await store.create("hash-b")
    await store.discard_queued(queued.id)
    with pytest.raises(JobNotFoundError):
        await store.get(queued.id)
    assert (await store.create("hash-b")).state is JobState.QUEUED


@pytest.mark.asyncio
async def test_get_can_enforce_client_ownership(tmp_path):
    store = JobStore(tmp_path, clock=lambda: NOW)
    job = await store.create("hash-a")

    assert (await store.get(job.id, client_key="hash-a")).id == job.id
    with pytest.raises(JobNotFoundError):
        await store.get(job.id, client_key="hash-b")


@pytest.mark.asyncio
async def test_completion_rejects_paths_outside_managed_output(tmp_path):
    store = JobStore(tmp_path / "managed", clock=lambda: NOW)
    job = await store.create("hash-a")
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"do not delete")

    with pytest.raises(ValueError, match="managed output"):
        await store.complete(job.id, outside)

    assert outside.exists()


@pytest.mark.asyncio
async def test_cleanup_expires_terminal_job_and_deletes_only_managed_audio(tmp_path):
    now = [NOW]
    managed = tmp_path / "managed"
    store = JobStore(managed, retention_seconds=3_600, clock=lambda: now[0])
    job = await store.create("hash-a")
    audio = managed / f"{job.id}.mp3"
    audio.write_bytes(b"audio")
    await store.complete(job.id, audio)
    now[0] += timedelta(seconds=3_601)

    expired_count = await store.cleanup_expired()

    assert expired_count == 1
    assert not audio.exists()
    expired = await store.get(job.id, client_key="hash-a")
    assert expired.state is JobState.EXPIRED
    assert expired.output_path is None


@pytest.mark.asyncio
async def test_cleanup_removes_old_orphan_part_files_but_keeps_recent_files(tmp_path):
    now = [NOW]
    store = JobStore(tmp_path, retention_seconds=3_600, clock=lambda: now[0])
    old_part = tmp_path / "old.mp3.part"
    recent_part = tmp_path / "recent.mp3.part"
    unrelated = tmp_path / "notes.txt"
    for path in (old_part, recent_part, unrelated):
        path.write_text("keep safe")
    old_timestamp = (NOW - timedelta(hours=2)).timestamp()
    recent_timestamp = (NOW - timedelta(minutes=5)).timestamp()
    os.utime(old_part, (old_timestamp, old_timestamp))
    os.utime(recent_part, (recent_timestamp, recent_timestamp))

    await store.cleanup_expired()

    assert not old_part.exists()
    assert recent_part.exists()
    assert unrelated.exists()
