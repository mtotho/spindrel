"""Tests for get_skill tool — simplified access model.

Skills are shared documents. Any bot can fetch any skill except other bots'
private skills (bots/{other_bot_id}/...).
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.context import (
    current_skills_in_context,
    current_resolved_skill_ids,
    current_ephemeral_skills,
    AgentContextSnapshot,
    snapshot_agent_context,
    restore_agent_context,
)


@pytest.mark.asyncio
async def test_any_skill_accessible():
    """Any non-bot-scoped skill is accessible to any bot."""
    from app.tools.local.skills import get_skill

    fake_row = MagicMock()
    fake_row.id = "shared/workspace-api-reference"
    fake_row.name = "Workspace API Reference"
    fake_row.content = "# API docs here"
    fake_row.archived_at = None

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=fake_row)
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.tools.local.skills.current_bot_id") as mock_bot_id,
        patch("app.tools.local.skills.async_session", return_value=mock_session),
    ):
        mock_bot_id.get.return_value = "some-random-bot"

        result = await get_skill(skill_id="shared/workspace-api-reference")

    assert "API docs here" in result
    assert "not configured" not in result


@pytest.mark.asyncio
async def test_bot_scoped_skill_denied_for_other_bot():
    """Skills prefixed with bots/{other_id}/ are denied."""
    from app.tools.local.skills import get_skill

    with patch("app.tools.local.skills.current_bot_id") as mock_bot_id:
        mock_bot_id.get.return_value = "my-bot"

        result = await get_skill(skill_id="bots/other-bot/private-notes")

    assert "not configured" in result


@pytest.mark.asyncio
async def test_bot_scoped_skill_allowed_for_owning_bot():
    """A bot can access its own bots/{id}/... skills."""
    from app.tools.local.skills import get_skill

    fake_row = MagicMock()
    fake_row.id = "bots/my-bot/private-notes"
    fake_row.name = "Private Notes"
    fake_row.content = "# My private notes"
    fake_row.archived_at = None

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=fake_row)
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.tools.local.skills.current_bot_id") as mock_bot_id,
        patch("app.tools.local.skills.async_session", return_value=mock_session),
    ):
        mock_bot_id.get.return_value = "my-bot"

        result = await get_skill(skill_id="bots/my-bot/private-notes")

    assert "My private notes" in result
    assert "not configured" not in result


@pytest.mark.asyncio
async def test_skill_not_found():
    """Non-existent skill returns not found message."""
    from app.tools.local.skills import get_skill

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=None)
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.tools.local.skills.current_bot_id") as mock_bot_id,
        patch("app.tools.local.skills.async_session", return_value=mock_session),
    ):
        mock_bot_id.get.return_value = "some-bot"

        result = await get_skill(skill_id="nonexistent-skill")

    assert "not found" in result


@pytest.mark.asyncio
async def test_get_skill_returns_already_loaded_when_skill_is_in_context():
    """Duplicate fetches should short-circuit unless refresh=True is requested."""
    from app.tools.local.skills import get_skill

    fake_row = MagicMock()
    fake_row.id = "shared/workspace-api-reference"
    fake_row.name = "Workspace API Reference"
    fake_row.content = "# API docs here"
    fake_row.archived_at = None

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=fake_row)
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    token = current_skills_in_context.set([
        {
            "skill_id": "shared/workspace-api-reference",
            "skill_name": "Workspace API Reference",
            "source": "loaded",
            "messages_ago": 0,
        }
    ])
    try:
        with (
            patch("app.tools.local.skills.current_bot_id") as mock_bot_id,
            patch("app.tools.local.skills.async_session", return_value=mock_session),
        ):
            mock_bot_id.get.return_value = "some-random-bot"

            result = await get_skill(skill_id="shared/workspace-api-reference")
    finally:
        current_skills_in_context.reset(token)

    assert '"already_loaded": true' in result
    assert "API docs here" not in result


@pytest.mark.asyncio
async def test_get_skill_marks_skill_as_resident_for_later_calls():
    """A fresh fetch should update current_skills_in_context for same-turn dedupe."""
    from app.tools.local.skills import get_skill

    fake_row = MagicMock()
    fake_row.id = "shared/workspace-api-reference"
    fake_row.name = "Workspace API Reference"
    fake_row.content = "# API docs here"
    fake_row.archived_at = None

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=fake_row)
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    token = current_skills_in_context.set([])
    try:
        with (
            patch("app.tools.local.skills.current_bot_id") as mock_bot_id,
            patch("app.tools.local.skills.async_session", return_value=mock_session),
        ):
            mock_bot_id.get.return_value = "some-random-bot"

            first = await get_skill(skill_id="shared/workspace-api-reference")
            second = await get_skill(skill_id="shared/workspace-api-reference")
    finally:
        current_skills_in_context.reset(token)

    assert "API docs here" in first
    assert '"already_loaded": true' in second


@pytest.mark.asyncio
async def test_get_skill_refresh_true_returns_full_content_even_if_skill_is_in_context():
    """Explicit refresh should preserve the old behavior and return full content."""
    from app.tools.local.skills import get_skill

    fake_row = MagicMock()
    fake_row.id = "shared/workspace-api-reference"
    fake_row.name = "Workspace API Reference"
    fake_row.content = "# API docs here"
    fake_row.archived_at = None

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=fake_row)
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    token = current_skills_in_context.set([
        {
            "skill_id": "shared/workspace-api-reference",
            "skill_name": "Workspace API Reference",
            "source": "loaded",
            "messages_ago": 0,
        }
    ])
    try:
        with (
            patch("app.tools.local.skills.current_bot_id") as mock_bot_id,
            patch("app.tools.local.skills.async_session", return_value=mock_session),
        ):
            mock_bot_id.get.return_value = "some-random-bot"

            result = await get_skill(
                skill_id="shared/workspace-api-reference",
                refresh=True,
            )
    finally:
        current_skills_in_context.reset(token)

    assert "API docs here" in result
    assert '"already_loaded": true' not in result


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


def test_snapshot_restore_preserves_skills_in_context():
    """snapshot/restore round-trip should preserve current_skills_in_context."""
    skills = [{"skill_id": "skill-a", "skill_name": "Skill A", "source": "loaded", "messages_ago": 1}]
    tok = current_skills_in_context.set(skills)

    try:
        snap = snapshot_agent_context()
        assert snap.skills_in_context == skills

        current_skills_in_context.set(None)
        assert current_skills_in_context.get() is None

        restore_agent_context(snap)
        assert current_skills_in_context.get() == skills
    finally:
        current_skills_in_context.reset(tok)
