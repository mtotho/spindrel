"""Tests for cascade_skill_deletion — removing deleted skills from bot/channel JSONB."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agent.skills import cascade_skill_deletion


def _make_bot(bot_id: str, skills: list[dict]):
    bot = MagicMock()
    bot.id = bot_id
    bot.skills = skills
    return bot


def _make_channel(channel_id: str, skills_extra: list[dict] | None):
    ch = MagicMock()
    ch.id = channel_id
    ch.skills_extra = skills_extra
    return ch


def _mock_db(bots: list, channels: list):
    """Build a mock db session that returns bots and channels from select()."""
    db = AsyncMock()

    async def _execute(stmt):
        result = MagicMock()
        # Distinguish between Bot and Channel queries by inspecting the statement
        stmt_str = str(stmt)
        if "channels" in stmt_str or "skills_extra" in stmt_str:
            result.scalars().all.return_value = channels
        else:
            result.scalars().all.return_value = bots
        return result

    db.execute = _execute
    return db


@pytest.mark.asyncio
async def test_removes_skill_from_bots():
    bots = [
        _make_bot("bot-a", [{"id": "slack_markdown", "mode": "pinned"}, {"id": "home-assistant", "mode": "pinned"}]),
        _make_bot("bot-b", [{"id": "slack_markdown", "mode": "pinned"}]),
        _make_bot("bot-c", [{"id": "other-skill", "mode": "on_demand"}]),
    ]
    db = _mock_db(bots, [])

    stats = await cascade_skill_deletion("slack_markdown", db)

    assert stats["bots_updated"] == 2
    assert bots[0].skills == [{"id": "home-assistant", "mode": "pinned"}]
    assert bots[1].skills == []
    assert bots[2].skills == [{"id": "other-skill", "mode": "on_demand"}]


@pytest.mark.asyncio
async def test_removes_skill_from_channels():
    channels = [
        _make_channel("ch-1", [{"id": "slack_markdown", "mode": "pinned"}, {"id": "context_mastery", "mode": "on_demand"}]),
        _make_channel("ch-2", [{"id": "other", "mode": "on_demand"}]),
    ]
    db = _mock_db([], channels)

    stats = await cascade_skill_deletion("slack_markdown", db)

    assert stats["channels_updated"] == 1
    assert channels[0].skills_extra == [{"id": "context_mastery", "mode": "on_demand"}]
    assert channels[1].skills_extra == [{"id": "other", "mode": "on_demand"}]


@pytest.mark.asyncio
async def test_no_matches_returns_zeros():
    bots = [_make_bot("bot-a", [{"id": "keep-this", "mode": "pinned"}])]
    channels = [_make_channel("ch-1", [{"id": "keep-this", "mode": "on_demand"}])]
    db = _mock_db(bots, channels)

    stats = await cascade_skill_deletion("nonexistent-skill", db)

    assert stats["bots_updated"] == 0
    assert stats["channels_updated"] == 0


@pytest.mark.asyncio
async def test_handles_empty_skills():
    bots = [
        _make_bot("bot-a", []),
        _make_bot("bot-b", None),
    ]
    db = _mock_db(bots, [])

    stats = await cascade_skill_deletion("slack_markdown", db)

    assert stats["bots_updated"] == 0


@pytest.mark.asyncio
async def test_handles_none_skills_extra():
    channels = [_make_channel("ch-1", None)]
    db = _mock_db([], channels)

    stats = await cascade_skill_deletion("any-skill", db)

    assert stats["channels_updated"] == 0
