"""Tests for the read_conversation_history tool."""
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.local.conversation_history import read_conversation_history, _read_section_transcript


def _mock_section(**kwargs):
    s = MagicMock()
    s.id = kwargs.get("id", uuid.uuid4())
    s.channel_id = kwargs.get("channel_id", uuid.uuid4())
    s.sequence = kwargs.get("sequence", 1)
    s.title = kwargs.get("title", "Test Section")
    s.summary = kwargs.get("summary", "A test section summary.")
    s.transcript_path = kwargs.get("transcript_path", None)
    s.transcript = kwargs.get("transcript", None)  # explicit None prevents MagicMock truthy
    s.tags = kwargs.get("tags", [])
    s.message_count = kwargs.get("message_count", 5)
    s.period_start = kwargs.get("period_start", datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc))
    s.period_end = kwargs.get("period_end", datetime(2026, 3, 20, 11, 30, tzinfo=timezone.utc))
    return s


@contextmanager
def patch_channel_id(channel_id):
    with patch("app.tools.local.conversation_history.current_channel_id") as mock_cv:
        mock_cv.get.return_value = channel_id
        yield mock_cv


@contextmanager
def patch_db_query(sections):
    with patch("app.tools.local.conversation_history.async_session") as mock_session:
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = sections
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
        yield mock_session


@contextmanager
def patch_db_get(section):
    with patch("app.tools.local.conversation_history.async_session") as mock_session:
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=section)
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
        yield mock_session


@contextmanager
def patch_db_section_lookup(section):
    """Mock the sequence-based section lookup (select...where sequence==N)."""
    with patch("app.tools.local.conversation_history.async_session") as mock_session, \
         patch("app.tools.local.conversation_history._track_view", new_callable=AsyncMock), \
         patch("app.tools.local.conversation_history._backfill_transcript", new_callable=AsyncMock):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = section
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
        yield mock_session


class TestReadConversationHistoryIndex:
    @pytest.mark.asyncio
    async def test_returns_all_sections_for_channel(self):
        """Index mode lists all sections with IDs, titles, summaries."""
        channel_id = uuid.uuid4()
        sections = [
            _mock_section(channel_id=channel_id, sequence=1, title="Setup",
                         summary="Initial setup.", message_count=15,
                         period_start=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc)),
            _mock_section(channel_id=channel_id, sequence=2, title="Debugging",
                         summary="Fixed bugs.", message_count=22,
                         period_start=datetime(2026, 3, 20, 14, 0, tzinfo=timezone.utc)),
        ]
        with patch_channel_id(channel_id), patch_db_query(sections):
            result = await read_conversation_history("index")
        assert "Setup" in result
        assert "Debugging" in result
        assert "15" in result
        assert "#1" in result  # sections indexed by sequence number

    @pytest.mark.asyncio
    async def test_empty_channel_returns_no_sections(self):
        channel_id = uuid.uuid4()
        with patch_channel_id(channel_id), patch_db_query([]):
            result = await read_conversation_history("index")
        assert "No archived" in result

    @pytest.mark.asyncio
    async def test_no_channel_context(self):
        """No current_channel_id set -> error message."""
        with patch_channel_id(None):
            result = await read_conversation_history("index")
        assert "No channel" in result


class TestNonUuidChannelId:
    """LLMs sometimes pass Slack channel IDs (e.g. 'C06RY3YBSLE') instead of DB UUIDs."""

    @pytest.mark.asyncio
    async def test_slack_channel_id_resolved_via_client_id(self):
        """Non-UUID channel_id should be looked up by client_id."""
        my_channel_id = uuid.uuid4()
        target_channel_id = uuid.uuid4()
        slack_id = "C06RY3YBSLE"
        sections = [
            _mock_section(channel_id=target_channel_id, sequence=1, title="Slack Channel",
                         summary="Some conversation.", message_count=5,
                         period_start=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc)),
        ]
        # Mock the client_id lookup query
        mock_lookup_result = MagicMock()
        mock_lookup_result.scalar_one_or_none.return_value = target_channel_id

        # Mock the Channel.get for access check
        mock_channel = MagicMock()
        mock_channel.bot_id = "test_bot"

        # Mock the sections query
        mock_sections_result = MagicMock()
        mock_sections_result.scalars.return_value.all.return_value = sections

        with patch_channel_id(my_channel_id), \
             patch("app.tools.local.conversation_history.current_bot_id") as mock_bot_id, \
             patch("app.tools.local.conversation_history.async_session") as mock_session:
            mock_bot_id.get.return_value = "test_bot"
            mock_db = AsyncMock()
            # First call: client_id lookup; second call: Channel.get; third call: sections query
            mock_db.execute = AsyncMock(side_effect=[mock_lookup_result, mock_sections_result])
            mock_db.get = AsyncMock(return_value=mock_channel)
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await read_conversation_history("index", channel_id=slack_id)
        assert "Slack Channel" in result

    @pytest.mark.asyncio
    async def test_unknown_non_uuid_channel_id(self):
        """Non-UUID channel_id that doesn't match any client_id returns error."""
        my_channel_id = uuid.uuid4()
        mock_lookup_result = MagicMock()
        mock_lookup_result.scalar_one_or_none.return_value = None

        with patch_channel_id(my_channel_id), \
             patch("app.tools.local.conversation_history.async_session") as mock_session:
            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(return_value=mock_lookup_result)
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await read_conversation_history("index", channel_id="BOGUS123")
        assert "Unknown channel" in result

    @pytest.mark.asyncio
    async def test_valid_uuid_string_still_works(self):
        """UUID passed as a string (from JSON) should still work."""
        channel_id = uuid.uuid4()
        sections = [
            _mock_section(channel_id=channel_id, sequence=1, title="Test",
                         summary="ok.", message_count=3,
                         period_start=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc)),
        ]
        # Pass channel_id as string (same as current channel — no cross-channel check needed)
        with patch_channel_id(channel_id), patch_db_query(sections):
            result = await read_conversation_history("index", channel_id=str(channel_id))
        assert "Test" in result


class TestReadConversationHistorySection:
    @pytest.mark.asyncio
    async def test_returns_full_section_content_from_file_old_format(self):
        """Old format transcript_path (.history/...) resolves via workspace_service."""
        channel_id = uuid.uuid4()
        file_content = "# Slack Setup\nFrom: 2026-03-20 10:00  To: 2026-03-20 11:30\nMessages: 10\n\nSummary: Setup.\n\n---\n\n[USER]: hello\n[ASSISTANT]: hi"
        section = _mock_section(
            channel_id=channel_id, sequence=1,
            title="Slack Setup", transcript_path=".history/001_slack_setup.md",
            message_count=10,
            period_start=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc),
            period_end=datetime(2026, 3, 20, 11, 30, tzinfo=timezone.utc),
        )
        mock_bot = MagicMock()
        mock_bot.id = "test_bot"
        with patch_channel_id(channel_id), patch_db_section_lookup(section), \
             patch("app.agent.context.current_bot_id") as mock_bot_id, \
             patch("app.agent.bots.get_bot", return_value=mock_bot), \
             patch("app.services.workspace.workspace_service") as mock_ws, \
             patch("builtins.open", MagicMock(return_value=MagicMock(
                 __enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=file_content))),
                 __exit__=MagicMock(return_value=False),
             ))):
            mock_bot_id.get.return_value = "test_bot"
            mock_ws.get_workspace_root.return_value = "/workspace"
            result = await read_conversation_history("1")
        assert "Slack Setup" in result
        assert "[USER]: hello" in result

    @pytest.mark.asyncio
    async def test_returns_full_section_content_from_file_new_format(self):
        """New format transcript_path (channels/...) resolves via channel workspace _get_ws_root."""
        channel_id = uuid.uuid4()
        file_content = "# Setup\n\n---\n\n[USER]: hello"
        section = _mock_section(
            channel_id=channel_id, sequence=1,
            title="Setup", transcript_path=f"channels/{channel_id}/.history/001_setup.md",
        )
        mock_bot = MagicMock()
        mock_bot.id = "test_bot"
        with patch_channel_id(channel_id), patch_db_section_lookup(section), \
             patch("app.agent.context.current_bot_id") as mock_bot_id, \
             patch("app.agent.bots.get_bot", return_value=mock_bot), \
             patch("app.services.channel_workspace._get_ws_root", return_value="/workspace"), \
             patch("builtins.open", MagicMock(return_value=MagicMock(
                 __enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=file_content))),
                 __exit__=MagicMock(return_value=False),
             ))):
            mock_bot_id.get.return_value = "test_bot"
            result = await read_conversation_history("1")
        assert "Setup" in result
        assert "[USER]: hello" in result

    @pytest.mark.asyncio
    async def test_returns_fallback_when_no_transcript_path(self):
        channel_id = uuid.uuid4()
        section = _mock_section(
            channel_id=channel_id, sequence=1,
            title="Slack Setup", transcript_path=None,
            message_count=10,
            period_start=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc),
            period_end=datetime(2026, 3, 20, 11, 30, tzinfo=timezone.utc),
        )
        with patch_channel_id(channel_id), patch_db_section_lookup(section):
            result = await read_conversation_history("1")
        assert "Slack Setup" in result
        assert "Transcript not available" in result

    @pytest.mark.asyncio
    async def test_invalid_section_returns_error(self):
        with patch_channel_id(uuid.uuid4()):
            result = await read_conversation_history("not-a-uuid")
        assert "Invalid section" in result

    @pytest.mark.asyncio
    async def test_nonexistent_section_returns_not_found(self):
        with patch_channel_id(uuid.uuid4()), patch_db_section_lookup(None):
            result = await read_conversation_history("999")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_section_not_in_channel_returns_not_found(self):
        """Query filters by channel_id, so a section from another channel yields no match."""
        my_channel = uuid.uuid4()
        with patch_channel_id(my_channel), patch_db_section_lookup(None):
            result = await read_conversation_history("1")
        assert "not found" in result


class TestCrossWorkspaceAccess:
    """Tests for cross-workspace access to other bots' conversation history."""

    @pytest.mark.asyncio
    async def test_cross_workspace_access_allowed(self):
        """Bot with cross_workspace_access=True can read another bot's channel history."""
        my_channel_id = uuid.uuid4()
        other_channel_id = uuid.uuid4()
        caller_bot_id = "orchestrator"
        owner_bot_id = "worker"

        mock_channel = MagicMock()
        mock_channel.bot_id = owner_bot_id

        caller_bot = MagicMock()
        caller_bot.cross_workspace_access = True

        sections = [
            _mock_section(channel_id=other_channel_id, sequence=1, title="Worker Section",
                         summary="Work done.", message_count=10,
                         period_start=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc)),
        ]

        with patch_channel_id(my_channel_id), \
             patch("app.tools.local.conversation_history.current_bot_id") as mock_bid, \
             patch("app.tools.local.conversation_history.async_session") as mock_session, \
             patch("app.agent.bots.get_bot", return_value=caller_bot):
            mock_bid.get.return_value = caller_bot_id

            # First async_session call: channel lookup (cross-channel check)
            # Second call: section query
            mock_db1 = AsyncMock()
            mock_db1.get = AsyncMock(return_value=mock_channel)
            mock_db2 = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = sections
            mock_db2.execute = AsyncMock(return_value=mock_result)

            call_count = [0]
            class FakeCtx:
                async def __aenter__(self_inner):
                    call_count[0] += 1
                    return mock_db1 if call_count[0] == 1 else mock_db2
                async def __aexit__(self_inner, *args):
                    return False
            mock_session.side_effect = lambda: FakeCtx()

            result = await read_conversation_history("index", channel_id=other_channel_id)

        assert "Worker Section" in result
        assert "Access denied" not in result

    @pytest.mark.asyncio
    async def test_cross_workspace_access_denied(self):
        """Bot without cross_workspace_access cannot read another bot's channel."""
        my_channel_id = uuid.uuid4()
        other_channel_id = uuid.uuid4()
        caller_bot_id = "limited_bot"
        owner_bot_id = "worker"

        mock_channel = MagicMock()
        mock_channel.bot_id = owner_bot_id

        caller_bot = MagicMock()
        caller_bot.cross_workspace_access = False

        with patch_channel_id(my_channel_id), \
             patch("app.tools.local.conversation_history.current_bot_id") as mock_bid, \
             patch("app.tools.local.conversation_history.async_session") as mock_session, \
             patch("app.agent.bots.get_bot", return_value=caller_bot):
            mock_bid.get.return_value = caller_bot_id

            mock_db = AsyncMock()
            mock_db.get = AsyncMock(return_value=mock_channel)
            mock_db.scalar = AsyncMock(return_value=False)  # not a member
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await read_conversation_history("index", channel_id=other_channel_id)

        assert "Access denied" in result


class TestDualRootPathResolution:
    """Tests for _read_section_transcript dual-root path detection."""

    def test_new_format_uses_channel_ws_root(self):
        """transcript_path starting with 'channels/' uses _get_ws_root."""
        channel_id = uuid.uuid4()
        sec = _mock_section(
            transcript=None,
            transcript_path=f"channels/{channel_id}/.history/001_setup.md",
        )
        file_content = "# Setup\nTranscript content"
        mock_bot = MagicMock()
        mock_bot.id = "test_bot"

        with patch("app.agent.context.current_bot_id") as mock_bid, \
             patch("app.agent.bots.get_bot", return_value=mock_bot), \
             patch("app.services.channel_workspace._get_ws_root", return_value="/shared-ws") as mock_cws, \
             patch("builtins.open", MagicMock(return_value=MagicMock(
                 __enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=file_content))),
                 __exit__=MagicMock(return_value=False),
             ))):
            mock_bid.get.return_value = "test_bot"
            result = _read_section_transcript(sec)

        assert result == file_content
        mock_cws.assert_called_once_with(mock_bot)

    def test_old_format_uses_workspace_service(self):
        """transcript_path starting with '.history/' uses workspace_service."""
        sec = _mock_section(
            transcript=None,
            transcript_path=".history/dev_channel/001_setup.md",
        )
        file_content = "# Setup\nOld format transcript"
        mock_bot = MagicMock()
        mock_bot.id = "test_bot"

        with patch("app.agent.context.current_bot_id") as mock_bid, \
             patch("app.agent.bots.get_bot", return_value=mock_bot), \
             patch("app.services.workspace.workspace_service") as mock_ws, \
             patch("builtins.open", MagicMock(return_value=MagicMock(
                 __enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=file_content))),
                 __exit__=MagicMock(return_value=False),
             ))):
            mock_bid.get.return_value = "test_bot"
            mock_ws.get_workspace_root.return_value = "/workspace"
            result = _read_section_transcript(sec)

        assert result == file_content
        mock_ws.get_workspace_root.assert_called_once_with("test_bot", mock_bot)

    def test_owner_bot_id_resolves_correct_workspace(self):
        """When owner_bot_id is set, resolves against that bot's workspace."""
        sec = _mock_section(
            transcript=None,
            transcript_path=".history/dev_channel/001_setup.md",
        )
        file_content = "# Owner's transcript"
        owner_bot = MagicMock()
        owner_bot.id = "owner_bot"

        with patch("app.agent.context.current_bot_id") as mock_bid, \
             patch("app.agent.bots.get_bot", return_value=owner_bot), \
             patch("app.services.workspace.workspace_service") as mock_ws, \
             patch("builtins.open", MagicMock(return_value=MagicMock(
                 __enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=file_content))),
                 __exit__=MagicMock(return_value=False),
             ))):
            mock_bid.get.return_value = "caller_bot"
            mock_ws.get_workspace_root.return_value = "/owner-workspace"
            result = _read_section_transcript(sec, owner_bot_id="owner_bot")

        assert result == file_content
        # Should resolve using owner_bot_id, not the caller's bot_id
        mock_ws.get_workspace_root.assert_called_once_with("owner_bot", owner_bot)
