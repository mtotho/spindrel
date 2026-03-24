"""Tests for SlackDispatcher — post_message and deliver with client_actions.

The core behavior being tested: when client_actions contain upload_image entries,
SlackDispatcher uploads them to Slack after posting the text message.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_dispatch_config(**overrides):
    defaults = {
        "channel_id": "C06RY3YBSLE",
        "thread_ts": "1234567890.123456",
        "token": "xoxb-test-token",
    }
    defaults.update(overrides)
    return defaults


def _make_upload_action(**overrides):
    defaults = {
        "type": "upload_image",
        "data": "aW1hZ2VieXRlcw==",  # base64("imagebytes")
        "filename": "generated.png",
        "caption": "A cool image",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# post_message
# ---------------------------------------------------------------------------

class TestSlackDispatcherPostMessage:
    @pytest.mark.asyncio
    async def test_posts_text_and_uploads_images(self):
        from integrations.slack.dispatcher import SlackDispatcher

        dispatcher = SlackDispatcher()
        config = _make_dispatch_config()
        actions = [_make_upload_action()]

        with patch("integrations.slack.dispatcher.post_message", new_callable=AsyncMock, return_value=True) as mock_post, \
             patch("integrations.slack.dispatcher.bot_attribution", return_value={"username": "child-bot"}) as mock_attr, \
             patch("integrations.slack.uploads.upload_image", new_callable=AsyncMock) as mock_upload:
            ok = await dispatcher.post_message(
                config, "here is your image",
                bot_id="child-bot",
                reply_in_thread=True,
                client_actions=actions,
            )

        assert ok is True
        mock_post.assert_awaited_once_with(
            "xoxb-test-token", "C06RY3YBSLE", "here is your image",
            thread_ts="1234567890.123456",
            reply_in_thread=True,
            username="child-bot",
        )
        mock_upload.assert_awaited_once_with(
            token="xoxb-test-token",
            channel_id="C06RY3YBSLE",
            thread_ts="1234567890.123456",
            reply_in_thread=True,
            action=actions[0],
        )

    @pytest.mark.asyncio
    async def test_no_upload_when_text_post_fails(self):
        """If posting the text message fails, don't attempt image uploads."""
        from integrations.slack.dispatcher import SlackDispatcher

        dispatcher = SlackDispatcher()
        config = _make_dispatch_config()
        actions = [_make_upload_action()]

        with patch("integrations.slack.dispatcher.post_message", new_callable=AsyncMock, return_value=False), \
             patch("integrations.slack.dispatcher.bot_attribution", return_value={}), \
             patch("integrations.slack.uploads.upload_image", new_callable=AsyncMock) as mock_upload:
            ok = await dispatcher.post_message(
                config, "text",
                bot_id="child-bot",
                client_actions=actions,
            )

        assert ok is False
        mock_upload.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_upload_when_no_client_actions(self):
        """No client_actions → text posted, no upload attempted."""
        from integrations.slack.dispatcher import SlackDispatcher

        dispatcher = SlackDispatcher()
        config = _make_dispatch_config()

        with patch("integrations.slack.dispatcher.post_message", new_callable=AsyncMock, return_value=True), \
             patch("integrations.slack.dispatcher.bot_attribution", return_value={}), \
             patch("integrations.slack.uploads.upload_image", new_callable=AsyncMock) as mock_upload:
            ok = await dispatcher.post_message(
                config, "just text",
                bot_id="child-bot",
                client_actions=None,
            )

        assert ok is True
        mock_upload.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_non_image_actions(self):
        """Only upload_image actions trigger upload; others are ignored."""
        from integrations.slack.dispatcher import SlackDispatcher

        dispatcher = SlackDispatcher()
        config = _make_dispatch_config()
        actions = [
            {"type": "play_audio", "data": "audio-data"},
            _make_upload_action(),
            {"type": "run_command", "command": "ls"},
        ]

        with patch("integrations.slack.dispatcher.post_message", new_callable=AsyncMock, return_value=True), \
             patch("integrations.slack.dispatcher.bot_attribution", return_value={}), \
             patch("integrations.slack.uploads.upload_image", new_callable=AsyncMock) as mock_upload:
            await dispatcher.post_message(
                config, "text",
                bot_id="child-bot",
                client_actions=actions,
            )

        # Only the upload_image action should trigger upload
        assert mock_upload.await_count == 1

    @pytest.mark.asyncio
    async def test_missing_channel_id_returns_false(self):
        from integrations.slack.dispatcher import SlackDispatcher

        dispatcher = SlackDispatcher()
        config = {"token": "xoxb-test", "thread_ts": "123"}  # no channel_id

        with patch("integrations.slack.dispatcher.post_message", new_callable=AsyncMock) as mock_post:
            ok = await dispatcher.post_message(config, "text")

        assert ok is False
        mock_post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_token_returns_false(self):
        from integrations.slack.dispatcher import SlackDispatcher

        dispatcher = SlackDispatcher()
        config = {"channel_id": "C123"}  # no token

        with patch("integrations.slack.dispatcher.post_message", new_callable=AsyncMock) as mock_post:
            ok = await dispatcher.post_message(config, "text")

        assert ok is False
        mock_post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_multiple_images_all_uploaded(self):
        from integrations.slack.dispatcher import SlackDispatcher

        dispatcher = SlackDispatcher()
        config = _make_dispatch_config()
        actions = [
            _make_upload_action(filename="img1.png"),
            _make_upload_action(filename="img2.png"),
            _make_upload_action(filename="img3.png"),
        ]

        with patch("integrations.slack.dispatcher.post_message", new_callable=AsyncMock, return_value=True), \
             patch("integrations.slack.dispatcher.bot_attribution", return_value={}), \
             patch("integrations.slack.uploads.upload_image", new_callable=AsyncMock) as mock_upload:
            await dispatcher.post_message(
                config, "three images",
                bot_id="child-bot",
                client_actions=actions,
            )

        assert mock_upload.await_count == 3


# ---------------------------------------------------------------------------
# deliver (task worker path)
# ---------------------------------------------------------------------------

class TestSlackDispatcherDeliver:
    def _make_task(self, **overrides):
        task = MagicMock()
        task.id = overrides.get("id", uuid.uuid4())
        task.bot_id = overrides.get("bot_id", "child-bot")
        task.client_id = overrides.get("client_id", "slack:C123")
        task.session_id = overrides.get("session_id", uuid.uuid4())
        task.dispatch_config = overrides.get("dispatch_config", _make_dispatch_config())
        return task

    @pytest.mark.asyncio
    async def test_deliver_posts_text_and_uploads(self):
        from integrations.slack.dispatcher import SlackDispatcher

        dispatcher = SlackDispatcher()
        task = self._make_task()
        actions = [_make_upload_action()]

        with patch("integrations.slack.dispatcher.post_message", new_callable=AsyncMock, return_value=True), \
             patch("integrations.slack.dispatcher.bot_attribution", return_value={}), \
             patch("integrations.slack.uploads.upload_image", new_callable=AsyncMock) as mock_upload, \
             patch("app.services.sessions.store_dispatch_echo", new_callable=AsyncMock):
            await dispatcher.deliver(task, "task result", client_actions=actions)

        mock_upload.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_deliver_no_upload_on_post_failure(self):
        """If any text chunk fails to post, skip uploads."""
        from integrations.slack.dispatcher import SlackDispatcher

        dispatcher = SlackDispatcher()
        task = self._make_task()
        actions = [_make_upload_action()]

        with patch("integrations.slack.dispatcher.post_message", new_callable=AsyncMock, return_value=False), \
             patch("integrations.slack.dispatcher.bot_attribution", return_value={}), \
             patch("integrations.slack.uploads.upload_image", new_callable=AsyncMock) as mock_upload:
            await dispatcher.deliver(task, "will fail", client_actions=actions)

        mock_upload.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_deliver_no_client_actions(self):
        """deliver() with no client_actions still posts text normally."""
        from integrations.slack.dispatcher import SlackDispatcher

        dispatcher = SlackDispatcher()
        task = self._make_task()

        with patch("integrations.slack.dispatcher.post_message", new_callable=AsyncMock, return_value=True) as mock_post, \
             patch("integrations.slack.dispatcher.bot_attribution", return_value={}), \
             patch("app.services.sessions.store_dispatch_echo", new_callable=AsyncMock):
            await dispatcher.deliver(task, "just text", client_actions=None)

        mock_post.assert_awaited_once()


# ---------------------------------------------------------------------------
# Dispatcher registry
# ---------------------------------------------------------------------------

class TestDispatcherRegistry:
    def test_get_returns_registered(self):
        from app.agent.dispatchers import get, register

        mock = MagicMock()
        register("test-type", mock)
        assert get("test-type") is mock

    def test_get_unknown_falls_back_to_none(self):
        from app.agent.dispatchers import get

        dispatcher = get("completely-unknown-type")
        # Should be the NoneDispatcher (or equivalent), not crash
        assert dispatcher is not None

    def test_get_none_returns_none_dispatcher(self):
        from app.agent.dispatchers import get

        dispatcher = get(None)
        assert dispatcher is not None

    @pytest.mark.asyncio
    async def test_none_dispatcher_post_message_returns_false(self):
        from app.agent.dispatchers import get

        dispatcher = get(None)
        result = await dispatcher.post_message({}, "text", client_actions=[])
        assert result is False
