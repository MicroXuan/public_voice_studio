from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).parents[1]
HTML_PATH = ROOT / "frontend" / "index.html"
CSS_PATH = ROOT / "frontend" / "styles.css"
JS_PATH = ROOT / "frontend" / "app.js"


class ContractParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids: set[str] = set()
        self.labels: set[str] = set()
        self.roles: set[str] = set()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        self.tags.append((tag, values))
        if values.get("id"):
            self.ids.add(values["id"])
        if tag == "label" and values.get("for"):
            self.labels.add(values["for"])
        if values.get("role"):
            self.roles.add(values["role"])


def parse_contract():
    html = HTML_PATH.read_text()
    parser = ContractParser()
    parser.feed(html)
    return html, parser


def test_page_has_brand_semantics_and_no_forbidden_copy():
    html, parser = parse_contract()

    assert "小宣 Voice Studio" in html
    assert "声屿" not in html
    assert "azure" not in html.lower()
    assert '<a class="skip-link" href="#workspace-main">' in html
    assert "main" in [tag for tag, _ in parser.tags]
    assert sum(tag == "svg" for tag, _ in parser.tags) >= 4
    assert not re.search(r"[😀-🙏🌀-🫿]", html)


def test_page_discloses_unofficial_provider_and_prohibits_abuse():
    html = HTML_PATH.read_text()

    assert "edge-tts" in html
    assert "Microsoft Edge 在线语音" in html
    assert "非官方客户端" in html
    assert "请勿滥用" in html


def test_all_creation_fields_have_explicit_labels_and_required_regions():
    html, parser = parse_contract()
    required_ids = {
        "voice-search",
        "language-filter",
        "region-filter",
        "gender-filter",
        "source-text",
        "rate-control",
        "pitch-control",
        "volume-control",
    }

    assert required_ids <= parser.ids
    assert required_ids <= parser.labels
    assert {"listbox", "status", "progressbar"} <= parser.roles
    assert "character-count" in parser.ids
    assert "voice-list" in parser.ids
    assert "audio-player" in parser.ids
    assert "download-audio" in parser.ids
    assert "generate-button" in parser.ids
    assert "aria-live=\"polite\"" in html or 'aria-live="polite"' in html


def test_inputs_do_not_depend_on_placeholders_for_their_names():
    _, parser = parse_contract()
    fields = [
        attrs
        for tag, attrs in parser.tags
        if tag in {"input", "select", "textarea"} and attrs.get("id")
    ]

    assert fields
    for field in fields:
        field_id = field["id"]
        if field.get("type") == "hidden":
            continue
        assert field_id in parser.labels or field.get("aria-label"), field_id


def test_styles_define_tokens_accessible_targets_breakpoints_and_motion():
    css = CSS_PATH.read_text()

    for token in (
        "--color-primary: #4f46e5",
        "--color-background: #f4f5fa",
        "--color-foreground: #111827",
        "--color-success: #0f8a5f",
    ):
        assert token in css.lower()
    assert "min-height: 44px" in css
    assert "@media (max-width: 1024px)" in css
    assert "@media (max-width: 768px)" in css
    assert "@media (max-width: 480px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "font-family: inter" in css.lower()
    assert "@import" not in css


def test_browser_logic_consumes_helpers_config_and_full_job_flow():
    html = HTML_PATH.read_text()
    javascript = JS_PATH.read_text()

    assert '<script src="./config.js"></script>' in html
    assert html.index('<script src="./config.js"></script>') < html.index('src="./app.js"')
    assert "window.XUAN_VOICE_CONFIG" in javascript
    assert "filterVoices" in javascript
    assert 'fetch(`${apiBase}/api/voices`' in javascript
    assert 'fetch(`${apiBase}/api/jobs`' in javascript
    assert "turnstile" in javascript.lower()
    assert "AbortController" in javascript
    assert "localStorage" in javascript


def test_public_catalog_dropdowns_and_result_navigation_are_intentional():
    javascript = JS_PATH.read_text()
    css = CSS_PATH.read_text()

    assert "filterVoicesByRegions" in javascript
    for region in ("US", "JP", "CN", "TW", "HK", "KR", "IN", "AR"):
        assert f'"{region}"' in javascript
    assert "new Option(item.label, item.code)" in javascript
    assert "${item.label} · ${item.count}" not in javascript
    assert "scrollIntoView" in javascript
    assert "prefers-reduced-motion: reduce" in javascript
    assert "scroll-margin-top" in css


def test_desktop_workspace_uses_compact_vertical_rhythm():
    css = CSS_PATH.read_text()

    assert re.search(r"\.site-header\s*\{[^}]*min-height:\s*64px", css, re.S)
    assert re.search(r"\.intro\s*\{[^}]*padding:\s*18px 14px 18px", css, re.S)
    assert re.search(r"#source-text\s*\{[^}]*min-height:\s*220px", css, re.S)
    assert re.search(r"\.voice-card\s*\{[^}]*min-height:\s*620px", css, re.S)
