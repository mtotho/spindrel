"""Tests for correlation_id isolation in member-bot memory flushes."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_member_bot_flushes_get_unique_correlation_ids():
    """Each member-bot memory flush should get its own correlation_id,
    not reuse the parent turn's correlation_id."""
    from app.services.compaction import _flush_member_bots

    channel = MagicMock()
    channel.id = "ch-1"
    session_id = uuid.uuid4()
    messages = [{"role": "user", "content": "hello"}]

    # Two member bots
    member1 = MagicMock()
    member1.memory_scheme = "workspace-files"
    member2 = MagicMock()
    member2.memory_scheme = "workspace-files"

    captured_ids: list[uuid.UUID | None] = []

    async def fake_flush(ch, bot, sid, msgs, *, correlation_id=None):
        captured_ids.append(correlation_id)
        return None

    with (
        patch("app.services.compaction.async_session") as mock_session_ctx,
        patch("app.services.compaction._run_memory_flush", side_effect=fake_flush) as mock_flush,
        patch("app.agent.bots.get_bot", side_effect=lambda bid: {"bot-a": member1, "bot-b": member2}[bid]),
    ):
        # Mock the DB query to return two bot IDs
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = ["bot-a", "bot-b"]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await _flush_member_bots(channel, session_id, messages)

    assert len(captured_ids) == 2
    # Both should be UUIDs
    assert all(isinstance(cid, uuid.UUID) for cid in captured_ids)
    # They should be different from each other
    assert captured_ids[0] != captured_ids[1]


@pytest.mark.asyncio
async def test_flush_member_bots_skips_non_workspace_files():
    """Bots without memory_scheme='workspace-files' should be skipped."""
    from app.services.compaction import _flush_member_bots

    channel = MagicMock()
    channel.id = "ch-1"

    bot_ws = MagicMock()
    bot_ws.memory_scheme = "workspace-files"
    bot_other = MagicMock()
    bot_other.memory_scheme = "none"

    with (
        patch("app.services.compaction.async_session") as mock_session_ctx,
        patch("app.services.compaction._run_memory_flush", new_callable=AsyncMock) as mock_flush,
        patch("app.agent.bots.get_bot", side_effect=lambda bid: {"ws": bot_ws, "other": bot_other}[bid]),
    ):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = ["ws", "other"]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await _flush_member_bots(channel, uuid.uuid4(), [])

    # Only the workspace-files bot should have been flushed
    assert mock_flush.call_count == 1
    assert mock_flush.call_args[0][1] is bot_ws
