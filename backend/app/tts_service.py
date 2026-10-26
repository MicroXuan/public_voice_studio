"""Bounded parallel edge-tts synthesis with ordered, atomic MP3 output."""

from __future__ import annotations

import asyncio
import inspect
import re
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


def split_for_parallel_synthesis(text: str) -> list[str]:
    """Split long text near equal lengths, only at natural pauses."""
    if len(text) < 800:
        return [text]

    boundary_sets = [
        [match.end() for match in re.finditer(r"[。！？!?；;\n]", text)],
        [match.end() for match in re.finditer(r"[。！？!?；;，,\n]|\s+", text)],
    ]
    for boundaries in boundary_sets:
        boundaries = sorted(set(boundaries) - {len(text)})
        for count in range(4, 1, -1):
            ideal = len(text) / count
            selected = [0]
            for index in range(1, count):
                target = ideal * index
                candidates = [
                    position
                    for position in boundaries
                    if position - selected[-1] >= 80
                    and len(text) - position >= 80 * (count - index)
                    and abs(position - target) <= ideal * 0.4
                ]
                if not candidates:
                    break
                selected.append(min(candidates, key=lambda position: abs(position - target)))
            if len(selected) == count:
                parts = [text[start:end] for start, end in zip(selected, selected[1:] + [len(text)])]
                if min(map(len, parts)) >= 80:
                    return parts
    return [text]


class EdgeTTSService:
    def __init__(self, communicator_factory=None, *, max_parallel_streams: int = 4) -> None:
        self._communicator_factory = communicator_factory or edge_tts.Communicate
        self._stream_limit = asyncio.Semaphore(max_parallel_streams)

    async def _collect_audio(
        self,
        text: str,
        request: SynthesisRequest,
        on_boundary: ProgressCallback | None = None,
    ) -> bytes:
        async with self._stream_limit:
            try:
                communicate = self._communicator_factory(
                    text=text,
                    voice=request.voice,
                    rate=_signed(request.rate, "%"),
                    pitch=_signed(request.pitch, "Hz"),
                    volume=_signed(request.volume, "%"),
                )
            except Exception as exc:
                raise SynthesisUnavailableError("语音服务暂时不可用") from exc

            audio = bytearray()
            try:
                async for chunk in communicate.stream():
                    kind = chunk.get("type")
                    if kind == "audio":
                        data = chunk.get("data")
                        if isinstance(data, bytes) and data:
                            audio.extend(data)
                    elif kind in {"WordBoundary", "SentenceBoundary"}:
                        await _report(on_boundary, 1)
            except SynthesisError:
                raise
            except Exception as exc:
                raise SynthesisUnavailableError("语音服务暂时不可用") from exc

            if not audio:
                raise SynthesisEmptyAudioError("语音服务未返回有效音频")
            return bytes(audio)

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
        parts = split_for_parallel_synthesis(request.text)
        progress = 5

        async def on_boundary(_: int) -> None:
            nonlocal progress
            progress = min(90, progress + 7)
            await _report(on_progress, progress)

        completed = 0

        async def collect_part(text: str) -> bytes:
            nonlocal completed
            audio = await self._collect_audio(
                text,
                request,
                on_boundary if len(parts) == 1 else None,
            )
            if len(parts) > 1:
                completed += 1
                await _report(on_progress, min(90, 5 + 85 * completed // len(parts)))
            return audio

        try:
            await _report(on_progress, progress)
            tasks = [asyncio.create_task(collect_part(text)) for text in parts]
            try:
                chunks = await asyncio.gather(*tasks)
            except BaseException:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise

            try:
                with partial.open("wb") as output:
                    for audio in chunks:
                        output.write(audio)
                partial.replace(output_path)
            except OSError as exc:
                raise SynthesisStorageError("暂时无法保存生成的音频") from exc
            await _report(on_progress, 95)
        finally:
            partial.unlink(missing_ok=True)
