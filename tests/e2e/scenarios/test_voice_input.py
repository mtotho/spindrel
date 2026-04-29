"""Voice input e2e coverage for the web-composer audio payload path."""

from __future__ import annotations

import base64

import pytest

from tests.e2e.harness.assertions import assert_contains_any
from tests.e2e.harness.client import E2EClient


@pytest.mark.e2e
class TestVoiceInput:
    async def test_chat_audio_transcribes_and_runs_turn(self, client: E2EClient) -> None:
        """Synthetic browser audio is transcribed by the e2e STT provider, then handled as chat."""

        audio_data = base64.b64encode(b"synthetic webm audio").decode("ascii")
        channel_id = client.new_channel_id()

        resp = await client.chat(
            "",
            channel_id=channel_id,
            audio_data=audio_data,
            audio_format="webm",
        )

        assert_contains_any(resp.response, ["VOICE_OK"])

    async def test_chat_audio_rejects_invalid_base64(self, client: E2EClient) -> None:
        raw = await client.post(
            "/chat",
            json={
                "message": "",
                "bot_id": client.default_bot_id,
                "audio_data": "not base64!!",
                "audio_format": "webm",
            },
        )

        assert raw.status_code == 400
        assert "Invalid base64 audio data" in raw.json()["detail"]
