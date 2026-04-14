"""Tests for cascade_skill_deletion — removing deleted skills from bot JSONB."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.agent.skills import cascade_skill_deletion


def _make_bot(bot_id: str, skills: list[dict]):
    bot = MagicMock()
    bot.id = bot_id
    bot.skills = skills
    return bot


def _mock_db(bots: list):
    """Build a mock db session that returns bots from select()."""
    db = AsyncMock()

    async def _execute(stmt):
        result = MagicMock()
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
    db = _mock_db(bots)

    stats = await cascade_skill_deletion("slack_markdown", db)

    assert stats["bots_updated"] == 2
    assert bots[0].skills == [{"id": "home-assistant", "mode": "pinned"}]
    assert bots[1].skills == []
    assert bots[2].skills == [{"id": "other-skill", "mode": "on_demand"}]


@pytest.mark.asyncio
async def test_no_matches_returns_zeros():
    bots = [_make_bot("bot-a", [{"id": "keep-this", "mode": "pinned"}])]
    db = _mock_db(bots)

    stats = await cascade_skill_deletion("nonexistent-skill", db)

    assert stats["bots_updated"] == 0


@pytest.mark.asyncio
async def test_handles_empty_skills():
    bots = [
        _make_bot("bot-a", []),
        _make_bot("bot-b", None),
    ]
    db = _mock_db(bots)

    stats = await cascade_skill_deletion("slack_markdown", db)

    assert stats["bots_updated"] == 0
