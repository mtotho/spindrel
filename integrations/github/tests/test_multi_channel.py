"""Tests for multi-channel GitHub webhook fan-out and event filtering."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from integrations.github.router import github_webhook


def _make_request(event_type: str = "push", body: bytes = b'{}', signature: str = "sha256=abc"):
    """Build a mock FastAPI Request."""
    req = AsyncMock()
    req.body.return_value = body
    req.headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": event_type,
    }
    req.json.return_value = {}
    return req


def _make_parsed(owner="org", repo="myrepo", run_agent=True, comment_target=None):
    parsed = MagicMock()
    parsed.message = "test event"
    parsed.run_agent = run_agent
    parsed.comment_target = comment_target
    parsed.owner = owner
    parsed.repo = repo
    parsed.sender = "someuser"
    return parsed


def _make_channel(channel_id=None, bot_id="default"):
    ch = MagicMock()
    ch.id = channel_id or uuid.uuid4()
    ch.bot_id = bot_id
    ch.client_id = None
    ch.integration = "github"
    ch.active_session_id = None
    return ch


def _make_binding(channel_id, client_id="github:org/myrepo", dispatch_config=None):
    b = MagicMock()
    b.channel_id = channel_id
    b.client_id = client_id
    b.dispatch_config = dispatch_config
    return b


class TestMultiChannelFanOut:
    @pytest.mark.asyncio
    async def test_fanout_to_two_channels(self):
        """Same webhook dispatches to 2 channels."""
        ch1 = _make_channel()
        ch2 = _make_channel()
        b1 = _make_binding(ch1.id)
        b2 = _make_binding(ch2.id)
        pairs = [(ch1, b1), (ch2, b2)]
        parsed = _make_parsed()
        session_id_1 = uuid.uuid4()
        session_id_2 = uuid.uuid4()

        session_ids = iter([session_id_1, session_id_2])

        async def mock_ensure(db, channel):
            return next(session_ids)

        request = _make_request("push")
        db = AsyncMock()

        with patch("integrations.github.router.validate_signature", return_value=True), \
             patch("integrations.github.router.parse_event", return_value=parsed), \
             patch("integrations.github.router.settings") as mock_settings, \
             patch("integrations.github.router.resolve_all_channels_by_client_id", return_value=pairs) as mock_resolve, \
             patch("integrations.github.router.ensure_active_session", side_effect=mock_ensure) as mock_ensure_session, \
             patch("integrations.github.router.utils") as mock_utils:

            mock_settings.GITHUB_BOT_LOGIN = None
            mock_utils.inject_message = AsyncMock(return_value={"message_id": "m1", "session_id": "s1", "task_id": "t1"})

            result = await github_webhook(request, db)

        assert result["status"] == "processed"
        assert result["channels"] == 2
        assert len(result["results"]) == 2
        assert mock_ensure_session.call_count == 2
        assert mock_utils.inject_message.call_count == 2

    @pytest.mark.asyncio
    async def test_event_filter_excludes_channel(self):
        """Channel with event_filter: ["push"] skips issue_comment events."""
        ch1 = _make_channel()
        ch2 = _make_channel()
        # ch1 only wants push events
        b1 = _make_binding(ch1.id, dispatch_config={"event_filter": ["push"]})
        # ch2 wants everything (no filter)
        b2 = _make_binding(ch2.id)
        pairs = [(ch1, b1), (ch2, b2)]
        parsed = _make_parsed()

        request = _make_request("issue_comment")
        db = AsyncMock()

        with patch("integrations.github.router.validate_signature", return_value=True), \
             patch("integrations.github.router.parse_event", return_value=parsed), \
             patch("integrations.github.router.settings") as mock_settings, \
             patch("integrations.github.router.resolve_all_channels_by_client_id", return_value=pairs), \
             patch("integrations.github.router.ensure_active_session", return_value=uuid.uuid4()) as mock_ensure, \
             patch("integrations.github.router.utils") as mock_utils:

            mock_settings.GITHUB_BOT_LOGIN = None
            mock_utils.inject_message = AsyncMock(return_value={"message_id": "m1", "session_id": "s1", "task_id": "t1"})

            result = await github_webhook(request, db)

        assert result["status"] == "processed"
        assert result["channels"] == 1
        # Only ch2 should have received the event
        assert mock_ensure.call_count == 1
        assert mock_utils.inject_message.call_count == 1

    @pytest.mark.asyncio
    async def test_event_filter_matches(self):
        """Channel with event_filter: ["push"] receives push events."""
        ch1 = _make_channel()
        b1 = _make_binding(ch1.id, dispatch_config={"event_filter": ["push"]})
        pairs = [(ch1, b1)]
        parsed = _make_parsed()

        request = _make_request("push")
        db = AsyncMock()

        with patch("integrations.github.router.validate_signature", return_value=True), \
             patch("integrations.github.router.parse_event", return_value=parsed), \
             patch("integrations.github.router.settings") as mock_settings, \
             patch("integrations.github.router.resolve_all_channels_by_client_id", return_value=pairs), \
             patch("integrations.github.router.ensure_active_session", return_value=uuid.uuid4()), \
             patch("integrations.github.router.utils") as mock_utils:

            mock_settings.GITHUB_BOT_LOGIN = None
            mock_utils.inject_message = AsyncMock(return_value={"message_id": "m1", "session_id": "s1", "task_id": "t1"})

            result = await github_webhook(request, db)

        assert result["status"] == "processed"
        assert result["channels"] == 1

    @pytest.mark.asyncio
    async def test_all_channels_filtered_returns_filtered_status(self):
        """When all channels' filters exclude the event, return 'filtered' status."""
        ch1 = _make_channel()
        b1 = _make_binding(ch1.id, dispatch_config={"event_filter": ["push"]})
        pairs = [(ch1, b1)]
        parsed = _make_parsed()

        request = _make_request("issues")
        db = AsyncMock()

        with patch("integrations.github.router.validate_signature", return_value=True), \
             patch("integrations.github.router.parse_event", return_value=parsed), \
             patch("integrations.github.router.settings") as mock_settings, \
             patch("integrations.github.router.resolve_all_channels_by_client_id", return_value=pairs), \
             patch("integrations.github.router.ensure_active_session") as mock_ensure, \
             patch("integrations.github.router.utils") as mock_utils:

            mock_settings.GITHUB_BOT_LOGIN = None

            result = await github_webhook(request, db)

        assert result["status"] == "filtered"
        mock_ensure.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_bindings_falls_back_to_legacy(self):
        """When no channel_integrations exist, falls back to legacy single-session."""
        parsed = _make_parsed()
        request = _make_request("push")
        db = AsyncMock()
        session_id = uuid.uuid4()

        with patch("integrations.github.router.validate_signature", return_value=True), \
             patch("integrations.github.router.parse_event", return_value=parsed), \
             patch("integrations.github.router.settings") as mock_settings, \
             patch("integrations.github.router.resolve_all_channels_by_client_id", return_value=[]), \
             patch("integrations.github.router.utils") as mock_utils:

            mock_settings.GITHUB_BOT_LOGIN = None
            mock_utils.get_or_create_session = AsyncMock(return_value=session_id)
            mock_utils.inject_message = AsyncMock(return_value={
                "message_id": "m1",
                "session_id": str(session_id),
                "task_id": "t1",
            })

            result = await github_webhook(request, db)

        assert result["status"] == "processed"
        assert result["session_id"] == str(session_id)
        mock_utils.get_or_create_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_config_includes_comment_target(self):
        """Per-event dispatch_config (with comment_target) is passed to inject_message."""
        ch1 = _make_channel()
        b1 = _make_binding(ch1.id)
        pairs = [(ch1, b1)]
        comment_target = {"type": "issue_comment", "issue_number": 42}
        parsed = _make_parsed(comment_target=comment_target)

        request = _make_request("issue_comment")
        db = AsyncMock()

        with patch("integrations.github.router.validate_signature", return_value=True), \
             patch("integrations.github.router.parse_event", return_value=parsed), \
             patch("integrations.github.router.settings") as mock_settings, \
             patch("integrations.github.router.resolve_all_channels_by_client_id", return_value=pairs), \
             patch("integrations.github.router.ensure_active_session", return_value=uuid.uuid4()), \
             patch("integrations.github.router.utils") as mock_utils:

            mock_settings.GITHUB_BOT_LOGIN = None
            mock_utils.inject_message = AsyncMock(return_value={"message_id": "m1", "session_id": "s1", "task_id": "t1"})

            await github_webhook(request, db)

        call_kwargs = mock_utils.inject_message.call_args
        assert call_kwargs.kwargs["dispatch_config"]["comment_target"] == comment_target
