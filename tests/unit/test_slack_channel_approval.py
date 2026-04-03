"""Tests for Slack channel creation approval gate.

Tests cover:
- Known channels bypass the gate
- Unknown channels with approval disabled bypass the gate
- Unknown channels with approval enabled post Block Kit prompt
- Approved channels allow through on next message
- Denied channels are silent, but @mention re-prompts
- Pending channels stay pending (no duplicate prompts)
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Set required Slack env vars before any imports that trigger slack_settings
os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test-token")
os.environ.setdefault("SLACK_APP_TOKEN", "xapp-test-token")
os.environ.setdefault("AGENT_API_KEY", "test-key")
os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest

# Ensure the Slack integration directory is on the path for same-dir imports
_SLACK_DIR = str(Path(__file__).resolve().parent.parent.parent / "integrations" / "slack")
if _SLACK_DIR not in sys.path:
    sys.path.insert(0, _SLACK_DIR)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_client():
    """Create a mock Slack client with chat_postMessage."""
    client = AsyncMock()
    client.chat_postMessage = AsyncMock(return_value={"ok": True})
    return client


def _mock_config(known_channels: dict | None = None):
    """Return a mock slack config dict."""
    return {
        "default_bot": "default",
        "channels": known_channels or {},
        "bots": {},
    }


# ---------------------------------------------------------------------------
# Tests for _should_gate_channel
# ---------------------------------------------------------------------------

class TestShouldGateChannel:
    def test_disabled_by_default(self):
        """Approval disabled → gate returns False."""
        from message_handlers import _should_gate_channel
        with patch("slack_settings.get_slack_config", return_value=_mock_config()), \
             patch.dict(os.environ, {"SLACK_REQUIRE_CHANNEL_APPROVAL": "false"}), \
             patch("app.services.integration_settings.get_value", side_effect=ImportError):
            assert _should_gate_channel("CUNKNOWN") is False

    def test_enabled_unknown_channel(self):
        """Approval enabled + unknown channel → gate returns True."""
        from message_handlers import _should_gate_channel
        with patch("slack_settings.get_slack_config", return_value=_mock_config()), \
             patch("app.services.integration_settings.get_value", return_value="true"):
            assert _should_gate_channel("CUNKNOWN") is True

    def test_enabled_known_channel(self):
        """Approval enabled + known channel → gate returns False."""
        from message_handlers import _should_gate_channel
        known = {"CKNOWN001": {"bot_id": "bot-a", "require_mention": True}}
        with patch("slack_settings.get_slack_config", return_value=_mock_config(known)), \
             patch("app.services.integration_settings.get_value", return_value="true"):
            assert _should_gate_channel("CKNOWN001") is False

    def test_enabled_via_env_var_fallback(self):
        """When integration_settings import fails, fall back to env var."""
        from message_handlers import _should_gate_channel
        with patch("slack_settings.get_slack_config", return_value=_mock_config()), \
             patch.dict(os.environ, {"SLACK_REQUIRE_CHANNEL_APPROVAL": "true"}), \
             patch("app.services.integration_settings.get_value", side_effect=ImportError):
            assert _should_gate_channel("CUNKNOWN") is True


# ---------------------------------------------------------------------------
# Tests for check_or_prompt_approval
# ---------------------------------------------------------------------------

class TestCheckOrPromptApproval:
    @pytest.mark.asyncio
    async def test_approved_channel_allows_through(self):
        """A channel with status='approved' should return True immediately."""
        from channel_approval import check_or_prompt_approval
        client = _make_mock_client()
        with patch("channel_approval.get_global_setting", return_value={"CAPPROVED": "approved"}):
            result = await check_or_prompt_approval("CAPPROVED", "bot-a", client, mentioned=False)
        assert result is True
        client.chat_postMessage.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_channel_posts_prompt(self):
        """An unknown channel should post a Block Kit prompt and return False."""
        from channel_approval import check_or_prompt_approval
        client = _make_mock_client()
        with patch("channel_approval.get_global_setting", return_value={}), \
             patch("channel_approval.set_global_setting") as mock_set:
            result = await check_or_prompt_approval("CUNKNOWN", "bot-a", client, mentioned=False)
        assert result is False
        client.chat_postMessage.assert_called_once()
        call_kwargs = client.chat_postMessage.call_args[1]
        assert call_kwargs["channel"] == "CUNKNOWN"
        # Should have blocks with approve/deny buttons
        blocks = call_kwargs["blocks"]
        action_block = [b for b in blocks if b["type"] == "actions"][0]
        action_ids = [e["action_id"] for e in action_block["elements"]]
        assert "approve_channel_create" in action_ids
        assert "deny_channel_create" in action_ids
        # Should have set status to pending
        mock_set.assert_called_once()
        args = mock_set.call_args[0]
        assert args[0] == "channel_approvals"
        assert args[1]["CUNKNOWN"] == "pending"

    @pytest.mark.asyncio
    async def test_denied_channel_silent_without_mention(self):
        """A denied channel without @mention should return False silently."""
        from channel_approval import check_or_prompt_approval
        client = _make_mock_client()
        with patch("channel_approval.get_global_setting", return_value={"CDENIED": "denied"}):
            result = await check_or_prompt_approval("CDENIED", "bot-a", client, mentioned=False)
        assert result is False
        client.chat_postMessage.assert_not_called()

    @pytest.mark.asyncio
    async def test_denied_channel_reprompts_on_mention(self):
        """A denied channel with @mention should re-post the approval prompt."""
        from channel_approval import check_or_prompt_approval
        client = _make_mock_client()
        with patch("channel_approval.get_global_setting", return_value={"CDENIED": "denied"}), \
             patch("channel_approval.set_global_setting") as mock_set:
            result = await check_or_prompt_approval("CDENIED", "bot-a", client, mentioned=True)
        assert result is False
        client.chat_postMessage.assert_called_once()
        # Should have reset status to pending
        mock_set.assert_called_once()
        args = mock_set.call_args[0]
        assert args[1]["CDENIED"] == "pending"

    @pytest.mark.asyncio
    async def test_pending_channel_no_duplicate_prompt(self):
        """A pending channel should return False without posting again."""
        from channel_approval import check_or_prompt_approval
        client = _make_mock_client()
        with patch("channel_approval.get_global_setting", return_value={"CPENDING": "pending"}):
            result = await check_or_prompt_approval("CPENDING", "bot-a", client, mentioned=False)
        assert result is False
        client.chat_postMessage.assert_not_called()

    @pytest.mark.asyncio
    async def test_pending_channel_no_duplicate_even_on_mention(self):
        """A pending channel should not post another prompt even on @mention."""
        from channel_approval import check_or_prompt_approval
        client = _make_mock_client()
        with patch("channel_approval.get_global_setting", return_value={"CPENDING": "pending"}):
            result = await check_or_prompt_approval("CPENDING", "bot-a", client, mentioned=True)
        assert result is False
        client.chat_postMessage.assert_not_called()


# ---------------------------------------------------------------------------
# Tests for approval action handlers
# ---------------------------------------------------------------------------

class TestChannelApprovalHandlers:
    @pytest.mark.asyncio
    async def test_approve_creates_channel(self):
        """Approve action should call ensure_channel and set status to approved."""
        from channel_approval_handlers import register_channel_approval_handlers

        # Build a mock app that captures registered handlers
        handlers = {}
        mock_app = MagicMock()

        def capture_action(action_id):
            def decorator(fn):
                handlers[action_id] = fn
                return fn
            return decorator

        mock_app.action = capture_action
        register_channel_approval_handlers(mock_app)

        assert "approve_channel_create" in handlers

        value = json.dumps({"channel": "CNEW001", "bot_id": "bot-a"})
        body = {
            "actions": [{"value": value}],
            "user": {"id": "U123"},
            "message": {"blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": "test"}},
                {"type": "actions", "elements": []},
            ]},
        }
        ack = AsyncMock()
        respond = AsyncMock()

        with patch("agent_client.ensure_channel", new_callable=AsyncMock, return_value={"id": "test"}) as mock_ensure, \
             patch("channel_approval._set_approval") as mock_set:
            await handlers["approve_channel_create"](ack=ack, body=body, respond=respond)

        ack.assert_called_once()
        mock_ensure.assert_called_once_with("slack:CNEW001", "bot-a")
        mock_set.assert_called_once_with("CNEW001", "approved")
        respond.assert_called_once()
        call_kwargs = respond.call_args[1]
        assert "approved" in call_kwargs["text"].lower()
        # Actions block should be removed
        for block in call_kwargs["blocks"]:
            assert block["type"] != "actions"

    @pytest.mark.asyncio
    async def test_deny_sets_status(self):
        """Deny action should set status to denied."""
        from channel_approval_handlers import register_channel_approval_handlers

        handlers = {}
        mock_app = MagicMock()

        def capture_action(action_id):
            def decorator(fn):
                handlers[action_id] = fn
                return fn
            return decorator

        mock_app.action = capture_action
        register_channel_approval_handlers(mock_app)

        assert "deny_channel_create" in handlers

        value = json.dumps({"channel": "CNEW001", "bot_id": "bot-a"})
        body = {
            "actions": [{"value": value}],
            "user": {"id": "U123"},
            "message": {"blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": "test"}},
                {"type": "actions", "elements": []},
            ]},
        }
        ack = AsyncMock()
        respond = AsyncMock()

        with patch("channel_approval._set_approval") as mock_set:
            await handlers["deny_channel_create"](ack=ack, body=body, respond=respond)

        ack.assert_called_once()
        mock_set.assert_called_once_with("CNEW001", "denied")
        respond.assert_called_once()
        call_kwargs = respond.call_args[1]
        assert "denied" in call_kwargs["text"].lower()

    @pytest.mark.asyncio
    async def test_approve_failure_shows_error(self):
        """When ensure_channel fails, show error message."""
        from channel_approval_handlers import register_channel_approval_handlers

        handlers = {}
        mock_app = MagicMock()

        def capture_action(action_id):
            def decorator(fn):
                handlers[action_id] = fn
                return fn
            return decorator

        mock_app.action = capture_action
        register_channel_approval_handlers(mock_app)

        value = json.dumps({"channel": "CNEW001", "bot_id": "bot-a"})
        body = {
            "actions": [{"value": value}],
            "user": {"id": "U123"},
            "message": {"blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": "test"}},
                {"type": "actions", "elements": []},
            ]},
        }
        ack = AsyncMock()
        respond = AsyncMock()

        with patch("agent_client.ensure_channel", new_callable=AsyncMock, return_value=None):
            await handlers["approve_channel_create"](ack=ack, body=body, respond=respond)

        ack.assert_called_once()
        respond.assert_called_once()
        call_kwargs = respond.call_args[1]
        assert "failed" in call_kwargs["text"].lower()
