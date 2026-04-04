"""Tests for the manage_bot_skill tool — bot self-authored skill CRUD."""

import json
import hashlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.local.bot_skills import (
    BOT_SKILL_COUNT_WARNING,
    _bot_skill_id,
    _build_content,
    _extract_body,
    _extract_frontmatter,
    _slugify,
    manage_bot_skill,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_skill_row(skill_id: str, name: str = "Test", content: str = "body",
                    source_type: str = "tool", **kw):
    row = MagicMock()
    row.id = skill_id
    row.name = name
    row.content = content
    row.content_hash = hashlib.sha256(content.encode()).hexdigest()
    row.source_type = source_type
    row.source_path = kw.get("source_path")
    row.created_at = kw.get("created_at", datetime.now(timezone.utc))
    row.updated_at = kw.get("updated_at", datetime.now(timezone.utc))
    return row


def _parse(result: str) -> dict:
    return json.loads(result)


def _mock_session(db_mock):
    """Create a mock async context manager that yields db_mock."""
    session_ctx = AsyncMock()
    session_ctx.__aenter__ = AsyncMock(return_value=db_mock)
    session_ctx.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock(return_value=session_ctx)
    return factory


# ---------------------------------------------------------------------------
# Unit tests — helpers
# ---------------------------------------------------------------------------

class TestBotSkillHelpers:

    def test_bot_skill_id_basic(self):
        assert _bot_skill_id("mybot", "my-skill") == "bots/mybot/my-skill"

    def test_bot_skill_id_spaces(self):
        assert _bot_skill_id("mybot", "My Skill Name") == "bots/mybot/my-skill-name"

    def test_bot_skill_id_uppercase(self):
        assert _bot_skill_id("mybot", "MySkill") == "bots/mybot/myskill"

    def test_bot_skill_id_rejects_empty(self):
        with pytest.raises(ValueError):
            _bot_skill_id("mybot", "!!!!")

    def test_slugify_strips_special_chars(self):
        assert _slugify("../../escape") == "escape"
        assert _slugify("hello world!") == "hello-world"
        assert _slugify("  My--Skill  ") == "my-skill"

    def test_slugify_empty_returns_empty(self):
        assert _slugify("") == ""
        assert _slugify("!!!") == ""

    def test_build_content_full(self):
        result = _build_content("My Title", "The body", triggers="error, crash", category="troubleshooting")
        assert "---" in result
        assert "name: My Title" in result
        assert "triggers: error, crash" in result
        assert "category: troubleshooting" in result
        assert "The body" in result

    def test_build_content_minimal(self):
        result = _build_content("Title", "Body only")
        assert "name: Title" in result
        assert "triggers:" not in result
        assert "category:" not in result
        assert "Body only" in result

    def test_extract_body(self):
        content = "---\nname: Test\ntriggers: foo\n---\n\nThe body here"
        assert _extract_body(content) == "The body here"

    def test_extract_body_no_frontmatter(self):
        assert _extract_body("Just content") == "Just content"

    def test_extract_frontmatter(self):
        content = "---\nname: Test\ntriggers: foo, bar\ncategory: debug\n---\n\nBody"
        fm = _extract_frontmatter(content)
        assert fm["name"] == "Test"
        assert fm["triggers"] == "foo, bar"
        assert fm["category"] == "debug"

    def test_extract_frontmatter_no_frontmatter(self):
        assert _extract_frontmatter("No frontmatter") == {}


# ---------------------------------------------------------------------------
# CRUD action tests
# ---------------------------------------------------------------------------

class TestCreate:

    @pytest.mark.asyncio
    async def test_no_bot_context(self):
        with patch("app.tools.local.bot_skills.current_bot_id") as ctx:
            ctx.get.return_value = None
            result = _parse(await manage_bot_skill(action="create"))
            assert "No bot context" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_fields(self):
        with patch("app.tools.local.bot_skills.current_bot_id") as ctx:
            ctx.get.return_value = "testbot"
            # Missing title and content
            result = _parse(await manage_bot_skill(action="create", name="foo"))
            assert "required" in result["error"]

    @pytest.mark.asyncio
    async def test_success(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        db.add = MagicMock()
        db.commit = AsyncMock()

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
            patch("app.tools.local.bot_skills._embed_skill_safe", new_callable=AsyncMock),
            patch("app.tools.local.bot_skills._check_count_warning", new_callable=AsyncMock, return_value=None),
            patch("asyncio.create_task"),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="create", name="my-skill", title="My Skill",
                content="# How to fix X\n\nDo Y.",
                triggers="fix, error", category="troubleshooting",
            ))
            assert result["ok"] is True
            assert result["id"] == "bots/testbot/my-skill"
            db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_duplicate_rejected(self):
        existing = _make_skill_row("bots/testbot/my-skill")
        db = AsyncMock()
        db.get = AsyncMock(return_value=existing)

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="create", name="my-skill", title="My Skill", content="c",
            ))
            assert "already exists" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_name_rejected(self):
        with patch("app.tools.local.bot_skills.current_bot_id") as ctx:
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="create", name="!!!!", title="Bad", content="c",
            ))
            assert "Invalid skill name" in result["error"]

    @pytest.mark.asyncio
    async def test_count_warning_included(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        db.add = MagicMock()
        db.commit = AsyncMock()

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
            patch("app.tools.local.bot_skills._embed_skill_safe", new_callable=AsyncMock),
            patch("app.tools.local.bot_skills._check_count_warning", new_callable=AsyncMock,
                  return_value="Warning: You now have 55 self-authored skills."),
            patch("asyncio.create_task"),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="create", name="s", title="T", content="c",
            ))
            assert result["ok"] is True
            assert "55" in result["message"]


class TestList:

    @pytest.mark.asyncio
    async def test_empty(self):
        db = AsyncMock()
        # execute returns a MagicMock (sync) with .scalars().all() chain
        exec_result = MagicMock()
        exec_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=exec_result)

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(action="list"))
            assert result["skills"] == []

    @pytest.mark.asyncio
    async def test_with_results(self):
        rows = [
            _make_skill_row("bots/testbot/skill-a", name="Skill A"),
            _make_skill_row("bots/testbot/skill-b", name="Skill B"),
        ]
        db = AsyncMock()
        exec_result = MagicMock()
        exec_result.scalars.return_value.all.return_value = rows
        db.execute = AsyncMock(return_value=exec_result)

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(action="list"))
            assert result["count"] == 2
            assert result["skills"][0]["id"] == "bots/testbot/skill-a"


class TestGet:

    @pytest.mark.asyncio
    async def test_missing_name(self):
        with patch("app.tools.local.bot_skills.current_bot_id") as ctx:
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(action="get"))
            assert "error" in result

    @pytest.mark.asyncio
    async def test_not_found(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(action="get", name="missing"))
            assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_success(self):
        row = _make_skill_row("bots/testbot/my-skill", name="My Skill", content="the content")
        db = AsyncMock()
        db.get = AsyncMock(return_value=row)

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(action="get", name="my-skill"))
            assert result["id"] == "bots/testbot/my-skill"
            assert result["content"] == "the content"


class TestUpdate:

    @pytest.mark.asyncio
    async def test_not_found(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(action="update", name="missing"))
            assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_file_managed_rejected(self):
        row = _make_skill_row("bots/testbot/my-skill", source_type="file")
        db = AsyncMock()
        db.get = AsyncMock(return_value=row)

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="update", name="my-skill", content="new",
            ))
            assert "file-managed" in result["error"]

    @pytest.mark.asyncio
    async def test_cross_bot_rejected(self):
        """A skill belonging to another bot should not be updatable."""
        row = _make_skill_row("bots/otherbot/skill", source_type="tool")
        db = AsyncMock()
        db.get = AsyncMock(return_value=row)

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            # _bot_skill_id("testbot", "skill") = "bots/testbot/skill"
            # but db returns row with id "bots/otherbot/skill"
            # The prefix check catches this.
            result = _parse(await manage_bot_skill(
                action="update", name="skill", content="new",
            ))
            assert "error" in result

    @pytest.mark.asyncio
    async def test_success(self):
        row = _make_skill_row("bots/testbot/my-skill", source_type="tool")
        db = AsyncMock()
        db.get = AsyncMock(return_value=row)
        db.commit = AsyncMock()

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
            patch("app.tools.local.bot_skills._embed_skill_safe", new_callable=AsyncMock),
            patch("asyncio.create_task"),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="update", name="my-skill", content="updated body",
            ))
            assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_update_preserves_existing_frontmatter(self):
        """Updating triggers should not drop existing category."""
        existing = "---\nname: My Skill\ntriggers: old-trigger\ncategory: debug\n---\n\nOriginal body"
        row = _make_skill_row("bots/testbot/my-skill", content=existing, source_type="tool")
        db = AsyncMock()
        db.get = AsyncMock(return_value=row)
        db.commit = AsyncMock()

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
            patch("app.tools.local.bot_skills._embed_skill_safe", new_callable=AsyncMock),
            patch("asyncio.create_task"),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="update", name="my-skill", triggers="new-trigger",
            ))
            assert result["ok"] is True
            # Verify category was preserved
            assert "category: debug" in row.content
            assert "triggers: new-trigger" in row.content
            assert "Original body" in row.content

    @pytest.mark.asyncio
    async def test_update_no_changes_rejected(self):
        row = _make_skill_row("bots/testbot/my-skill", source_type="tool")
        db = AsyncMock()
        db.get = AsyncMock(return_value=row)

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(action="update", name="my-skill"))
            assert "error" in result
            assert "at least one" in result["error"]


class TestDelete:

    @pytest.mark.asyncio
    async def test_not_found(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(action="delete", name="missing"))
            assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_file_rejected(self):
        row = _make_skill_row("bots/testbot/my-skill", source_type="file")
        db = AsyncMock()
        db.get = AsyncMock(return_value=row)

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(action="delete", name="my-skill"))
            assert "file-managed" in result["error"]

    @pytest.mark.asyncio
    async def test_success(self):
        row = _make_skill_row("bots/testbot/my-skill", source_type="tool")
        db = AsyncMock()
        db.get = AsyncMock(return_value=row)
        db.delete = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(action="delete", name="my-skill"))
            assert result["ok"] is True
            db.delete.assert_called_once()


class TestPatch:

    @pytest.mark.asyncio
    async def test_missing_texts(self):
        with patch("app.tools.local.bot_skills.current_bot_id") as ctx:
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="patch", name="x", old_text="", new_text="y",
            ))
            assert "required" in result["error"]

    @pytest.mark.asyncio
    async def test_old_text_not_found(self):
        row = _make_skill_row("bots/testbot/my-skill", content="original content", source_type="tool")
        db = AsyncMock()
        db.get = AsyncMock(return_value=row)

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="patch", name="my-skill",
                old_text="not here", new_text="replacement",
            ))
            assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_success(self):
        row = _make_skill_row("bots/testbot/my-skill", content="original content", source_type="tool")
        db = AsyncMock()
        db.get = AsyncMock(return_value=row)
        db.commit = AsyncMock()

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
            patch("app.tools.local.bot_skills._embed_skill_safe", new_callable=AsyncMock),
            patch("asyncio.create_task"),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="patch", name="my-skill",
                old_text="original", new_text="updated",
            ))
            assert result["ok"] is True
            assert "updated content" in row.content


class TestUnknownAction:

    @pytest.mark.asyncio
    async def test_unknown(self):
        with patch("app.tools.local.bot_skills.current_bot_id") as ctx:
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(action="nope"))
            assert "Unknown action" in result["error"]


# ---------------------------------------------------------------------------
# Security: prefix enforcement
# ---------------------------------------------------------------------------

class TestSecurity:

    def test_skill_id_scoped_to_bot(self):
        assert _bot_skill_id("alice", "hack") == "bots/alice/hack"

    def test_skill_id_slug_normalization(self):
        assert _bot_skill_id("bot", "My Great Skill") == "bots/bot/my-great-skill"


# ---------------------------------------------------------------------------
# Count warning
# ---------------------------------------------------------------------------

class TestCountWarning:

    @pytest.mark.asyncio
    async def test_no_warning_under_limit(self):
        from app.tools.local.bot_skills import _check_count_warning

        db = AsyncMock()
        exec_result = MagicMock()
        exec_result.scalar_one.return_value = 10
        db.execute = AsyncMock(return_value=exec_result)

        with patch("app.db.engine.async_session", _mock_session(db)):
            result = await _check_count_warning("testbot", "bots/testbot/")
            assert result is None

    @pytest.mark.asyncio
    async def test_warning_at_limit(self):
        from app.tools.local.bot_skills import _check_count_warning

        db = AsyncMock()
        exec_result = MagicMock()
        exec_result.scalar_one.return_value = BOT_SKILL_COUNT_WARNING
        db.execute = AsyncMock(return_value=exec_result)

        with patch("app.db.engine.async_session", _mock_session(db)):
            result = await _check_count_warning("testbot", "bots/testbot/")
            assert result is not None
            assert "50" in result


# ---------------------------------------------------------------------------
# Access control in get_skill
# ---------------------------------------------------------------------------

class TestGetSkillAccess:

    @pytest.mark.asyncio
    async def test_bot_prefix_check_logic(self):
        """Verify the bot-prefix access check recognizes own skills."""
        # This tests the logic directly rather than through the full
        # get_skill function (which needs a real DB session).
        bot_id = "testbot"
        skill_id = f"bots/{bot_id}/my-skill"
        assert skill_id.startswith(f"bots/{bot_id}/")

        other_skill = "bots/otherbot/secret"
        assert not other_skill.startswith(f"bots/{bot_id}/")

    @pytest.mark.asyncio
    async def test_bot_can_access_own_skill_via_get_skill(self):
        """Bot should access its own self-authored skills via get_skill."""
        from app.tools.local.skills import get_skill

        row = _make_skill_row("bots/testbot/my-skill", name="My Skill", content="body")

        db = AsyncMock()
        db.get = AsyncMock(return_value=row)

        mock_bot = MagicMock()
        mock_bot.skills = []
        mock_bot.skill_ids = set()
        mock_bot.api_permissions = None

        # get_skill imports async_session from app.db.engine inside its body
        with (
            patch("app.tools.local.skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
            patch("app.tools.local.skills.async_session", _mock_session(db)),
            patch("app.agent.bots.get_bot", return_value=mock_bot),
        ):
            ctx.get.return_value = "testbot"
            result = await get_skill(skill_id="bots/testbot/my-skill")
            assert "not configured" not in result
            assert "My Skill" in result
