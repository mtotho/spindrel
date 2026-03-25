"""Unit tests for app.tools.local.summarize_channel tool function."""
import uuid
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSummarizeChannelTool:
    async def test_no_channel_id_returns_error(self):
        from app.tools.local.summarize_channel import summarize_channel

        with patch(
            "app.tools.local.summarize_channel.current_channel_id",
            MagicMock(get=MagicMock(return_value=None)),
        ):
            result = await summarize_channel()
        assert "Error" in result

    async def test_delegates_to_service(self):
        from app.tools.local.summarize_channel import summarize_channel

        ch_id = uuid.uuid4()
        mock_summarize = AsyncMock(return_value="Summary of conversation.")

        with (
            patch(
                "app.tools.local.summarize_channel.current_channel_id",
                MagicMock(get=MagicMock(return_value=ch_id)),
            ),
            patch(
                "app.services.summarizer.summarize_messages",
                mock_summarize,
            ),
        ):
            result = await summarize_channel(skip=10, take=50, prompt="focus on DB")

        assert result == "Summary of conversation."
        mock_summarize.assert_called_once_with(
            channel_id=ch_id,
            skip=10,
            take=50,
            target_size=None,
            prompt="focus on DB",
            start_date=None,
            end_date=None,
        )

    async def test_passes_date_range(self):
        from app.tools.local.summarize_channel import summarize_channel

        ch_id = uuid.uuid4()
        mock_summarize = AsyncMock(return_value="Date-filtered summary.")

        with (
            patch(
                "app.tools.local.summarize_channel.current_channel_id",
                MagicMock(get=MagicMock(return_value=ch_id)),
            ),
            patch(
                "app.services.summarizer.summarize_messages",
                mock_summarize,
            ),
        ):
            result = await summarize_channel(
                start_date="2026-03-20",
                end_date="2026-03-22",
            )

        assert result == "Date-filtered summary."
        call_kwargs = mock_summarize.call_args.kwargs
        assert call_kwargs["start_date"] == "2026-03-20"
        assert call_kwargs["end_date"] == "2026-03-22"

    async def test_passes_target_size(self):
        from app.tools.local.summarize_channel import summarize_channel

        ch_id = uuid.uuid4()
        mock_summarize = AsyncMock(return_value="Short summary.")

        with (
            patch(
                "app.tools.local.summarize_channel.current_channel_id",
                MagicMock(get=MagicMock(return_value=ch_id)),
            ),
            patch(
                "app.services.summarizer.summarize_messages",
                mock_summarize,
            ),
        ):
            result = await summarize_channel(target_size=500)

        call_kwargs = mock_summarize.call_args.kwargs
        assert call_kwargs["target_size"] == 500
