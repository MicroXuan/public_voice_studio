# 小宣 Voice Studio 公开版实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建并上线一个前后端分离、仅使用 edge-tts 全部在线语音、可供公众免费使用的“小宣 Voice Studio”。

**Architecture:** Cloudflare Pages 承载无框架静态前端，Render Free 以单进程运行 FastAPI API、内存限流、有界异步队列和临时 MP3。后端通过接口隔离语音目录、额度、任务存储、人机验证与合成器，便于后续替换为持久化和商业 TTS；前端从构建时配置读取 API 地址并处理冷启动。

**Tech Stack:** Python 3.11、FastAPI、Pydantic、edge-tts 7.2、pytest/pytest-asyncio、原生 HTML/CSS/JavaScript、Node.js 构建脚本、Docker、Render Blueprint、Cloudflare Pages

**Spec:** `docs/superpowers/specs/2026-10-13-public-edge-tts-studio-design.md`

## Global Constraints

- 品牌名称必须为“小宣 Voice Studio”，不得出现“声屿 Voice Studio”。
- 不得包含 Azure Speech SDK、REST 客户端、密钥、Region、provider 路由或 Azure 文案。
- 语音目录必须来自 `edge_tts.list_voices()`，并展示 edge-tts 当前返回的全部语音。
- 单次文本最多 10,000 个 Unicode 字符；每 IP 每小时最多 10 次、每 UTC 日最多 30,000 字符、同时最多 1 个任务。
- 全站并发合成数为 2，等待队列上限为 8；完成音频保留 3,600 秒。
- Render 必须使用单 worker；运行时文件和状态都视为临时数据。
- 不持久化用户文本，不把完整文本或原始 IP 写入日志。
- UI 必须遵循 `design-system/voice-studio/MASTER.md`，并在 375、768、1024、1440px 验证。
- 正文对比度至少 4.5:1、交互目标至少 44×44px、键盘焦点可见，并尊重 `prefers-reduced-motion`。

## Review Focus

- Render 在任务执行中重启：轮询必须收到可理解的“任务不存在或服务已重启”，用户文本仍保留并可重新提交；Task 5 的 API 集成测试覆盖。
- 多个请求并发命中同一 IP 和全站队列：必须原子地只接受允许的任务，且拒绝任务不错误消耗字符额度；Task 3 的并发测试覆盖。
- 上游语音目录首次失败与刷新失败：首次失败返回 503，已有缓存时继续返回最后成功目录；Task 2 的缓存测试覆盖。
- 恶意伪造转发头、大请求体和未知 Origin：不得绕过客户端身份、请求体限制或 CORS；Task 5 的安全测试覆盖。
- 几百个语音、长名称、无搜索结果和损坏的本地收藏：界面不得溢出或无法操作；Task 6 与 Task 7 的前端测试覆盖。

---

### Task 1: 项目骨架、配置与 API 模型

**Files:**
- Create: `backend/__init__.py`
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/app/models.py`
- Create: `tests/test_config.py`
- Create: `tests/test_models.py`
- Create: `tests/conftest.py`
- Create: `requirements.txt`
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`

**Interfaces:**
- Produces: `Settings.from_env() -> Settings`
- Produces: `VoiceOption`, `SynthesisRequest`, `JobState`, `JobResponse`
- Produces: shared pytest fixtures and dependency fakes used by later tasks

- [ ] **Step 1: Create dependency and test-runner manifests, then install the development environment**

Declare the compatible dependency ranges and pytest asyncio mode, create `.venv`, and run `.venv/bin/python -m pip install -r requirements.txt`. This setup step contains no product behavior.

- [ ] **Step 2: Write failing configuration tests**

Test defaults for 10,000 characters, 10 hourly requests, 30,000 daily characters, 2 workers, queue size 8, 3,600-second retention, localhost origins, optional Turnstile settings and whitespace-normalized comma-separated origins.

- [ ] **Step 3: Run the configuration tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: FAIL because `backend.app.config` does not exist.

- [ ] **Step 4: Implement `Settings` in `backend/app/config.py`**

Use a frozen dataclass with typed fields and `from_env()`; keep secrets hidden from `repr`. Add `.env.example` without real credentials.

- [ ] **Step 5: Write failing model tests**

Assert that `SynthesisRequest` trims text, rejects whitespace and 10,001 characters, bounds rate/pitch/volume to -50…50, and that voice/job responses expose only public fields.

- [ ] **Step 6: Run model tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_models.py -v`
Expected: FAIL because the models are undefined.

- [ ] **Step 7: Implement the models and project configuration**

Use Pydantic frozen response models, stable public enum values `queued`, `running`, `completed`, `failed`, and `expired`. Pin compatible ranges for FastAPI, Uvicorn, edge-tts, httpx, pytest and pytest-asyncio.

- [ ] **Step 8: Verify Task 1 GREEN**

Run: `.venv/bin/python -m pytest tests/test_config.py tests/test_models.py -v`
Expected: all tests pass.

- [ ] **Step 9: Commit Task 1**

```bash
git add backend tests requirements.txt pyproject.toml .gitignore .env.example
git commit -m "feat: establish public studio core models"
```

### Task 2: 动态 edge-tts 语音目录

**Files:**
- Create: `backend/app/voice_catalog.py`
- Create: `tests/test_voice_catalog.py`

**Interfaces:**
- Consumes: `VoiceOption`
- Produces: `VoiceProvider.list_voices() -> list[dict[str, object]]`
- Produces: `EdgeVoiceProvider.list_voices() -> list[dict[str, object]]`
- Produces: `VoiceCatalog.list(force_refresh: bool = False) -> tuple[VoiceOption, ...]`
- Produces: `VoiceCatalog.get(short_name: str) -> VoiceOption | None`

- [ ] **Step 1: Write failing normalization and complete-catalog tests**

Use a fake provider containing Chinese, English and Japanese voices. Assert all entries survive normalization; short name, friendly name, local name, locale and gender map correctly; sorting is stable by locale and name.

- [ ] **Step 2: Run the catalog tests and verify RED**

Run: `python -m pytest tests/test_voice_catalog.py -v`
Expected: FAIL because `VoiceCatalog` is missing.

- [ ] **Step 3: Implement provider and catalog normalization**

Wrap `edge_tts.list_voices()` behind `EdgeVoiceProvider`; accept upstream key variants without fabricating provider-specific capabilities.

- [ ] **Step 4: Write failing cache and failure-fallback tests**

Assert concurrent first loads call the provider once, successful values cache for 3,600 seconds, refresh failure returns last-good values, and first-load failure raises `VoiceCatalogUnavailableError`.

- [ ] **Step 5: Implement locked TTL cache and last-good fallback**

Inject the clock and provider for deterministic tests. Never log the voice request or user content.

- [ ] **Step 6: Verify Task 2 GREEN**

Run: `python -m pytest tests/test_voice_catalog.py -v`
Expected: all tests pass.

- [ ] **Step 7: Commit Task 2**

```bash
git add backend/app/voice_catalog.py tests/test_voice_catalog.py
git commit -m "feat: load every edge tts voice dynamically"
```

### Task 3: 客户端身份、额度和任务状态

**Files:**
- Create: `backend/app/client_identity.py`
- Create: `backend/app/quota.py`
- Create: `backend/app/job_store.py`
- Create: `tests/test_client_identity.py`
- Create: `tests/test_quota.py`
- Create: `tests/test_job_store.py`

**Interfaces:**
- Consumes: `Settings`, `JobState`
- Produces: `ClientIdentityResolver.resolve(request: Request) -> str`
- Produces: `InMemoryQuotaStore.reserve(client_key: str, characters: int, now: datetime) -> QuotaSnapshot`
- Produces: `InMemoryQuotaStore.refund(reservation: QuotaReservation) -> None`
- Produces: `JobStore.create(client_key: str) -> JobRecord`
- Produces: `JobStore.start/update_progress/complete/fail/get/cleanup_expired`

- [ ] **Step 1: Write failing client identity tests**

Assert the resolver emits a deterministic HMAC digest, never the raw IP, uses the trusted proxy-derived request client, and does not let an arbitrary `X-Forwarded-For` value become the key when proxy trust is disabled.

- [ ] **Step 2: Run identity tests and verify RED**

Run: `python -m pytest tests/test_client_identity.py -v`
Expected: FAIL because the resolver is missing.

- [ ] **Step 3: Implement client identity resolution**

Use an environment secret when configured and an in-process random secret otherwise. Keep raw addresses out of records and logs.

- [ ] **Step 4: Write failing quota tests**

Cover exactly 10 hourly requests, 30,000 daily characters, UTC boundary reset, reservation refund, bounded memory cleanup, and 20 concurrent reservations accepting only the permitted count.

- [ ] **Step 5: Implement `InMemoryQuotaStore` with one asyncio lock**

Raise distinct `HourlyLimitError` and `DailyCharacterLimitError` carrying public retry metadata.

- [ ] **Step 6: Write failing job-store tests**

Cover one active job per client, different clients concurrently, monotonic progress capped at 95 until completion, safe file cleanup, external-path protection, expired records, and orphan `.mp3.part` cleanup.

- [ ] **Step 7: Implement `JobStore`**

Store the hashed client key only. Add `discard_queued()` so a failed queue admission can release the active slot safely.

- [ ] **Step 8: Verify Task 3 GREEN**

Run: `python -m pytest tests/test_client_identity.py tests/test_quota.py tests/test_job_store.py -v`
Expected: all tests pass.

- [ ] **Step 9: Commit Task 3**

```bash
git add backend/app/client_identity.py backend/app/quota.py backend/app/job_store.py tests
git commit -m "feat: protect public synthesis capacity"
```

### Task 4: edge-tts 合成器与有界任务协调器

**Files:**
- Create: `backend/app/tts_service.py`
- Create: `backend/app/coordinator.py`
- Create: `tests/test_tts_service.py`
- Create: `tests/test_coordinator.py`

**Interfaces:**
- Consumes: `SynthesisRequest`, `VoiceCatalog`, `JobStore`, `InMemoryQuotaStore`
- Produces: `SpeechSynthesizer.synthesize(..., on_progress: ProgressCallback) -> None`
- Produces: `EdgeTTSService.synthesize(...) -> None`
- Produces: `SynthesisCoordinator.start()`, `stop()`, `submit(client_key, request) -> JobRecord`

- [ ] **Step 1: Write failing edge stream tests**

Assert signed rate/pitch/volume formatting, ordered MP3 chunk writes, atomic `.part` rename, monotonic boundary progress, empty-audio detection, cancellation cleanup, network error mapping and filesystem error mapping.

- [ ] **Step 2: Run service tests and verify RED**

Run: `python -m pytest tests/test_tts_service.py -v`
Expected: FAIL because the service is missing.

- [ ] **Step 3: Implement `EdgeTTSService`**

Wrap `edge_tts.Communicate`; translate upstream details into typed internal exceptions without exposing them publicly.

- [ ] **Step 4: Write failing coordinator tests**

Assert exactly two jobs execute concurrently, the next eight queue, the eleventh waiting job is rejected, same-client duplicate submission is rejected, unknown voice is rejected before quota consumption, and all failed admission paths refund reservations and active slots.

- [ ] **Step 5: Implement `SynthesisCoordinator`**

Use two long-lived worker tasks and `asyncio.Queue(maxsize=8)`. Make admission atomic with a coordinator lock; start/stop workers through FastAPI lifespan later.

- [ ] **Step 6: Verify Task 4 GREEN**

Run: `python -m pytest tests/test_tts_service.py tests/test_coordinator.py -v`
Expected: all tests pass with no leaked tasks.

- [ ] **Step 7: Commit Task 4**

```bash
git add backend/app/tts_service.py backend/app/coordinator.py tests
git commit -m "feat: queue edge tts synthesis jobs"
```

### Task 5: FastAPI、CORS、安全响应与 Turnstile

**Files:**
- Create: `backend/app/human_verification.py`
- Create: `backend/app/main.py`
- Create: `tests/test_human_verification.py`
- Create: `tests/test_api.py`
- Create: `tests/test_security_contract.py`

**Interfaces:**
- Consumes: all Task 1–4 interfaces
- Produces: `create_app(...) -> FastAPI`
- Produces: `GET /healthz`, `GET /api/voices`, `POST /api/jobs`, `GET /api/jobs/{id}`, `GET /api/jobs/{id}/audio`
- Produces: `HumanVerifier.verify(token: str | None, remote_ip: str) -> bool`

- [ ] **Step 1: Write failing Turnstile adapter tests**

Assert no-op mode when no secret is configured, verified mode posts only token and remote IP to Cloudflare, timeouts fail closed, and provider response details never reach clients.

- [ ] **Step 2: Implement verification adapters**

Use injected `httpx.AsyncClient` and a short timeout. Do not require Turnstile when deployment keys are absent.

- [ ] **Step 3: Write failing API lifecycle and route tests**

Cover health response, full voice schema, 202 creation with Location, polling states, inline/attachment audio, unknown/expired/restarted task messaging, all quota and queue status codes, upstream public errors, and lifespan worker shutdown.

- [ ] **Step 4: Run API tests and verify RED**

Run: `python -m pytest tests/test_human_verification.py tests/test_api.py -v`
Expected: FAIL because `create_app` and routes are missing.

- [ ] **Step 5: Implement the FastAPI application**

Return stable Chinese error codes and messages. Add `Retry-After` where meaningful. Build absolute audio URLs from the API request origin or let the frontend resolve relative URLs safely.

- [ ] **Step 6: Write failing security contract tests**

Assert allowlisted CORS only, OPTIONS behavior, JSON-only creation, maximum body enforcement before parsing, `X-Content-Type-Options`, `Referrer-Policy`, restrictive API CSP, no raw IP/text in logs, and no Azure strings or dependencies.

- [ ] **Step 7: Implement middleware and security headers**

Keep `/healthz` lightweight so Render can wake and monitor the service. Configure proxy trust only through deployment arguments and documented settings.

- [ ] **Step 8: Verify Task 5 GREEN**

Run: `python -m pytest tests/test_human_verification.py tests/test_api.py tests/test_security_contract.py -v`
Expected: all tests pass.

- [ ] **Step 9: Commit Task 5**

```bash
git add backend/app/human_verification.py backend/app/main.py tests
git commit -m "feat: expose secure public synthesis api"
```

### Task 6: 前端数据逻辑与静态构建

**Files:**
- Create: `frontend/lib.js`
- Create: `tests/js/frontend-lib.test.mjs`
- Create: `package.json`

**Interfaces:**
- Consumes: Task 5 HTTP API
- Produces: `normalizeApiBase`, `filterVoices`, `groupLocales`, `loadFavorites`, `toggleFavorite`, `formatApiError`, `backoffDelay`

- [ ] **Step 1: Write failing pure JavaScript tests**

Cover accent/case-insensitive search across names and locale, language/region/gender filters, stable favorites-first sorting, hundreds of voices, long names, empty results, corrupted localStorage JSON, API URL resolution and capped cold-start backoff.

- [ ] **Step 2: Run JavaScript tests and verify RED**

Run: `node --test tests/js/frontend-lib.test.mjs`
Expected: FAIL because `frontend/lib.js` is missing.

- [ ] **Step 3: Implement testable frontend helpers**

Keep DOM-free logic in `lib.js`; use `Intl.DisplayNames` when available with locale-code fallback.

- [ ] **Step 4: Verify Task 6 GREEN**

Run: `node --test tests/js/frontend-lib.test.mjs`
Expected: all tests pass.

- [ ] **Step 5: Commit Task 6**

```bash
git add frontend/lib.js tests/js/frontend-lib.test.mjs package.json
git commit -m "feat: prepare voice studio frontend logic"
```

### Task 7: 简约高级工作台界面

**Files:**
- Create: `frontend/index.html`
- Create: `frontend/styles.css`
- Create: `frontend/app.js`
- Create: `tests/test_frontend_contract.py`

**Interfaces:**
- Consumes: Task 6 helpers and generated `window.XUAN_VOICE_CONFIG`
- Produces: accessible browser UI for voice discovery, synthesis, progress, playback and download

- [ ] **Step 1: Write failing HTML/CSS contract tests**

Assert “小宣 Voice Studio”, explicit labels, searchable voice list, locale/gender filters, character counter, status live region, progressbar semantics, audio/download region, skip link, inline SVG icons, design tokens, 44px targets, required breakpoints and reduced-motion rule. Assert no “声屿”, Azure, Emoji icons, remote font dependency or placeholder-only field.

- [ ] **Step 2: Run frontend contract tests and verify RED**

Run: `python -m pytest tests/test_frontend_contract.py -v`
Expected: FAIL because the page does not exist.

- [ ] **Step 3: Implement semantic HTML following the approved reference**

Build the mist-gray canvas, centered white workbench, compact left voice catalog, wide right editor, restrained parameter cards, single dominant indigo-violet CTA, output region and privacy/service note.

- [ ] **Step 4: Implement responsive CSS from the persisted design system**

Use system fonts, hairline borders, long soft shadows and non-shifting selected/hover states. At mobile widths reorder to text → voice → parameters → generate → output without covering content.

- [ ] **Step 5: Wire UI states in `frontend/app.js`**

Implement voice loading/filter/favorite/selection, controls, guarded submission, Turnstile token when configured, cold-start retry, duplicate-safe polling, quota/queue errors, audio playback/download and text preservation on failure.

- [ ] **Step 6: Verify Task 7 GREEN**

Run: `python -m pytest tests/test_frontend_contract.py -v && node --test tests/js/frontend-lib.test.mjs`
Expected: all tests pass.

- [ ] **Step 7: Commit Task 7**

```bash
git add frontend tests/test_frontend_contract.py
git commit -m "feat: build premium xuan voice studio interface"
```

### Task 8: 容器、Render、Cloudflare Pages 与文档

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `render.yaml`
- Create: `frontend/config.template.js`
- Create: `scripts/build-frontend.mjs`
- Create: `README.md`
- Create: `docs/deployment.md`
- Create: `tests/test_deployment_contract.py`
- Create: `tests/test_frontend_build.py`

**Interfaces:**
- Consumes: `backend.app.main:app`, `scripts/build-frontend.mjs`
- Produces: reproducible Render backend and Cloudflare Pages frontend deployments

- [ ] **Step 1: Write failing static-build tests**

Assert the build requires `API_BASE_URL`, replaces the placeholder without changing source files, copies only public assets, and leaves no secret/environment dump in `dist/`.

- [ ] **Step 2: Implement the dependency-free Node build script**

Generate `dist/config.js` from the template and copy frontend assets. Treat the Turnstile site key as public configuration; never emit its secret.

- [ ] **Step 3: Write failing deployment contract tests**

Assert Python 3.11 slim image, non-root runtime user, one Uvicorn worker, `$PORT`, proxy headers, `/healthz`, Render Free plan, required environment declarations, Cloudflare build command/output directory and no Azure variables.

- [ ] **Step 4: Run deployment tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_frontend_build.py tests/test_deployment_contract.py -v`
Expected: FAIL because deployment files are missing.

- [ ] **Step 5: Implement deployment artifacts**

Use a cache-friendly Dockerfile and Render Blueprint. Document `ALLOWED_ORIGINS`, `IP_HASH_SECRET`, optional Turnstile values, `API_BASE_URL`, custom domains and rollback.

- [ ] **Step 6: Write operating documentation**

Document local backend/frontend startup, tests, temporary files, Render cold start, quota reset on restart, privacy behavior, service disclaimer and future migration path.

- [ ] **Step 7: Verify Task 8 GREEN**

Run: `.venv/bin/python -m pytest tests/test_frontend_build.py tests/test_deployment_contract.py -v && API_BASE_URL=http://127.0.0.1:8000 node scripts/build-frontend.mjs && docker build -t xuan-voice-studio:local .`
Expected: tests pass and Docker exits 0.

- [ ] **Step 8: Commit Task 8**

```bash
git add Dockerfile .dockerignore render.yaml frontend/config.template.js scripts/build-frontend.mjs README.md docs/deployment.md tests/test_frontend_build.py tests/test_deployment_contract.py
git commit -m "chore: package public voice studio deployment"
```

### Task 9: 全量验证、推送与公开部署

**Files:**
- Modify only files required by observed verification failures

**Interfaces:**
- Consumes: complete repository
- Produces: GitHub `main`, Render public API URL, Cloudflare Pages URL and custom-domain readiness

- [ ] **Step 1: Install from the declared manifests in a clean virtual environment**

Run: `python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt`
Expected: dependency installation exits 0.

- [ ] **Step 2: Run the complete automated verification suite**

Run: `.venv/bin/python -m pytest -v && .venv/bin/python -m compileall -q backend && node --test tests/js/*.test.mjs && API_BASE_URL=http://127.0.0.1:8000 node scripts/build-frontend.mjs && git diff --check`
Expected: every command exits 0 with no failed tests.

- [ ] **Step 3: Run local backend and frontend browser QA**

Run the backend on port 8000 and `dist/` on port 4173. Verify 1440×900, 1024×768, 768×1024 and 375×812; keyboard-only use; reduced motion; large text; voice search; no-results state; simulated cold start; generation; playback and download.

- [ ] **Step 4: Run a real edge-tts smoke test locally**

Synthesize a short neutral sentence with one dynamically returned Chinese voice. Confirm a non-empty MP3, then remove the test artifact through the app cleanup path.

- [ ] **Step 5: Commit any verification-only fixes**

```bash
git add -A
git commit -m "fix: complete production verification"
```

Skip this commit when verification required no source changes.

- [ ] **Step 6: Push the verified branch**

Run: `git push -u origin main`
Expected: GitHub reports the new `main` branch and repository files.

- [ ] **Step 7: Deploy the Render Free backend**

Create or connect the Render service from `render.yaml`, set secrets, wait for a healthy deployment, and verify `/healthz`, `/api/voices` and one real synthesis through the public URL.

- [ ] **Step 8: Deploy the Cloudflare Pages frontend**

Connect `MicroXuan/public_voice_studio`, set build command `node scripts/build-frontend.mjs`, output `dist`, and configure `API_BASE_URL` to the verified Render URL. Verify the Pages URL before binding the custom domain.

- [ ] **Step 9: Bind and verify the user domain**

After receiving the exact domain, add the required DNS/custom-domain records, configure `ALLOWED_ORIGINS`, redeploy, and verify HTTPS, CORS, generation, playback and download on the final domain.

- [ ] **Step 10: Final requirements audit**

Re-read the spec and design system; check every constraint, report any hosting/account action that required user takeover, and record the deployed URLs and verified commit SHA in `README.md` or the final handoff.
