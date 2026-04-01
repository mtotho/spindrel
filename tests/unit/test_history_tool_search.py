"""Tests for conversation history tool — DB-first reads, smart search, mode removal."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_section(seq: int, **overrides):
    """Create a mock ConversationSection."""
    s = MagicMock()
    s.id = uuid.uuid4()
    s.sequence = seq
    s.title = overrides.get("title", f"Section {seq}")
    s.summary = overrides.get("summary", f"Summary for section {seq}")
    s.transcript = overrides.get("transcript", None)
    s.transcript_path = overrides.get("transcript_path", None)
    s.message_count = overrides.get("message_count", 10)
    s.period_start = overrides.get("period_start", datetime(2024, 1, seq, tzinfo=timezone.utc))
    s.period_end = overrides.get("period_end", None)
    s.tags = overrides.get("tags", None)
    s.view_count = overrides.get("view_count", 0)
    s.last_viewed_at = None
    s.embedding = overrides.get("embedding", None)
    s.channel_id = overrides.get("channel_id", uuid.uuid4())
    return s


class TestReadSectionTranscript:
    def test_prefers_db_transcript(self):
        from app.tools.local.conversation_history import _read_section_transcript

        sec = _make_section(1, transcript="DB transcript content", transcript_path="some/file.md")
        result = _read_section_transcript(sec)
        assert result == "DB transcript content"

    def test_falls_back_to_file_when_no_db_transcript(self):
        from app.tools.local.conversation_history import _read_section_transcript

        sec = _make_section(1, transcript=None, transcript_path="channels/abc/.history/001.md")

        mock_bot = MagicMock()
        with (
            patch("app.agent.context.current_bot_id") as mock_ctx,
            patch("app.agent.bots.get_bot", return_value=mock_bot),
            patch("app.services.channel_workspace._get_ws_root", return_value="/tmp"),
            patch("builtins.open", MagicMock(return_value=MagicMock(
                __enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value="file content"))),
                __exit__=MagicMock(return_value=False),
            ))),
        ):
            mock_ctx.get.return_value = "test-bot"
            result = _read_section_transcript(sec)
        assert result == "file content"

    def test_summary_fallback_when_nothing_available(self):
        from app.tools.local.conversation_history import _read_section_transcript

        sec = _make_section(1, transcript=None, transcript_path=None, title="Test Title")
        result = _read_section_transcript(sec)
        assert "Test Title" in result
        assert "Transcript not available" in result


class TestExtractSnippet:
    def test_basic_snippet(self):
        from app.tools.local.conversation_history import _extract_snippet

        text = "A" * 200 + "MATCH_HERE" + "B" * 200
        snippet = _extract_snippet(text, "MATCH_HERE", context_chars=20)
        assert "MATCH_HERE" in snippet
        assert snippet.startswith("...")
        assert snippet.endswith("...")

    def test_no_match_returns_none(self):
        from app.tools.local.conversation_history import _extract_snippet

        result = _extract_snippet("some text", "nonexistent")
        assert result is None

    def test_match_at_start(self):
        from app.tools.local.conversation_history import _extract_snippet

        result = _extract_snippet("hello world and more text here", "hello", context_chars=10)
        assert result is not None
        assert "hello" in result
        assert not result.startswith("...")  # No prefix since match is at start


class TestSearchSections:
    @pytest.mark.asyncio
    async def test_metadata_keyword_match(self):
        from app.tools.local.conversation_history import search_sections

        channel_id = uuid.uuid4()
        sec = _make_section(1, title="Database Migration Guide", summary="How to run migrations")

        mock_db = AsyncMock()
        # Single session: metadata, transcript grep, semantic — all in one db context
        mock_db.execute = AsyncMock(side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[sec])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ])

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.tools.local.conversation_history.async_session", return_value=mock_session),
            patch("app.agent.embeddings.embed_text", AsyncMock(return_value=[0.1] * 384)),
        ):
            results = await search_sections(channel_id, "migration")

        assert len(results) >= 1
        assert results[0]["source"] == "metadata"

    @pytest.mark.asyncio
    async def test_deduplication(self):
        from app.tools.local.conversation_history import search_sections

        channel_id = uuid.uuid4()
        sec = _make_section(1, title="Test Topic", transcript="Test content about topic")

        mock_db = AsyncMock()
        # Single session: all three phases return the same section
        mock_db.execute = AsyncMock(side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[sec])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[sec])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[sec])))),
        ])

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.tools.local.conversation_history.async_session", return_value=mock_session),
            patch("app.agent.embeddings.embed_text", AsyncMock(return_value=[0.1] * 384)),
        ):
            results = await search_sections(channel_id, "topic")

        # Deduplication: only one result
        assert len(results) == 1
        assert results[0]["source"] == "metadata"


class TestToolSchemaDescription:
    def test_no_messages_mode_in_schema(self):
        from app.tools.local.conversation_history import _SCHEMA

        desc = _SCHEMA["function"]["description"]
        assert "messages:" not in desc
        assert "search:" in desc
        assert "semantic similarity" in desc

    def test_no_uuid_in_param_description(self):
        from app.tools.local.conversation_history import _SCHEMA

        param_desc = _SCHEMA["function"]["parameters"]["properties"]["section"]["description"]
        assert "UUID" not in param_desc


class TestReadConversationHistory:
    @pytest.mark.asyncio
    async def test_invalid_section_returns_error(self):
        from app.tools.local.conversation_history import read_conversation_history

        channel_id = uuid.uuid4()
        with (
            patch("app.tools.local.conversation_history.current_channel_id") as mock_ch,
            patch("app.tools.local.conversation_history.current_bot_id") as mock_bot,
        ):
            mock_ch.get.return_value = channel_id
            mock_bot.get.return_value = "test-bot"
            result = await read_conversation_history("not-a-number-or-command")

        assert "Invalid section" in result
        assert "'index'" in result

    @pytest.mark.asyncio
    async def test_uuid_no_longer_accepted(self):
        from app.tools.local.conversation_history import read_conversation_history

        channel_id = uuid.uuid4()
        test_uuid = str(uuid.uuid4())
        with (
            patch("app.tools.local.conversation_history.current_channel_id") as mock_ch,
            patch("app.tools.local.conversation_history.current_bot_id") as mock_bot,
        ):
            mock_ch.get.return_value = channel_id
            mock_bot.get.return_value = "test-bot"
            result = await read_conversation_history(test_uuid)

        assert "Invalid section" in result

    @pytest.mark.asyncio
    async def test_section_by_sequence_with_backfill(self):
        from app.tools.local.conversation_history import read_conversation_history

        channel_id = uuid.uuid4()
        # Section with file but no DB transcript — should trigger backfill
        sec = _make_section(5, transcript=None, transcript_path="channels/x/.history/005.md")
        sec.channel_id = channel_id

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sec
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.tools.local.conversation_history.current_channel_id") as mock_ch,
            patch("app.tools.local.conversation_history.current_bot_id") as mock_bot,
            patch("app.tools.local.conversation_history.async_session", return_value=mock_session),
            patch("app.tools.local.conversation_history._track_view", AsyncMock()),
            patch("app.tools.local.conversation_history._read_section_transcript", return_value="File transcript content"),
            patch("app.tools.local.conversation_history._backfill_transcript", AsyncMock()) as mock_backfill,
        ):
            mock_ch.get.return_value = channel_id
            mock_bot.get.return_value = "test-bot"
            result = await read_conversation_history("5")

        assert result == "File transcript content"
        mock_backfill.assert_called_once_with(sec.id, "File transcript content")

    @pytest.mark.asyncio
    async def test_no_backfill_on_error_transcript(self):
        from app.tools.local.conversation_history import read_conversation_history

        channel_id = uuid.uuid4()
        sec = _make_section(5, transcript=None, transcript_path="channels/x/.history/005.md")
        sec.channel_id = channel_id

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sec
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.tools.local.conversation_history.current_channel_id") as mock_ch,
            patch("app.tools.local.conversation_history.current_bot_id") as mock_bot,
            patch("app.tools.local.conversation_history.async_session", return_value=mock_session),
            patch("app.tools.local.conversation_history._track_view", AsyncMock()),
            patch("app.tools.local.conversation_history._read_section_transcript", return_value="Transcript file not found: x. Re-run backfill."),
            patch("app.tools.local.conversation_history._backfill_transcript", AsyncMock()) as mock_backfill,
        ):
            mock_ch.get.return_value = channel_id
            mock_bot.get.return_value = "test-bot"
            await read_conversation_history("5")

        mock_backfill.assert_not_called()
