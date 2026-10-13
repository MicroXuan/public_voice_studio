from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.config import Settings
from tests.test_api import app_bundle, payload


def test_cors_allows_only_configured_origins_and_preflight(tmp_path):
    app, _, _ = app_bundle(tmp_path)
    with TestClient(app) as client:
        allowed = client.get(
            "/healthz", headers={"Origin": "https://voice.example.com"}
        )
        blocked = client.get(
            "/healthz", headers={"Origin": "https://attacker.example"}
        )
        preflight = client.options(
            "/api/jobs",
            headers={
                "Origin": "https://voice.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        rejected_preflight = client.options(
            "/api/jobs",
            headers={
                "Origin": "https://attacker.example",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert allowed.headers["access-control-allow-origin"] == "https://voice.example.com"
    assert "access-control-allow-origin" not in blocked.headers
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "https://voice.example.com"
    assert rejected_preflight.status_code == 400
    assert "access-control-allow-origin" not in rejected_preflight.headers


def test_job_creation_requires_json_and_rejects_large_body_before_parsing(tmp_path):
    # The frozen settings are replaced before app creation in this dedicated case.
    from tests.test_api import FakeCatalog, FakeCoordinator, FixedIdentity
    from backend.app.human_verification import DisabledHumanVerifier
    from backend.app.job_store import JobStore
    from backend.app.main import create_app

    settings = replace(
        Settings(), output_dir=tmp_path, max_request_bytes=128
    )
    jobs = JobStore(tmp_path)
    coordinator = FakeCoordinator(jobs)
    limited_app = create_app(
        settings=settings,
        catalog=FakeCatalog(),
        jobs=jobs,
        coordinator=coordinator,
        identity=FixedIdentity(),
        verifier=DisabledHumanVerifier(),
    )

    with TestClient(limited_app) as client:
        wrong_type = client.post(
            "/api/jobs", content="plain text", headers={"Content-Type": "text/plain"}
        )
        oversized = client.post(
            "/api/jobs",
            json=payload(text="声" * 200),
        )

    assert wrong_type.status_code == 415
    assert wrong_type.json()["error"]["code"] == "json_required"
    assert oversized.status_code == 413
    assert oversized.json()["error"]["code"] == "request_too_large"


def test_every_api_response_has_restrictive_security_headers(tmp_path):
    app, _, _ = app_bundle(tmp_path)
    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"


def test_requests_do_not_log_raw_ip_or_user_text(tmp_path, caplog):
    app, _, _ = app_bundle(tmp_path)
    secret_text = "DO-NOT-LOG-THIS-VOICE-TEXT"
    caplog.set_level(logging.DEBUG)

    with TestClient(app, client=("203.0.113.88", 50000)) as client:
        response = client.post("/api/jobs", json=payload(text=secret_text))

    assert response.status_code == 202
    logs = caplog.text
    assert secret_text not in logs
    assert "203.0.113.88" not in logs


def test_runtime_and_dependency_files_have_no_azure_integration():
    root = Path(__file__).parents[1]
    files = [root / "requirements.txt", *sorted((root / "backend").rglob("*.py"))]

    offenders = [str(path.relative_to(root)) for path in files if "azure" in path.read_text().lower()]

    assert offenders == []
