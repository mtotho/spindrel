"""Tests for get_skill tool — carapace-resolved skill access."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.context import (
    current_resolved_skill_ids,
    current_ephemeral_skills,
    AgentContextSnapshot,
    snapshot_agent_context,
    restore_agent_context,
)


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
    fake_bot.carapaces = []

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


@pytest.mark.asyncio
async def test_get_skill_carapace_fallback():
    """When context var is None, get_skill should fallback to resolving bot's carapaces."""
    from app.tools.local.skills import get_skill

    fake_bot = MagicMock()
    fake_bot.skills = [MagicMock(id="base-skill")]
    fake_bot.skill_ids = ["base-skill"]
    fake_bot.api_permissions = None
    fake_bot.shared_workspace_id = None
    fake_bot.carapaces = ["qa"]

    fake_row = MagicMock()
    fake_row.id = "qa-deep-skill"
    fake_row.name = "QA Deep Skill"
    fake_row.content = "# QA Deep Content"

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=fake_row)
    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session_factory = MagicMock(return_value=mock_session_ctx)

    # Simulate resolved carapace returning the skill
    mock_resolved = MagicMock()
    mock_resolved.skills = [MagicMock(id="qa-deep-skill")]

    # Set context var to None (simulating delegation without snapshot/restore)
    tok_bot = current_resolved_skill_ids.set(None)
    tok_eph = current_ephemeral_skills.set([])

    try:
        with (
            patch("app.tools.local.skills.current_bot_id") as mock_bot_id,
            patch("app.tools.local.skills.async_session", mock_session_factory),
            patch("app.agent.bots.get_bot", return_value=fake_bot),
            patch("app.agent.carapaces.resolve_carapaces", return_value=mock_resolved) as mock_resolve,
        ):
            mock_bot_id.get.return_value = "testbot"

            result = await get_skill(skill_id="qa-deep-skill")
    finally:
        current_resolved_skill_ids.reset(tok_bot)
        current_ephemeral_skills.reset(tok_eph)

    assert "QA Deep Content" in result
    assert "not configured" not in result
    mock_resolve.assert_called_once_with(["qa"])


def test_snapshot_restore_preserves_resolved_skill_ids():
    """snapshot/restore round-trip should preserve current_resolved_skill_ids."""
    tok = current_resolved_skill_ids.set({"skill-a", "skill-b", "skill-c"})

    try:
        snap = snapshot_agent_context()
        assert snap.resolved_skill_ids == {"skill-a", "skill-b", "skill-c"}

        # Clear the context var
        current_resolved_skill_ids.set(None)
        assert current_resolved_skill_ids.get() is None

        # Restore should bring it back
        restore_agent_context(snap)
        assert current_resolved_skill_ids.get() == {"skill-a", "skill-b", "skill-c"}
    finally:
        current_resolved_skill_ids.reset(tok)


@pytest.mark.asyncio
async def test_channel_carapaces_extra_fallback():
    """When resolved_skill_ids is None and bot has no carapaces, channel
    carapaces_extra should be resolved to find the skill."""
    from app.tools.local.skills import get_skill
    from app.agent.context import current_channel_id

    fake_bot = MagicMock()
    fake_bot.skills = [MagicMock(id="base-skill")]
    fake_bot.skill_ids = ["base-skill"]
    fake_bot.api_permissions = None
    fake_bot.shared_workspace_id = None
    fake_bot.carapaces = []  # no carapaces on the bot itself

    fake_row = MagicMock()
    fake_row.id = "carapaces/orchestrator/workflow-compiler"
    fake_row.name = "Workflow Compiler"
    fake_row.content = "# Compiler content"

    import uuid as _uuid
    _ch_id = _uuid.uuid4()

    # Channel has carapaces_extra: ["orchestrator"]
    fake_channel = MagicMock()
    fake_channel.skills_extra = None
    fake_channel.carapaces_extra = ["orchestrator"]

    mock_db = AsyncMock()
    async def _fake_get(model, pk):
        if model.__name__ == "Channel":
            return fake_channel
        if pk == "carapaces/orchestrator/workflow-compiler":
            return fake_row
        return None
    mock_db.get = AsyncMock(side_effect=_fake_get)

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session_factory = MagicMock(return_value=mock_session_ctx)

    # Resolved carapace returns the skill
    mock_resolved = MagicMock()
    mock_resolved.skills = [MagicMock(id="carapaces/orchestrator/workflow-compiler")]

    tok_resolved = current_resolved_skill_ids.set(None)
    tok_eph = current_ephemeral_skills.set([])
    tok_ch = current_channel_id.set(_ch_id)

    try:
        with (
            patch("app.tools.local.skills.current_bot_id") as mock_bot_id,
            patch("app.tools.local.skills.async_session", mock_session_factory),
            patch("app.agent.bots.get_bot", return_value=fake_bot),
            patch("app.agent.carapaces.resolve_carapaces", return_value=mock_resolved),
        ):
            mock_bot_id.get.return_value = "mybot"

            result = await get_skill(skill_id="carapaces/orchestrator/workflow-compiler")
    finally:
        current_resolved_skill_ids.reset(tok_resolved)
        current_ephemeral_skills.reset(tok_eph)
        current_channel_id.reset(tok_ch)

    assert "Compiler content" in result
    assert "not configured" not in result


@pytest.mark.asyncio
async def test_keepalive_context_var_bridge():
    """_with_keepalive should propagate context var changes across Task boundaries."""
    import asyncio

    test_var = current_resolved_skill_ids  # reuse a real context var

    async def fake_stream():
        test_var.set({"skill-from-assembly"})
        yield {"type": "assembly"}
        # Next yield boundary — with the fix, the var should survive
        val = test_var.get()
        yield {"type": "check", "value": val}

    from app.routers.chat import _with_keepalive

    tok = test_var.set(None)
    try:
        events = []
        async for event in _with_keepalive(fake_stream(), interval=60):
            if event is not None:
                events.append(event)
    finally:
        test_var.reset(tok)

    assert len(events) == 2
    assert events[0]["type"] == "assembly"
    assert events[1]["type"] == "check"
    # The critical assertion: the var survived the Task boundary
    assert events[1]["value"] == {"skill-from-assembly"}
