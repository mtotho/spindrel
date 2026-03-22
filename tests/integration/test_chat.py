"""Integration tests for /chat and /bots endpoints.

Heavy mocking required — we test request validation and response shape,
not the full agent loop.
"""
import uuid
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


@dataclass
class FakeRunResult:
    response: str = "Hello from bot"
    transcript: str = ""
    client_actions: list = None

    def __post_init__(self):
        if self.client_actions is None:
            self.client_actions = []


# ---------------------------------------------------------------------------
# GET /bots
# ---------------------------------------------------------------------------

class TestBots:
    async def test_list_bots(self, client):
        resp = await client.get("/bots", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        bots = resp.json()
        assert isinstance(bots, list)
        assert len(bots) >= 1
        # Check shape
        bot = bots[0]
        assert "id" in bot
        assert "name" in bot
        assert "model" in bot


# ---------------------------------------------------------------------------
# POST /chat
# ---------------------------------------------------------------------------

class TestChat:
    @pytest.fixture(autouse=True)
    def _mock_run(self):
        """Mock the agent run() function to avoid real LLM calls."""
        with patch("app.routers.chat.run", new_callable=AsyncMock) as mock:
            mock.return_value = FakeRunResult()
            self._mock_run_fn = mock
            yield mock

    @pytest.fixture(autouse=True)
    def _mock_persist(self):
        """Mock persist_turn to avoid complex DB operations."""
        with patch("app.routers.chat.persist_turn", new_callable=AsyncMock):
            yield

    @pytest.fixture(autouse=True)
    def _mock_compact(self):
        """Mock maybe_compact to avoid background compaction."""
        with patch("app.routers.chat.maybe_compact"):
            yield

    async def test_chat_basic(self, client):
        resp = await client.post(
            "/chat",
            json={"message": "Hello", "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "session_id" in body
        assert body["response"] == "Hello from bot"
        assert body["transcript"] == ""
        assert body["client_actions"] == []

    async def test_chat_with_client_id(self, client):
        resp = await client.post(
            "/chat",
            json={"message": "Hi", "client_id": "my-client", "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert "session_id" in resp.json()

    async def test_chat_empty_message_no_attachments(self, client):
        resp = await client.post(
            "/chat",
            json={"message": "", "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 400
        assert "No message" in resp.json()["detail"]

    async def test_chat_passive_mode(self, client):
        resp = await client.post(
            "/chat",
            json={"message": "Just store this", "bot_id": "test-bot", "passive": True},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["response"] == ""
        # run() should NOT have been called
        self._mock_run_fn.assert_not_awaited()

    async def test_chat_with_transcript(self, client):
        self._mock_run_fn.return_value = FakeRunResult(
            response="Noted",
            transcript="User said: hello",
        )
        resp = await client.post(
            "/chat",
            json={"message": "Hello", "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["transcript"] == "User said: hello"

    async def test_chat_with_client_actions(self, client):
        self._mock_run_fn.return_value = FakeRunResult(
            response="Done",
            client_actions=[{"action": "tts", "text": "hello"}],
        )
        resp = await client.post(
            "/chat",
            json={"message": "Speak", "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert len(resp.json()["client_actions"]) == 1

    async def test_chat_unknown_bot(self, client):
        resp = await client.post(
            "/chat",
            json={"message": "Hi", "bot_id": "nonexistent"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /chat/tool_result
# ---------------------------------------------------------------------------

class TestToolResult:
    async def test_tool_result_not_found(self, client):
        resp = await client.post(
            "/chat/tool_result",
            json={"request_id": "fake-id", "result": "some result"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404

    async def test_tool_result_success(self, client):
        """Register a pending request, then resolve it."""
        from app.agent.pending import create_pending
        import asyncio

        req_id = "test-req-123"
        future = asyncio.get_event_loop().create_future()
        with patch("app.agent.pending._pending", {req_id: future}):
            resp = await client.post(
                "/chat/tool_result",
                json={"request_id": req_id, "result": "tool output"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
