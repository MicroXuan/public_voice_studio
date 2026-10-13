from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.coordinator import QueueCapacityError, UnknownVoiceError
from backend.app.human_verification import DisabledHumanVerifier
from backend.app.job_store import ActiveJobError, JobStore
from backend.app.main import create_app
from backend.app.models import JobState, VoiceOption
from backend.app.quota import DailyCharacterLimitError, HourlyLimitError
from backend.app.voice_catalog import VoiceCatalogUnavailableError


NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
VOICE = VoiceOption(
    short_name="zh-CN-XiaoxiaoNeural",
    friendly_name="Xiaoxiao",
    local_name="晓晓",
    locale="zh-CN",
    gender="Female",
)


class FixedIdentity:
    def resolve(self, request):
        return "hashed-client"


class FakeCatalog:
    def __init__(self, *, error=None):
        self.error = error

    async def list(self, force_refresh=False):
        if self.error:
            raise self.error
        return (VOICE,)


class FakeCoordinator:
    def __init__(self, jobs, *, error=None):
        self.jobs = jobs
        self.error = error
        self.started = False
        self.stopped = False

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def submit(self, client_key, request):
        if self.error:
            raise self.error
        return await self.jobs.create(client_key)


class RejectingVerifier:
    async def verify(self, token, remote_ip):
        return False


def app_bundle(tmp_path, *, catalog=None, coordinator_error=None, verifier=None):
    settings = replace(
        Settings(),
        output_dir=tmp_path,
        cors_origins=("https://voice.example.com", "http://localhost:5173"),
    )
    jobs = JobStore(tmp_path, clock=lambda: NOW)
    coordinator = FakeCoordinator(jobs, error=coordinator_error)
    app = create_app(
        settings=settings,
        catalog=catalog or FakeCatalog(),
        jobs=jobs,
        coordinator=coordinator,
        identity=FixedIdentity(),
        verifier=verifier or DisabledHumanVerifier(),
    )
    return app, jobs, coordinator


def payload(**overrides):
    value = {"text": "你好，世界", "voice": VOICE.short_name}
    value.update(overrides)
    return value


def test_health_is_lightweight_and_lifespan_starts_and_stops_workers(tmp_path):
    app, _, coordinator = app_bundle(tmp_path)

    with TestClient(app) as client:
        response = client.get("/healthz")
        assert coordinator.started is True
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "小宣 Voice Studio"}

    assert coordinator.stopped is True


def test_voice_route_returns_complete_public_schema(tmp_path):
    app, _, _ = app_bundle(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/voices")

    assert response.status_code == 200
    assert response.json() == {"count": 1, "voices": [VOICE.model_dump()]}


def test_voice_route_maps_first_upstream_failure_to_public_503(tmp_path):
    error = VoiceCatalogUnavailableError("private provider failure")
    app, _, _ = app_bundle(tmp_path, catalog=FakeCatalog(error=error))
    with TestClient(app) as client:
        response = client.get("/api/voices")

    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "voice_catalog_unavailable", "message": "语音列表暂时不可用，请稍后重试"}
    }
    assert "private provider failure" not in response.text


def test_job_creation_returns_202_location_and_pollable_state(tmp_path):
    app, _, _ = app_bundle(tmp_path)
    with TestClient(app) as client:
        created = client.post("/api/jobs", json=payload())
        polled = client.get(created.headers["location"])

    assert created.status_code == 202
    body = created.json()
    assert created.headers["location"] == f"/api/jobs/{body['id']}"
    assert body["state"] == "queued"
    assert polled.status_code == 200
    assert polled.json()["id"] == body["id"]


def test_audio_supports_inline_and_download_dispositions(tmp_path):
    app, jobs, _ = app_bundle(tmp_path)
    with TestClient(app) as client:
        created = client.post("/api/jobs", json=payload()).json()
        audio_path = tmp_path / f"{created['id']}.mp3"
        audio_path.write_bytes(b"fake-mp3")
        import asyncio

        asyncio.run(jobs.complete(created["id"], audio_path))
        inline = client.get(f"/api/jobs/{created['id']}/audio")
        download = client.get(f"/api/jobs/{created['id']}/audio?download=1")

    assert inline.status_code == 200
    assert inline.headers["content-type"] == "audio/mpeg"
    assert inline.content == b"fake-mp3"
    assert "attachment" not in inline.headers.get("content-disposition", "")
    assert "attachment" in download.headers["content-disposition"]
    assert "xiaoxuan-voice.mp3" in download.headers["content-disposition"]


def test_missing_restarted_and_expired_jobs_have_clear_messages(tmp_path):
    app, jobs, _ = app_bundle(tmp_path)
    with TestClient(app) as client:
        missing = client.get("/api/jobs/missing")
        created = client.post("/api/jobs", json=payload()).json()
        import asyncio

        asyncio.run(jobs.fail(created["id"], "failed"))
        record = asyncio.run(jobs.get(created["id"]))
        record.state = JobState.EXPIRED
        expired = client.get(f"/api/jobs/{created['id']}")

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "job_not_found"
    assert "重启" in missing.json()["error"]["message"]
    assert expired.status_code == 410
    assert expired.json()["error"]["code"] == "job_expired"


@pytest.mark.parametrize(
    ("error", "status", "code", "retry_after"),
    [
        (UnknownVoiceError("detail"), 422, "voice_not_found", None),
        (ActiveJobError("detail"), 409, "active_job_exists", None),
        (HourlyLimitError("detail", retry_after_seconds=91), 429, "hourly_limit", "91"),
        (
            DailyCharacterLimitError("detail", retry_after_seconds=123),
            429,
            "daily_character_limit",
            "123",
        ),
        (QueueCapacityError("detail"), 503, "queue_full", "30"),
    ],
)
def test_creation_errors_have_stable_public_codes(
    tmp_path, error, status, code, retry_after
):
    app, _, _ = app_bundle(tmp_path, coordinator_error=error)
    with TestClient(app) as client:
        response = client.post("/api/jobs", json=payload())

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "detail" not in response.text
    assert response.headers.get("retry-after") == retry_after


def test_failed_human_verification_is_forbidden(tmp_path):
    app, _, _ = app_bundle(tmp_path, verifier=RejectingVerifier())
    with TestClient(app) as client:
        response = client.post("/api/jobs", json=payload())

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "human_verification_failed"
