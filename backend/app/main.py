"""FastAPI entry point for the public Xiao Xuan Voice Studio API."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.cors import CORSMiddleware

from backend.app.client_identity import ClientIdentityResolver
from backend.app.config import Settings
from backend.app.coordinator import (
    QueueCapacityError,
    SynthesisCoordinator,
    UnknownVoiceError,
)
from backend.app.human_verification import HumanVerifier, build_human_verifier
from backend.app.job_store import ActiveJobError, JobNotFoundError, JobStore
from backend.app.models import JobState, SynthesisRequest
from backend.app.quota import (
    DailyCharacterLimitError,
    HourlyLimitError,
    InMemoryQuotaStore,
    QuotaLimitError,
)
from backend.app.tts_service import EdgeTTSService
from backend.app.voice_catalog import (
    EdgeVoiceProvider,
    VoiceCatalog,
    VoiceCatalogUnavailableError,
)


def _error(
    status_code: int,
    code: str,
    message: str,
    *,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}},
        status_code=status_code,
        headers=headers,
    )


class RequestContractMiddleware:
    """Enforce JSON and a small body limit before application parsing."""

    def __init__(self, app, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if not (
            scope["type"] == "http"
            and scope["method"] == "POST"
            and scope["path"] == "/api/jobs"
        ):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json" and not content_type.endswith("+json"):
            await _error(415, "json_required", "请使用 JSON 格式提交请求")(
                scope, receive, send
            )
            return

        content_length = headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self.max_bytes:
                    await _error(413, "request_too_large", "请求内容超过大小限制")(
                        scope, receive, send
                    )
                    return
            except ValueError:
                await _error(400, "invalid_content_length", "请求头无效")(
                    scope, receive, send
                )
                return

        body = bytearray()
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.max_bytes:
                await _error(413, "request_too_large", "请求内容超过大小限制")(
                    scope, receive, send
                )
                return
            more_body = message.get("more_body", False)

        delivered = False

        async def replay_body():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return {"type": "http.disconnect"}

        await self.app(scope, replay_body, send)


class SecurityHeadersMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("Referrer-Policy", "no-referrer")
                headers.setdefault(
                    "Content-Security-Policy",
                    "default-src 'none'; frame-ancestors 'none'",
                )
                headers.setdefault(
                    "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
                )
            await send(message)

        await self.app(scope, receive, send_with_headers)


def create_app(
    *,
    settings: Settings | None = None,
    catalog: VoiceCatalog | None = None,
    jobs: JobStore | None = None,
    quota: InMemoryQuotaStore | None = None,
    coordinator: SynthesisCoordinator | None = None,
    identity: ClientIdentityResolver | None = None,
    verifier: HumanVerifier | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    catalog = catalog or VoiceCatalog(
        EdgeVoiceProvider(), ttl_seconds=settings.voice_cache_ttl_seconds
    )
    jobs = jobs or JobStore(
        settings.output_dir, retention_seconds=settings.audio_retention_seconds
    )
    quota = quota or InMemoryQuotaStore(
        hourly_limit=settings.hourly_request_limit,
        daily_character_limit=settings.daily_character_limit,
    )
    coordinator = coordinator or SynthesisCoordinator(
        catalog=catalog,
        quota=quota,
        jobs=jobs,
        synthesizer=EdgeTTSService(),
        worker_count=settings.synthesis_workers,
        queue_maxsize=settings.queue_maxsize,
    )
    identity = identity or ClientIdentityResolver.from_settings(settings)
    verifier = verifier or build_human_verifier(
        secret_key=settings.turnstile_secret_key
    )

    cleanup_task: asyncio.Task[None] | None = None

    async def cleanup_loop() -> None:
        while True:
            await asyncio.sleep(min(300, settings.audio_retention_seconds))
            await jobs.cleanup_expired()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal cleanup_task
        await coordinator.start()
        cleanup_task = asyncio.create_task(cleanup_loop(), name="audio-cleanup")
        try:
            yield
        finally:
            if cleanup_task is not None:
                cleanup_task.cancel()
                with suppress(asyncio.CancelledError):
                    await cleanup_task
            await coordinator.stop()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        RequestContractMiddleware, max_bytes=settings.max_request_bytes
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
        expose_headers=["Location", "Retry-After"],
        max_age=600,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.state.settings = settings
    app.state.catalog = catalog
    app.state.jobs = jobs
    app.state.coordinator = coordinator

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        del request, exc
        return _error(422, "invalid_request", "请求内容不符合要求")

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "service": settings.app_name}

    @app.get("/api/voices")
    async def list_voices():
        try:
            voices = await catalog.list()
        except VoiceCatalogUnavailableError:
            return _error(
                503,
                "voice_catalog_unavailable",
                "语音列表暂时不可用，请稍后重试",
                headers={"Retry-After": "30"},
            )
        return {"count": len(voices), "voices": [voice.model_dump() for voice in voices]}

    @app.post("/api/jobs")
    async def create_job(request: Request, synthesis: SynthesisRequest):
        if len(synthesis.text) > settings.max_text_chars:
            return _error(422, "text_too_long", "文本长度超过单次限制")

        remote_ip = request.client.host if request.client else ""
        if not await verifier.verify(synthesis.turnstile_token, remote_ip):
            return _error(403, "human_verification_failed", "人机验证未通过，请重试")

        client_key = identity.resolve(request)
        try:
            job = await coordinator.submit(client_key, synthesis)
        except UnknownVoiceError:
            return _error(422, "voice_not_found", "所选语音不存在，请刷新后重试")
        except ActiveJobError:
            return _error(409, "active_job_exists", "请等待当前任务完成")
        except HourlyLimitError as exc:
            return _quota_error(exc, "hourly_limit", "本小时生成次数已用完")
        except DailyCharacterLimitError as exc:
            return _quota_error(exc, "daily_character_limit", "今日字符额度已用完")
        except QueueCapacityError:
            return _error(
                503,
                "queue_full",
                "当前生成队列已满，请稍后重试",
                headers={"Retry-After": "30"},
            )
        except VoiceCatalogUnavailableError:
            return _error(
                503,
                "voice_catalog_unavailable",
                "语音列表暂时不可用，请稍后重试",
                headers={"Retry-After": "30"},
            )

        location = f"/api/jobs/{job.id}"
        return JSONResponse(
            job.to_response().model_dump(mode="json"),
            status_code=202,
            headers={"Location": location},
        )

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str, request: Request):
        client_key = identity.resolve(request)
        try:
            job = await jobs.get(job_id, client_key=client_key)
        except JobNotFoundError:
            return _error(
                404,
                "job_not_found",
                "任务不存在或服务已重启，请保留文本并重新提交",
            )
        if job.state is JobState.EXPIRED:
            return _error(410, "job_expired", "音频已过期，请重新生成")
        return job.to_response()

    @app.get("/api/jobs/{job_id}/audio")
    async def get_audio(
        job_id: str,
        request: Request,
        download: bool = Query(default=False),
    ):
        client_key = identity.resolve(request)
        try:
            job = await jobs.get(job_id, client_key=client_key)
        except JobNotFoundError:
            return _error(
                404,
                "job_not_found",
                "任务不存在或服务已重启，请重新提交",
            )
        if job.state is JobState.EXPIRED:
            return _error(410, "job_expired", "音频已过期，请重新生成")
        if job.state is not JobState.COMPLETED or job.output_path is None:
            return _error(409, "audio_not_ready", "音频仍在生成中")
        if not job.output_path.exists():
            return _error(410, "audio_expired", "音频已不可用，请重新生成")
        return FileResponse(
            job.output_path,
            media_type="audio/mpeg",
            filename="xiaoxuan-voice.mp3" if download else None,
            content_disposition_type="attachment" if download else "inline",
        )

    return app


def _quota_error(exc: QuotaLimitError, code: str, message: str) -> JSONResponse:
    return _error(
        429,
        code,
        message,
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


app = create_app()
