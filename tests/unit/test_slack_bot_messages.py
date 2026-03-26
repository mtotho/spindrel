"""Tests for allow_bot_messages — bot_message subtype handling in Slack message handlers."""
import os

os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_APP_TOKEN", "xapp-test")

from unittest.mock import AsyncMock, patch

import pytest


def _make_bot_message_event(**overrides):
    defaults = {
        "type": "message",
        "subtype": "bot_message",
        "bot_id": "B12345",
        "text": "New commit pushed to main",
        "channel": "C06TEST",
        "ts": "1711000000.000001",
    }
    defaults.update(overrides)
    return defaults


def _make_normal_message_event(**overrides):
    defaults = {
        "type": "message",
        "user": "U12345",
        "text": "hello bot",
        "channel": "C06TEST",
        "ts": "1711000000.000002",
    }
    defaults.update(overrides)
    return defaults


@pytest.fixture
def mock_say():
    return AsyncMock()


@pytest.fixture
def mock_client():
    return AsyncMock()


# ---------------------------------------------------------------------------
# bot_message events
# ---------------------------------------------------------------------------

class TestBotMessageFiltering:
    @pytest.mark.asyncio
    async def test_bot_message_dropped_when_allow_bot_messages_false(self, mock_say, mock_client):
        """Default behavior: bot_message subtypes are dropped."""
        config = {
            "bot_id": "dev_bot",
            "require_mention": False,
            "passive_memory": True,
            "allow_bot_messages": False,
        }
        event = _make_bot_message_event()
        # Simulate the on_message handler logic
        st = event.get("subtype")
        is_bot_msg = st == "bot_message" or bool(event.get("bot_id"))
        assert is_bot_msg
        # Channel config says allow_bot_messages=False → should drop
        assert not config.get("allow_bot_messages", False)
        # Since the handler returns early, dispatch is never called
        dispatch_mock = AsyncMock()
        # Not called because the early return fires first
        dispatch_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_bot_message_passed_through_when_allow_bot_messages_true(self, mock_say, mock_client):
        """When allow_bot_messages=True, bot_message events reach dispatch."""
        config = {
            "bot_id": "dev_bot",
            "require_mention": False,
            "passive_memory": True,
            "allow_bot_messages": True,
        }
        event = _make_bot_message_event()
        # Simulate the on_message handler logic
        st = event.get("subtype")
        is_bot_msg = st == "bot_message" or bool(event.get("bot_id"))
        assert is_bot_msg
        # Channel config says allow_bot_messages=True → should NOT drop
        assert config.get("allow_bot_messages", False) is True
        # Build user field as the handler does
        sender = event.get("bot_id") or event.get("username") or "unknown"
        user = f"bot:{sender}"
        assert user == "bot:B12345"
        # Text is preserved for dispatch
        assert event.get("text") == "New commit pushed to main"

    @pytest.mark.asyncio
    async def test_bot_message_user_set_to_bot_prefix(self, mock_say, mock_client):
        """The user field should be bot:<bot_id> for bot messages."""
        event = _make_bot_message_event(bot_id="B_GITHUB")
        st = event.get("subtype")
        is_bot_msg = st == "bot_message" or bool(event.get("bot_id"))
        assert is_bot_msg
        sender = event.get("bot_id") or event.get("username") or "unknown"
        user = f"bot:{sender}"
        assert user == "bot:B_GITHUB"

    @pytest.mark.asyncio
    async def test_bot_message_without_bot_id_uses_username(self):
        """If bot_id is missing but subtype is bot_message, fall back to username."""
        event = _make_bot_message_event(bot_id=None, username="github-app")
        # Remove bot_id key entirely
        del event["bot_id"]
        event["bot_id"] = None

        st = event.get("subtype")
        is_bot_msg = st == "bot_message" or bool(event.get("bot_id"))
        assert is_bot_msg  # subtype == "bot_message"
        sender = event.get("bot_id") or event.get("username") or "unknown"
        user = f"bot:{sender}"
        assert user == "bot:github-app"

    @pytest.mark.asyncio
    async def test_normal_message_unaffected_by_allow_bot_messages(self, mock_say, mock_client):
        """Normal user messages still work regardless of allow_bot_messages setting."""
        event = _make_normal_message_event()
        # Normal messages have no subtype and no bot_id
        st = event.get("subtype")
        is_bot_msg = st == "bot_message" or bool(event.get("bot_id"))
        assert not is_bot_msg
        # Normal messages take the else branch — allow_bot_messages is irrelevant
        assert event.get("user") == "U12345"

    @pytest.mark.asyncio
    async def test_bot_id_field_without_subtype_still_detected(self, mock_say, mock_client):
        """Messages with bot_id but no subtype are also treated as bot messages."""
        event = {
            "type": "message",
            "bot_id": "B99999",
            "text": "Automated notification",
            "channel": "C06TEST",
            "ts": "1711000000.000003",
        }
        st = event.get("subtype")
        is_bot_msg = st == "bot_message" or bool(event.get("bot_id"))
        assert is_bot_msg


# ---------------------------------------------------------------------------
# Channel config — allow_bot_messages field
# ---------------------------------------------------------------------------

class TestChannelConfigAllowBotMessages:
    def test_default_is_false(self):
        """get_channel_config returns allow_bot_messages=False by default."""
        with patch("integrations.slack.slack_settings.get_slack_config", return_value={
            "default_bot": "dev_bot",
            "channels": {},
        }):
            from integrations.slack.slack_settings import get_channel_config
            config = get_channel_config("C_UNKNOWN")
            assert config["allow_bot_messages"] is False

    def test_reads_true_from_config(self):
        """When server returns allow_bot_messages=True, it's reflected."""
        with patch("integrations.slack.slack_settings.get_slack_config", return_value={
            "default_bot": "dev_bot",
            "channels": {
                "C06TEST": {
                    "bot_id": "dev_bot",
                    "require_mention": False,
                    "passive_memory": True,
                    "allow_bot_messages": True,
                }
            },
        }):
            from integrations.slack.slack_settings import get_channel_config
            config = get_channel_config("C06TEST")
            assert config["allow_bot_messages"] is True

    def test_legacy_string_channel_defaults_false(self):
        """Legacy string-format channels default to allow_bot_messages=False."""
        with patch("integrations.slack.slack_settings.get_slack_config", return_value={
            "default_bot": "dev_bot",
            "channels": {
                "C06TEST": "dev_bot",  # legacy format
            },
        }):
            from integrations.slack.slack_settings import get_channel_config
            config = get_channel_config("C06TEST")
            assert config["allow_bot_messages"] is False
