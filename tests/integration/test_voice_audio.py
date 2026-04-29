import base64
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def transcribe_auth_client(db_session):
    from app.dependencies import get_db
    from app.routers.transcribe import router as transcribe_router

    app = FastAPI()
    app.include_router(transcribe_router)

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _create_scoped_key(db_session, scopes: list[str]) -> str:
    from app.services.api_keys import create_api_key

    _, full_key = await create_api_key(db_session, "voice-test-key", scopes)
    return full_key


class TestChatAudioInput:
    @pytest.fixture(autouse=True)
    def _mock_start_turn(self):
        from app.services.turns import TurnHandle

        with patch("app.routers.chat._routes.start_turn", new_callable=AsyncMock) as mock:
            mock.return_value = TurnHandle(
                session_id=uuid.uuid4(),
                channel_id=uuid.uuid4(),
                turn_id=uuid.uuid4(),
            )
            self._mock_start_turn = mock
            yield mock

    async def test_chat_audio_transcribes_before_starting_turn(self, client):
        audio_b64 = base64.b64encode(b"fake webm bytes").decode("ascii")

        with patch(
            "app.routers.chat._routes._transcribe_audio_data",
            new_callable=AsyncMock,
            return_value="transcribed voice message",
        ) as transcribe:
            resp = await client.post(
                "/chat",
                json={
                    "message": "",
                    "bot_id": "test-bot",
                    "audio_data": audio_b64,
                    "audio_format": "webm",
                },
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 202, resp.text
        transcribe.assert_awaited_once_with(audio_b64, "webm")
        kwargs = self._mock_start_turn.await_args.kwargs
        assert kwargs["user_message"] == "transcribed voice message"
        assert kwargs["audio_data"] is None

    async def test_chat_audio_rejects_invalid_base64_before_turn(self, client):
        resp = await client.post(
            "/chat",
            json={
                "message": "",
                "bot_id": "test-bot",
                "audio_data": "not base64!!",
                "audio_format": "webm",
            },
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 400
        assert "Invalid base64 audio data" in resp.json()["detail"]
        self._mock_start_turn.assert_not_awaited()

    async def test_chat_audio_rejects_unsupported_format_before_turn(self, client):
        audio_b64 = base64.b64encode(b"fake bytes").decode("ascii")

        resp = await client.post(
            "/chat",
            json={
                "message": "",
                "bot_id": "test-bot",
                "audio_data": audio_b64,
                "audio_format": "application/json",
            },
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 400
        assert "Unsupported audio format" in resp.json()["detail"]
        self._mock_start_turn.assert_not_awaited()


class TestTranscribeAuth:
    async def test_transcribe_requires_chat_scope(self, transcribe_auth_client, db_session):
        key = await _create_scoped_key(db_session, ["bots:read"])

        resp = await transcribe_auth_client.post(
            "/transcribe",
            content=b"abc",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "audio/webm",
            },
        )

        assert resp.status_code == 403
        assert "Missing required scope" in resp.json()["detail"]

    async def test_transcribe_accepts_chat_scope(self, transcribe_auth_client, db_session):
        key = await _create_scoped_key(db_session, ["chat"])

        with patch("app.routers.transcribe.stt_transcribe", return_value="hello voice"):
            resp = await transcribe_auth_client.post(
                "/transcribe",
                content=b"fake webm bytes",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "audio/webm",
                },
            )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"text": "hello voice"}
