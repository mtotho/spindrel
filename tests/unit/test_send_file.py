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
