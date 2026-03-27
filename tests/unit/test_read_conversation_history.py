"""Tests for the read_conversation_history tool."""
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.local.conversation_history import read_conversation_history


def _mock_section(**kwargs):
    s = MagicMock()
    s.id = kwargs.get("id", uuid.uuid4())
    s.channel_id = kwargs.get("channel_id", uuid.uuid4())
    s.sequence = kwargs.get("sequence", 1)
    s.title = kwargs.get("title", "Test Section")
    s.summary = kwargs.get("summary", "A test section summary.")
    s.transcript_path = kwargs.get("transcript_path", None)
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
        assert str(sections[0].id) in result

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


class TestReadConversationHistorySection:
    @pytest.mark.asyncio
    async def test_returns_full_section_content_from_file(self):
        channel_id = uuid.uuid4()
        section_id = uuid.uuid4()
        file_content = "# Slack Setup\nFrom: 2026-03-20 10:00  To: 2026-03-20 11:30\nMessages: 10\n\nSummary: Setup.\n\n---\n\n[USER]: hello\n[ASSISTANT]: hi"
        section = _mock_section(
            id=section_id, channel_id=channel_id,
            title="Slack Setup", transcript_path=".history/001_slack_setup.md",
            message_count=10,
            period_start=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc),
            period_end=datetime(2026, 3, 20, 11, 30, tzinfo=timezone.utc),
        )
        mock_bot = MagicMock()
        mock_bot.id = "test_bot"
        with patch_channel_id(channel_id), patch_db_get(section), \
             patch("app.agent.context.current_bot_id") as mock_bot_id, \
             patch("app.agent.bots.get_bot", return_value=mock_bot), \
             patch("app.services.workspace.workspace_service") as mock_ws, \
             patch("builtins.open", MagicMock(return_value=MagicMock(
                 __enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=file_content))),
                 __exit__=MagicMock(return_value=False),
             ))):
            mock_bot_id.get.return_value = "test_bot"
            mock_ws.get_workspace_root.return_value = "/workspace"
            result = await read_conversation_history(str(section_id))
        assert "Slack Setup" in result
        assert "[USER]: hello" in result

    @pytest.mark.asyncio
    async def test_returns_fallback_when_no_transcript_path(self):
        channel_id = uuid.uuid4()
        section_id = uuid.uuid4()
        section = _mock_section(
            id=section_id, channel_id=channel_id,
            title="Slack Setup", transcript_path=None,
            message_count=10,
            period_start=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc),
            period_end=datetime(2026, 3, 20, 11, 30, tzinfo=timezone.utc),
        )
        with patch_channel_id(channel_id), patch_db_get(section):
            result = await read_conversation_history(str(section_id))
        assert "Slack Setup" in result
        assert "Transcript file not available" in result

    @pytest.mark.asyncio
    async def test_invalid_uuid_returns_error(self):
        with patch_channel_id(uuid.uuid4()):
            result = await read_conversation_history("not-a-uuid")
        assert "Invalid section ID" in result

    @pytest.mark.asyncio
    async def test_nonexistent_section_returns_not_found(self):
        with patch_channel_id(uuid.uuid4()), patch_db_get(None):
            result = await read_conversation_history(str(uuid.uuid4()))
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_wrong_channel_returns_not_found(self):
        """Section exists but belongs to a different channel."""
        my_channel = uuid.uuid4()
        other_channel = uuid.uuid4()
        section = _mock_section(id=uuid.uuid4(), channel_id=other_channel)
        with patch_channel_id(my_channel), patch_db_get(section):
            result = await read_conversation_history(str(section.id))
        assert "not found" in result
