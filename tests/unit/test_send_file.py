"""Unit tests for the send_file tool."""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _fake_attachment(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        type="image",
        url=None,
        filename="snapshot.png",
        mime_type="image/png",
        size_bytes=1024,
        file_data=b"fake-image-bytes",
        posted_by="agent",
        source_integration="web",
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


@pytest.mark.asyncio
class TestSendFileRepostSameChannel:
    """send_file(attachment_id=...) in the same channel must create a new attachment."""

    async def test_same_channel_creates_new_attachment(self):
        channel_id = uuid.uuid4()
        att = _fake_attachment(channel_id=channel_id)

        mock_create = AsyncMock()

        with (
            patch("app.tools.local.send_file.current_channel_id") as mock_ch,
            patch("app.tools.local.send_file.current_bot_id") as mock_bot,
            patch("app.tools.local.send_file.current_dispatch_type") as mock_dt,
            patch("app.tools.local.send_file.get_attachment_by_id", new_callable=AsyncMock, return_value=att),
            patch("app.tools.local.send_file.create_attachment", mock_create),
        ):
            mock_ch.get.return_value = channel_id
            mock_bot.get.return_value = "test-bot"
            mock_dt.get.return_value = "web"

            from app.tools.local.send_file import send_file
            result = await send_file(attachment_id=str(att.id), caption="Here it is")

        data = json.loads(result)
        assert "error" not in data
        assert "Sent" in data["message"]

        # A new attachment was created even though channel_id matches
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["channel_id"] == channel_id
        assert call_kwargs["message_id"] is None
        assert call_kwargs["filename"] == "snapshot.png"

    async def test_orphaned_same_channel_skips_duplicate(self):
        """When the attachment is orphaned (no message_id) in the same channel,
        send_file should NOT create a duplicate — it'll be orphan-linked."""
        channel_id = uuid.uuid4()
        att = _fake_attachment(channel_id=channel_id, message_id=None)

        mock_create = AsyncMock()

        with (
            patch("app.tools.local.send_file.current_channel_id") as mock_ch,
            patch("app.tools.local.send_file.current_bot_id") as mock_bot,
            patch("app.tools.local.send_file.current_dispatch_type") as mock_dt,
            patch("app.tools.local.send_file.get_attachment_by_id", new_callable=AsyncMock, return_value=att),
            patch("app.tools.local.send_file.create_attachment", mock_create),
        ):
            mock_ch.get.return_value = channel_id
            mock_bot.get.return_value = "test-bot"
            mock_dt.get.return_value = "web"

            from app.tools.local.send_file import send_file
            result = await send_file(attachment_id=str(att.id), caption="Here it is")

        data = json.loads(result)
        assert "error" not in data
        assert "Sent" in data["message"]

        # No duplicate created — the original orphan will be linked by persist_turn
        mock_create.assert_not_called()

        # No client_action — the original tool already emitted one for display.
        # Returning another would cause Slack to upload the image twice.
        assert "client_action" not in data

    async def test_orphaned_different_channel_creates_new_attachment(self):
        """Orphaned attachment from a different channel must still create a copy."""
        att = _fake_attachment(channel_id=uuid.uuid4(), message_id=None)
        target_channel = uuid.uuid4()

        mock_create = AsyncMock()

        with (
            patch("app.tools.local.send_file.current_channel_id") as mock_ch,
            patch("app.tools.local.send_file.current_bot_id") as mock_bot,
            patch("app.tools.local.send_file.current_dispatch_type") as mock_dt,
            patch("app.tools.local.send_file.get_attachment_by_id", new_callable=AsyncMock, return_value=att),
            patch("app.tools.local.send_file.create_attachment", mock_create),
        ):
            mock_ch.get.return_value = target_channel
            mock_bot.get.return_value = "test-bot"
            mock_dt.get.return_value = "web"

            from app.tools.local.send_file import send_file
            result = await send_file(attachment_id=str(att.id))

        data = json.loads(result)
        assert "error" not in data
        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["channel_id"] == target_channel

    async def test_different_channel_creates_new_attachment(self):
        att = _fake_attachment(channel_id=uuid.uuid4())
        target_channel = uuid.uuid4()

        mock_create = AsyncMock()

        with (
            patch("app.tools.local.send_file.current_channel_id") as mock_ch,
            patch("app.tools.local.send_file.current_bot_id") as mock_bot,
            patch("app.tools.local.send_file.current_dispatch_type") as mock_dt,
            patch("app.tools.local.send_file.get_attachment_by_id", new_callable=AsyncMock, return_value=att),
            patch("app.tools.local.send_file.create_attachment", mock_create),
        ):
            mock_ch.get.return_value = target_channel
            mock_bot.get.return_value = "test-bot"
            mock_dt.get.return_value = "slack"

            from app.tools.local.send_file import send_file
            result = await send_file(attachment_id=str(att.id))

        data = json.loads(result)
        assert "error" not in data
        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["channel_id"] == target_channel

    async def test_no_channel_skips_attachment_creation(self):
        att = _fake_attachment(channel_id=None)

        mock_create = AsyncMock()

        with (
            patch("app.tools.local.send_file.current_channel_id") as mock_ch,
            patch("app.tools.local.send_file.current_bot_id") as mock_bot,
            patch("app.tools.local.send_file.current_dispatch_type") as mock_dt,
            patch("app.tools.local.send_file.get_attachment_by_id", new_callable=AsyncMock, return_value=att),
            patch("app.tools.local.send_file.create_attachment", mock_create),
        ):
            mock_ch.get.return_value = None
            mock_bot.get.return_value = "test-bot"
            mock_dt.get.return_value = "web"

            from app.tools.local.send_file import send_file
            result = await send_file(attachment_id=str(att.id))

        data = json.loads(result)
        assert "error" not in data
        # No channel → no new attachment
        mock_create.assert_not_called()

    async def test_client_action_includes_base64(self):
        channel_id = uuid.uuid4()
        att = _fake_attachment(channel_id=channel_id, mime_type="image/jpeg")

        with (
            patch("app.tools.local.send_file.current_channel_id") as mock_ch,
            patch("app.tools.local.send_file.current_bot_id") as mock_bot,
            patch("app.tools.local.send_file.current_dispatch_type") as mock_dt,
            patch("app.tools.local.send_file.get_attachment_by_id", new_callable=AsyncMock, return_value=att),
            patch("app.tools.local.send_file.create_attachment", new_callable=AsyncMock),
        ):
            mock_ch.get.return_value = channel_id
            mock_bot.get.return_value = "test-bot"
            mock_dt.get.return_value = "web"

            from app.tools.local.send_file import send_file
            result = await send_file(attachment_id=str(att.id))

        data = json.loads(result)
        action = data["client_action"]
        assert action["type"] == "upload_image"
        assert len(action["data"]) > 0  # base64 present

    async def test_not_found_returns_error(self):
        with (
            patch("app.tools.local.send_file.current_channel_id") as mock_ch,
            patch("app.tools.local.send_file.current_bot_id") as mock_bot,
            patch("app.tools.local.send_file.current_dispatch_type") as mock_dt,
            patch("app.tools.local.send_file.get_attachment_by_id", new_callable=AsyncMock, return_value=None),
        ):
            mock_ch.get.return_value = uuid.uuid4()
            mock_bot.get.return_value = "test-bot"
            mock_dt.get.return_value = "web"

            from app.tools.local.send_file import send_file
            result = await send_file(attachment_id=str(uuid.uuid4()))

        data = json.loads(result)
        assert "error" in data
        assert "not found" in data["error"]


@pytest.mark.asyncio
class TestSendFilePathModeOrphanDedup:
    """send_file(path=...) should detect existing orphan attachments in the
    same channel with matching size and skip creating a duplicate."""

    async def test_path_mode_skips_duplicate_when_orphan_exists(self, tmp_path):
        """If an orphan attachment with matching size+mime exists in the channel,
        send_file should NOT create a new attachment and should suppress client_action."""
        channel_id = uuid.uuid4()
        img_data = b"fake-png-bytes-1234"
        img_file = tmp_path / "robot.png"
        img_file.write_bytes(img_data)

        existing_orphan = _fake_attachment(
            channel_id=channel_id,
            message_id=None,
            posted_by="image-bot",
            size_bytes=len(img_data),
            mime_type="image/png",
        )
        mock_create = AsyncMock()

        with (
            patch("app.tools.local.send_file.current_channel_id") as mock_ch,
            patch("app.tools.local.send_file.current_bot_id") as mock_bot,
            patch("app.tools.local.send_file.current_dispatch_type") as mock_dt,
            patch("app.tools.local.send_file.create_attachment", mock_create),
            patch("app.tools.local.send_file.find_orphan_duplicate", new_callable=AsyncMock, return_value=existing_orphan),
        ):
            mock_ch.get.return_value = channel_id
            mock_bot.get.return_value = "test-bot"
            mock_dt.get.return_value = "web"

            from app.tools.local.send_file import send_file
            result = await send_file(path=str(img_file))

        data = json.loads(result)
        assert "error" not in data
        assert "Sent" in data["message"]
        # No duplicate attachment created
        mock_create.assert_not_called()
        # No client_action — the original tool already emitted one
        assert "client_action" not in data

    async def test_path_mode_creates_attachment_when_no_orphan(self, tmp_path):
        """When no matching orphan exists, send_file should create attachment normally."""
        channel_id = uuid.uuid4()
        img_data = b"new-image-bytes"
        img_file = tmp_path / "chart.png"
        img_file.write_bytes(img_data)

        mock_create = AsyncMock()

        with (
            patch("app.tools.local.send_file.current_channel_id") as mock_ch,
            patch("app.tools.local.send_file.current_bot_id") as mock_bot,
            patch("app.tools.local.send_file.current_dispatch_type") as mock_dt,
            patch("app.tools.local.send_file.create_attachment", mock_create),
            patch("app.tools.local.send_file.find_orphan_duplicate", new_callable=AsyncMock, return_value=None),
        ):
            mock_ch.get.return_value = channel_id
            mock_bot.get.return_value = "test-bot"
            mock_dt.get.return_value = "web"

            from app.tools.local.send_file import send_file
            result = await send_file(path=str(img_file))

        data = json.loads(result)
        assert "error" not in data
        mock_create.assert_called_once()
        assert "client_action" in data

    async def test_path_mode_no_channel_skips_dedup(self, tmp_path):
        """When there's no channel_id, no dedup check should happen."""
        img_data = b"image-bytes"
        img_file = tmp_path / "pic.png"
        img_file.write_bytes(img_data)

        mock_create = AsyncMock()
        mock_find = AsyncMock(return_value=None)

        with (
            patch("app.tools.local.send_file.current_channel_id") as mock_ch,
            patch("app.tools.local.send_file.current_bot_id") as mock_bot,
            patch("app.tools.local.send_file.current_dispatch_type") as mock_dt,
            patch("app.tools.local.send_file.create_attachment", mock_create),
            patch("app.tools.local.send_file.find_orphan_duplicate", mock_find),
        ):
            mock_ch.get.return_value = None
            mock_bot.get.return_value = "test-bot"
            mock_dt.get.return_value = "web"

            from app.tools.local.send_file import send_file
            result = await send_file(path=str(img_file))

        data = json.loads(result)
        assert "error" not in data
        # No dedup check when no channel
        mock_find.assert_not_called()

    async def test_path_mode_dedup_error_falls_through(self, tmp_path):
        """If find_orphan_duplicate raises, send_file should still work normally."""
        channel_id = uuid.uuid4()
        img_data = b"some-image"
        img_file = tmp_path / "pic.png"
        img_file.write_bytes(img_data)

        mock_create = AsyncMock()
        mock_find = AsyncMock(side_effect=Exception("DB gone"))

        with (
            patch("app.tools.local.send_file.current_channel_id") as mock_ch,
            patch("app.tools.local.send_file.current_bot_id") as mock_bot,
            patch("app.tools.local.send_file.current_dispatch_type") as mock_dt,
            patch("app.tools.local.send_file.create_attachment", mock_create),
            patch("app.tools.local.send_file.find_orphan_duplicate", mock_find),
        ):
            mock_ch.get.return_value = channel_id
            mock_bot.get.return_value = "test-bot"
            mock_dt.get.return_value = "web"

            from app.tools.local.send_file import send_file
            result = await send_file(path=str(img_file))

        data = json.loads(result)
        assert "error" not in data
        # Falls through to normal path — creates attachment
        mock_create.assert_called_once()
        assert "client_action" in data
