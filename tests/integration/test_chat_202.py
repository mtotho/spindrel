"""Phase E — POST /chat returns 202 + {session_id, channel_id, turn_id}.

These tests cover the new HTTP contract introduced in Phase E of the
Integration Delivery refactor. The agent loop and turn worker are
mocked at ``app.routers.chat._routes.start_turn`` so we exercise the
request handler in isolation: validation, channel/session resolution,
throttle / pause / busy-session policy, and the 202 response shape.

End-to-end coverage of the worker → bus → outbox → drainer → renderer
flow lives in ``tests/integration/test_outbox_drainer_smoke.py`` and
``tests/integration/test_turn_worker.py``.
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


def _fake_handle():
    """Build a TurnHandle with all-fresh UUIDs."""
    from app.services.turns import TurnHandle
    return TurnHandle(
        session_id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        turn_id=uuid.uuid4(),
    )


class TestChat202:
    @pytest.fixture(autouse=True)
    def _mock_start_turn(self):
        with patch(
            "app.routers.chat._routes.start_turn", new_callable=AsyncMock
        ) as mock:
            mock.return_value = _fake_handle()
            self._mock = mock
            yield mock

    async def test_post_chat_returns_202_with_handle(self, client):
        resp = await client.post(
            "/chat",
            json={"message": "hi", "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 202
        body = resp.json()
        assert "session_id" in body
        assert "turn_id" in body
        assert "channel_id" in body
        # The handle fields are UUID strings — round-trip parses them.
        uuid.UUID(body["turn_id"])
        uuid.UUID(body["session_id"])
        uuid.UUID(body["channel_id"])

    async def test_post_chat_stream_returns_same_202(self, client):
        """``/chat/stream`` is a compat shim that returns the same 202."""
        resp = await client.post(
            "/chat/stream",
            json={"message": "hi", "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 202
        body = resp.json()
        assert "turn_id" in body

    async def test_start_turn_called_once_per_request(self, client):
        await client.post(
            "/chat",
            json={"message": "hello", "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        assert self._mock.await_count == 1
        kwargs = self._mock.await_args.kwargs
        assert kwargs["bot"].id == "test-bot"
        assert kwargs["user_message"] == "hello"

    async def test_passive_message_does_not_call_start_turn(self, client):
        resp = await client.post(
            "/chat",
            json={"message": "store me", "bot_id": "test-bot", "passive": True},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 202
        assert resp.json().get("passive") is True
        self._mock.assert_not_awaited()

    async def test_busy_session_returns_queued_202(self, client):
        """If start_turn raises SessionBusyError, the request returns a
        queued task id rather than failing."""
        from app.services.turns import SessionBusyError
        self._mock.side_effect = SessionBusyError("busy")

        resp = await client.post(
            "/chat",
            json={"message": "queue me", "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body.get("queued") is True
        assert "task_id" in body
