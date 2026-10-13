"""Streaming edge-tts adapter with atomic output and safe public errors."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol

import edge_tts

from backend.app.models import SynthesisRequest


ProgressCallback = Callable[[int], Awaitable[None] | None]


class SynthesisError(RuntimeError):
    pass


class SynthesisUnavailableError(SynthesisError):
    pass


class SynthesisStorageError(SynthesisError):
    pass


class SynthesisEmptyAudioError(SynthesisError):
    pass


class SpeechSynthesizer(Protocol):
    async def synthesize(
        self,
        request: SynthesisRequest,
        output_path: Path,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> None: ...


def _signed(value: int, unit: str) -> str:
    return f"{value:+d}{unit}"


async def _report(callback: ProgressCallback | None, value: int) -> None:
    if callback is None:
        return
    result = callback(value)
    if inspect.isawaitable(result):
        await result


class _WriteFailed(Exception):
    pass


class EdgeTTSService:
    def __init__(self, communicator_factory=None) -> None:
        self._communicator_factory = communicator_factory or edge_tts.Communicate

    async def synthesize(
        self,
        request: SynthesisRequest,
        output_path: Path,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        partial = output_path.with_suffix(f"{output_path.suffix}.part")
        partial.unlink(missing_ok=True)
        wrote_audio = False
        progress = 5

        try:
            try:
                communicate = self._communicator_factory(
                    text=request.text,
                    voice=request.voice,
                    rate=_signed(request.rate, "%"),
                    pitch=_signed(request.pitch, "Hz"),
                    volume=_signed(request.volume, "%"),
                )
            except Exception as exc:
                raise SynthesisUnavailableError("语音服务暂时不可用") from exc

            try:
                file_handle = partial.open("wb")
            except OSError as exc:
                raise SynthesisStorageError("暂时无法保存生成的音频") from exc

            try:
                with file_handle:
                    await _report(on_progress, progress)
                    try:
                        async for chunk in communicate.stream():
                            kind = chunk.get("type")
                            if kind == "audio":
                                data = chunk.get("data")
                                if isinstance(data, bytes) and data:
                                    try:
                                        file_handle.write(data)
                                    except OSError as exc:
                                        raise _WriteFailed from exc
                                    wrote_audio = True
                            elif kind in {"WordBoundary", "SentenceBoundary"}:
                                progress = min(90, progress + 7)
                                await _report(on_progress, progress)
                    except _WriteFailed as exc:
                        raise SynthesisStorageError("暂时无法保存生成的音频") from exc
                    except SynthesisError:
                        raise
                    except Exception as exc:
                        raise SynthesisUnavailableError("语音服务暂时不可用") from exc
            except OSError as exc:
                raise SynthesisStorageError("暂时无法保存生成的音频") from exc

            if not wrote_audio:
                raise SynthesisEmptyAudioError("语音服务未返回有效音频")

            try:
                partial.replace(output_path)
            except OSError as exc:
                raise SynthesisStorageError("暂时无法保存生成的音频") from exc
            await _report(on_progress, 95)
        finally:
            partial.unlink(missing_ok=True)
