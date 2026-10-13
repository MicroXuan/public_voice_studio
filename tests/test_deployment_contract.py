from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


def test_docker_image_is_python_311_non_root_and_single_worker():
    dockerfile = (ROOT / "Dockerfile").read_text().lower()

    assert "from python:3.11-slim" in dockerfile
    assert "user app" in dockerfile
    assert "${port:-8000}" in dockerfile
    assert "--workers 1" in dockerfile
    assert "--proxy-headers" in dockerfile
    assert "--forwarded-allow-ips" in dockerfile
    assert "/healthz" in dockerfile


def test_render_blueprint_uses_free_plan_healthcheck_and_safe_environment():
    blueprint = yaml.safe_load((ROOT / "render.yaml").read_text())
    service = blueprint["services"][0]

    assert service["type"] == "web"
    assert service["runtime"] == "docker"
    assert service["plan"] == "free"
    assert service["healthCheckPath"] == "/healthz"
    assert "maxShutdownDelaySeconds" not in service
    environment = {item["key"]: item for item in service["envVars"]}
    assert environment["ALLOWED_ORIGINS"]["sync"] is False
    assert environment["IP_HASH_SECRET"]["generateValue"] is True
    assert environment["TURNSTILE_SECRET_KEY"]["sync"] is False
    assert environment["OUTPUT_DIR"]["value"].startswith("/tmp/")
    assert environment["MAX_TEXT_CHARS"]["value"] == "5000"
    assert environment["DAILY_CHARACTER_LIMIT"]["value"] == "50000"
    assert "PORT" not in environment


def test_cloudflare_pages_build_contract_and_domains_are_documented():
    deployment = (ROOT / "docs" / "deployment.md").read_text()
    readme = (ROOT / "README.md").read_text()
    combined = f"{deployment}\n{readme}"

    assert "npm run build" in deployment
    assert "API_BASE_URL" in deployment
    assert "dist" in deployment
    assert "Cloudflare Pages" in deployment
    assert "Render Free" in deployment
    assert "自定义域名" in deployment
    assert "回滚" in deployment
    assert "冷启动" in combined
    assert "单 worker" in combined


def test_deployment_files_contain_no_forbidden_provider_variables():
    paths = [
        ROOT / "Dockerfile",
        ROOT / "render.yaml",
        ROOT / ".env.example",
        ROOT / "frontend" / "config.template.js",
        ROOT / "scripts" / "build-frontend.mjs",
    ]
    combined = "\n".join(path.read_text().lower() for path in paths)

    assert "azure" not in combined
    assert "speech_key" not in combined
    assert "speech_region" not in combined


def test_backend_accepts_documented_deployment_environment_names():
    config = (ROOT / "backend" / "app" / "config.py").read_text()

    assert 'os.getenv("ALLOWED_ORIGINS")' in config
    assert '_optional("IP_HASH_SECRET")' in config
