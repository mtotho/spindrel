"""Unit tests for attachment retention: write-time enforcement + purge sweep."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_channel(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        attachment_retention_days=None,
        attachment_max_size_bytes=None,
        attachment_types_allowed=None,
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def _mock_db_session():
    """Create a mock async_session context manager."""
    mock_db = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_factory = MagicMock(return_value=mock_ctx)
    return mock_factory, mock_db


# ---------------------------------------------------------------------------
# get_effective_retention
# ---------------------------------------------------------------------------

class TestGetEffectiveRetention:
    def test_channel_overrides_global(self):
        from app.services.attachment_retention import get_effective_retention

        channel = _fake_channel(
            attachment_retention_days=30,
            attachment_max_size_bytes=5_000_000,
            attachment_types_allowed=["image", "text"],
        )
        with patch("app.services.attachment_retention.settings") as mock_settings:
            mock_settings.ATTACHMENT_RETENTION_DAYS = 90
            mock_settings.ATTACHMENT_MAX_SIZE_BYTES = 10_000_000
            mock_settings.ATTACHMENT_TYPES_ALLOWED = None

            result = get_effective_retention(channel)
            assert result["retention_days"] == 30
            assert result["max_size_bytes"] == 5_000_000
            assert result["types_allowed"] == ["image", "text"]

    def test_falls_back_to_global(self):
        from app.services.attachment_retention import get_effective_retention

        channel = _fake_channel()  # all None
        with patch("app.services.attachment_retention.settings") as mock_settings:
            mock_settings.ATTACHMENT_RETENTION_DAYS = 60
            mock_settings.ATTACHMENT_MAX_SIZE_BYTES = 20_000_000
            mock_settings.ATTACHMENT_TYPES_ALLOWED = ["image"]

            result = get_effective_retention(channel)
            assert result["retention_days"] == 60
            assert result["max_size_bytes"] == 20_000_000
            assert result["types_allowed"] == ["image"]

    def test_no_channel_uses_global(self):
        from app.services.attachment_retention import get_effective_retention

        with patch("app.services.attachment_retention.settings") as mock_settings:
            mock_settings.ATTACHMENT_RETENTION_DAYS = None
            mock_settings.ATTACHMENT_MAX_SIZE_BYTES = None
            mock_settings.ATTACHMENT_TYPES_ALLOWED = None

            result = get_effective_retention(None)
            assert result["retention_days"] is None
            assert result["max_size_bytes"] is None
            assert result["types_allowed"] is None


# ---------------------------------------------------------------------------
# create_attachment — write-time enforcement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCreateAttachmentRetention:
    async def test_oversized_file_stores_metadata_only(self):
        """File exceeding max_size_bytes: row created, file_data is None."""
        channel = _fake_channel(attachment_max_size_bytes=1000)

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=channel)
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.attachments.async_session", return_value=mock_ctx),
            patch("app.services.attachments.settings") as mock_settings,
            patch("app.services.attachments._get_bot_attachment_config", new_callable=AsyncMock, return_value={}),
        ):
            mock_settings.ATTACHMENT_SUMMARY_ENABLED = False
            mock_settings.ATTACHMENT_RETENTION_DAYS = None
            mock_settings.ATTACHMENT_MAX_SIZE_BYTES = None
            mock_settings.ATTACHMENT_TYPES_ALLOWED = None

            from app.services.attachments import create_attachment

            with patch("asyncio.create_task"):
                att = await create_attachment(
                    message_id=uuid.uuid4(),
                    channel_id=channel.id,
                    filename="big_file.zip",
                    mime_type="application/zip",
                    size_bytes=5000,  # exceeds 1000 limit
                    posted_by=None,
                    source_integration="web",
                    file_data=b"x" * 5000,
                )

            # The attachment was added to db
            mock_db.add.assert_called_once()
            added_att = mock_db.add.call_args[0][0]
            # file_data should be None because size exceeds limit
            assert added_att.file_data is None
            # But metadata is preserved
            assert added_att.filename == "big_file.zip"
            assert added_att.size_bytes == 5000

    async def test_disallowed_type_stores_metadata_only(self):
        """Attachment type not in allowed list: row created, file_data is None."""
        channel = _fake_channel(attachment_types_allowed=["image", "text"])

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=channel)
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.attachments.async_session", return_value=mock_ctx),
            patch("app.services.attachments.settings") as mock_settings,
            patch("app.services.attachments._get_bot_attachment_config", new_callable=AsyncMock, return_value={}),
        ):
            mock_settings.ATTACHMENT_SUMMARY_ENABLED = False
            mock_settings.ATTACHMENT_RETENTION_DAYS = None
            mock_settings.ATTACHMENT_MAX_SIZE_BYTES = None
            mock_settings.ATTACHMENT_TYPES_ALLOWED = None

            from app.services.attachments import create_attachment

            with patch("asyncio.create_task"):
                att = await create_attachment(
                    message_id=uuid.uuid4(),
                    channel_id=channel.id,
                    filename="song.mp3",
                    mime_type="audio/mpeg",
                    size_bytes=3000,
                    posted_by=None,
                    source_integration="web",
                    file_data=b"audio-bytes",
                )

            added_att = mock_db.add.call_args[0][0]
            assert added_att.file_data is None
            assert added_att.type == "audio"
            assert added_att.filename == "song.mp3"

    async def test_allowed_type_stores_file_data(self):
        """Attachment type in allowed list: file_data is preserved."""
        channel = _fake_channel(attachment_types_allowed=["image", "text"])

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=channel)
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.attachments.async_session", return_value=mock_ctx),
            patch("app.services.attachments.settings") as mock_settings,
            patch("app.services.attachments._get_bot_attachment_config", new_callable=AsyncMock, return_value={}),
        ):
            mock_settings.ATTACHMENT_SUMMARY_ENABLED = False
            mock_settings.ATTACHMENT_RETENTION_DAYS = None
            mock_settings.ATTACHMENT_MAX_SIZE_BYTES = None
            mock_settings.ATTACHMENT_TYPES_ALLOWED = None

            from app.services.attachments import create_attachment

            with patch("asyncio.create_task"):
                att = await create_attachment(
                    message_id=uuid.uuid4(),
                    channel_id=channel.id,
                    filename="photo.png",
                    mime_type="image/png",
                    size_bytes=500,
                    posted_by=None,
                    source_integration="web",
                    file_data=b"image-bytes",
                )

            added_att = mock_db.add.call_args[0][0]
            assert added_att.file_data == b"image-bytes"


# ---------------------------------------------------------------------------
# Purge sweep
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestPurgeSweep:
    async def test_purge_sweep_executes_queries(self):
        """Sweep runs SQL queries and commits."""
        mock_factory, mock_db = _mock_db_session()

        # Mock execute results
        result_mock = MagicMock()
        result_mock.rowcount = 5
        mock_db.execute = AsyncMock(return_value=result_mock)

        with (
            patch("app.services.attachment_retention.async_session", mock_factory),
            patch("app.services.attachment_retention.settings") as mock_settings,
        ):
            mock_settings.ATTACHMENT_RETENTION_DAYS = 30

            from app.services.attachment_retention import run_attachment_purge_sweep
            total = await run_attachment_purge_sweep()

            # Should have executed queries and committed
            assert mock_db.execute.call_count >= 1
            mock_db.commit.assert_called_once()
            assert total > 0

    async def test_purge_sweep_no_global_retention(self):
        """When global retention is None, only per-channel purge runs."""
        mock_factory, mock_db = _mock_db_session()

        result_mock = MagicMock()
        result_mock.rowcount = 0
        mock_db.execute = AsyncMock(return_value=result_mock)

        with (
            patch("app.services.attachment_retention.async_session", mock_factory),
            patch("app.services.attachment_retention.settings") as mock_settings,
        ):
            mock_settings.ATTACHMENT_RETENTION_DAYS = None

            from app.services.attachment_retention import run_attachment_purge_sweep
            total = await run_attachment_purge_sweep()

            # Only 1 query (per-channel), no global/orphan queries
            assert mock_db.execute.call_count == 1
            assert total == 0

    async def test_purge_sweep_with_global_runs_all_queries(self):
        """When global retention is set, all three queries run."""
        mock_factory, mock_db = _mock_db_session()

        result_mock = MagicMock()
        result_mock.rowcount = 2
        mock_db.execute = AsyncMock(return_value=result_mock)

        with (
            patch("app.services.attachment_retention.async_session", mock_factory),
            patch("app.services.attachment_retention.settings") as mock_settings,
        ):
            mock_settings.ATTACHMENT_RETENTION_DAYS = 90

            from app.services.attachment_retention import run_attachment_purge_sweep
            total = await run_attachment_purge_sweep()

            # 3 queries: per-channel, global-channel, orphaned
            assert mock_db.execute.call_count == 3
            assert total == 6  # 2 per query * 3 queries
