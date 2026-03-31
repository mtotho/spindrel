"""Unit tests for list_attachments local tool — especially string coercion of limit/page."""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _fake_attachment(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        type="image",
        filename="test.png",
        mime_type="image/png",
        size_bytes=1000,
        description="A test image",
        posted_by="test-bot",
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


@pytest.fixture
def _mock_db():
    """Patch async_session to return fake DB results."""
    channel_id = uuid.uuid4()
    attachments = [_fake_attachment(channel_id=channel_id) for _ in range(3)]

    # Mock the DB session and query results
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = attachments

    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_count_result = MagicMock()
    mock_count_result.scalar.return_value = 3

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[mock_count_result, mock_result])

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.db.engine.async_session", return_value=mock_ctx),
        patch("app.agent.context.current_channel_id") as mock_ch,
    ):
        mock_ch.get.return_value = channel_id
        yield channel_id


@pytest.mark.asyncio
async def test_list_attachments_string_limit(_mock_db):
    """Regression: LLMs pass limit as string '5', should not raise TypeError."""
    from app.tools.local.attachments import list_attachments

    result = json.loads(await list_attachments(limit="5"))
    assert "error" not in result
    assert result["total_count"] == 3


@pytest.mark.asyncio
async def test_list_attachments_string_page(_mock_db):
    """Regression: LLMs pass page as string '2', should not raise TypeError."""
    from app.tools.local.attachments import list_attachments

    result = json.loads(await list_attachments(page="2"))
    assert "error" not in result


@pytest.mark.asyncio
async def test_list_attachments_int_params(_mock_db):
    """Normal int params still work fine."""
    from app.tools.local.attachments import list_attachments

    result = json.loads(await list_attachments(limit=5, page=1))
    assert "error" not in result
    assert len(result["attachments"]) == 3
