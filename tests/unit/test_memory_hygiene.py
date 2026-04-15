"""Tests for app.services.memory_hygiene — scheduler, resolution, and task creation."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------

class TestResolveEnabled:
    def _make_bot(self, memory_scheme="workspace-files", hygiene_enabled=None):
        bot = MagicMock()
        bot.memory_scheme = memory_scheme
        bot.memory_hygiene_enabled = hygiene_enabled
        return bot

    def test_requires_workspace_files(self):
        from app.services.memory_hygiene import resolve_enabled
        bot = self._make_bot(memory_scheme=None)
        assert resolve_enabled(bot) is False

    def test_requires_workspace_files_even_if_enabled(self):
        from app.services.memory_hygiene import resolve_enabled
        bot = self._make_bot(memory_scheme="something-else", hygiene_enabled=True)
        assert resolve_enabled(bot) is False

    def test_inherits_global_when_none(self):
        from app.services.memory_hygiene import resolve_enabled
        bot = self._make_bot(hygiene_enabled=None)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_ENABLED = True
            assert resolve_enabled(bot) is True
            mock_settings.MEMORY_HYGIENE_ENABLED = False
            assert resolve_enabled(bot) is False

    def test_bot_override_true(self):
        from app.services.memory_hygiene import resolve_enabled
        bot = self._make_bot(hygiene_enabled=True)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_ENABLED = False
            assert resolve_enabled(bot) is True

    def test_bot_override_false(self):
        from app.services.memory_hygiene import resolve_enabled
        bot = self._make_bot(hygiene_enabled=False)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_ENABLED = True
            assert resolve_enabled(bot) is False


class TestResolveInterval:
    def _make_bot(self, interval=None):
        bot = MagicMock()
        bot.memory_hygiene_interval_hours = interval
        return bot

    def test_inherits_global(self):
        from app.services.memory_hygiene import resolve_interval
        bot = self._make_bot(interval=None)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_INTERVAL_HOURS = 48
            assert resolve_interval(bot) == 48

    def test_bot_override(self):
        from app.services.memory_hygiene import resolve_interval
        bot = self._make_bot(interval=12)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_INTERVAL_HOURS = 48
            assert resolve_interval(bot) == 12


class TestResolveOnlyIfActive:
    def _make_bot(self, only_if_active=None):
        bot = MagicMock()
        bot.memory_hygiene_only_if_active = only_if_active
        return bot

    def test_inherits_global(self):
        from app.services.memory_hygiene import resolve_only_if_active
        bot = self._make_bot(only_if_active=None)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_ONLY_IF_ACTIVE = False
            assert resolve_only_if_active(bot) is False

    def test_bot_override(self):
        from app.services.memory_hygiene import resolve_only_if_active
        bot = self._make_bot(only_if_active=False)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_ONLY_IF_ACTIVE = True
            assert resolve_only_if_active(bot) is False


class TestResolvePrompt:
    def _make_bot(self, prompt=None):
        bot = MagicMock()
        bot.memory_hygiene_prompt = prompt
        return bot

    def test_falls_through_to_builtin(self):
        from app.services.memory_hygiene import resolve_prompt
        from app.config import DEFAULT_MEMORY_HYGIENE_PROMPT
        bot = self._make_bot(prompt=None)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_PROMPT = ""
            result = resolve_prompt(bot)
            assert result == DEFAULT_MEMORY_HYGIENE_PROMPT

    def test_global_override(self):
        from app.services.memory_hygiene import resolve_prompt
        bot = self._make_bot(prompt=None)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_PROMPT = "global custom"
            assert resolve_prompt(bot) == "global custom"

    def test_bot_override(self):
        from app.services.memory_hygiene import resolve_prompt
        bot = self._make_bot(prompt="bot custom")
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_PROMPT = "global custom"
            assert resolve_prompt(bot) == "bot custom"


# ---------------------------------------------------------------------------
# Task creation
# ---------------------------------------------------------------------------

class TestCreateHygieneTask:
    @pytest.mark.asyncio
    async def test_creates_task_with_correct_fields(self):
        from app.services.memory_hygiene import create_hygiene_task

        bot_row = MagicMock()
        bot_row.id = "test-bot"
        bot_row.memory_hygiene_prompt = None
        bot_row.memory_scheme = "workspace-files"

        db = AsyncMock()
        db.get = AsyncMock(return_value=bot_row)
        db.add = MagicMock()
        db.commit = AsyncMock()

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_PROMPT = ""
            task_id = await create_hygiene_task("test-bot", db)

        assert task_id is not None
        db.add.assert_called_once()
        task = db.add.call_args[0][0]
        assert task.bot_id == "test-bot"
        assert task.task_type == "memory_hygiene"
        assert task.status == "pending"
        assert task.channel_id is None
        assert task.session_id is None
        assert task.dispatch_type == "none"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_on_missing_bot(self):
        from app.services.memory_hygiene import create_hygiene_task

        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="Bot not found"):
            await create_hygiene_task("nonexistent", db)


# ---------------------------------------------------------------------------
# Scheduler (check_memory_hygiene)
# ---------------------------------------------------------------------------

class TestCheckMemoryHygiene:
    def _make_bot_row(self, bot_id="test-bot", enabled=True, scheme="workspace-files",
                      interval=24, only_if_active=False, next_run=None, last_run=None):
        bot = MagicMock()
        bot.id = bot_id
        bot.memory_scheme = scheme
        bot.memory_hygiene_enabled = enabled
        bot.memory_hygiene_interval_hours = interval
        bot.memory_hygiene_only_if_active = only_if_active
        bot.memory_hygiene_prompt = None
        bot.memory_hygiene_target_hour = None
        bot.memory_hygiene_extra_instructions = None
        bot.next_hygiene_run_at = next_run
        bot.last_hygiene_run_at = last_run
        # Skill review defaults — disabled so it doesn't interfere with hygiene tests
        bot.skill_review_enabled = None
        bot.skill_review_interval_hours = None
        bot.skill_review_only_if_active = None
        bot.skill_review_prompt = None
        bot.skill_review_model = None
        bot.skill_review_model_provider_id = None
        bot.skill_review_target_hour = None
        bot.skill_review_extra_instructions = None
        bot.next_skill_review_run_at = None
        bot.last_skill_review_run_at = None
        return bot

    def _mock_db_session(self, bots, existing_task_count=0):
        """Create a mocked async_session context manager."""
        db = AsyncMock()

        # select(BotRow).where(...) returns scalars().all() → bots
        bots_result = MagicMock()
        bots_result.scalars.return_value.all.return_value = bots

        # select(func.count())... for dedup check → returns existing_task_count
        count_result = MagicMock()
        count_result.scalar.return_value = existing_task_count

        db.execute = AsyncMock(side_effect=[bots_result, count_result])
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.get = AsyncMock()

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm, db

    @pytest.mark.asyncio
    async def test_creates_task_when_due(self):
        from app.services.memory_hygiene import check_memory_hygiene

        now = datetime.now(timezone.utc)
        bot = self._make_bot_row(
            next_run=now - timedelta(minutes=5),  # past due
            only_if_active=False,
        )
        # For create_hygiene_task — it will call db.get for the bot row
        bot_for_create = MagicMock()
        bot_for_create.id = "test-bot"
        bot_for_create.memory_hygiene_prompt = None

        session_cm, db = self._mock_db_session([bot], existing_task_count=0)
        db.get = AsyncMock(return_value=bot_for_create)

        with patch("app.db.engine.async_session", return_value=session_cm), \
             patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_ENABLED = True
            mock_settings.MEMORY_HYGIENE_INTERVAL_HOURS = 24
            mock_settings.MEMORY_HYGIENE_ONLY_IF_ACTIVE = False
            mock_settings.MEMORY_HYGIENE_PROMPT = ""
            await check_memory_hygiene()

        # Task was added
        db.add.assert_called_once()
        task = db.add.call_args[0][0]
        assert task.task_type == "memory_hygiene"
        assert task.bot_id == "test-bot"

        # Schedule advanced
        assert bot.next_hygiene_run_at is not None
        assert bot.last_hygiene_run_at is not None

    @pytest.mark.asyncio
    async def test_skips_when_not_due(self):
        from app.services.memory_hygiene import check_memory_hygiene

        now = datetime.now(timezone.utc)
        bot = self._make_bot_row(
            next_run=now + timedelta(hours=12),  # future
            only_if_active=False,
        )
        session_cm, db = self._mock_db_session([bot])

        with patch("app.db.engine.async_session", return_value=session_cm), \
             patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_ENABLED = True
            mock_settings.MEMORY_HYGIENE_INTERVAL_HOURS = 24
            mock_settings.MEMORY_HYGIENE_ONLY_IF_ACTIVE = False
            mock_settings.MEMORY_HYGIENE_PROMPT = ""
            await check_memory_hygiene()

        # No task created
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self):
        from app.services.memory_hygiene import check_memory_hygiene

        now = datetime.now(timezone.utc)
        bot = self._make_bot_row(
            enabled=False,
            next_run=now - timedelta(hours=1),
        )
        session_cm, db = self._mock_db_session([bot])

        with patch("app.db.engine.async_session", return_value=session_cm), \
             patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_ENABLED = False
            mock_settings.MEMORY_HYGIENE_INTERVAL_HOURS = 24
            mock_settings.MEMORY_HYGIENE_ONLY_IF_ACTIVE = False
            mock_settings.MEMORY_HYGIENE_PROMPT = ""
            await check_memory_hygiene()

        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_dedup_skips_when_task_exists(self):
        from app.services.memory_hygiene import check_memory_hygiene

        now = datetime.now(timezone.utc)
        bot = self._make_bot_row(
            next_run=now - timedelta(minutes=5),
            only_if_active=False,
        )
        session_cm, db = self._mock_db_session([bot], existing_task_count=1)

        with patch("app.db.engine.async_session", return_value=session_cm), \
             patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_ENABLED = True
            mock_settings.MEMORY_HYGIENE_INTERVAL_HOURS = 24
            mock_settings.MEMORY_HYGIENE_ONLY_IF_ACTIVE = False
            mock_settings.MEMORY_HYGIENE_PROMPT = ""
            await check_memory_hygiene()

        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_activity_check_skips_no_activity(self):
        from app.services.memory_hygiene import check_memory_hygiene

        now = datetime.now(timezone.utc)
        bot = self._make_bot_row(
            next_run=now - timedelta(minutes=5),
            only_if_active=True,
            last_run=now - timedelta(hours=25),
        )

        db = AsyncMock()
        # First execute: select bots
        bots_result = MagicMock()
        bots_result.scalars.return_value.all.return_value = [bot]
        # Second execute: activity check (count=0, no activity)
        activity_result = MagicMock()
        activity_result.scalar.return_value = 0

        db.execute = AsyncMock(side_effect=[bots_result, activity_result])
        db.commit = AsyncMock()
        db.add = MagicMock()

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.engine.async_session", return_value=cm), \
             patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_ENABLED = True
            mock_settings.MEMORY_HYGIENE_INTERVAL_HOURS = 24
            mock_settings.MEMORY_HYGIENE_ONLY_IF_ACTIVE = True
            mock_settings.MEMORY_HYGIENE_PROMPT = ""
            mock_settings.MEMORY_HYGIENE_TARGET_HOUR = -1
            await check_memory_hygiene()

        # A skipped Task row was inserted so the Learning Center surfaces the
        # decision instead of dropping the cycle silently.
        db.add.assert_called_once()
        skip_task = db.add.call_args[0][0]
        assert skip_task.task_type == "memory_hygiene"
        assert skip_task.status == "skipped"
        assert skip_task.bot_id == "test-bot"
        assert skip_task.result and "No user messages" in skip_task.result
        assert skip_task.completed_at is not None

        # Schedule still advanced past now
        assert bot.next_hygiene_run_at is not None
        assert bot.next_hygiene_run_at > now


# ---------------------------------------------------------------------------
# Activity check function
# ---------------------------------------------------------------------------

class TestHasActivitySince:
    @pytest.mark.asyncio
    async def test_returns_true_when_messages_exist(self):
        from app.services.memory_hygiene import _has_activity_since

        db = AsyncMock()
        result = MagicMock()
        result.scalar.return_value = 3
        db.execute = AsyncMock(return_value=result)

        since = datetime.now(timezone.utc) - timedelta(hours=24)
        assert await _has_activity_since("test-bot", since, db) is True

    @pytest.mark.asyncio
    async def test_returns_false_when_no_messages(self):
        from app.services.memory_hygiene import _has_activity_since

        db = AsyncMock()
        result = MagicMock()
        result.scalar.return_value = 0
        db.execute = AsyncMock(return_value=result)

        since = datetime.now(timezone.utc) - timedelta(hours=24)
        assert await _has_activity_since("test-bot", since, db) is False

    @pytest.mark.asyncio
    async def test_query_includes_member_channels(self):
        """Verify that _has_activity_since uses bot_channel_filter (OR with ChannelBotMember)."""
        from app.services.memory_hygiene import _has_activity_since

        db = AsyncMock()
        result = MagicMock()
        result.scalar.return_value = 1
        db.execute = AsyncMock(return_value=result)

        since = datetime.now(timezone.utc) - timedelta(hours=24)
        await _has_activity_since("test-bot", since, db)

        # Inspect the compiled query — it should contain an OR with a subquery
        # referencing channel_bot_members
        call_args = db.execute.call_args
        stmt = call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "channel_bot_members" in compiled, (
            "Query should include channel_bot_members subquery for member channel visibility"
        )
        assert "OR" in compiled.upper(), (
            "Query should use OR to combine primary and member channel filters"
        )


# ---------------------------------------------------------------------------
# Bootstrap schedule
# ---------------------------------------------------------------------------

class TestBootstrapHygieneSchedule:
    @pytest.mark.asyncio
    async def test_sets_next_run_with_stagger(self):
        from app.services.memory_hygiene import bootstrap_hygiene_schedule

        bot_row = MagicMock()
        bot_row.id = "test-bot"
        bot_row.memory_hygiene_interval_hours = 12
        bot_row.memory_hygiene_target_hour = None
        bot_row.next_hygiene_run_at = None

        db = AsyncMock()
        db.commit = AsyncMock()

        now = datetime.now(timezone.utc)
        await bootstrap_hygiene_schedule(bot_row, db)

        assert bot_row.next_hygiene_run_at is not None
        # With stagger, next_run should be within [now, now + 12h)
        delta = bot_row.next_hygiene_run_at - now
        assert timedelta(0) <= delta < timedelta(hours=12)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_different_bots_get_different_offsets(self):
        """Two bots with different IDs should generally get different stagger offsets."""
        from app.services.memory_hygiene import bootstrap_hygiene_schedule

        times = []
        for bot_id in ["alpha-bot", "beta-bot"]:
            bot_row = MagicMock()
            bot_row.id = bot_id
            bot_row.memory_hygiene_interval_hours = 24
            bot_row.memory_hygiene_target_hour = None
            bot_row.next_hygiene_run_at = None

            db = AsyncMock()
            db.commit = AsyncMock()

            await bootstrap_hygiene_schedule(bot_row, db)
            times.append(bot_row.next_hygiene_run_at)

        # Different bots should (very likely) get different stagger offsets
        # This could theoretically fail if two bot IDs hash to the same offset,
        # but with a 1440-minute window that's extremely unlikely
        assert times[0] != times[1]


# ---------------------------------------------------------------------------
# Bot channel filter helper
# ---------------------------------------------------------------------------

class TestBotChannelFilter:
    def test_produces_or_with_subquery(self):
        """bot_channel_filter should produce an OR clause with ChannelBotMember subquery."""
        from app.services.channels import bot_channel_filter

        clause = bot_channel_filter("my-bot")
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "channel_bot_members" in compiled
        assert "OR" in compiled.upper()
        assert "my-bot" in compiled


# ---------------------------------------------------------------------------
# Enhanced hygiene prompt content
# ---------------------------------------------------------------------------

class TestHygienePromptContent:
    """Verify that the maintenance prompt includes key features."""

    def test_maintenance_has_six_steps(self):
        from app.config import DEFAULT_MEMORY_HYGIENE_PROMPT
        for step_num in range(1, 7):
            assert f"## Step {step_num}" in DEFAULT_MEMORY_HYGIENE_PROMPT, (
                f"Missing Step {step_num} in maintenance prompt"
            )
        # Steps 7-8 should NOT be in maintenance (they're in skill review)
        assert "## Step 7" not in DEFAULT_MEMORY_HYGIENE_PROMPT

    def test_has_contradiction_detection(self):
        from app.config import DEFAULT_MEMORY_HYGIENE_PROMPT
        assert "contradiction" in DEFAULT_MEMORY_HYGIENE_PROMPT.lower()
        assert "superseded" in DEFAULT_MEMORY_HYGIENE_PROMPT.lower()

    def test_has_lifecycle_annotations(self):
        from app.config import DEFAULT_MEMORY_HYGIENE_PROMPT
        assert "[updated:" in DEFAULT_MEMORY_HYGIENE_PROMPT
        assert "[confidence:" in DEFAULT_MEMORY_HYGIENE_PROMPT
        assert "[source:" in DEFAULT_MEMORY_HYGIENE_PROMPT

    def test_has_importance_scoring(self):
        from app.config import DEFAULT_MEMORY_HYGIENE_PROMPT
        prompt_lower = DEFAULT_MEMORY_HYGIENE_PROMPT.lower()
        assert "future utility" in prompt_lower
        assert "factual confidence" in prompt_lower
        assert "semantic novelty" in prompt_lower

    def test_has_archive_maintenance(self):
        from app.config import DEFAULT_MEMORY_HYGIENE_PROMPT
        assert "Archive maintenance" in DEFAULT_MEMORY_HYGIENE_PROMPT
        assert "14 days" in DEFAULT_MEMORY_HYGIENE_PROMPT

    def test_has_archive_path_guidance(self):
        from app.config import DEFAULT_MEMORY_HYGIENE_PROMPT
        assert "memory/logs/archive" in DEFAULT_MEMORY_HYGIENE_PROMPT

    def test_has_archive_tool_guidance(self):
        from app.config import DEFAULT_MEMORY_HYGIENE_PROMPT
        assert 'operation="mkdir"' in DEFAULT_MEMORY_HYGIENE_PROMPT
        assert 'operation="move"' in DEFAULT_MEMORY_HYGIENE_PROMPT

    def test_maintenance_does_not_have_skill_hygiene(self):
        from app.config import DEFAULT_MEMORY_HYGIENE_PROMPT
        assert "Skill hygiene" not in DEFAULT_MEMORY_HYGIENE_PROMPT
        assert "prune_enrolled_skills" not in DEFAULT_MEMORY_HYGIENE_PROMPT


class TestSkillReviewPromptContent:
    """Verify that the skill review prompt includes key features."""

    def test_has_three_steps(self):
        from app.config import DEFAULT_SKILL_REVIEW_PROMPT
        for step_num in range(1, 4):
            assert f"## Step {step_num}" in DEFAULT_SKILL_REVIEW_PROMPT, (
                f"Missing Step {step_num} in skill review prompt"
            )

    def test_has_cross_channel_reflection(self):
        from app.config import DEFAULT_SKILL_REVIEW_PROMPT
        assert "Cross-channel reflection" in DEFAULT_SKILL_REVIEW_PROMPT
        assert "[reflection YYYY-MM-DD]" in DEFAULT_SKILL_REVIEW_PROMPT

    def test_has_reflections_section_guidance(self):
        from app.config import DEFAULT_SKILL_REVIEW_PROMPT
        assert "## Reflections" in DEFAULT_SKILL_REVIEW_PROMPT

    def test_has_skill_hygiene(self):
        from app.config import DEFAULT_SKILL_REVIEW_PROMPT
        assert "Skill hygiene" in DEFAULT_SKILL_REVIEW_PROMPT
        assert "prune_enrolled_skills" in DEFAULT_SKILL_REVIEW_PROMPT

    def test_has_auto_inject_audit(self):
        from app.config import DEFAULT_SKILL_REVIEW_PROMPT
        assert "Auto-inject quality" in DEFAULT_SKILL_REVIEW_PROMPT

    def test_does_not_have_archive_maintenance(self):
        from app.config import DEFAULT_SKILL_REVIEW_PROMPT
        assert "Archive maintenance" not in DEFAULT_SKILL_REVIEW_PROMPT


# ---------------------------------------------------------------------------
# Model resolution helpers
# ---------------------------------------------------------------------------

class TestResolveModel:
    def _make_bot(self, model=None):
        bot = MagicMock()
        bot.memory_hygiene_model = model
        return bot

    def test_bot_override_wins(self):
        from app.services.memory_hygiene import resolve_model
        bot = self._make_bot(model="gpt-4o")
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_MODEL = "gemini-flash"
            assert resolve_model(bot) == "gpt-4o"

    def test_global_fallback(self):
        from app.services.memory_hygiene import resolve_model
        bot = self._make_bot(model=None)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_MODEL = "gemini-flash"
            assert resolve_model(bot) == "gemini-flash"

    def test_returns_none_when_both_empty(self):
        from app.services.memory_hygiene import resolve_model
        bot = self._make_bot(model=None)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_MODEL = ""
            assert resolve_model(bot) is None


class TestResolveModelProviderId:
    def _make_bot(self, provider=None):
        bot = MagicMock()
        bot.memory_hygiene_model_provider_id = provider
        return bot

    def test_bot_override_wins(self):
        from app.services.memory_hygiene import resolve_model_provider_id
        bot = self._make_bot(provider="openai-prod")
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_MODEL_PROVIDER_ID = "openai-dev"
            assert resolve_model_provider_id(bot) == "openai-prod"

    def test_global_fallback(self):
        from app.services.memory_hygiene import resolve_model_provider_id
        bot = self._make_bot(provider=None)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_MODEL_PROVIDER_ID = "openai-dev"
            assert resolve_model_provider_id(bot) == "openai-dev"

    def test_returns_none_when_both_empty(self):
        from app.services.memory_hygiene import resolve_model_provider_id
        bot = self._make_bot(provider=None)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_MODEL_PROVIDER_ID = ""
            assert resolve_model_provider_id(bot) is None


# ---------------------------------------------------------------------------
# Stagger offset
# ---------------------------------------------------------------------------

class TestStaggerOffset:
    def test_deterministic(self):
        from app.services.memory_hygiene import _stagger_offset_minutes
        a = _stagger_offset_minutes("my-bot", 24)
        b = _stagger_offset_minutes("my-bot", 24)
        assert a == b

    def test_different_bots_different_offsets(self):
        from app.services.memory_hygiene import _stagger_offset_minutes
        a = _stagger_offset_minutes("alpha-bot", 24)
        b = _stagger_offset_minutes("beta-bot", 24)
        assert a != b  # extremely unlikely to collide with 1440-minute window

    def test_within_range(self):
        from app.services.memory_hygiene import _stagger_offset_minutes
        for bot_id in ["bot-a", "bot-b", "bot-c", "bot-d", "bot-e"]:
            offset = _stagger_offset_minutes(bot_id, 12)
            assert 0 <= offset < 12 * 60, f"Offset {offset} out of range for bot {bot_id}"

    def test_zero_interval_no_crash(self):
        """Interval of 0 should not cause division by zero."""
        from app.services.memory_hygiene import _stagger_offset_minutes
        offset = _stagger_offset_minutes("bot-a", 0)
        assert offset == 0  # window=max(0,1)=1, so offset is 0


# ---------------------------------------------------------------------------
# Create hygiene task with execution_config
# ---------------------------------------------------------------------------

class TestCreateHygieneTaskExecutionConfig:
    @pytest.mark.asyncio
    async def test_execution_config_populated_when_model_set(self):
        from app.services.memory_hygiene import create_hygiene_task

        bot_row = MagicMock()
        bot_row.id = "test-bot"
        bot_row.memory_hygiene_prompt = None
        bot_row.memory_scheme = "workspace-files"
        bot_row.memory_hygiene_model = "gpt-4o-mini"
        bot_row.memory_hygiene_model_provider_id = "openai-prod"

        db = AsyncMock()
        db.get = AsyncMock(return_value=bot_row)
        db.add = MagicMock()
        db.commit = AsyncMock()

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_PROMPT = ""
            mock_settings.MEMORY_HYGIENE_MODEL = ""
            mock_settings.MEMORY_HYGIENE_MODEL_PROVIDER_ID = ""
            await create_hygiene_task("test-bot", db)

        task = db.add.call_args[0][0]
        assert task.execution_config is not None
        assert task.execution_config["model_override"] == "gpt-4o-mini"
        assert task.execution_config["model_provider_id_override"] == "openai-prod"

    @pytest.mark.asyncio
    async def test_execution_config_none_when_no_override(self):
        from app.services.memory_hygiene import create_hygiene_task

        bot_row = MagicMock()
        bot_row.id = "test-bot"
        bot_row.memory_hygiene_prompt = None
        bot_row.memory_scheme = "workspace-files"
        bot_row.memory_hygiene_model = None
        bot_row.memory_hygiene_model_provider_id = None

        db = AsyncMock()
        db.get = AsyncMock(return_value=bot_row)
        db.add = MagicMock()
        db.commit = AsyncMock()

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_PROMPT = ""
            mock_settings.MEMORY_HYGIENE_MODEL = ""
            mock_settings.MEMORY_HYGIENE_MODEL_PROVIDER_ID = ""
            await create_hygiene_task("test-bot", db)

        task = db.add.call_args[0][0]
        assert task.execution_config is None

    @pytest.mark.asyncio
    async def test_execution_config_with_only_model(self):
        from app.services.memory_hygiene import create_hygiene_task

        bot_row = MagicMock()
        bot_row.id = "test-bot"
        bot_row.memory_hygiene_prompt = None
        bot_row.memory_scheme = "workspace-files"
        bot_row.memory_hygiene_model = "gpt-4o"
        bot_row.memory_hygiene_model_provider_id = None

        db = AsyncMock()
        db.get = AsyncMock(return_value=bot_row)
        db.add = MagicMock()
        db.commit = AsyncMock()

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_PROMPT = ""
            mock_settings.MEMORY_HYGIENE_MODEL = ""
            mock_settings.MEMORY_HYGIENE_MODEL_PROVIDER_ID = ""
            await create_hygiene_task("test-bot", db)

        task = db.add.call_args[0][0]
        assert task.execution_config is not None
        assert task.execution_config["model_override"] == "gpt-4o"
        assert "model_provider_id_override" not in task.execution_config

    @pytest.mark.asyncio
    async def test_execution_config_with_global_model_fallback(self):
        from app.services.memory_hygiene import create_hygiene_task

        bot_row = MagicMock()
        bot_row.id = "test-bot"
        bot_row.memory_hygiene_prompt = None
        bot_row.memory_scheme = "workspace-files"
        bot_row.memory_hygiene_model = None
        bot_row.memory_hygiene_model_provider_id = None

        db = AsyncMock()
        db.get = AsyncMock(return_value=bot_row)
        db.add = MagicMock()
        db.commit = AsyncMock()

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_PROMPT = ""
            mock_settings.MEMORY_HYGIENE_MODEL = "global-model"
            mock_settings.MEMORY_HYGIENE_MODEL_PROVIDER_ID = ""
            await create_hygiene_task("test-bot", db)

        task = db.add.call_args[0][0]
        assert task.execution_config is not None
        assert task.execution_config["model_override"] == "global-model"


# ---------------------------------------------------------------------------
# Target hour resolution
# ---------------------------------------------------------------------------

class TestResolveTargetHour:
    def _make_bot(self, target_hour=None):
        bot = MagicMock()
        bot.memory_hygiene_target_hour = target_hour
        return bot

    def test_bot_override(self):
        from app.services.memory_hygiene import resolve_target_hour
        bot = self._make_bot(target_hour=3)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_TARGET_HOUR = 5
            assert resolve_target_hour(bot) == 3

    def test_global_fallback(self):
        from app.services.memory_hygiene import resolve_target_hour
        bot = self._make_bot(target_hour=None)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_TARGET_HOUR = 5
            assert resolve_target_hour(bot) == 5

    def test_disabled_default(self):
        from app.services.memory_hygiene import resolve_target_hour
        bot = self._make_bot(target_hour=None)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_TARGET_HOUR = -1
            assert resolve_target_hour(bot) == -1

    def test_bot_override_disabled(self):
        """Bot can explicitly set -1 to disable even when global is set."""
        from app.services.memory_hygiene import resolve_target_hour
        bot = self._make_bot(target_hour=-1)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_TARGET_HOUR = 3
            assert resolve_target_hour(bot) == -1


# ---------------------------------------------------------------------------
# Stagger offset target mode
# ---------------------------------------------------------------------------

class TestStaggerOffsetTargetMode:
    def test_target_mode_within_60_minutes(self):
        from app.services.memory_hygiene import _stagger_offset_minutes
        for bot_id in ["bot-a", "bot-b", "bot-c", "bot-d", "bot-e"]:
            offset = _stagger_offset_minutes(bot_id, 24, target_mode=True)
            assert 0 <= offset < 60, f"Target mode offset {offset} out of 60-min window for {bot_id}"

    def test_target_mode_deterministic(self):
        from app.services.memory_hygiene import _stagger_offset_minutes
        a = _stagger_offset_minutes("my-bot", 24, target_mode=True)
        b = _stagger_offset_minutes("my-bot", 24, target_mode=True)
        assert a == b

    def test_non_target_mode_uses_full_window(self):
        from app.services.memory_hygiene import _stagger_offset_minutes
        # With 24h interval, non-target window is 1440 minutes
        offset = _stagger_offset_minutes("bot-a", 24, target_mode=False)
        assert 0 <= offset < 1440


# ---------------------------------------------------------------------------
# _next_target_run
# ---------------------------------------------------------------------------

class TestNextTargetRun:
    """Test the _next_target_run helper that computes target-hour-anchored schedule."""

    def test_bootstrap_same_day_future(self):
        """If target hour is later today, schedule for today."""
        from app.services.memory_hygiene import _next_target_run

        tz = ZoneInfo("America/New_York")
        # Simulate "now" as 1:00 AM local -> target 3 AM should be today
        now_local = datetime(2026, 4, 6, 1, 0, 0, tzinfo=tz)
        now_utc = now_local.astimezone(timezone.utc)

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.TIMEZONE = "America/New_York"
            result = _next_target_run("test-bot", 3, 24, now_utc, after_run=False)

        # Result should be today at 3:00 AM + stagger (0-59 min), in UTC
        result_local = result.astimezone(tz)
        assert result_local.day == 6
        assert result_local.hour == 3
        assert 0 <= result_local.minute < 60

    def test_bootstrap_next_day_wrap(self):
        """If target hour already passed today, schedule for tomorrow."""
        from app.services.memory_hygiene import _next_target_run

        tz = ZoneInfo("America/New_York")
        # Simulate "now" as 5:00 AM local -> target 3 AM already passed
        now_local = datetime(2026, 4, 6, 5, 0, 0, tzinfo=tz)
        now_utc = now_local.astimezone(timezone.utc)

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.TIMEZONE = "America/New_York"
            result = _next_target_run("test-bot", 3, 24, now_utc, after_run=False)

        result_local = result.astimezone(tz)
        assert result_local.day == 7  # tomorrow
        assert result_local.hour == 3

    def test_after_run_daily_next_day(self):
        """After a run slightly past target hour, next run is tomorrow at target hour.

        Regression: previously the 'earliest = now + interval_hours' floor
        caused runs completing just past the target hour to be pushed two days
        out instead of one, because the 'tomorrow at target_hour' candidate
        fell short of the literal 24h floor by the run's own few minutes.
        """
        from app.services.memory_hygiene import _next_target_run

        tz = ZoneInfo("America/New_York")
        # Now is 3:30 AM, target is 3 AM, interval is 24h (daily).
        # Next run should be tomorrow at 3 AM + stagger.
        now_local = datetime(2026, 4, 6, 3, 30, 0, tzinfo=tz)
        now_utc = now_local.astimezone(timezone.utc)

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.TIMEZONE = "America/New_York"
            result = _next_target_run("test-bot", 3, 24, now_utc, after_run=True)

        result_local = result.astimezone(tz)
        assert result_local.day == 7  # tomorrow
        assert result_local.hour == 3

    def test_after_run_bennie_regression(self):
        """Regression: run completes at 04:36, target hour 04, next = tomorrow 04:XX.

        Exact scenario that produced the 48h cadence bug in production on
        2026-04-11: Bennie Bot finished at 04:36:09 with target_hour=4 and
        interval=24. Expected: next run 04-12 at 04:XX (≈24h later), not 04-13.
        """
        from app.services.memory_hygiene import _next_target_run

        tz = ZoneInfo("America/New_York")
        now_local = datetime(2026, 4, 11, 4, 36, 9, tzinfo=tz)
        now_utc = now_local.astimezone(timezone.utc)

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.TIMEZONE = "America/New_York"
            result = _next_target_run("bennie-bot", 4, 24, now_utc, after_run=True)

        result_local = result.astimezone(tz)
        assert result_local.day == 12  # next day, not day-after
        assert result_local.hour == 4

    def test_after_run_multi_day_interval(self):
        """With 48h interval, should anchor to target hour ~2 days out."""
        from app.services.memory_hygiene import _next_target_run

        tz = ZoneInfo("America/New_York")
        now_local = datetime(2026, 4, 6, 4, 0, 0, tzinfo=tz)
        now_utc = now_local.astimezone(timezone.utc)

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.TIMEZONE = "America/New_York"
            result = _next_target_run("test-bot", 3, 48, now_utc, after_run=True)

        result_local = result.astimezone(tz)
        # days_between = 2. Next target occurrence after now is Apr 7 3 AM,
        # then +1 day = Apr 8 3 AM.
        assert result_local.day == 8
        assert result_local.hour == 3

    def test_after_run_exact_target_hour(self):
        """Run that finishes exactly at target_hour:00:00 still schedules next day.

        Edge case: the 'strictly after now' rule handles the boundary cleanly.
        """
        from app.services.memory_hygiene import _next_target_run

        tz = ZoneInfo("America/New_York")
        now_local = datetime(2026, 4, 6, 3, 0, 0, tzinfo=tz)
        now_utc = now_local.astimezone(timezone.utc)

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.TIMEZONE = "America/New_York"
            result = _next_target_run("test-bot", 3, 24, now_utc, after_run=True)

        result_local = result.astimezone(tz)
        assert result_local.day == 7
        assert result_local.hour == 3

    def test_after_run_before_target_hour(self):
        """Run finishes at 01:00, target hour is 03:00: next run is today at 03:00."""
        from app.services.memory_hygiene import _next_target_run

        tz = ZoneInfo("America/New_York")
        now_local = datetime(2026, 4, 6, 1, 0, 0, tzinfo=tz)
        now_utc = now_local.astimezone(timezone.utc)

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.TIMEZONE = "America/New_York"
            result = _next_target_run("test-bot", 3, 24, now_utc, after_run=True)

        result_local = result.astimezone(tz)
        # 03:00 today is strictly after 01:00 now, so candidate stays today.
        # days_between=1, no extra days. Next = today at 03:00.
        assert result_local.day == 6
        assert result_local.hour == 3

    def test_stagger_within_window(self):
        """Two different bots get different stagger offsets within the 60-min window."""
        from app.services.memory_hygiene import _next_target_run

        tz = ZoneInfo("America/New_York")
        now_local = datetime(2026, 4, 6, 1, 0, 0, tzinfo=tz)
        now_utc = now_local.astimezone(timezone.utc)

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.TIMEZONE = "America/New_York"
            r1 = _next_target_run("alpha-bot", 3, 24, now_utc)
            r2 = _next_target_run("beta-bot", 3, 24, now_utc)

        # Both should be on the same day, same hour, but different minutes
        r1_local = r1.astimezone(tz)
        r2_local = r2.astimezone(tz)
        assert r1_local.day == r2_local.day
        assert r1_local.hour == r2_local.hour == 3
        # Very unlikely to have the same minute with 60-min window
        assert r1_local.minute != r2_local.minute


# ---------------------------------------------------------------------------
# Bootstrap with target hour
# ---------------------------------------------------------------------------

class TestBootstrapWithTargetHour:
    @pytest.mark.asyncio
    async def test_bootstrap_anchors_to_target_hour(self):
        """When target_hour is set, bootstrap should anchor to that hour."""
        from app.services.memory_hygiene import bootstrap_hygiene_schedule

        tz = ZoneInfo("America/New_York")
        bot_row = MagicMock()
        bot_row.id = "test-bot"
        bot_row.memory_hygiene_interval_hours = 24
        bot_row.memory_hygiene_target_hour = 3
        bot_row.next_hygiene_run_at = None

        db = AsyncMock()
        db.commit = AsyncMock()

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_INTERVAL_HOURS = 24
            mock_settings.MEMORY_HYGIENE_TARGET_HOUR = -1  # global disabled
            mock_settings.TIMEZONE = "America/New_York"
            await bootstrap_hygiene_schedule(bot_row, db)

        assert bot_row.next_hygiene_run_at is not None
        result_local = bot_row.next_hygiene_run_at.astimezone(tz)
        assert result_local.hour == 3
        assert 0 <= result_local.minute < 60

    @pytest.mark.asyncio
    async def test_bootstrap_disabled_target_uses_stagger(self):
        """When target_hour is -1, should use the old stagger behaviour."""
        from app.services.memory_hygiene import bootstrap_hygiene_schedule

        bot_row = MagicMock()
        bot_row.id = "test-bot"
        bot_row.memory_hygiene_interval_hours = 12
        bot_row.memory_hygiene_target_hour = None  # inherit global
        bot_row.next_hygiene_run_at = None

        db = AsyncMock()
        db.commit = AsyncMock()

        now = datetime.now(timezone.utc)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_INTERVAL_HOURS = 12
            mock_settings.MEMORY_HYGIENE_TARGET_HOUR = -1
            mock_settings.TIMEZONE = "America/New_York"
            await bootstrap_hygiene_schedule(bot_row, db)

        assert bot_row.next_hygiene_run_at is not None
        delta = bot_row.next_hygiene_run_at - now
        # Old behaviour: stagger within [0, 12h)
        assert timedelta(0) <= delta < timedelta(hours=12)


# ---------------------------------------------------------------------------
# _compute_next_run
# ---------------------------------------------------------------------------

class TestComputeNextRun:
    def test_uses_target_when_set(self):
        from app.services.memory_hygiene import _compute_next_run

        tz = ZoneInfo("America/New_York")
        now_local = datetime(2026, 4, 6, 1, 0, 0, tzinfo=tz)
        now_utc = now_local.astimezone(timezone.utc)

        bot_row = MagicMock()
        bot_row.id = "test-bot"
        bot_row.memory_hygiene_interval_hours = 24
        bot_row.memory_hygiene_target_hour = 3

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_INTERVAL_HOURS = 24
            mock_settings.MEMORY_HYGIENE_TARGET_HOUR = -1
            mock_settings.TIMEZONE = "America/New_York"
            result = _compute_next_run(bot_row, now_utc, after_run=True)

        result_local = result.astimezone(tz)
        assert result_local.hour == 3

    def test_falls_back_to_interval_when_disabled(self):
        from app.services.memory_hygiene import _compute_next_run

        now_utc = datetime(2026, 4, 6, 5, 0, 0, tzinfo=timezone.utc)

        bot_row = MagicMock()
        bot_row.id = "test-bot"
        bot_row.memory_hygiene_interval_hours = 24
        bot_row.memory_hygiene_target_hour = None

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_INTERVAL_HOURS = 24
            mock_settings.MEMORY_HYGIENE_TARGET_HOUR = -1
            mock_settings.TIMEZONE = "America/New_York"
            result = _compute_next_run(bot_row, now_utc)

        # Should be now + 24h
        expected = now_utc + timedelta(hours=24)
        assert result == expected


# ---------------------------------------------------------------------------
# Skill review: resolve_config
# ---------------------------------------------------------------------------

class TestSkillReviewResolveConfig:
    """Verify that skill_review config resolution follows the same pattern."""

    def _make_bot(self, **overrides):
        bot = MagicMock()
        bot.memory_scheme = "workspace-files"
        # memory_hygiene defaults
        bot.memory_hygiene_enabled = None
        bot.memory_hygiene_interval_hours = None
        bot.memory_hygiene_only_if_active = None
        bot.memory_hygiene_prompt = None
        bot.memory_hygiene_model = None
        bot.memory_hygiene_model_provider_id = None
        bot.memory_hygiene_target_hour = None
        bot.memory_hygiene_extra_instructions = None
        # skill_review defaults
        bot.skill_review_enabled = None
        bot.skill_review_interval_hours = None
        bot.skill_review_only_if_active = None
        bot.skill_review_prompt = None
        bot.skill_review_model = None
        bot.skill_review_model_provider_id = None
        bot.skill_review_target_hour = None
        bot.skill_review_extra_instructions = None
        for k, v in overrides.items():
            setattr(bot, k, v)
        return bot

    def test_disabled_without_workspace_files(self):
        from app.services.memory_hygiene import resolve_config
        bot = self._make_bot(memory_scheme=None)
        cfg = resolve_config(bot, "skill_review")
        assert cfg.enabled is False

    def test_inherits_global_enabled(self):
        from app.services.memory_hygiene import resolve_config
        bot = self._make_bot()
        with patch("app.services.memory_hygiene.settings") as ms:
            ms.SKILL_REVIEW_ENABLED = True
            ms.SKILL_REVIEW_INTERVAL_HOURS = 72
            ms.SKILL_REVIEW_ONLY_IF_ACTIVE = False
            ms.SKILL_REVIEW_PROMPT = ""
            ms.SKILL_REVIEW_MODEL = ""
            ms.SKILL_REVIEW_MODEL_PROVIDER_ID = ""
            ms.SKILL_REVIEW_TARGET_HOUR = -1
            cfg = resolve_config(bot, "skill_review")
        assert cfg.enabled is True
        assert cfg.interval_hours == 72

    def test_bot_override_wins(self):
        from app.services.memory_hygiene import resolve_config
        bot = self._make_bot(
            skill_review_enabled=True,
            skill_review_interval_hours=48,
            skill_review_model="gpt-4",
        )
        with patch("app.services.memory_hygiene.settings") as ms:
            ms.SKILL_REVIEW_ENABLED = False
            ms.SKILL_REVIEW_INTERVAL_HOURS = 72
            ms.SKILL_REVIEW_ONLY_IF_ACTIVE = False
            ms.SKILL_REVIEW_PROMPT = ""
            ms.SKILL_REVIEW_MODEL = ""
            ms.SKILL_REVIEW_MODEL_PROVIDER_ID = ""
            ms.SKILL_REVIEW_TARGET_HOUR = -1
            cfg = resolve_config(bot, "skill_review")
        assert cfg.enabled is True
        assert cfg.interval_hours == 48
        assert cfg.model == "gpt-4"

    def test_default_only_if_active_is_false(self):
        """Skill review defaults to only_if_active=False (skill rot is activity-independent)."""
        from app.services.memory_hygiene import resolve_config
        bot = self._make_bot()
        with patch("app.services.memory_hygiene.settings") as ms:
            ms.SKILL_REVIEW_ENABLED = True
            ms.SKILL_REVIEW_INTERVAL_HOURS = 72
            ms.SKILL_REVIEW_ONLY_IF_ACTIVE = False
            ms.SKILL_REVIEW_PROMPT = ""
            ms.SKILL_REVIEW_MODEL = ""
            ms.SKILL_REVIEW_MODEL_PROVIDER_ID = ""
            ms.SKILL_REVIEW_TARGET_HOUR = -1
            cfg = resolve_config(bot, "skill_review")
        assert cfg.only_if_active is False

    def test_extra_instructions_resolved(self):
        from app.services.memory_hygiene import resolve_config
        bot = self._make_bot(skill_review_extra_instructions="Use firecrawl for research")
        with patch("app.services.memory_hygiene.settings") as ms:
            ms.SKILL_REVIEW_ENABLED = True
            ms.SKILL_REVIEW_INTERVAL_HOURS = 72
            ms.SKILL_REVIEW_ONLY_IF_ACTIVE = False
            ms.SKILL_REVIEW_PROMPT = ""
            ms.SKILL_REVIEW_MODEL = ""
            ms.SKILL_REVIEW_MODEL_PROVIDER_ID = ""
            ms.SKILL_REVIEW_TARGET_HOUR = -1
            cfg = resolve_config(bot, "skill_review")
        assert cfg.extra_instructions == "Use firecrawl for research"


# ---------------------------------------------------------------------------
# Cross-job stagger
# ---------------------------------------------------------------------------

class TestCrossJobStagger:
    """Verify that two jobs don't run within 30 min of each other for the same bot."""

    def test_pushes_forward_when_too_close(self):
        from app.services.memory_hygiene import _cross_job_stagger
        now = datetime(2026, 4, 15, 10, 0, 0, tzinfo=timezone.utc)

        bot = MagicMock()
        bot.id = "test-bot"
        # Other job scheduled 10 min later
        bot.next_hygiene_run_at = now + timedelta(minutes=10)

        # skill_review proposed at now — should be pushed forward 60 min
        result = _cross_job_stagger(bot, "skill_review", now)
        assert result == now + timedelta(minutes=60)

    def test_no_push_when_far_apart(self):
        from app.services.memory_hygiene import _cross_job_stagger
        now = datetime(2026, 4, 15, 10, 0, 0, tzinfo=timezone.utc)

        bot = MagicMock()
        bot.id = "test-bot"
        # Other job scheduled 2 hours later
        bot.next_hygiene_run_at = now + timedelta(hours=2)

        result = _cross_job_stagger(bot, "skill_review", now)
        assert result == now  # unchanged

    def test_no_push_when_other_not_scheduled(self):
        from app.services.memory_hygiene import _cross_job_stagger
        now = datetime(2026, 4, 15, 10, 0, 0, tzinfo=timezone.utc)

        bot = MagicMock()
        bot.id = "test-bot"
        bot.next_hygiene_run_at = None

        result = _cross_job_stagger(bot, "skill_review", now)
        assert result == now  # unchanged
