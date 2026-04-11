"""Integration tests for /chat and /bots endpoints.

Heavy mocking required — we test request validation and response shape,
not the full agent loop.
"""
import json
import uuid
from dataclasses import dataclass, field
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
    """POST /chat now returns 202 + {session_id, turn_id, stream_id}.

    The full request → bus → outbox → renderer flow lives in
    ``tests/integration/test_chat_202.py``. The tests here cover request
    validation only — auth, missing fields, unknown bots, passive mode.
    """

    @pytest.fixture(autouse=True)
    def _mock_start_turn(self):
        """Stub start_turn so the request handler doesn't actually spawn a worker."""
        from app.services.turns import TurnHandle
        with patch("app.routers.chat._routes.start_turn", new_callable=AsyncMock) as mock:
            mock.return_value = TurnHandle(
                session_id=uuid.uuid4(),
                channel_id=uuid.uuid4(),
                turn_id=uuid.uuid4(),
            )
            self._mock_start_turn = mock
            yield mock

    async def test_chat_basic_returns_202_with_handle(self, client):
        resp = await client.post(
            "/chat",
            json={"message": "Hello", "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 202
        body = resp.json()
        # Phase E: POST /chat returns the turn handle (channel_id +
        # session_id + turn_id) so the client can subscribe to the SSE
        # bus. The legacy `stream_id` field was removed when the long-
        # poll SSE body was deleted.
        assert "session_id" in body
        assert "turn_id" in body
        assert "channel_id" in body
        assert self._mock_start_turn.await_count == 1

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
        assert resp.status_code == 202
        body = resp.json()
        assert body.get("passive") is True
        # start_turn should NOT have been called for passive messages
        self._mock_start_turn.assert_not_awaited()

    async def test_chat_unknown_bot(self, client):
        resp = await client.post(
            "/chat",
            json={"message": "Hi", "bot_id": "nonexistent"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Mirror tests deleted in Phase E — _mirror_to_integration is gone.
# Integration delivery now flows through the outbox + drainer + renderer
# pipeline. End-to-end coverage lives in tests/integration/test_chat_202.py
# and tests/integration/test_outbox_drainer_smoke.py.
# ---------------------------------------------------------------------------



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
