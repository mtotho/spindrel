"""Tests for GitHub event dispatcher."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock heavy dependencies before importing dispatcher
_fake_utils = MagicMock()
_fake_utils.inject_message = AsyncMock(return_value={"message_id": "m1", "session_id": "s1", "task_id": None})
sys.modules.setdefault("integrations.utils", _fake_utils)

if "app.config" not in sys.modules:
    _fake_config = MagicMock()
    _fake_config.settings = MagicMock()
    sys.modules["app.config"] = _fake_config

from integrations.github.dispatcher import dispatch, EVENT_HANDLERS  # noqa: E402


class TestDispatcher:
    def test_event_handlers_registered(self):
        assert "workflow_run" in EVENT_HANDLERS
        assert "check_run" in EVENT_HANDLERS

    @pytest.mark.asyncio
    async def test_dispatch_unknown_event_returns_none(self):
        db = AsyncMock()
        result = await dispatch("unknown_event", {}, db)
        assert result is None

    @pytest.mark.asyncio
    async def test_dispatch_workflow_run_success_is_ignored(self):
        """workflow_run with conclusion=success should not inject a message."""
        db = AsyncMock()
        payload = {
            "workflow_run": {"conclusion": "success", "name": "CI", "head_branch": "main", "html_url": "", "id": 1},
            "repository": {"full_name": "org/repo"},
        }
        result = await dispatch("workflow_run", payload, db)
        assert result is None

    @pytest.mark.asyncio
    async def test_dispatch_workflow_run_failure_posts_to_slack(self):
        """workflow_run with conclusion=failure should post to Slack."""
        db = AsyncMock()
        payload = {
            "workflow_run": {"conclusion": "failure", "name": "CI", "head_branch": "main", "html_url": "https://example.com", "id": 42},
            "repository": {"full_name": "org/repo"},
        }
        with patch("integrations.github.handlers.github_config") as mock_cfg, \
             patch("integrations.github.handlers.post_message", new_callable=AsyncMock, return_value=True):
            mock_cfg.SLACK_CHANNEL_ID = "C01ABCDEF"
            mock_cfg.SLACK_BOT_TOKEN = "xoxb-test"
            result = await dispatch("workflow_run", payload, db)
        assert result is not None

    @pytest.mark.asyncio
    async def test_dispatch_check_run_failure_posts_to_slack(self):
        """check_run with conclusion=failure should post to Slack."""
        db = AsyncMock()
        payload = {
            "check_run": {"conclusion": "failure", "name": "lint", "html_url": "https://example.com"},
            "repository": {"full_name": "org/repo"},
        }
        with patch("integrations.github.handlers.github_config") as mock_cfg, \
             patch("integrations.github.handlers.post_message", new_callable=AsyncMock, return_value=True):
            mock_cfg.SLACK_CHANNEL_ID = "C01ABCDEF"
            mock_cfg.SLACK_BOT_TOKEN = "xoxb-test"
            result = await dispatch("check_run", payload, db)
        assert result is not None
