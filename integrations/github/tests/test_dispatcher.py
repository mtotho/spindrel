"""Tests for GitHub dispatcher — posting comments via GitHub API."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from integrations.github.dispatcher import GitHubDispatcher, _split_body


class TestSplitBody:
    def test_short_body_no_split(self):
        assert _split_body("hello", 100) == ["hello"]

    def test_long_body_splits(self):
        text = "a" * 200
        chunks = _split_body(text, 100)
        assert len(chunks) >= 2
        assert "".join(chunks) == text

    def test_splits_at_newline(self):
        text = "line1\nline2\nline3\nline4"
        chunks = _split_body(text, 15)
        assert all(len(c) <= 15 for c in chunks)


class TestGitHubDispatcher:
    @pytest.mark.asyncio
    async def test_deliver_posts_comment(self):
        dispatcher = GitHubDispatcher()
        task = MagicMock()
        task.id = "task-1"
        task.session_id = "sess-1"
        task.client_id = "github:org/repo"
        task.bot_id = "default"
        task.dispatch_config = {
            "type": "github",
            "owner": "org",
            "repo": "myrepo",
            "comment_target": {"type": "issue_comment", "issue_number": 42},
        }

        with patch("integrations.github.dispatcher._post_comment", new_callable=AsyncMock, return_value=True) as mock_post, \
             patch("integrations.github.dispatcher._get_token", return_value="ghp_test"), \
             patch("app.services.sessions.store_dispatch_echo", new_callable=AsyncMock):
            await dispatcher.deliver(task, "Here is the review.")
            mock_post.assert_called_once_with("ghp_test", "org", "myrepo", 42, "Here is the review.")

    @pytest.mark.asyncio
    async def test_deliver_skips_informational_events(self):
        """No comment_target means informational — no comment posted."""
        dispatcher = GitHubDispatcher()
        task = MagicMock()
        task.dispatch_config = {"type": "github", "owner": "org", "repo": "myrepo"}

        with patch("integrations.github.dispatcher._post_comment", new_callable=AsyncMock) as mock_post:
            await dispatcher.deliver(task, "Push notification")
            mock_post.assert_not_called()

    @pytest.mark.asyncio
    async def test_post_message_returns_false_without_target(self):
        dispatcher = GitHubDispatcher()
        result = await dispatcher.post_message(
            {"type": "github", "owner": "org", "repo": "repo"},
            "text",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_post_message_with_target(self):
        dispatcher = GitHubDispatcher()
        cfg = {
            "type": "github",
            "owner": "org",
            "repo": "repo",
            "comment_target": {"type": "issue_comment", "issue_number": 7},
        }
        with patch("integrations.github.dispatcher._post_comment", new_callable=AsyncMock, return_value=True) as mock_post, \
             patch("integrations.github.dispatcher._get_token", return_value="ghp_test"):
            result = await dispatcher.post_message(cfg, "hello")
            assert result is True
            mock_post.assert_called_once_with("ghp_test", "org", "repo", 7, "hello")
