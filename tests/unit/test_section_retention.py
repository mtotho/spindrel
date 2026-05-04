"""Tests for section retention pruning in app.services.compaction."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_section(seq: int, days_ago: int = 0, **overrides):
    """Create a mock ConversationSection."""
    s = MagicMock()
    s.id = uuid.uuid4()
    s.sequence = seq
    s.transcript_path = overrides.get("transcript_path", None)
    s.created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _mock_settings(**overrides):
    defaults = dict(
        SECTION_RETENTION_MODE="forever",
        SECTION_RETENTION_VALUE=100,
    )
    defaults.update(overrides)
    s = MagicMock()
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


class TestPruneSections:
    @pytest.mark.asyncio
    async def test_forever_mode_is_noop(self):
        from app.services.compaction import prune_sections

        with patch("app.services.compaction.settings", _mock_settings(SECTION_RETENTION_MODE="forever")):
            result = await prune_sections(uuid.uuid4())
        assert result == 0

    @pytest.mark.asyncio
    async def test_count_mode_deletes_oldest(self):
        from app.services.compaction import prune_sections

        channel_id = uuid.uuid4()
        # 5 sections total, keep 3 → delete 2 oldest
        sections = [_make_section(i + 1) for i in range(5)]
        keep_ids = {sections[i].id for i in [2, 3, 4]}  # seq 3,4,5

        mock_db = AsyncMock()
        # First execute: keep_q returns keep_ids
        # Second execute: all_q returns all sections
        mock_db.execute = AsyncMock(side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=list(keep_ids))))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=sections)))),
        ])
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.compaction.settings", _mock_settings(SECTION_RETENTION_MODE="count", SECTION_RETENTION_VALUE=3)),
            patch("app.services.compaction.async_session", return_value=mock_session),
        ):
            result = await prune_sections(channel_id)

        assert result == 2
        assert mock_db.delete.call_count == 2
        assert mock_db.commit.call_count == 1

    @pytest.mark.asyncio
    async def test_days_mode_deletes_old(self):
        from app.services.compaction import prune_sections

        channel_id = uuid.uuid4()
        old_section = _make_section(1, days_ago=60)
        new_section = _make_section(2, days_ago=5)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[old_section])))
        ))
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.compaction.settings", _mock_settings(SECTION_RETENTION_MODE="days", SECTION_RETENTION_VALUE=30)),
            patch("app.services.compaction.async_session", return_value=mock_session),
        ):
            result = await prune_sections(channel_id)

        assert result == 1
        assert mock_db.delete.call_count == 1

    @pytest.mark.asyncio
    async def test_count_mode_nothing_to_delete(self):
        from app.services.compaction import prune_sections

        channel_id = uuid.uuid4()
        sections = [_make_section(i + 1) for i in range(3)]
        all_ids = {s.id for s in sections}

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=list(all_ids))))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=sections)))),
        ])
        mock_db.commit = AsyncMock()

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.compaction.settings", _mock_settings(SECTION_RETENTION_MODE="count", SECTION_RETENTION_VALUE=5)),
            patch("app.services.compaction.async_session", return_value=mock_session),
        ):
            result = await prune_sections(channel_id)

        assert result == 0

    @pytest.mark.asyncio
    async def test_unknown_mode_returns_zero(self):
        from app.services.compaction import prune_sections

        mock_db = AsyncMock()
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.compaction.settings", _mock_settings(SECTION_RETENTION_MODE="unknown")),
            patch("app.services.compaction.async_session", return_value=mock_session),
        ):
            result = await prune_sections(uuid.uuid4())

        assert result == 0


class TestDeleteSectionFile:
    def test_no_transcript_path_is_noop(self):
        from app.services.compaction import _delete_section_file

        sec = _make_section(1, transcript_path=None)
        # Should not raise
        _delete_section_file(sec)

    def test_deletes_existing_file(self, tmp_path):
        from app.services.compaction import _delete_section_file

        # Create a temp file
        f = tmp_path / "test_section.md"
        f.write_text("transcript content")

        sec = _make_section(1, transcript_path=str(f))
        _delete_section_file(sec, bot=None)
        assert not f.exists()

    def test_deletes_channel_history_file_from_channel_workspace_root(self, tmp_path):
        from app.services.compaction import _delete_section_file

        rel_path = "channels/channel-1/.history/section_001.md"
        f = tmp_path / rel_path
        f.parent.mkdir(parents=True)
        f.write_text("transcript content")

        sec = _make_section(1, transcript_path=rel_path)
        bot = MagicMock()
        with patch("app.services.compaction._get_channel_ws_root", return_value=str(tmp_path)):
            _delete_section_file(sec, bot=bot)

        assert not f.exists()

    def test_missing_file_does_not_raise(self):
        from app.services.compaction import _delete_section_file

        sec = _make_section(1, transcript_path="/nonexistent/file.md")
        # Should not raise
        _delete_section_file(sec, bot=None)


class TestFormatSectionIndexHeader:
    def test_no_messages_mode_in_header(self):
        from app.services.compaction import format_section_index

        sec = _make_section(1)
        sec.title = "Test Section"
        sec.summary = "A test summary"
        sec.period_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        sec.period_end = datetime(2024, 1, 2, tzinfo=timezone.utc)
        sec.message_count = 10
        sec.tags = None

        result = format_section_index([sec])
        assert "messages:" not in result
        assert "search:<query>" in result
        assert "semantic similarity" in result
