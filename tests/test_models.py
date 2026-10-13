from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.app.models import JobResponse, JobState, SynthesisRequest, VoiceOption


def test_synthesis_request_trims_text_and_voice():
    request = SynthesisRequest(text="  你好，世界。  ", voice="  zh-CN-XiaoxiaoNeural  ")

    assert request.text == "你好，世界。"
    assert request.voice == "zh-CN-XiaoxiaoNeural"
    assert request.rate == 0
    assert request.pitch == 0
    assert request.volume == 0


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_synthesis_request_rejects_blank_text(text):
    with pytest.raises(ValidationError):
        SynthesisRequest(text=text, voice="zh-CN-XiaoxiaoNeural")


def test_synthesis_request_rejects_more_than_ten_thousand_unicode_characters():
    with pytest.raises(ValidationError):
        SynthesisRequest(text="声" * 10_001, voice="zh-CN-XiaoxiaoNeural")


@pytest.mark.parametrize("field", ["rate", "pitch", "volume"])
@pytest.mark.parametrize("value", [-51, 51])
def test_synthesis_controls_are_bounded(field, value):
    with pytest.raises(ValidationError):
        SynthesisRequest(
            text="测试",
            voice="zh-CN-XiaoxiaoNeural",
            **{field: value},
        )


def test_voice_option_exposes_only_provider_neutral_public_fields():
    voice = VoiceOption(
        short_name="zh-CN-XiaoxiaoNeural",
        friendly_name="Microsoft Xiaoxiao Online (Natural) - Chinese (Mainland)",
        local_name="晓晓",
        locale="zh-CN",
        gender="Female",
    )

    assert voice.model_dump() == {
        "short_name": "zh-CN-XiaoxiaoNeural",
        "friendly_name": "Microsoft Xiaoxiao Online (Natural) - Chinese (Mainland)",
        "local_name": "晓晓",
        "locale": "zh-CN",
        "gender": "Female",
    }


def test_job_response_has_stable_public_states_and_no_internal_fields():
    response = JobResponse(
        id="public-id",
        state=JobState.QUEUED,
        progress=0,
        message="任务已进入队列",
        created_at=datetime(2026, 10, 13, tzinfo=UTC),
    )

    assert [state.value for state in JobState] == [
        "queued",
        "running",
        "completed",
        "failed",
        "expired",
    ]
    assert response.model_dump(mode="json") == {
        "id": "public-id",
        "state": "queued",
        "progress": 0,
        "message": "任务已进入队列",
        "created_at": "2026-10-13T00:00:00Z",
        "audio_url": None,
        "download_url": None,
    }
    assert "client_key" not in response.model_dump()
    assert "output_path" not in response.model_dump()
