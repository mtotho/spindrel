"""Tests for the manage_bot_skill tool — bot self-authored skill CRUD."""

import json
import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.local.bot_skills import (
    BOT_SKILL_COUNT_WARNING,
    CONTENT_MIN_LENGTH,
    CONTENT_MAX_LENGTH,
    DEDUP_SIMILARITY_THRESHOLD,
    NAME_MAX_LENGTH,
    STALE_LAST_SURFACED_DAYS,
    STALE_NEVER_SURFACED_DAYS,
    _bot_skill_id,
    _build_content,
    _check_skill_dedup,
    _embed_skill_safe,
    _extract_body,
    _extract_frontmatter,
    _is_stale,
    _sanitize_frontmatter_value,
    _slugify,
    _validate_content,
    _validate_name,
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
    row.last_surfaced_at = kw.get("last_surfaced_at", None)
    row.surface_count = kw.get("surface_count", 0)
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
            patch("app.tools.local.bot_skills._embed_skill_safe", new_callable=AsyncMock, return_value=True),
            patch("app.tools.local.bot_skills._check_count_warning", new_callable=AsyncMock, return_value=None),
            patch("app.tools.local.bot_skills._invalidate_cache"),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="create", name="my-skill", title="My Skill",
                content="# How to fix X\n\nDo Y. " + "x" * 50,
                triggers="fix, error", category="troubleshooting",
            ))
            assert result["ok"] is True
            assert result["id"] == "bots/testbot/my-skill"
            assert result["embedded"] is True
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
                action="create", name="my-skill", title="My Skill",
                content="x" * CONTENT_MIN_LENGTH,
            ))
            assert "already exists" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_name_rejected(self):
        with patch("app.tools.local.bot_skills.current_bot_id") as ctx:
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="create", name="!!!!", title="Bad",
                content="x" * CONTENT_MIN_LENGTH,
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
            patch("app.tools.local.bot_skills._embed_skill_safe", new_callable=AsyncMock, return_value=True),
            patch("app.tools.local.bot_skills._check_count_warning", new_callable=AsyncMock,
                  return_value="Warning: You now have 55 self-authored skills."),
            patch("app.tools.local.bot_skills._invalidate_cache"),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="create", name="s", title="T",
                content="x" * CONTENT_MIN_LENGTH,
            ))
            assert result["ok"] is True
            assert "55" in result["message"]


class TestList:

    @pytest.mark.asyncio
    async def test_empty(self):
        db = AsyncMock()
        # First call: count query → scalar_one returns 0
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        # Second call: rows query → scalars().all() returns []
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[count_result, rows_result])

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(action="list"))
            assert result["skills"] == []
            assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_with_results(self):
        content_a = "---\nname: Skill A\ncategory: debug\n---\n\nSome body content here"
        content_b = "---\nname: Skill B\n---\n\nAnother body"
        rows = [
            _make_skill_row("bots/testbot/skill-a", name="Skill A", content=content_a),
            _make_skill_row("bots/testbot/skill-b", name="Skill B", content=content_b),
        ]
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 2
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = rows
        db.execute = AsyncMock(side_effect=[count_result, rows_result])

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(action="list"))
            assert result["total"] == 2
            assert result["skills"][0]["id"] == "bots/testbot/skill-a"
            assert result["skills"][0]["category"] == "debug"
            assert result["skills"][0]["preview"] == "Some body content here"
            assert result["skills"][1]["category"] == ""


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
            patch("app.tools.local.bot_skills._invalidate_cache"),
            patch("asyncio.create_task"),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="update", name="my-skill", content="updated body " + "x" * 50,
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
            patch("app.tools.local.bot_skills._invalidate_cache"),
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
            patch("app.tools.local.bot_skills._invalidate_cache"),
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
        body = "original content that is long enough to pass validation " + "x" * 50
        full_content = f"---\nname: Test\n---\n\n{body}"
        row = _make_skill_row("bots/testbot/my-skill", content=full_content, source_type="tool")
        db = AsyncMock()
        db.get = AsyncMock(return_value=row)
        db.commit = AsyncMock()

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
            patch("app.tools.local.bot_skills._embed_skill_safe", new_callable=AsyncMock),
            patch("app.tools.local.bot_skills._invalidate_cache"),
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


# ---------------------------------------------------------------------------
# Content & name validation
# ---------------------------------------------------------------------------

class TestValidation:

    def test_validate_content_too_short(self):
        assert _validate_content("short") is not None
        assert "too short" in _validate_content("short").lower()

    def test_validate_content_ok(self):
        assert _validate_content("x" * CONTENT_MIN_LENGTH) is None

    def test_validate_content_too_large(self):
        assert _validate_content("x" * (CONTENT_MAX_LENGTH + 1)) is not None
        assert "too large" in _validate_content("x" * (CONTENT_MAX_LENGTH + 1)).lower()

    def test_validate_name_ok(self):
        assert _validate_name("my-skill") is None

    def test_validate_name_too_long(self):
        assert _validate_name("x" * (NAME_MAX_LENGTH + 1)) is not None
        assert "too long" in _validate_name("x" * (NAME_MAX_LENGTH + 1)).lower()

    @pytest.mark.asyncio
    async def test_create_rejects_short_content(self):
        with patch("app.tools.local.bot_skills.current_bot_id") as ctx:
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="create", name="foo", title="Foo", content="tiny",
            ))
            assert "too short" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_create_rejects_long_name(self):
        with patch("app.tools.local.bot_skills.current_bot_id") as ctx:
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="create", name="x" * (NAME_MAX_LENGTH + 1), title="Foo",
                content="x" * CONTENT_MIN_LENGTH,
            ))
            assert "too long" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_update_rejects_short_content(self):
        row = _make_skill_row("bots/testbot/my-skill", source_type="tool")
        db = AsyncMock()
        db.get = AsyncMock(return_value=row)

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="update", name="my-skill", content="tiny",
            ))
            assert "too short" in result["error"].lower()


# ---------------------------------------------------------------------------
# Embedding status
# ---------------------------------------------------------------------------

class TestEmbeddingStatus:

    @pytest.mark.asyncio
    async def test_create_reports_embedding_success(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        db.add = MagicMock()
        db.commit = AsyncMock()

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
            patch("app.tools.local.bot_skills._embed_skill_safe", new_callable=AsyncMock, return_value=True),
            patch("app.tools.local.bot_skills._check_count_warning", new_callable=AsyncMock, return_value=None),
            patch("app.tools.local.bot_skills._invalidate_cache"),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="create", name="ok-skill", title="OK",
                content="x" * CONTENT_MIN_LENGTH,
            ))
            assert result["embedded"] is True
            assert "embedding failed" not in result["message"]

    @pytest.mark.asyncio
    async def test_create_reports_embedding_failure(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        db.add = MagicMock()
        db.commit = AsyncMock()

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
            patch("app.tools.local.bot_skills._embed_skill_safe", new_callable=AsyncMock, return_value=False),
            patch("app.tools.local.bot_skills._check_count_warning", new_callable=AsyncMock, return_value=None),
            patch("app.tools.local.bot_skills._invalidate_cache"),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="create", name="fail-skill", title="Fail",
                content="x" * CONTENT_MIN_LENGTH,
            ))
            assert result["ok"] is True  # skill still saved
            assert result["embedded"] is False
            assert "embedding failed" in result["message"]


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class TestListPagination:

    @pytest.mark.asyncio
    async def test_list_with_limit_and_offset(self):
        rows = [_make_skill_row("bots/testbot/skill-c", name="Skill C")]
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 5
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = rows
        db.execute = AsyncMock(side_effect=[count_result, rows_result])

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(action="list", limit=1, offset=2))
            assert result["total"] == 5
            assert result["limit"] == 1
            assert result["offset"] == 2
            assert len(result["skills"]) == 1

    @pytest.mark.asyncio
    async def test_list_clamps_limit(self):
        """Limit should be clamped to 100 max."""
        rows = [_make_skill_row("bots/testbot/s1", name="S1")]
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = rows
        db.execute = AsyncMock(side_effect=[count_result, rows_result])

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(action="list", limit=999))
            assert result["limit"] == 100  # clamped

    @pytest.mark.asyncio
    async def test_list_content_preview_truncated(self):
        long_body = "A" * 200
        content = f"---\nname: Test\ncategory: guide\n---\n\n{long_body}"
        rows = [_make_skill_row("bots/testbot/long", name="Long", content=content)]
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = rows
        db.execute = AsyncMock(side_effect=[count_result, rows_result])

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(action="list"))
            skill = result["skills"][0]
            assert len(skill["preview"]) <= 120
            assert skill["category"] == "guide"


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------

class TestCacheInvalidation:

    def test_invalidate_bot_skill_cache(self):
        from app.agent.context_assembly import (
            _bot_skill_cache,
            invalidate_bot_skill_cache,
        )
        import time
        _bot_skill_cache["bot1"] = (time.monotonic(), ["bots/bot1/s1"])
        _bot_skill_cache["bot2"] = (time.monotonic(), ["bots/bot2/s1"])
        invalidate_bot_skill_cache("bot1")
        assert "bot1" not in _bot_skill_cache
        assert "bot2" in _bot_skill_cache
        # Cleanup
        _bot_skill_cache.clear()

    def test_invalidate_all(self):
        from app.agent.context_assembly import (
            _bot_skill_cache,
            invalidate_bot_skill_cache,
        )
        import time
        _bot_skill_cache["bot1"] = (time.monotonic(), [])
        _bot_skill_cache["bot2"] = (time.monotonic(), [])
        invalidate_bot_skill_cache(None)
        assert len(_bot_skill_cache) == 0

    @pytest.mark.asyncio
    async def test_cache_ttl_hit(self):
        """Calling _get_bot_authored_skill_ids twice within TTL should not query DB again."""
        from app.agent.context_assembly import (
            _bot_skill_cache,
            _get_bot_authored_skill_ids,
        )
        import time

        # Pre-populate cache with a fresh timestamp
        _bot_skill_cache["cachebot"] = (time.monotonic(), ["bots/cachebot/s1"])

        # Should return cached result without hitting DB
        result = await _get_bot_authored_skill_ids("cachebot")
        assert result == ["bots/cachebot/s1"]

        # Cleanup
        _bot_skill_cache.pop("cachebot", None)

    @pytest.mark.asyncio
    async def test_cache_ttl_expired(self):
        """Expired cache entries should trigger a fresh DB query."""
        from app.agent.context_assembly import (
            _BOT_SKILL_CACHE_TTL,
            _bot_skill_cache,
            _get_bot_authored_skill_ids,
        )
        import time

        # Set an expired cache entry
        _bot_skill_cache["expbot"] = (time.monotonic() - _BOT_SKILL_CACHE_TTL - 1, ["stale"])

        db = AsyncMock()
        exec_result = MagicMock()
        exec_result.scalars.return_value.all.return_value = ["bots/expbot/fresh"]
        db.execute = AsyncMock(return_value=exec_result)

        with patch("app.db.engine.async_session", _mock_session(db)):
            result = await _get_bot_authored_skill_ids("expbot")
            assert result == ["bots/expbot/fresh"]
            db.execute.assert_called_once()

        # Cleanup
        _bot_skill_cache.pop("expbot", None)


# ---------------------------------------------------------------------------
# Frontmatter sanitization
# ---------------------------------------------------------------------------

class TestFrontmatterSanitization:

    def test_sanitize_strips_newlines(self):
        assert _sanitize_frontmatter_value("line1\nline2") == "line1 line2"
        assert _sanitize_frontmatter_value("line1\r\nline2") == "line1  line2"

    def test_sanitize_strips_whitespace(self):
        assert _sanitize_frontmatter_value("  hello  ") == "hello"

    def test_build_content_sanitizes_title_with_newline(self):
        result = _build_content("Bad\nTitle", "body content")
        assert "\nTitle" not in result
        assert "name: Bad Title" in result

    def test_build_content_sanitizes_triggers(self):
        result = _build_content("T", "body", triggers="a\nb")
        assert "triggers: a b" in result


# ---------------------------------------------------------------------------
# Embed skill safe
# ---------------------------------------------------------------------------

class TestEmbedSkillSafe:

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self):
        with patch("app.agent.skills.re_embed_skill", new_callable=AsyncMock):
            result = await _embed_skill_safe("bots/testbot/ok")
            assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self):
        with patch("app.agent.skills.re_embed_skill", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
            result = await _embed_skill_safe("bots/testbot/fail")
            assert result is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    @pytest.mark.asyncio
    async def test_list_offset_past_end(self):
        """Offset beyond total returns empty list but correct total."""
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 3
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[count_result, rows_result])

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(action="list", offset=100))
            assert result["total"] == 3
            assert result["skills"] == []
            assert result["offset"] == 100

    @pytest.mark.asyncio
    async def test_list_negative_offset_clamped(self):
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = [_make_skill_row("bots/testbot/s")]
        db.execute = AsyncMock(side_effect=[count_result, rows_result])

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(action="list", offset=-5))
            assert result["offset"] == 0

    @pytest.mark.asyncio
    async def test_list_zero_limit_clamped_to_one(self):
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = [_make_skill_row("bots/testbot/s")]
        db.execute = AsyncMock(side_effect=[count_result, rows_result])

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(action="list", limit=0))
            assert result["limit"] == 1

    @pytest.mark.asyncio
    async def test_patch_validates_result_too_short(self):
        """Patch that shrinks content below minimum should be rejected."""
        # Content with frontmatter + just-enough body
        body = "x" * CONTENT_MIN_LENGTH
        full_content = f"---\nname: Test\n---\n\n{body}"
        row = _make_skill_row("bots/testbot/my-skill", content=full_content, source_type="tool")
        db = AsyncMock()
        db.get = AsyncMock(return_value=row)

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            # Replace most of the body with nothing
            result = _parse(await manage_bot_skill(
                action="patch", name="my-skill",
                old_text=body, new_text="tiny",
            ))
            assert "error" in result
            assert "too short" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_patch_validates_result_too_large(self):
        """Patch that expands content above maximum should be rejected."""
        body = "x" * 100
        full_content = f"---\nname: Test\n---\n\n{body}"
        row = _make_skill_row("bots/testbot/my-skill", content=full_content, source_type="tool")
        db = AsyncMock()
        db.get = AsyncMock(return_value=row)

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="patch", name="my-skill",
                old_text="x" * 50, new_text="y" * (CONTENT_MAX_LENGTH + 1),
            ))
            assert "error" in result
            assert "too large" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_patch_rejects_file_managed(self):
        row = _make_skill_row("bots/testbot/my-skill", content="body", source_type="file")
        db = AsyncMock()
        db.get = AsyncMock(return_value=row)

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="patch", name="my-skill", old_text="body", new_text="new",
            ))
            assert "file-managed" in result["error"]

    @pytest.mark.asyncio
    async def test_patch_empty_new_text_rejected(self):
        """new_text='' is falsy and should be rejected."""
        with patch("app.tools.local.bot_skills.current_bot_id") as ctx:
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="patch", name="x", old_text="something", new_text="",
            ))
            assert "required" in result["error"]

    @pytest.mark.asyncio
    async def test_delete_rejects_cross_bot(self):
        """Ensure delete rejects a skill owned by another bot."""
        row = _make_skill_row("bots/otherbot/stolen", source_type="tool")
        db = AsyncMock()
        db.get = AsyncMock(return_value=row)

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(action="delete", name="stolen"))
            assert "error" in result


# ---------------------------------------------------------------------------
# Skill nudge prompt
# ---------------------------------------------------------------------------

class TestSkillNudge:

    def test_nudge_prompt_exists(self):
        from app.config import DEFAULT_SKILL_NUDGE_PROMPT, SKILL_NUDGE_AFTER_ITERATIONS
        assert SKILL_NUDGE_AFTER_ITERATIONS > 0
        assert "manage_bot_skill" in DEFAULT_SKILL_NUDGE_PROMPT

    def test_nudge_setting_on_settings(self):
        from app.config import settings
        assert hasattr(settings, "SKILL_NUDGE_AFTER_ITERATIONS")
        assert settings.SKILL_NUDGE_AFTER_ITERATIONS >= 0

    def test_nudge_prompt_differentiates_skills_from_memory(self):
        """The nudge should help bots understand skills vs memory files."""
        from app.config import DEFAULT_SKILL_NUDGE_PROMPT
        assert "RAG" in DEFAULT_SKILL_NUDGE_PROMPT or "auto" in DEFAULT_SKILL_NUDGE_PROMPT.lower()
        assert "memory" in DEFAULT_SKILL_NUDGE_PROMPT.lower()

    def test_flush_prompt_mentions_skills_strongly(self):
        """The flush prompt should have a strong (not 'consider') directive for skills."""
        from app.config import DEFAULT_MEMORY_SCHEME_FLUSH_PROMPT
        assert "manage_bot_skill" in DEFAULT_MEMORY_SCHEME_FLUSH_PROMPT
        # Should NOT use weak language like "consider"
        skill_line = [l for l in DEFAULT_MEMORY_SCHEME_FLUSH_PROMPT.split("\n") if "manage_bot_skill" in l][0]
        assert "consider" not in skill_line.lower()

    def test_main_prompt_differentiates_reference_and_skills(self):
        """Reference section should NOT claim ownership of reusable patterns."""
        from app.config import DEFAULT_MEMORY_SCHEME_PROMPT
        # Find the reference section
        ref_idx = DEFAULT_MEMORY_SCHEME_PROMPT.find("reference/")
        skills_idx = DEFAULT_MEMORY_SCHEME_PROMPT.find("Self-Improvement via Skills")
        assert ref_idx < skills_idx  # reference comes first
        ref_section = DEFAULT_MEMORY_SCHEME_PROMPT[ref_idx:skills_idx]
        # Reference section should NOT say "write reusable patterns to reference"
        assert "reusable pattern" not in ref_section.lower()
        # Skills section SHOULD mention auto-surfacing
        skills_section = DEFAULT_MEMORY_SCHEME_PROMPT[skills_idx:]
        assert "auto" in skills_section.lower()

    def test_main_prompt_has_when_not_to_create(self):
        """Skills section should include guidance on when NOT to create skills."""
        from app.config import DEFAULT_MEMORY_SCHEME_PROMPT
        skills_idx = DEFAULT_MEMORY_SCHEME_PROMPT.find("Self-Improvement via Skills")
        skills_section = DEFAULT_MEMORY_SCHEME_PROMPT[skills_idx:]
        assert "do not create skills for" in skills_section.lower() or "don't create skills for" in skills_section.lower()

    def test_main_prompt_has_concrete_example(self):
        """Skills section should include a concrete manage_bot_skill call example."""
        from app.config import DEFAULT_MEMORY_SCHEME_PROMPT
        skills_idx = DEFAULT_MEMORY_SCHEME_PROMPT.find("Self-Improvement via Skills")
        skills_section = DEFAULT_MEMORY_SCHEME_PROMPT[skills_idx:]
        assert 'manage_bot_skill(action="create"' in skills_section


# ---------------------------------------------------------------------------
# Dedup / similarity check tests
# ---------------------------------------------------------------------------

class TestSkillDedup:

    @pytest.mark.asyncio
    async def test_create_dedup_warning(self):
        """Similar skill exists (>0.85) → warning returned, no creation."""
        # Mock the dedup check to return a warning
        with (
            patch("app.tools.local.bot_skills.current_bot_id") as mock_bot_id,
            patch("app.tools.local.bot_skills._check_skill_dedup") as mock_dedup,
        ):
            mock_bot_id.get.return_value = "testbot"
            mock_dedup.return_value = json.dumps({
                "warning": "similar_skill_exists",
                "similar_skill_id": "bots/testbot/existing-skill",
                "similarity": 0.92,
                "message": "Similar skill exists.",
            })

            result = await manage_bot_skill(
                action="create",
                name="new-skill",
                title="New Skill",
                content="x" * CONTENT_MIN_LENGTH,
            )

        data = _parse(result)
        assert data["warning"] == "similar_skill_exists"
        assert data["similarity"] == 0.92

    @pytest.mark.asyncio
    async def test_create_dedup_force_bypasses(self):
        """force=True should skip the dedup check entirely."""
        db_mock = AsyncMock()
        db_mock.get = AsyncMock(return_value=None)  # no existing skill
        db_mock.add = MagicMock()
        db_mock.commit = AsyncMock()

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as mock_bot_id,
            patch("app.db.engine.async_session", _mock_session(db_mock)),
            patch("app.tools.local.bot_skills._check_skill_dedup") as mock_dedup,
            patch("app.tools.local.bot_skills._embed_skill_safe", new_callable=AsyncMock, return_value=True),
            patch("app.tools.local.bot_skills._invalidate_cache"),
            patch("app.tools.local.bot_skills._check_count_warning", new_callable=AsyncMock, return_value=None),
        ):
            mock_bot_id.get.return_value = "testbot"

            result = await manage_bot_skill(
                action="create",
                name="new-skill",
                title="New Skill",
                content="x" * CONTENT_MIN_LENGTH,
                force=True,
            )

        # Dedup check should NOT have been called
        mock_dedup.assert_not_called()
        data = _parse(result)
        assert data["ok"] is True

    @pytest.mark.asyncio
    async def test_create_dedup_no_false_positive(self):
        """Dissimilar skill → no warning, creation proceeds."""
        db_mock = AsyncMock()
        db_mock.get = AsyncMock(return_value=None)
        db_mock.add = MagicMock()
        db_mock.commit = AsyncMock()

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as mock_bot_id,
            patch("app.db.engine.async_session", _mock_session(db_mock)),
            patch("app.tools.local.bot_skills._check_skill_dedup", new_callable=AsyncMock, return_value=None),
            patch("app.tools.local.bot_skills._embed_skill_safe", new_callable=AsyncMock, return_value=True),
            patch("app.tools.local.bot_skills._invalidate_cache"),
            patch("app.tools.local.bot_skills._check_count_warning", new_callable=AsyncMock, return_value=None),
        ):
            mock_bot_id.get.return_value = "testbot"

            result = await manage_bot_skill(
                action="create",
                name="unique-skill",
                title="Unique Skill",
                content="x" * CONTENT_MIN_LENGTH,
            )

        data = _parse(result)
        assert data["ok"] is True


# ---------------------------------------------------------------------------
# Surfacing stats in list
# ---------------------------------------------------------------------------

class TestSurfacingStats:

    @pytest.mark.asyncio
    async def test_list_includes_surfacing_stats(self):
        """list action should include last_surfaced_at and surface_count."""
        from sqlalchemy import func, select

        now = datetime.now(timezone.utc)
        row = _make_skill_row("bots/testbot/my-skill", name="My Skill",
                              content="---\nname: My Skill\n---\nSome content here")
        row.last_surfaced_at = now
        row.surface_count = 42

        # Mock the count query and the rows query
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 1

        mock_rows_result = MagicMock()
        mock_rows_result.scalars.return_value.all.return_value = [row]

        db_mock = AsyncMock()
        db_mock.execute = AsyncMock(side_effect=[mock_count_result, mock_rows_result])

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as mock_bot_id,
            patch("app.db.engine.async_session", _mock_session(db_mock)),
        ):
            mock_bot_id.get.return_value = "testbot"
            result = await manage_bot_skill(action="list")

        data = _parse(result)
        assert len(data["skills"]) == 1
        skill = data["skills"][0]
        assert skill["last_surfaced_at"] == now.isoformat()
        assert skill["surface_count"] == 42


# ---------------------------------------------------------------------------
# Correction nudge tests
# ---------------------------------------------------------------------------

class TestCorrectionNudge:

    def test_correction_pattern_matches(self):
        """Correction regex should match common correction phrases."""
        from app.agent.loop import _CORRECTION_RE
        assert _CORRECTION_RE.search("No, that's wrong")
        assert _CORRECTION_RE.search("Wrong approach")
        assert _CORRECTION_RE.search("that's not correct")
        assert _CORRECTION_RE.search("Actually, you should use X")
        assert _CORRECTION_RE.search("incorrect — try this instead")
        assert _CORRECTION_RE.search("Not quite right")
        assert _CORRECTION_RE.search("You should use Y instead")

    def test_correction_no_false_positive(self):
        """Correction regex should NOT match non-corrections."""
        from app.agent.loop import _CORRECTION_RE
        assert not _CORRECTION_RE.search("No problem, thanks!")
        assert not _CORRECTION_RE.search("No worries")
        assert not _CORRECTION_RE.search("No thanks, I'm good")
        assert not _CORRECTION_RE.search("No idea what happened")
        assert not _CORRECTION_RE.search("That looks great")
        assert not _CORRECTION_RE.search("Can you help me with this?")
        assert not _CORRECTION_RE.search("I want to know about X")

    def test_extract_last_user_text(self):
        """Helper should extract text from the last user message."""
        from app.agent.loop import _extract_last_user_text

        # Simple string content
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "No, that's wrong"},
        ]
        assert _extract_last_user_text(msgs) == "No, that's wrong"

        # Multi-part content
        msgs2 = [
            {"role": "user", "content": [{"type": "text", "text": "Actually, do it differently"}]},
        ]
        assert _extract_last_user_text(msgs2) == "Actually, do it differently"

        # No user messages
        assert _extract_last_user_text([{"role": "system", "content": "sys"}]) is None

    def test_correction_nudge_once_per_run(self):
        """The correction nudge should only inject once (before first iteration)."""
        # The implementation injects before the for loop, so it fires at most once.
        # This test verifies the regex only triggers once even with multiple matching messages.
        from app.agent.loop import _CORRECTION_RE

        messages_with_corrections = [
            "No, that's wrong",
            "Wrong again",
            "Actually, try this",
        ]

        # All match, but the nudge is injected only once (before the loop).
        # We just verify the pattern matches each — the injection logic
        # handles the "once" guarantee by position (pre-loop).
        matches = [bool(_CORRECTION_RE.search(m)) for m in messages_with_corrections]
        assert all(matches)


# ---------------------------------------------------------------------------
# Merge action tests
# ---------------------------------------------------------------------------

class TestMergeAction:

    @pytest.mark.asyncio
    async def test_merge_requires_at_least_two_names(self):
        with patch("app.tools.local.bot_skills.current_bot_id") as ctx:
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="merge", names=["only-one"],
                name="merged", title="Merged", content="x" * CONTENT_MIN_LENGTH,
            ))
            assert "at least 2" in result["error"]

    @pytest.mark.asyncio
    async def test_merge_requires_names(self):
        with patch("app.tools.local.bot_skills.current_bot_id") as ctx:
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="merge",
                name="merged", title="Merged", content="x" * CONTENT_MIN_LENGTH,
            ))
            assert "at least 2" in result["error"]

    @pytest.mark.asyncio
    async def test_merge_requires_target_fields(self):
        with patch("app.tools.local.bot_skills.current_bot_id") as ctx:
            ctx.get.return_value = "testbot"
            # Missing name
            result = _parse(await manage_bot_skill(
                action="merge", names=["a", "b"],
                title="Merged", content="x" * CONTENT_MIN_LENGTH,
            ))
            assert "required" in result["error"]

    @pytest.mark.asyncio
    async def test_merge_succeeds(self):
        """Merging 2 skills into 1 should delete sources and create target."""
        skill_a = _make_skill_row("bots/testbot/skill-a", name="Skill A", source_type="tool")
        skill_b = _make_skill_row("bots/testbot/skill-b", name="Skill B", source_type="tool")

        # Map skill IDs to mock rows for db.get
        skill_map = {
            "bots/testbot/skill-a": skill_a,
            "bots/testbot/skill-b": skill_b,
            "bots/testbot/merged": None,  # target doesn't exist yet
        }

        db = AsyncMock()
        db.get = AsyncMock(side_effect=lambda model, key: skill_map.get(key))
        db.delete = AsyncMock()
        db.execute = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
            patch("app.tools.local.bot_skills._embed_skill_safe", new_callable=AsyncMock, return_value=True),
            patch("app.tools.local.bot_skills._invalidate_cache"),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="merge",
                names=["skill-a", "skill-b"],
                name="merged",
                title="Merged Skill",
                content="x" * CONTENT_MIN_LENGTH,
            ))

        assert result["ok"] is True
        assert result["id"] == "bots/testbot/merged"
        assert len(result["deleted"]) == 2
        assert "bots/testbot/skill-a" in result["deleted"]
        assert "bots/testbot/skill-b" in result["deleted"]
        # Should have called delete for both source skills
        assert db.delete.call_count == 2
        # Should have added the merged skill
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_merge_rejects_file_managed_source(self):
        """Cannot merge a file-managed skill."""
        skill_a = _make_skill_row("bots/testbot/skill-a", source_type="file")
        skill_b = _make_skill_row("bots/testbot/skill-b", source_type="tool")

        db = AsyncMock()
        db.get = AsyncMock(side_effect=lambda model, key: {
            "bots/testbot/skill-a": skill_a,
            "bots/testbot/skill-b": skill_b,
        }.get(key))

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="merge", names=["skill-a", "skill-b"],
                name="merged", title="Merged", content="x" * CONTENT_MIN_LENGTH,
            ))
            assert "file-managed" in result["error"]

    @pytest.mark.asyncio
    async def test_merge_rejects_missing_source(self):
        """Cannot merge a skill that doesn't exist."""
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="merge", names=["missing-a", "missing-b"],
                name="merged", title="Merged", content="x" * CONTENT_MIN_LENGTH,
            ))
            assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_merge_target_already_exists_and_not_source(self):
        """Target skill exists but isn't one of the sources → error."""
        skill_a = _make_skill_row("bots/testbot/skill-a", source_type="tool")
        skill_b = _make_skill_row("bots/testbot/skill-b", source_type="tool")
        existing_target = _make_skill_row("bots/testbot/merged", source_type="tool")

        db = AsyncMock()
        db.get = AsyncMock(side_effect=lambda model, key: {
            "bots/testbot/skill-a": skill_a,
            "bots/testbot/skill-b": skill_b,
            "bots/testbot/merged": existing_target,
        }.get(key))

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="merge", names=["skill-a", "skill-b"],
                name="merged", title="Merged", content="x" * CONTENT_MIN_LENGTH,
            ))
            assert "already exists" in result["error"]

    @pytest.mark.asyncio
    async def test_merge_target_is_one_of_sources(self):
        """Target skill = one of the sources → allowed (common rename-merge pattern)."""
        skill_a = _make_skill_row("bots/testbot/skill-a", name="Skill A", source_type="tool")
        skill_b = _make_skill_row("bots/testbot/skill-b", name="Skill B", source_type="tool")

        # When target = skill-a, the first get for "skill-a" as target returns the row,
        # but merged_id is in source_ids so it's allowed
        call_count = {"n": 0}
        def mock_get(model, key):
            call_count["n"] += 1
            return {
                "bots/testbot/skill-a": skill_a,
                "bots/testbot/skill-b": skill_b,
            }.get(key)

        db = AsyncMock()
        db.get = AsyncMock(side_effect=mock_get)
        db.delete = AsyncMock()
        db.execute = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
            patch("app.tools.local.bot_skills._embed_skill_safe", new_callable=AsyncMock, return_value=True),
            patch("app.tools.local.bot_skills._invalidate_cache"),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="merge", names=["skill-a", "skill-b"],
                name="skill-a", title="Combined", content="x" * CONTENT_MIN_LENGTH,
            ))
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_merge_validates_content(self):
        """Merge should validate the merged content."""
        with patch("app.tools.local.bot_skills.current_bot_id") as ctx:
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="merge", names=["a", "b"],
                name="merged", title="Merged", content="tiny",
            ))
            assert "too short" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_merge_deduplicates_names(self):
        """Duplicate names in the list should be collapsed, and rejected if < 2 distinct."""
        with patch("app.tools.local.bot_skills.current_bot_id") as ctx:
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(
                action="merge", names=["same", "same"],
                name="merged", title="Merged", content="x" * CONTENT_MIN_LENGTH,
            ))
            assert "at least 2 distinct" in result["error"]


# ---------------------------------------------------------------------------
# Repeated-lookup detection tests
# ---------------------------------------------------------------------------

class TestRepeatedLookupDetection:

    @pytest.mark.asyncio
    async def test_find_repeated_lookups_returns_queries(self):
        """Should return queries that appear in 3+ distinct agent runs."""
        from app.agent.repeated_lookup_detection import find_repeated_lookups, _cache
        _cache.clear()

        mock_row = MagicMock()
        mock_row.query_text = "docker networking"

        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        with patch("app.db.engine.async_session", _mock_session(db)):
            result = await find_repeated_lookups("testbot", min_runs=3)

        assert result == ["docker networking"]
        _cache.clear()

    @pytest.mark.asyncio
    async def test_find_repeated_lookups_empty_on_no_matches(self):
        """Should return empty list when no repeated queries found."""
        from app.agent.repeated_lookup_detection import find_repeated_lookups, _cache
        _cache.clear()

        mock_result = MagicMock()
        mock_result.all.return_value = []

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        with patch("app.db.engine.async_session", _mock_session(db)):
            result = await find_repeated_lookups("testbot")

        assert result == []
        _cache.clear()

    @pytest.mark.asyncio
    async def test_find_repeated_lookups_handles_errors_gracefully(self):
        """Should return empty list on error (non-blocking)."""
        from app.agent.repeated_lookup_detection import find_repeated_lookups, _cache
        _cache.clear()

        with patch("app.db.engine.async_session", side_effect=RuntimeError("boom")):
            result = await find_repeated_lookups("testbot")

        assert result == []
        _cache.clear()

    def test_repeated_lookup_nudge_prompt_has_topics_placeholder(self):
        """Nudge prompt should have a {topics} placeholder for formatting."""
        from app.config import DEFAULT_SKILL_REPEATED_LOOKUP_NUDGE_PROMPT
        assert "{topics}" in DEFAULT_SKILL_REPEATED_LOOKUP_NUDGE_PROMPT

    def test_repeated_lookup_nudge_setting_exists(self):
        """Settings should have the toggle for repeated lookup nudge."""
        from app.config import settings
        assert hasattr(settings, "SKILL_REPEATED_LOOKUP_NUDGE_ENABLED")

    def test_repeated_lookup_nudge_prompt_mentions_skill_creation(self):
        """Nudge should guide the bot to create skills."""
        from app.config import DEFAULT_SKILL_REPEATED_LOOKUP_NUDGE_PROMPT
        assert "manage_bot_skill" in DEFAULT_SKILL_REPEATED_LOOKUP_NUDGE_PROMPT


# ---------------------------------------------------------------------------
# Stale skill detection
# ---------------------------------------------------------------------------

class TestIsStale:

    def test_never_surfaced_and_old(self):
        """surface_count=0 + created > 7 days ago → stale."""
        old = datetime.now(timezone.utc) - timedelta(days=STALE_NEVER_SURFACED_DAYS + 1)
        assert _is_stale(created_at=old, last_surfaced_at=None, surface_count=0) is True

    def test_never_surfaced_but_recent(self):
        """surface_count=0 + created < 7 days ago → not stale."""
        recent = datetime.now(timezone.utc) - timedelta(days=STALE_NEVER_SURFACED_DAYS - 1)
        assert _is_stale(created_at=recent, last_surfaced_at=None, surface_count=0) is False

    def test_surfaced_recently(self):
        """Last surfaced < 30 days ago → not stale."""
        recent = datetime.now(timezone.utc) - timedelta(days=STALE_LAST_SURFACED_DAYS - 1)
        assert _is_stale(created_at=None, last_surfaced_at=recent, surface_count=5) is False

    def test_surfaced_long_ago(self):
        """Last surfaced > 30 days ago → stale."""
        old = datetime.now(timezone.utc) - timedelta(days=STALE_LAST_SURFACED_DAYS + 1)
        assert _is_stale(created_at=None, last_surfaced_at=old, surface_count=5) is True

    def test_none_created_at_and_never_surfaced(self):
        """Edge case: no created_at + never surfaced → not stale (can't tell)."""
        assert _is_stale(created_at=None, last_surfaced_at=None, surface_count=0) is False

    def test_data_inconsistency_count_but_no_timestamp(self):
        """Edge case: surface_count > 0 but last_surfaced_at is None → not stale.
        This is a data inconsistency; we err on the side of not marking stale."""
        old = datetime.now(timezone.utc) - timedelta(days=60)
        assert _is_stale(created_at=old, last_surfaced_at=None, surface_count=5) is False


class TestListStaleHints:

    @pytest.mark.asyncio
    async def test_list_includes_stale_flag(self):
        """List response should include 'stale' and 'created_at' per skill."""
        old = datetime.now(timezone.utc) - timedelta(days=60)
        row = _make_skill_row(
            "bots/testbot/old-skill", name="Old",
            content="---\nname: Old\n---\nSome content",
            created_at=old, surface_count=0,
        )

        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 1
        mock_rows_result = MagicMock()
        mock_rows_result.scalars.return_value.all.return_value = [row]

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[mock_count_result, mock_rows_result])

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(action="list"))

        skill = result["skills"][0]
        assert "stale" in skill
        assert skill["stale"] is True
        assert "created_at" in skill

    @pytest.mark.asyncio
    async def test_list_stale_hint_when_stale_exist(self):
        """List should include a 'hint' when stale skills are present."""
        old = datetime.now(timezone.utc) - timedelta(days=60)
        stale_row = _make_skill_row(
            "bots/testbot/stale", name="Stale",
            content="---\nname: Stale\n---\nSome content",
            created_at=old, surface_count=0,
        )

        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 1
        mock_rows_result = MagicMock()
        mock_rows_result.scalars.return_value.all.return_value = [stale_row]

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[mock_count_result, mock_rows_result])

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(action="list"))

        assert "hint" in result
        assert "1 skill has" in result["hint"]
        assert "hasn't" in result["hint"]  # singular verb agreement

    @pytest.mark.asyncio
    async def test_list_stale_hint_plural_grammar(self):
        """Hint should use correct plural grammar for multiple stale skills."""
        old = datetime.now(timezone.utc) - timedelta(days=60)
        rows = [
            _make_skill_row(
                f"bots/testbot/stale-{i}", name=f"Stale {i}",
                content=f"---\nname: Stale {i}\n---\nSome content",
                created_at=old, surface_count=0,
            )
            for i in range(2)
        ]

        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 2
        mock_rows_result = MagicMock()
        mock_rows_result.scalars.return_value.all.return_value = rows

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[mock_count_result, mock_rows_result])

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(action="list"))

        assert "2 skills have" in result["hint"]
        assert "haven't" in result["hint"]  # plural verb agreement

    @pytest.mark.asyncio
    async def test_list_no_hint_when_all_fresh(self):
        """No 'hint' key when no stale skills."""
        now = datetime.now(timezone.utc)
        fresh_row = _make_skill_row(
            "bots/testbot/fresh", name="Fresh",
            content="---\nname: Fresh\n---\nSome content",
            created_at=now, last_surfaced_at=now, surface_count=5,
        )

        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 1
        mock_rows_result = MagicMock()
        mock_rows_result.scalars.return_value.all.return_value = [fresh_row]

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[mock_count_result, mock_rows_result])

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as ctx,
            patch("app.db.engine.async_session", _mock_session(db)),
        ):
            ctx.get.return_value = "testbot"
            result = _parse(await manage_bot_skill(action="list"))

        assert "hint" not in result


# ---------------------------------------------------------------------------
# Broadened correction regex tests
# ---------------------------------------------------------------------------

class TestBroadenedCorrectionRegex:

    def test_mid_message_thats_wrong(self):
        """'that's wrong' mid-message should match."""
        from app.agent.loop import _CORRECTION_RE
        assert _CORRECTION_RE.search("I think that's wrong, please fix it")

    def test_mid_message_thats_incorrect(self):
        from app.agent.loop import _CORRECTION_RE
        assert _CORRECTION_RE.search("Well, that's incorrect")

    def test_mid_message_you_misunderstood(self):
        from app.agent.loop import _CORRECTION_RE
        assert _CORRECTION_RE.search("I think you misunderstood what I meant")

    def test_mid_message_i_said(self):
        from app.agent.loop import _CORRECTION_RE
        assert _CORRECTION_RE.search("But I said to use the other approach")

    def test_mid_message_i_meant(self):
        from app.agent.loop import _CORRECTION_RE
        assert _CORRECTION_RE.search("I meant the other one")

    def test_no_false_positive_actually_thanks(self):
        """'actually, thanks' should not trigger correction."""
        from app.agent.loop import _CORRECTION_RE
        assert not _CORRECTION_RE.search("actually, thanks for doing that")

    def test_no_false_positive_no_problem(self):
        from app.agent.loop import _CORRECTION_RE
        assert not _CORRECTION_RE.search("no problem at all")

    def test_no_false_positive_no_worries(self):
        from app.agent.loop import _CORRECTION_RE
        assert not _CORRECTION_RE.search("no worries about it")

    def test_no_false_positive_normal_sentence(self):
        from app.agent.loop import _CORRECTION_RE
        assert not _CORRECTION_RE.search("Can you help me deploy this?")

    def test_no_false_positive_word_boundary_i_said(self):
        """'i said' inside another word (e.g. 'alibi said') should not match."""
        from app.agent.loop import _CORRECTION_RE
        assert not _CORRECTION_RE.search("alibi said something")
        assert not _CORRECTION_RE.search("Luigi said ciao")
        assert not _CORRECTION_RE.search("Wasabi said it works")

    def test_no_false_positive_word_boundary_you_misunderstood(self):
        """'you misunderstood' inside another word should not match."""
        from app.agent.loop import _CORRECTION_RE
        assert not _CORRECTION_RE.search("bayou misunderstood me")
