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
    @pytest.fixture(autouse=True)
    def _mock_run(self):
        """Mock the agent run() function to avoid real LLM calls."""
        with patch("app.routers.chat._routes.run", new_callable=AsyncMock) as mock:
            mock.return_value = FakeRunResult()
            self._mock_run_fn = mock
            yield mock

    @pytest.fixture(autouse=True)
    def _mock_persist(self):
        """Mock persist_turn to avoid complex DB operations."""
        with patch("app.routers.chat._routes.persist_turn", new_callable=AsyncMock):
            yield

    @pytest.fixture(autouse=True)
    def _mock_compact(self):
        """Mock maybe_compact to avoid background compaction."""
        with patch("app.routers.chat._routes.maybe_compact"):
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
# Integration mirroring (/chat and /chat/stream)
# ---------------------------------------------------------------------------

def _make_channel(integration=None, dispatch_config=None):
    """Create a fake Channel object for mirror tests."""
    ch = MagicMock()
    ch.id = uuid.uuid4()
    ch.integration = integration
    ch.dispatch_config = dispatch_config
    return ch


class TestChatMirror:
    """Tests that UI messages are mirrored to connected integrations."""

    @pytest.fixture(autouse=True)
    def _mock_run(self):
        with patch("app.routers.chat._routes.run", new_callable=AsyncMock) as mock:
            mock.return_value = FakeRunResult(response="Bot reply")
            self._mock_run_fn = mock
            yield mock

    @pytest.fixture(autouse=True)
    def _mock_persist(self):
        with patch("app.routers.chat._routes.persist_turn", new_callable=AsyncMock):
            yield

    @pytest.fixture(autouse=True)
    def _mock_compact(self):
        with patch("app.routers.chat._routes.maybe_compact"):
            yield

    async def test_chat_mirrors_to_slack(self, client):
        """POST /chat mirrors user message + response to Slack when channel has integration."""
        ch = _make_channel(integration="slack", dispatch_config={"channel_id": "C123", "token": "xoxb-test"})
        mock_dispatcher = MagicMock()
        mock_dispatcher.post_message = AsyncMock(return_value=True)

        with (
            patch("app.routers.chat._routes._resolve_channel_and_session", new_callable=AsyncMock,
                  return_value=(ch, uuid.uuid4(), [], False)),
            patch("app.agent.dispatchers.get", return_value=mock_dispatcher),
        ):
            # No dispatch_config on request → UI request → should mirror
            resp = await client.post(
                "/chat",
                json={"message": "Hello from UI", "bot_id": "test-bot"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        # Should have been called twice: once for user msg, once for response
        assert mock_dispatcher.post_message.await_count == 2
        calls = mock_dispatcher.post_message.call_args_list
        # First call: user message (prefixed, no bot_id, top-level)
        assert calls[0].args[1] == "[web] Hello from UI"
        assert calls[0].kwargs.get("bot_id") is None
        assert calls[0].kwargs.get("reply_in_thread") is False
        # Second call: bot response (top-level, with bot attribution)
        assert calls[1].args[1] == "Bot reply"
        assert calls[1].kwargs.get("bot_id") == "test-bot"
        assert calls[1].kwargs.get("reply_in_thread") is False

    async def test_chat_no_mirror_when_dispatch_config_present(self, client):
        """POST /chat skips mirroring when request carries dispatch_config (integration handles delivery)."""
        ch = _make_channel(integration="slack", dispatch_config={"channel_id": "C123", "token": "xoxb-test"})
        mock_dispatcher = MagicMock()
        mock_dispatcher.post_message = AsyncMock(return_value=True)

        with (
            patch("app.routers.chat._routes._resolve_channel_and_session", new_callable=AsyncMock,
                  return_value=(ch, uuid.uuid4(), [], True)),
            patch("app.agent.dispatchers.get", return_value=mock_dispatcher),
        ):
            # dispatch_config on request → integration caller → skip mirror
            resp = await client.post(
                "/chat",
                json={
                    "message": "From Slack", "bot_id": "test-bot",
                    "dispatch_config": {"channel_id": "C123", "token": "xoxb-test"},
                },
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        mock_dispatcher.post_message.assert_not_awaited()

    async def test_chat_mirrors_even_with_integration_client_id(self, client):
        """POST /chat mirrors when client_id looks like integration but no dispatch_config."""
        ch = _make_channel(integration="slack", dispatch_config={"channel_id": "C123", "token": "xoxb-test"})
        mock_dispatcher = MagicMock()
        mock_dispatcher.post_message = AsyncMock(return_value=True)

        with (
            patch("app.routers.chat._routes._resolve_channel_and_session", new_callable=AsyncMock,
                  return_value=(ch, uuid.uuid4(), [], True)),
            patch("app.agent.dispatchers.get", return_value=mock_dispatcher),
        ):
            # UI on a Slack channel sends client_id="slack:C123" but no dispatch_config
            resp = await client.post(
                "/chat",
                json={"message": "From UI", "bot_id": "test-bot", "client_id": "slack:C123"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        assert mock_dispatcher.post_message.await_count == 2

    async def test_chat_no_mirror_without_integration(self, client):
        """POST /chat doesn't try to mirror when channel has no integration."""
        ch = _make_channel(integration=None, dispatch_config=None)

        with (
            patch("app.routers.chat._routes._resolve_channel_and_session", new_callable=AsyncMock,
                  return_value=(ch, uuid.uuid4(), [], False)),
            patch("app.agent.dispatchers.get") as mock_get,
        ):
            resp = await client.post(
                "/chat",
                json={"message": "Hello", "bot_id": "test-bot"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        mock_get.assert_not_called()

    async def test_chat_no_mirror_on_empty_response(self, client):
        """POST /chat mirrors user message but not an empty response."""
        ch = _make_channel(integration="slack", dispatch_config={"channel_id": "C123", "token": "xoxb-test"})
        mock_dispatcher = MagicMock()
        mock_dispatcher.post_message = AsyncMock(return_value=True)
        self._mock_run_fn.return_value = FakeRunResult(response="")

        with (
            patch("app.routers.chat._routes._resolve_channel_and_session", new_callable=AsyncMock,
                  return_value=(ch, uuid.uuid4(), [], False)),
            patch("app.agent.dispatchers.get", return_value=mock_dispatcher),
        ):
            resp = await client.post(
                "/chat",
                json={"message": "Hello", "bot_id": "test-bot"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        # Only user message mirrored, not the empty response
        assert mock_dispatcher.post_message.await_count == 1


class TestChatStreamMirror:
    """Tests that /chat/stream mirrors messages to connected integrations."""

    @pytest.fixture(autouse=True)
    def _mock_persist(self):
        with patch("app.routers.chat._routes.persist_turn", new_callable=AsyncMock):
            yield

    @pytest.fixture(autouse=True)
    def _mock_compact(self):
        with patch("app.routers.chat._routes.maybe_compact"):
            yield

    @pytest.fixture(autouse=True)
    def _mock_session_locks(self):
        with patch("app.routers.chat._routes.session_locks") as mock:
            mock.acquire.return_value = True
            yield mock

    async def test_stream_mirrors_to_slack(self, client):
        """POST /chat/stream mirrors user message + response to Slack."""
        ch = _make_channel(integration="slack", dispatch_config={"channel_id": "C123", "token": "xoxb-test"})
        mock_dispatcher = MagicMock()
        mock_dispatcher.post_message = AsyncMock(return_value=True)

        async def fake_stream(*a, **kw):
            yield {"type": "chunk", "text": "Bot "}
            yield {"type": "chunk", "text": "reply"}
            yield {"type": "response", "text": "Bot reply", "client_actions": []}

        with (
            patch("app.routers.chat._routes._resolve_channel_and_session", new_callable=AsyncMock,
                  return_value=(ch, uuid.uuid4(), [], False)),
            patch("app.routers.chat._routes.run_stream", side_effect=fake_stream),
            patch("app.agent.dispatchers.get", return_value=mock_dispatcher),
        ):
            resp = await client.post(
                "/chat/stream",
                json={"message": "Hello from UI", "bot_id": "test-bot"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        assert mock_dispatcher.post_message.await_count == 2
        calls = mock_dispatcher.post_message.call_args_list
        # User message (prefixed, top-level)
        assert calls[0].args[1] == "[web] Hello from UI"
        assert calls[0].kwargs.get("reply_in_thread") is False
        # Bot response (top-level, with bot attribution)
        assert calls[1].args[1] == "Bot reply"
        assert calls[1].kwargs.get("bot_id") == "test-bot"
        assert calls[1].kwargs.get("reply_in_thread") is False

    async def test_stream_no_mirror_when_dispatch_config_present(self, client):
        """POST /chat/stream skips mirroring when request carries dispatch_config."""
        ch = _make_channel(integration="slack", dispatch_config={"channel_id": "C123", "token": "xoxb-test"})
        mock_dispatcher = MagicMock()
        mock_dispatcher.post_message = AsyncMock(return_value=True)

        async def fake_stream(*a, **kw):
            yield {"type": "response", "text": "reply", "client_actions": []}

        with (
            patch("app.routers.chat._routes._resolve_channel_and_session", new_callable=AsyncMock,
                  return_value=(ch, uuid.uuid4(), [], True)),
            patch("app.routers.chat._routes.run_stream", side_effect=fake_stream),
            patch("app.agent.dispatchers.get", return_value=mock_dispatcher),
        ):
            resp = await client.post(
                "/chat/stream",
                json={
                    "message": "From Slack", "bot_id": "test-bot",
                    "dispatch_config": {"channel_id": "C123", "token": "xoxb-test"},
                },
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        mock_dispatcher.post_message.assert_not_awaited()

    async def test_stream_no_mirror_without_integration(self, client):
        """POST /chat/stream doesn't mirror when channel has no integration."""
        ch = _make_channel(integration=None, dispatch_config=None)

        async def fake_stream(*a, **kw):
            yield {"type": "response", "text": "reply", "client_actions": []}

        with (
            patch("app.routers.chat._routes._resolve_channel_and_session", new_callable=AsyncMock,
                  return_value=(ch, uuid.uuid4(), [], False)),
            patch("app.routers.chat._routes.run_stream", side_effect=fake_stream),
            patch("app.agent.dispatchers.get") as mock_get,
        ):
            resp = await client.post(
                "/chat/stream",
                json={"message": "Hello", "bot_id": "test-bot"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        mock_get.assert_not_called()

    async def test_stream_captures_response_with_client_actions(self, client):
        """POST /chat/stream mirrors response including client_actions."""
        ch = _make_channel(integration="slack", dispatch_config={"channel_id": "C123", "token": "xoxb-test"})
        mock_dispatcher = MagicMock()
        mock_dispatcher.post_message = AsyncMock(return_value=True)
        actions = [{"action": "tts", "text": "hello"}]

        async def fake_stream(*a, **kw):
            yield {"type": "response", "text": "Speak this", "client_actions": actions}

        with (
            patch("app.routers.chat._routes._resolve_channel_and_session", new_callable=AsyncMock,
                  return_value=(ch, uuid.uuid4(), [], False)),
            patch("app.routers.chat._routes.run_stream", side_effect=fake_stream),
            patch("app.agent.dispatchers.get", return_value=mock_dispatcher),
        ):
            resp = await client.post(
                "/chat/stream",
                json={"message": "Speak", "bot_id": "test-bot"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        # Response mirror should include client_actions
        response_call = mock_dispatcher.post_message.call_args_list[1]
        assert response_call.kwargs.get("client_actions") == actions

    async def test_stream_mirror_failure_does_not_break_response(self, client):
        """Mirror failure is logged but doesn't affect the SSE response."""
        ch = _make_channel(integration="slack", dispatch_config={"channel_id": "C123", "token": "xoxb-test"})
        mock_dispatcher = MagicMock()
        mock_dispatcher.post_message = AsyncMock(side_effect=Exception("Slack API down"))

        async def fake_stream(*a, **kw):
            yield {"type": "response", "text": "reply", "client_actions": []}

        with (
            patch("app.routers.chat._routes._resolve_channel_and_session", new_callable=AsyncMock,
                  return_value=(ch, uuid.uuid4(), [], False)),
            patch("app.routers.chat._routes.run_stream", side_effect=fake_stream),
            patch("app.agent.dispatchers.get", return_value=mock_dispatcher),
        ):
            resp = await client.post(
                "/chat/stream",
                json={"message": "Hello", "bot_id": "test-bot"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        # Stream should still complete successfully despite mirror failure
        body = resp.text
        assert "error" not in body.lower() or "Mirror" not in body


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
