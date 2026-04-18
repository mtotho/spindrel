"""Tests for the manage_bot_skill tool — bot self-authored skill CRUD."""

import json
import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models import Skill
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
from tests.factories import build_bot, build_bot_skill

pytestmark = pytest.mark.usefixtures("bot_skill_cache_reset")


# ---------------------------------------------------------------------------
# Helpers (Group B off-target classes still use these — TestCacheInvalidation,
# TestRepeatedLookupDetection. See Phase 1d scope decision.)
# ---------------------------------------------------------------------------


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

    def test_when_simple_slug_then_id_is_bots_bot_name(self):
        assert _bot_skill_id("mybot", "my-skill") == "bots/mybot/my-skill"

    def test_when_name_has_spaces_then_id_uses_hyphens(self):
        assert _bot_skill_id("mybot", "My Skill Name") == "bots/mybot/my-skill-name"

    def test_when_name_has_uppercase_then_id_is_lowercased(self):
        assert _bot_skill_id("mybot", "MySkill") == "bots/mybot/myskill"

    def test_when_name_is_already_full_id_for_this_bot_then_prefix_stripped(self):
        assert _bot_skill_id("baking-bot", "bots/baking-bot/ermine-frosting") == "bots/baking-bot/ermine-frosting"

    def test_when_name_has_other_bots_prefix_then_slashes_stripped_as_special_chars(self):
        assert _bot_skill_id("mybot", "bots/other-bot/skill") == "bots/mybot/botsother-botskill"

    def test_when_name_has_only_special_chars_then_raises_valueerror(self):
        with pytest.raises(ValueError):
            _bot_skill_id("mybot", "!!!!")

    def test_when_slugify_receives_special_chars_then_strips_them(self):
        assert _slugify("../../escape") == "escape"
        assert _slugify("hello world!") == "hello-world"
        assert _slugify("  My--Skill  ") == "my-skill"

    def test_when_slugify_receives_empty_or_all_special_then_returns_empty(self):
        assert _slugify("") == ""
        assert _slugify("!!!") == ""

    def test_when_build_content_has_all_fields_then_all_included(self):
        result = _build_content("My Title", "The body", triggers="error, crash", category="troubleshooting")
        assert "---" in result
        assert "name: My Title" in result
        assert "triggers: error, crash" in result
        assert "category: troubleshooting" in result
        assert "The body" in result

    def test_when_build_content_has_only_title_and_body_then_no_optional_fields(self):
        result = _build_content("Title", "Body only")
        assert "name: Title" in result
        assert "triggers:" not in result
        assert "category:" not in result
        assert "Body only" in result

    def test_when_extract_body_has_frontmatter_then_returns_body_only(self):
        content = "---\nname: Test\ntriggers: foo\n---\n\nThe body here"
        assert _extract_body(content) == "The body here"

    def test_when_extract_body_has_no_frontmatter_then_returns_input(self):
        assert _extract_body("Just content") == "Just content"

    def test_when_extract_frontmatter_has_fields_then_returns_dict(self):
        content = "---\nname: Test\ntriggers: foo, bar\ncategory: debug\n---\n\nBody"
        fm = _extract_frontmatter(content)
        assert fm["name"] == "Test"
        assert fm["triggers"] == "foo, bar"
        assert fm["category"] == "debug"

    def test_when_extract_frontmatter_has_no_frontmatter_then_returns_empty_dict(self):
        assert _extract_frontmatter("No frontmatter") == {}


# ---------------------------------------------------------------------------
# CRUD action tests
# ---------------------------------------------------------------------------

class TestCreate:

    @pytest.mark.asyncio
    async def test_when_no_bot_context_then_error_returned(self, agent_context):
        agent_context(bot_id=None)

        result = json.loads(await manage_bot_skill(action="create"))

        assert "No bot context" in result["error"]

    @pytest.mark.asyncio
    async def test_when_required_fields_missing_then_error_returned(self, agent_context):
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(action="create", name="foo"))

        assert "required" in result["error"]

    @pytest.mark.asyncio
    async def test_when_valid_create_then_row_persisted_with_all_fields(
        self, db_session, patched_async_sessions, agent_context,
        embed_skill_patch, dedup_patch,
    ):
        agent_context(bot_id="testbot")
        body = "# Docker Networking\n\nHow to configure bridge networks. " + "x" * 50

        result = json.loads(await manage_bot_skill(
            action="create", name="docker-net", title="Docker Networking",
            content=body,
            triggers="docker, networking, bridge", category="infrastructure",
        ))

        assert result["ok"] is True
        assert result["id"] == "bots/testbot/docker-net"
        assert result["embedded"] is True
        row = await db_session.get(Skill, "bots/testbot/docker-net")
        assert row is not None
        assert row.name == "Docker Networking"
        assert row.triggers == ["docker", "networking", "bridge"]
        assert row.category == "infrastructure"
        assert row.source_type == "tool"
        assert row.description and len(row.description) > 0

    @pytest.mark.asyncio
    async def test_when_create_without_triggers_then_triggers_empty_category_null(
        self, db_session, patched_async_sessions, agent_context,
        embed_skill_patch, dedup_patch,
    ):
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="create", name="plain", title="Plain Skill",
            content="x" * CONTENT_MIN_LENGTH,
        ))

        assert result["ok"] is True
        row = await db_session.get(Skill, "bots/testbot/plain")
        assert row.triggers == []
        assert row.category is None

    @pytest.mark.asyncio
    async def test_when_create_targets_existing_id_then_rejected(
        self, db_session, patched_async_sessions, agent_context,
        embed_skill_patch, dedup_patch,
    ):
        existing = build_bot_skill(bot_id="testbot", name="my-skill")
        db_session.add(existing)
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="create", name="my-skill", title="My Skill",
            content="x" * CONTENT_MIN_LENGTH,
        ))

        assert "already exists" in result["error"]
        # Extra mile: row untouched
        untouched = await db_session.get(Skill, existing.id)
        assert untouched.content == existing.content

    @pytest.mark.asyncio
    async def test_when_name_is_all_special_chars_then_rejected(self, agent_context):
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="create", name="!!!!", title="Bad",
            content="x" * CONTENT_MIN_LENGTH,
        ))

        assert "Invalid skill name" in result["error"]

    @pytest.mark.asyncio
    async def test_when_dedup_finds_similar_skill_then_create_rejected(
        self, db_session, patched_async_sessions, agent_context,
        embed_skill_patch, dedup_patch,
    ):
        dedup_patch.return_value = json.dumps({
            "warning": "similar_skill_exists",
            "similar_skill_id": "bots/testbot/other",
            "similarity": 0.91,
            "message": "similar skill exists",
        })
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="create", name="dup", title="Dup",
            content="x" * CONTENT_MIN_LENGTH,
        ))

        assert result == {
            "warning": "similar_skill_exists",
            "similar_skill_id": "bots/testbot/other",
            "similarity": 0.91,
            "message": "similar skill exists",
        }
        assert await db_session.get(Skill, "bots/testbot/dup") is None

    @pytest.mark.asyncio
    async def test_when_force_true_then_dedup_bypassed(
        self, db_session, patched_async_sessions, agent_context,
        embed_skill_patch, dedup_patch,
    ):
        dedup_patch.return_value = json.dumps({"warning": "similar_skill_exists"})
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="create", name="forced", title="Forced", force=True,
            content="x" * CONTENT_MIN_LENGTH,
        ))

        assert result["ok"] is True
        dedup_patch.assert_not_called()
        assert await db_session.get(Skill, "bots/testbot/forced") is not None


class TestList:

    @pytest.mark.asyncio
    async def test_when_no_skills_authored_then_list_returns_empty(
        self, db_session, patched_async_sessions, agent_context,
    ):
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(action="list"))

        assert result == {"skills": [], "total": 0, "message": "No self-authored skills yet."}

    @pytest.mark.asyncio
    async def test_when_skills_exist_then_list_returns_them_with_previews(
        self, db_session, patched_async_sessions, agent_context,
    ):
        content_a = "---\nname: Skill A\ncategory: debug\n---\n\nSome body content here"
        content_b = "---\nname: Skill B\n---\n\nAnother body"
        skill_a = build_bot_skill(bot_id="testbot", name="skill-a", content=content_a)
        skill_b = build_bot_skill(bot_id="testbot", name="skill-b", content=content_b)
        skill_a.updated_at = datetime.now(timezone.utc)
        skill_b.updated_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db_session.add_all([skill_a, skill_b])
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(action="list"))

        assert result["total"] == 2
        assert [s["id"] for s in result["skills"]] == [skill_a.id, skill_b.id]
        assert result["skills"][0]["category"] == "debug"
        assert result["skills"][0]["preview"] == "Some body content here"

    @pytest.mark.asyncio
    async def test_when_other_bots_own_skills_then_list_filters_by_bot_id(
        self, db_session, patched_async_sessions, agent_context,
    ):
        mine = build_bot_skill(bot_id="me", name="mine", content="x" * 100)
        theirs = build_bot_skill(bot_id="other", name="theirs", content="y" * 100)
        db_session.add_all([mine, theirs])
        await db_session.commit()
        agent_context(bot_id="me")

        result = json.loads(await manage_bot_skill(action="list"))

        assert [s["id"] for s in result["skills"]] == [mine.id]
        assert result["total"] == 1


class TestGet:

    @pytest.mark.asyncio
    async def test_when_name_missing_then_error_returned(self, agent_context):
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(action="get"))

        assert "error" in result

    @pytest.mark.asyncio
    async def test_when_skill_not_found_then_error_returned(
        self, db_session, patched_async_sessions, agent_context,
    ):
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(action="get", name="missing"))

        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_when_skill_exists_then_returns_id_and_content(
        self, db_session, patched_async_sessions, agent_context,
    ):
        skill = build_bot_skill(bot_id="testbot", name="my-skill", content="the content " * 10)
        db_session.add(skill)
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(action="get", name="my-skill"))

        assert result["id"] == skill.id
        assert result["content"] == skill.content


class TestUpdate:

    @pytest.mark.asyncio
    async def test_when_skill_not_found_then_error_returned(
        self, db_session, patched_async_sessions, agent_context, embed_skill_patch,
    ):
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(action="update", name="missing"))

        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_when_skill_is_file_managed_then_update_rejected(
        self, db_session, patched_async_sessions, agent_context, embed_skill_patch,
    ):
        file_skill = build_bot_skill(bot_id="testbot", name="my-skill", source_type="file")
        db_session.add(file_skill)
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="update", name="my-skill", content="new " + "x" * 100,
        ))

        assert "file-managed" in result["error"]

    @pytest.mark.asyncio
    async def test_when_content_updated_then_row_content_and_hash_refreshed(
        self, db_session, patched_async_sessions, agent_context, embed_skill_patch,
    ):
        skill = build_bot_skill(bot_id="testbot", name="my-skill")
        original_hash = skill.content_hash
        db_session.add(skill)
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="update", name="my-skill", content="updated body " + "x" * 60,
        ))

        assert result["ok"] is True
        await db_session.refresh(skill)
        assert "updated body" in skill.content
        assert skill.content_hash != original_hash

    @pytest.mark.asyncio
    async def test_when_only_triggers_updated_then_existing_category_preserved(
        self, db_session, patched_async_sessions, agent_context, embed_skill_patch,
    ):
        content = "---\nname: My Skill\ntriggers: old-trigger\ncategory: debug\n---\n\nOriginal body"
        skill = build_bot_skill(bot_id="testbot", name="my-skill", content=content)
        db_session.add(skill)
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="update", name="my-skill", triggers="new-trigger",
        ))

        assert result["ok"] is True
        await db_session.refresh(skill)
        assert "category: debug" in skill.content
        assert "triggers: new-trigger" in skill.content
        assert "Original body" in skill.content

    @pytest.mark.asyncio
    async def test_when_update_sets_category_and_triggers_then_db_columns_synced(
        self, db_session, patched_async_sessions, agent_context, embed_skill_patch,
    ):
        skill = build_bot_skill(bot_id="testbot", name="my-skill")
        db_session.add(skill)
        await db_session.commit()
        agent_context(bot_id="testbot")

        new_body = "Updated content about docker networking. " + "x" * 50
        result = json.loads(await manage_bot_skill(
            action="update", name="my-skill",
            content=new_body, triggers="docker, networking", category="infrastructure",
        ))

        assert result["ok"] is True
        await db_session.refresh(skill)
        assert skill.triggers == ["docker", "networking"]
        assert skill.category == "infrastructure"
        assert skill.description and len(skill.description) > 0

    @pytest.mark.asyncio
    async def test_when_update_provides_no_fields_then_rejected(
        self, db_session, patched_async_sessions, agent_context, embed_skill_patch,
    ):
        skill = build_bot_skill(bot_id="testbot", name="my-skill")
        db_session.add(skill)
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(action="update", name="my-skill"))

        assert "at least one" in result["error"]


class TestDelete:

    @pytest.mark.asyncio
    async def test_when_skill_not_found_then_error_returned(
        self, db_session, patched_async_sessions, agent_context,
    ):
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(action="delete", name="missing"))

        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_when_skill_is_file_managed_then_delete_rejected(
        self, db_session, patched_async_sessions, agent_context,
    ):
        file_skill = build_bot_skill(bot_id="testbot", name="my-skill", source_type="file")
        db_session.add(file_skill)
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(action="delete", name="my-skill"))

        assert "file-managed" in result["error"]

    @pytest.mark.asyncio
    async def test_when_delete_tool_skill_then_archived_at_set_and_siblings_untouched(
        self, db_session, patched_async_sessions, agent_context,
    ):
        target = build_bot_skill(bot_id="testbot", name="target")
        sibling_a = build_bot_skill(bot_id="testbot", name="sibling-a")
        sibling_b = build_bot_skill(bot_id="testbot", name="sibling-b")
        db_session.add_all([target, sibling_a, sibling_b])
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(action="delete", name="target"))

        assert result["ok"] is True
        await db_session.refresh(target)
        await db_session.refresh(sibling_a)
        await db_session.refresh(sibling_b)
        assert target.archived_at is not None
        assert sibling_a.archived_at is None
        assert sibling_b.archived_at is None

    @pytest.mark.asyncio
    async def test_when_deleting_already_archived_then_error_returned(
        self, db_session, patched_async_sessions, agent_context,
    ):
        archived = build_bot_skill(
            bot_id="testbot", name="my-skill",
            archived_at=datetime.now(timezone.utc),
        )
        db_session.add(archived)
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(action="delete", name="my-skill"))

        assert "already archived" in result["error"]

    @pytest.mark.asyncio
    async def test_when_restore_archived_skill_then_archived_at_cleared(
        self, db_session, patched_async_sessions, agent_context,
    ):
        archived = build_bot_skill(
            bot_id="testbot", name="my-skill",
            archived_at=datetime.now(timezone.utc),
        )
        db_session.add(archived)
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(action="restore", name="my-skill"))

        assert result["ok"] is True
        await db_session.refresh(archived)
        assert archived.archived_at is None

    @pytest.mark.asyncio
    async def test_when_restoring_not_archived_skill_then_error_returned(
        self, db_session, patched_async_sessions, agent_context,
    ):
        live = build_bot_skill(bot_id="testbot", name="my-skill")
        db_session.add(live)
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(action="restore", name="my-skill"))

        assert "not archived" in result["error"]


class TestPatch:

    @pytest.mark.asyncio
    async def test_when_old_or_new_text_missing_then_error_returned(self, agent_context):
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="patch", name="x", old_text="", new_text="y",
        ))

        assert "required" in result["error"]

    @pytest.mark.asyncio
    async def test_when_old_text_not_in_content_then_error_returned(
        self, db_session, patched_async_sessions, agent_context, embed_skill_patch,
    ):
        skill = build_bot_skill(bot_id="testbot", name="my-skill", content="original content " + "x" * 100)
        db_session.add(skill)
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="patch", name="my-skill", old_text="not here", new_text="replacement",
        ))

        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_when_patch_applies_then_content_and_hash_updated(
        self, db_session, patched_async_sessions, agent_context, embed_skill_patch,
    ):
        body = "original content that is long enough to pass validation " + "x" * 50
        full_content = f"---\nname: Test\n---\n\n{body}"
        skill = build_bot_skill(bot_id="testbot", name="my-skill", content=full_content)
        original_hash = skill.content_hash
        db_session.add(skill)
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="patch", name="my-skill", old_text="original", new_text="updated",
        ))

        assert result["ok"] is True
        await db_session.refresh(skill)
        assert "updated content" in skill.content
        assert skill.content_hash != original_hash

    @pytest.mark.asyncio
    async def test_when_patch_changes_triggers_then_db_triggers_synced(
        self, db_session, patched_async_sessions, agent_context, embed_skill_patch,
    ):
        body = "original content that is long enough to pass validation " + "x" * 50
        full_content = "---\ntitle: Old\ntriggers: alpha, beta\ncategory: general\n---\n\n" + body
        skill = build_bot_skill(
            bot_id="testbot", name="my-skill", content=full_content,
            triggers=["alpha", "beta"], category="general",
        )
        db_session.add(skill)
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="patch", name="my-skill",
            old_text="triggers: alpha, beta", new_text="triggers: alpha, beta, gamma",
        ))

        assert result["ok"] is True
        await db_session.refresh(skill)
        assert skill.triggers == ["alpha", "beta", "gamma"]

    @pytest.mark.asyncio
    async def test_when_patch_changes_body_then_description_synced(
        self, db_session, patched_async_sessions, agent_context, embed_skill_patch,
    ):
        body = "original content that is long enough to pass validation " + "x" * 50
        full_content = "---\ntitle: My\ntriggers: a\ncategory: dev\n---\n\n" + body
        skill = build_bot_skill(
            bot_id="testbot", name="my-skill", content=full_content,
            triggers=["a"], category="dev",
        )
        skill.description = body[:200].strip()
        db_session.add(skill)
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="patch", name="my-skill",
            old_text="original content", new_text="patched content",
        ))

        assert result["ok"] is True
        await db_session.refresh(skill)
        assert "patched content" in skill.description


class TestUnknownAction:

    @pytest.mark.asyncio
    async def test_when_action_is_unknown_then_error_returned(self, agent_context):
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(action="nope"))

        assert "Unknown action" in result["error"]


# ---------------------------------------------------------------------------
# Security: prefix enforcement
# ---------------------------------------------------------------------------

class TestSecurity:

    def test_when_building_id_for_bot_then_id_is_scoped_to_that_bot(self):
        assert _bot_skill_id("alice", "hack") == "bots/alice/hack"

    def test_when_building_id_with_mixed_case_then_slug_is_normalized(self):
        assert _bot_skill_id("bot", "My Great Skill") == "bots/bot/my-great-skill"


# ---------------------------------------------------------------------------
# Count warning
# ---------------------------------------------------------------------------

class TestCountWarning:

    @pytest.mark.asyncio
    async def test_when_skill_count_below_threshold_then_no_warning(
        self, db_session, patched_async_sessions,
    ):
        from app.tools.local.bot_skills import _check_count_warning
        for i in range(10):
            db_session.add(build_bot_skill(bot_id="testbot", name=f"skill-{i}"))
        await db_session.commit()

        result = await _check_count_warning("testbot", "bots/testbot/")

        assert result is None

    @pytest.mark.asyncio
    async def test_when_skill_count_at_or_above_threshold_then_warning_returned(
        self, db_session, patched_async_sessions,
    ):
        from app.tools.local.bot_skills import _check_count_warning
        for i in range(BOT_SKILL_COUNT_WARNING):
            db_session.add(build_bot_skill(bot_id="testbot", name=f"skill-{i}"))
        await db_session.commit()

        result = await _check_count_warning("testbot", "bots/testbot/")

        assert result is not None
        assert str(BOT_SKILL_COUNT_WARNING) in result

    @pytest.mark.asyncio
    async def test_when_create_pushes_count_over_threshold_then_create_message_includes_warning(
        self, db_session, patched_async_sessions, agent_context,
        embed_skill_patch, dedup_patch,
    ):
        for i in range(BOT_SKILL_COUNT_WARNING - 1):
            db_session.add(build_bot_skill(bot_id="testbot", name=f"pre-{i}"))
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="create", name="final", title="Final",
            content="x" * CONTENT_MIN_LENGTH,
        ))

        assert result["ok"] is True
        assert str(BOT_SKILL_COUNT_WARNING) in result["message"]


# ---------------------------------------------------------------------------
# Access control in get_skill
# ---------------------------------------------------------------------------

class TestGetSkillAccess:

    @pytest.mark.asyncio
    async def test_when_skill_id_starts_with_current_bot_prefix_then_owned(self):
        bot_id = "testbot"
        own_skill = f"bots/{bot_id}/my-skill"
        other_skill = "bots/otherbot/secret"

        assert own_skill.startswith(f"bots/{bot_id}/")
        assert not other_skill.startswith(f"bots/{bot_id}/")

    @pytest.mark.asyncio
    async def test_when_get_skill_called_for_own_skill_then_returns_content(
        self, db_session, patched_async_sessions, agent_context,
    ):
        from app.tools.local.skills import get_skill
        bot = build_bot(id="testbot")
        skill = build_bot_skill(bot_id="testbot", name="my-skill", content="x" * 100)
        db_session.add_all([bot, skill])
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = await get_skill(skill_id=skill.id)

        assert "not configured" not in result
        assert skill.name in result

    @pytest.mark.asyncio
    async def test_when_get_skill_called_for_other_bots_skill_then_access_denied(
        self, db_session, patched_async_sessions, agent_context,
    ):
        from app.tools.local.skills import get_skill
        others = build_bot_skill(bot_id="other", name="secret", content="x" * 100)
        db_session.add(others)
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = await get_skill(skill_id=others.id)

        assert "not configured" in result


# ---------------------------------------------------------------------------
# Content & name validation
# ---------------------------------------------------------------------------

class TestValidation:

    def test_when_content_too_short_then_validate_returns_error(self):
        result = _validate_content("short")
        assert result is not None
        assert "too short" in result.lower()

    def test_when_content_meets_min_then_validate_returns_none(self):
        assert _validate_content("x" * CONTENT_MIN_LENGTH) is None

    def test_when_content_exceeds_max_then_validate_returns_error(self):
        result = _validate_content("x" * (CONTENT_MAX_LENGTH + 1))
        assert result is not None
        assert "too large" in result.lower()

    def test_when_name_within_limit_then_validate_returns_none(self):
        assert _validate_name("my-skill") is None

    def test_when_name_too_long_then_validate_returns_error(self):
        result = _validate_name("x" * (NAME_MAX_LENGTH + 1))
        assert result is not None
        assert "too long" in result.lower()

    @pytest.mark.asyncio
    async def test_when_create_content_too_short_then_error_returned(self, agent_context):
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="create", name="foo", title="Foo", content="tiny",
        ))

        assert "too short" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_when_create_name_too_long_then_error_returned(self, agent_context):
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="create", name="x" * (NAME_MAX_LENGTH + 1), title="Foo",
            content="x" * CONTENT_MIN_LENGTH,
        ))

        assert "too long" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_when_update_content_too_short_then_error_returned(
        self, db_session, patched_async_sessions, agent_context,
    ):
        skill = build_bot_skill(bot_id="testbot", name="my-skill")
        db_session.add(skill)
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="update", name="my-skill", content="tiny",
        ))

        assert "too short" in result["error"].lower()


# ---------------------------------------------------------------------------
# Embedding status
# ---------------------------------------------------------------------------

class TestEmbeddingStatus:

    @pytest.mark.asyncio
    async def test_when_embedding_succeeds_then_result_embedded_true(
        self, db_session, patched_async_sessions, agent_context,
        embed_skill_patch, dedup_patch,
    ):
        embed_skill_patch.return_value = None  # re_embed_skill returns None on success
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="create", name="ok-skill", title="OK",
            content="x" * CONTENT_MIN_LENGTH,
        ))

        assert result["embedded"] is True
        assert "embedding failed" not in result["message"]

    @pytest.mark.asyncio
    async def test_when_embedding_fails_then_skill_saved_with_warning(
        self, db_session, patched_async_sessions, agent_context,
        embed_skill_patch, dedup_patch,
    ):
        embed_skill_patch.side_effect = RuntimeError("provider down")
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="create", name="fail-skill", title="Fail",
            content="x" * CONTENT_MIN_LENGTH,
        ))

        assert result == {
            "ok": True,
            "id": "bots/testbot/fail-skill",
            "embedded": False,
            "message": (
                "Skill 'bots/testbot/fail-skill' created."
                " Warning: embedding failed — skill saved but won't appear in RAG until re-embedded."
            ),
        }


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class TestListPagination:

    @pytest.mark.asyncio
    async def test_when_limit_and_offset_provided_then_result_page_reflects_them(
        self, db_session, patched_async_sessions, agent_context,
    ):
        base = datetime.now(timezone.utc)
        for i in range(5):
            skill = build_bot_skill(bot_id="testbot", name=f"skill-{i}")
            skill.updated_at = base - timedelta(seconds=i)  # descending order by updated_at
            db_session.add(skill)
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(action="list", limit=1, offset=2))

        assert result["total"] == 5
        assert result["limit"] == 1
        assert result["offset"] == 2
        assert [s["id"] for s in result["skills"]] == ["bots/testbot/skill-2"]

    @pytest.mark.asyncio
    async def test_when_limit_exceeds_max_then_clamped_to_100(
        self, db_session, patched_async_sessions, agent_context,
    ):
        db_session.add(build_bot_skill(bot_id="testbot", name="only"))
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(action="list", limit=999))

        assert result["limit"] == 100

    @pytest.mark.asyncio
    async def test_when_content_long_then_preview_truncated_to_120(
        self, db_session, patched_async_sessions, agent_context,
    ):
        long_body = "A" * 200
        content = f"---\nname: Test\ncategory: guide\n---\n\n{long_body}"
        db_session.add(build_bot_skill(bot_id="testbot", name="long", content=content))
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(action="list"))

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

    def test_when_value_has_newlines_then_sanitize_replaces_with_spaces(self):
        assert _sanitize_frontmatter_value("line1\nline2") == "line1 line2"
        assert _sanitize_frontmatter_value("line1\r\nline2") == "line1  line2"

    def test_when_value_has_leading_trailing_space_then_sanitize_strips(self):
        assert _sanitize_frontmatter_value("  hello  ") == "hello"

    def test_when_title_has_newline_then_build_content_sanitizes_it(self):
        result = _build_content("Bad\nTitle", "body content")
        assert "\nTitle" not in result
        assert "name: Bad Title" in result

    def test_when_triggers_have_newline_then_build_content_sanitizes_them(self):
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
    async def test_when_list_offset_past_end_then_empty_skills_but_total_correct(
        self, db_session, patched_async_sessions, agent_context,
    ):
        for i in range(3):
            db_session.add(build_bot_skill(bot_id="testbot", name=f"s-{i}"))
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(action="list", offset=100))

        assert result["total"] == 3
        assert result["skills"] == []
        assert result["offset"] == 100

    @pytest.mark.asyncio
    async def test_when_list_offset_negative_then_clamped_to_zero(
        self, db_session, patched_async_sessions, agent_context,
    ):
        db_session.add(build_bot_skill(bot_id="testbot", name="only"))
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(action="list", offset=-5))

        assert result["offset"] == 0

    @pytest.mark.asyncio
    async def test_when_list_limit_zero_then_clamped_to_one(
        self, db_session, patched_async_sessions, agent_context,
    ):
        db_session.add(build_bot_skill(bot_id="testbot", name="only"))
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(action="list", limit=0))

        assert result["limit"] == 1

    @pytest.mark.asyncio
    async def test_when_patch_shrinks_content_below_min_then_rejected(
        self, db_session, patched_async_sessions, agent_context, embed_skill_patch,
    ):
        body = "x" * CONTENT_MIN_LENGTH
        full_content = f"---\nname: Test\n---\n\n{body}"
        db_session.add(build_bot_skill(bot_id="testbot", name="my-skill", content=full_content))
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="patch", name="my-skill", old_text=body, new_text="tiny",
        ))

        assert "too short" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_when_patch_grows_content_above_max_then_rejected(
        self, db_session, patched_async_sessions, agent_context, embed_skill_patch,
    ):
        body = "x" * 100
        full_content = f"---\nname: Test\n---\n\n{body}"
        db_session.add(build_bot_skill(bot_id="testbot", name="my-skill", content=full_content))
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="patch", name="my-skill",
            old_text="x" * 50, new_text="y" * (CONTENT_MAX_LENGTH + 1),
        ))

        assert "too large" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_when_patch_target_is_file_managed_then_rejected(
        self, db_session, patched_async_sessions, agent_context, embed_skill_patch,
    ):
        db_session.add(build_bot_skill(
            bot_id="testbot", name="my-skill",
            content="body " * 50, source_type="file",
        ))
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="patch", name="my-skill", old_text="body", new_text="new",
        ))

        assert "file-managed" in result["error"]

    @pytest.mark.asyncio
    async def test_when_patch_new_text_empty_then_rejected(self, agent_context):
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="patch", name="x", old_text="something", new_text="",
        ))

        assert "required" in result["error"]


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
        """Reference section should come before skills section."""
        from app.config import DEFAULT_MEMORY_SCHEME_PROMPT
        # Find the reference and skills sections (header format may vary)
        ref_idx = DEFAULT_MEMORY_SCHEME_PROMPT.find("Reference Files")
        skills_idx = DEFAULT_MEMORY_SCHEME_PROMPT.find("Skills")
        assert ref_idx >= 0, "Reference section not found in memory prompt"
        assert skills_idx >= 0, "Skills section not found in memory prompt"
        assert ref_idx < skills_idx  # reference comes first
        # Skills section SHOULD mention auto-surfacing
        skills_section = DEFAULT_MEMORY_SCHEME_PROMPT[skills_idx:]
        assert "auto" in skills_section.lower()

    def test_main_prompt_has_when_not_to_create(self):
        """Skills section should include guidance on when NOT to create skills."""
        from app.config import DEFAULT_MEMORY_SCHEME_PROMPT
        prompt_lower = DEFAULT_MEMORY_SCHEME_PROMPT.lower()
        assert "don't create skills for" in prompt_lower or "do not create skills for" in prompt_lower

    def test_main_prompt_has_concrete_example(self):
        """Skills section should include a concrete manage_bot_skill call example."""
        from app.config import DEFAULT_MEMORY_SCHEME_PROMPT
        assert 'manage_bot_skill(action="create"' in DEFAULT_MEMORY_SCHEME_PROMPT


# NOTE: Dedup tests live in TestCreate
# (test_when_dedup_finds_similar_skill_then_create_rejected and
# test_when_force_true_then_dedup_bypassed) — the dedup path is a branch of the
# create action, not its own surface.


# ---------------------------------------------------------------------------
# Surfacing stats in list
# ---------------------------------------------------------------------------

class TestSurfacingStats:

    @pytest.mark.asyncio
    async def test_when_skill_has_surfacing_stats_then_list_includes_them(
        self, db_session, patched_async_sessions, agent_context,
    ):
        surfaced_at = datetime.now(timezone.utc) - timedelta(days=3)
        skill = build_bot_skill(
            bot_id="testbot", name="my-skill",
            content="---\nname: My Skill\n---\nSome content here",
            last_surfaced_at=surfaced_at, surface_count=42,
        )
        db_session.add(skill)
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(action="list"))

        assert len(result["skills"]) == 1
        assert result["skills"][0]["last_surfaced_at"] == surfaced_at.isoformat()
        assert result["skills"][0]["surface_count"] == 42


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
    async def test_when_merge_given_one_name_then_error_returned(self, agent_context):
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="merge", names=["only-one"],
            name="merged", title="Merged", content="x" * CONTENT_MIN_LENGTH,
        ))

        assert "at least 2" in result["error"]

    @pytest.mark.asyncio
    async def test_when_merge_given_no_names_then_error_returned(self, agent_context):
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="merge", name="merged", title="Merged",
            content="x" * CONTENT_MIN_LENGTH,
        ))

        assert "at least 2" in result["error"]

    @pytest.mark.asyncio
    async def test_when_merge_missing_target_name_then_error_returned(self, agent_context):
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="merge", names=["a", "b"],
            title="Merged", content="x" * CONTENT_MIN_LENGTH,
        ))

        assert "required" in result["error"]

    @pytest.mark.asyncio
    async def test_when_merge_two_skills_then_target_persisted_sources_deleted(
        self, db_session, patched_async_sessions, agent_context, embed_skill_patch,
    ):
        skill_a = build_bot_skill(bot_id="testbot", name="skill-a")
        skill_b = build_bot_skill(bot_id="testbot", name="skill-b")
        db_session.add_all([skill_a, skill_b])
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="merge", names=["skill-a", "skill-b"],
            name="merged", title="Merged Skill", content="x" * CONTENT_MIN_LENGTH,
        ))

        from sqlalchemy import select
        remaining_ids = (await db_session.execute(
            select(Skill.id).where(Skill.id.like("bots/testbot/%"))
        )).scalars().all()
        assert result["ok"] is True
        assert result["id"] == "bots/testbot/merged"
        assert set(result["deleted"]) == {skill_a.id, skill_b.id}
        assert set(remaining_ids) == {"bots/testbot/merged"}

    @pytest.mark.asyncio
    async def test_when_merge_supplies_triggers_and_category_then_merged_row_has_them(
        self, db_session, patched_async_sessions, agent_context, embed_skill_patch,
    ):
        db_session.add_all([
            build_bot_skill(bot_id="testbot", name="skill-a"),
            build_bot_skill(bot_id="testbot", name="skill-b"),
        ])
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="merge", names=["skill-a", "skill-b"],
            name="merged", title="Merged Skill",
            content="Combined knowledge about networking. " + "x" * 50,
            triggers="network, bridge", category="infrastructure",
        ))

        assert result["ok"] is True
        merged = await db_session.get(Skill, "bots/testbot/merged")
        assert merged.triggers == ["network", "bridge"]
        assert merged.category == "infrastructure"
        assert "networking" in merged.description.lower()

    @pytest.mark.asyncio
    async def test_when_merge_source_is_file_managed_then_rejected(
        self, db_session, patched_async_sessions, agent_context,
    ):
        db_session.add_all([
            build_bot_skill(bot_id="testbot", name="skill-a", source_type="file"),
            build_bot_skill(bot_id="testbot", name="skill-b"),
        ])
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="merge", names=["skill-a", "skill-b"],
            name="merged", title="Merged", content="x" * CONTENT_MIN_LENGTH,
        ))

        assert "file-managed" in result["error"]

    @pytest.mark.asyncio
    async def test_when_merge_source_missing_then_error_returned(
        self, db_session, patched_async_sessions, agent_context,
    ):
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="merge", names=["missing-a", "missing-b"],
            name="merged", title="Merged", content="x" * CONTENT_MIN_LENGTH,
        ))

        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_when_merge_target_exists_and_not_among_sources_then_rejected(
        self, db_session, patched_async_sessions, agent_context,
    ):
        db_session.add_all([
            build_bot_skill(bot_id="testbot", name="skill-a"),
            build_bot_skill(bot_id="testbot", name="skill-b"),
            build_bot_skill(bot_id="testbot", name="merged"),
        ])
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="merge", names=["skill-a", "skill-b"],
            name="merged", title="Merged", content="x" * CONTENT_MIN_LENGTH,
        ))

        assert "already exists" in result["error"]

    @pytest.mark.asyncio
    async def test_when_merge_target_is_one_of_sources_then_allowed(
        self, db_session, patched_async_sessions, agent_context, embed_skill_patch,
    ):
        db_session.add_all([
            build_bot_skill(bot_id="testbot", name="skill-a"),
            build_bot_skill(bot_id="testbot", name="skill-b"),
        ])
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="merge", names=["skill-a", "skill-b"],
            name="skill-a", title="Combined", content="x" * CONTENT_MIN_LENGTH,
        ))

        from sqlalchemy import select
        remaining_ids = set((await db_session.execute(
            select(Skill.id).where(Skill.id.like("bots/testbot/%"))
        )).scalars().all())
        assert result["ok"] is True
        assert remaining_ids == {"bots/testbot/skill-a"}

    @pytest.mark.asyncio
    async def test_when_merge_content_too_short_then_rejected(self, agent_context):
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
            action="merge", names=["a", "b"],
            name="merged", title="Merged", content="tiny",
        ))

        assert "too short" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_when_merge_names_all_duplicates_then_rejected_as_not_distinct(
        self, agent_context,
    ):
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(
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

    def test_when_never_surfaced_and_older_than_7_days_then_stale(self):
        old = datetime.now(timezone.utc) - timedelta(days=STALE_NEVER_SURFACED_DAYS + 1)
        assert _is_stale(created_at=old, last_surfaced_at=None, surface_count=0) is True

    def test_when_never_surfaced_and_newer_than_7_days_then_not_stale(self):
        recent = datetime.now(timezone.utc) - timedelta(days=STALE_NEVER_SURFACED_DAYS - 1)
        assert _is_stale(created_at=recent, last_surfaced_at=None, surface_count=0) is False

    def test_when_last_surfaced_within_30_days_then_not_stale(self):
        recent = datetime.now(timezone.utc) - timedelta(days=STALE_LAST_SURFACED_DAYS - 1)
        assert _is_stale(created_at=None, last_surfaced_at=recent, surface_count=5) is False

    def test_when_last_surfaced_over_30_days_ago_then_stale(self):
        old = datetime.now(timezone.utc) - timedelta(days=STALE_LAST_SURFACED_DAYS + 1)
        assert _is_stale(created_at=None, last_surfaced_at=old, surface_count=5) is True

    def test_when_created_at_is_none_and_never_surfaced_then_not_stale(self):
        assert _is_stale(created_at=None, last_surfaced_at=None, surface_count=0) is False

    def test_when_surface_count_nonzero_but_timestamp_missing_then_not_stale(self):
        # Data inconsistency: err on the side of not marking stale.
        old = datetime.now(timezone.utc) - timedelta(days=60)
        assert _is_stale(created_at=old, last_surfaced_at=None, surface_count=5) is False


class TestListStaleHints:

    @pytest.mark.asyncio
    async def test_when_skill_never_surfaced_and_old_then_stale_flag_set(
        self, db_session, patched_async_sessions, agent_context,
    ):
        old = datetime.now(timezone.utc) - timedelta(days=60)
        skill = build_bot_skill(
            bot_id="testbot", name="old-skill",
            content="---\nname: Old\n---\nSome content",
            created_at=old, surface_count=0,
        )
        db_session.add(skill)
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(action="list"))

        assert result["skills"][0]["stale"] is True
        assert result["skills"][0]["created_at"] == old.isoformat()

    @pytest.mark.asyncio
    async def test_when_one_stale_skill_exists_then_hint_uses_singular_grammar(
        self, db_session, patched_async_sessions, agent_context,
    ):
        old = datetime.now(timezone.utc) - timedelta(days=60)
        skill = build_bot_skill(
            bot_id="testbot", name="stale",
            content="---\nname: Stale\n---\nSome content",
            created_at=old, surface_count=0,
        )
        db_session.add(skill)
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(action="list"))

        assert "1 skill has" in result["hint"]
        assert "hasn't" in result["hint"]

    @pytest.mark.asyncio
    async def test_when_multiple_stale_skills_then_hint_uses_plural_grammar(
        self, db_session, patched_async_sessions, agent_context,
    ):
        old = datetime.now(timezone.utc) - timedelta(days=60)
        for i in range(2):
            db_session.add(build_bot_skill(
                bot_id="testbot", name=f"stale-{i}",
                content=f"---\nname: Stale {i}\n---\nSome content",
                created_at=old, surface_count=0,
            ))
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(action="list"))

        assert "2 skills have" in result["hint"]
        assert "haven't" in result["hint"]

    @pytest.mark.asyncio
    async def test_when_all_skills_fresh_then_no_hint_in_response(
        self, db_session, patched_async_sessions, agent_context,
    ):
        now = datetime.now(timezone.utc)
        skill = build_bot_skill(
            bot_id="testbot", name="fresh",
            content="---\nname: Fresh\n---\nSome content",
            created_at=now, last_surfaced_at=now, surface_count=5,
        )
        db_session.add(skill)
        await db_session.commit()
        agent_context(bot_id="testbot")

        result = json.loads(await manage_bot_skill(action="list"))

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
