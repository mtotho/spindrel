"""Tests for BlueBubbles dispatcher."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from integrations.bluebubbles.dispatcher import BlueBubblesDispatcher, _split_text


class TestSplitText:
    def test_short_text(self):
        assert _split_text("Hello") == ["Hello"]

    def test_exact_limit(self):
        text = "x" * 100
        assert _split_text(text, max_len=100) == [text]

    def test_split_at_newline(self):
        text = "line1\n" + "x" * 50
        chunks = _split_text(text, max_len=10)
        assert chunks[0] == "line1"
        assert len(chunks) > 1

    def test_split_long_no_newline(self):
        text = "x" * 200
        chunks = _split_text(text, max_len=100)
        assert len(chunks) == 2
        assert chunks[0] == "x" * 100
        assert chunks[1] == "x" * 100

    def test_newline_past_halfway_used(self):
        """Newline past the 50% mark should be used as split point."""
        # 60 chars of 'a', newline, then 50 chars of 'b'
        text = "a" * 60 + "\n" + "b" * 50
        chunks = _split_text(text, max_len=100)
        # Should split at the newline (position 60) since 60 > 100//2=50
        assert chunks[0] == "a" * 60
        assert chunks[1] == "b" * 50

    def test_newline_before_halfway_ignored(self):
        """Newline before the 50% mark should be ignored (hard split instead)."""
        text = "a" * 10 + "\n" + "b" * 150
        chunks = _split_text(text, max_len=100)
        # Newline at position 10 < 50, so hard split at 100
        assert len(chunks[0]) == 100


class TestBlueBubblesDispatcher:
    @pytest.fixture
    def dispatcher(self):
        return BlueBubblesDispatcher()

    @pytest.mark.asyncio
    async def test_deliver_missing_config(self, dispatcher):
        """deliver() with missing config should log warning and return."""
        task = MagicMock()
        task.id = "task-1"
        task.dispatch_config = {}
        await dispatcher.deliver(task, "Hello")

    @pytest.mark.asyncio
    async def test_deliver_missing_password(self, dispatcher):
        task = MagicMock()
        task.id = "task-1"
        task.dispatch_config = {"server_url": "http://bb", "chat_guid": "chat-1"}
        await dispatcher.deliver(task, "Hello")

    @pytest.mark.asyncio
    @patch("integrations.bluebubbles.dispatcher._bb_send", new_callable=AsyncMock)
    async def test_deliver_success(self, mock_send, dispatcher):
        mock_send.return_value = True

        task = MagicMock()
        task.id = "task-1"
        task.session_id = "sess-1"
        task.client_id = "bb:chat-1"
        task.bot_id = "bot-1"
        task.dispatch_config = {
            "server_url": "http://bb:1234",
            "password": "pass123",
            "chat_guid": "iMessage;-;+15551234567",
        }

        with patch("app.services.sessions.store_dispatch_echo", new_callable=AsyncMock):
            await dispatcher.deliver(task, "Agent response")

        mock_send.assert_called_once_with(
            "http://bb:1234", "pass123", "iMessage;-;+15551234567", "Agent response",
            method=None,
        )

    @pytest.mark.asyncio
    @patch("integrations.bluebubbles.dispatcher._bb_send", new_callable=AsyncMock)
    async def test_deliver_with_delegation_prefix(self, mock_send, dispatcher):
        mock_send.return_value = True

        task = MagicMock()
        task.id = "task-1"
        task.session_id = "sess-1"
        task.client_id = "bb:chat-1"
        task.bot_id = "bot-1"
        task.dispatch_config = {
            "server_url": "http://bb:1234",
            "password": "pass123",
            "chat_guid": "chat-1",
        }

        with patch("app.services.sessions.store_dispatch_echo", new_callable=AsyncMock):
            await dispatcher.deliver(
                task, "Result",
                extra_metadata={"delegated_by_display": "orchestrator"},
            )

        sent_text = mock_send.call_args[0][3]
        assert "[Delegated by orchestrator]" in sent_text

    @pytest.mark.asyncio
    @patch("integrations.bluebubbles.dispatcher._bb_send", new_callable=AsyncMock)
    async def test_deliver_send_failure(self, mock_send, dispatcher):
        mock_send.return_value = False

        task = MagicMock()
        task.id = "task-1"
        task.dispatch_config = {
            "server_url": "http://bb:1234",
            "password": "pass123",
            "chat_guid": "chat-1",
        }
        await dispatcher.deliver(task, "Agent response")

    @pytest.mark.asyncio
    @patch("integrations.bluebubbles.dispatcher._bb_send", new_callable=AsyncMock)
    async def test_post_message_success(self, mock_send, dispatcher):
        mock_send.return_value = True

        result = await dispatcher.post_message(
            {"server_url": "http://bb:1234", "password": "pass123", "chat_guid": "chat-1"},
            "Hello from post_message",
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_post_message_missing_config(self, dispatcher):
        result = await dispatcher.post_message({}, "Hello")
        assert result is False

    @pytest.mark.asyncio
    @patch("integrations.bluebubbles.dispatcher._bb_send", new_callable=AsyncMock)
    async def test_post_message_failure(self, mock_send, dispatcher):
        mock_send.return_value = False

        result = await dispatcher.post_message(
            {"server_url": "http://bb:1234", "password": "pass123", "chat_guid": "chat-1"},
            "Hello",
        )
        assert result is False

    @pytest.mark.asyncio
    @patch("integrations.bluebubbles.dispatcher._bb_send", new_callable=AsyncMock)
    async def test_notify_start_is_noop(self, mock_send, dispatcher):
        """notify_start is a no-op for iMessage (no typing indicator, avoids echo noise)."""
        task = MagicMock()
        task.dispatch_config = {
            "server_url": "http://bb:1234",
            "password": "pass123",
            "chat_guid": "chat-1",
        }
        await dispatcher.notify_start(task)
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    @patch("integrations.bluebubbles.dispatcher._bb_send", new_callable=AsyncMock)
    async def test_request_approval(self, mock_send, dispatcher):
        mock_send.return_value = True

        await dispatcher.request_approval(
            dispatch_config={"server_url": "http://bb:1234", "password": "pass123", "chat_guid": "chat-1"},
            approval_id="appr-123",
            bot_id="bot-1",
            tool_name="exec_command",
            arguments={"command": "ls -la"},
            reason="Dangerous tool",
        )
        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][3]
        assert "exec_command" in sent_text
        assert "appr-123" in sent_text
        assert "Dangerous tool" in sent_text

    @pytest.mark.asyncio
    async def test_request_approval_missing_config(self, dispatcher):
        await dispatcher.request_approval(
            dispatch_config={},
            approval_id="appr-123",
            bot_id="bot-1",
            tool_name="exec_command",
            arguments={},
            reason=None,
        )  # Should not raise

    @pytest.mark.asyncio
    @patch("integrations.bluebubbles.dispatcher._bb_send", new_callable=AsyncMock)
    async def test_deliver_with_send_method(self, mock_send, dispatcher):
        """Per-binding send_method in dispatch_config is passed to _bb_send."""
        mock_send.return_value = True

        task = MagicMock()
        task.id = "task-1"
        task.session_id = "sess-1"
        task.client_id = "bb:chat-1"
        task.bot_id = "bot-1"
        task.dispatch_config = {
            "server_url": "http://bb:1234",
            "password": "pass123",
            "chat_guid": "iMessage;-;+15551234567",
            "send_method": "private-api",
        }

        with patch("app.services.sessions.store_dispatch_echo", new_callable=AsyncMock):
            await dispatcher.deliver(task, "Agent response")

        mock_send.assert_called_once_with(
            "http://bb:1234", "pass123", "iMessage;-;+15551234567", "Agent response",
            method="private-api",
        )

    @pytest.mark.asyncio
    @patch("integrations.bluebubbles.dispatcher._bb_send", new_callable=AsyncMock)
    async def test_post_message_with_send_method(self, mock_send, dispatcher):
        """Per-binding send_method passed through post_message."""
        mock_send.return_value = True

        result = await dispatcher.post_message(
            {"server_url": "http://bb:1234", "password": "pass123",
             "chat_guid": "chat-1", "send_method": "apple-script"},
            "Hello",
        )
        assert result is True
        mock_send.assert_called_once_with(
            "http://bb:1234", "pass123", "chat-1", "Hello",
            method="apple-script",
        )
