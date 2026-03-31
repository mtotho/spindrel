"""Tests for get_skill tool — carapace-resolved skill access."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.context import current_resolved_skill_ids, current_ephemeral_skills


@pytest.mark.asyncio
async def test_carapace_skill_allowed_via_resolved_context():
    """Skills injected by carapaces should be accessible via get_skill."""
    from app.tools.local.skills import get_skill

    fake_bot = MagicMock()
    fake_bot.skills = [MagicMock(id="base-skill")]
    fake_bot.skill_ids = ["base-skill"]
    fake_bot.api_permissions = None
    fake_bot.shared_workspace_id = None

    fake_row = MagicMock()
    fake_row.id = "carapaces/orchestrator/workspace-api-reference"
    fake_row.name = "Workspace API Reference"
    fake_row.content = "# API docs here"

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=fake_row)
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    # Set ContextVars directly instead of patching
    tok_bot = current_resolved_skill_ids.set({
        "base-skill",
        "carapaces/orchestrator/workspace-api-reference",
    })
    tok_eph = current_ephemeral_skills.set([])

    try:
        with (
            patch("app.tools.local.skills.current_bot_id") as mock_bot_id,
            patch("app.tools.local.skills.async_session", return_value=mock_session),
            patch("app.agent.bots.get_bot", return_value=fake_bot),
        ):
            mock_bot_id.get.return_value = "orchestrator"

            result = await get_skill(skill_id="carapaces/orchestrator/workspace-api-reference")
    finally:
        current_resolved_skill_ids.reset(tok_bot)
        current_ephemeral_skills.reset(tok_eph)

    assert "API docs here" in result
    assert "not configured" not in result


@pytest.mark.asyncio
async def test_unconfigured_skill_blocked():
    """Skills not in bot config, carapaces, or ephemeral list should be rejected."""
    from app.tools.local.skills import get_skill

    fake_bot = MagicMock()
    fake_bot.skills = [MagicMock(id="base-skill")]
    fake_bot.skill_ids = ["base-skill"]
    fake_bot.api_permissions = None
    fake_bot.shared_workspace_id = None

    tok_bot = current_resolved_skill_ids.set({"base-skill"})
    tok_eph = current_ephemeral_skills.set([])

    try:
        with (
            patch("app.tools.local.skills.current_bot_id") as mock_bot_id,
            patch("app.agent.bots.get_bot", return_value=fake_bot),
        ):
            mock_bot_id.get.return_value = "orchestrator"

            result = await get_skill(skill_id="some-random-skill")
    finally:
        current_resolved_skill_ids.reset(tok_bot)
        current_ephemeral_skills.reset(tok_eph)

    assert "not configured" in result
