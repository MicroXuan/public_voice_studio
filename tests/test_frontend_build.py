from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1]
DIST = ROOT / "dist"
PUBLIC_ASSETS = {"index.html", "styles.css", "app.js", "lib.js", "config.js", "favicon.png"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_build(env):
    return subprocess.run(
        ["node", "scripts/build-frontend.mjs"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_build_requires_api_base_url(monkeypatch):
    shutil.rmtree(DIST, ignore_errors=True)
    env = os.environ.copy()
    env.pop("API_BASE_URL", None)

    result = run_build(env)

    assert result.returncode != 0
    assert "API_BASE_URL" in result.stderr


def test_build_copies_only_public_assets_and_preserves_sources():
    source_files = [
        ROOT / "frontend" / name
        for name in ("index.html", "styles.css", "app.js", "lib.js", "config.template.js", "favicon.png")
    ]
    before = {path: digest(path) for path in source_files}
    env = os.environ.copy()
    env.update(
        {
            "API_BASE_URL": "https://api.voice.example.com/",
            "TURNSTILE_SITE_KEY": "public-site-key",
            "TURNSTILE_SECRET_KEY": "must-never-be-emitted",
            "CLIENT_IDENTITY_SECRET": "also-never-public",
        }
    )

    result = run_build(env)

    assert result.returncode == 0, result.stderr
    assert {path.name for path in DIST.iterdir()} == PUBLIC_ASSETS
    assert {path: digest(path) for path in source_files} == before
    assert digest(DIST / "favicon.png") == digest(ROOT / "frontend" / "favicon.png")
    config = (DIST / "config.js").read_text()
    assert json.dumps("https://api.voice.example.com") in config
    assert json.dumps("public-site-key") in config
    combined = "\n".join(path.read_text() for path in DIST.iterdir() if path.suffix != ".png")
    assert "must-never-be-emitted" not in combined
    assert "also-never-public" not in combined
    assert "process.env" not in combined

    index = (DIST / "index.html").read_text()
    app = (DIST / "app.js").read_text()
    assert re.search(r'\./styles\.css\?v=[0-9a-f]{12}', index)
    assert re.search(r'\./config\.js\?v=[0-9a-f]{12}', index)
    assert re.search(r'\./app\.js\?v=[0-9a-f]{12}', index)
    assert re.search(r'from "\./lib\.js\?v=[0-9a-f]{12}"', app)
