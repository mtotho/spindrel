"""Tests for app.services.memory_hygiene — scheduler, resolution, and task creation."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

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
        bot.next_hygiene_run_at = next_run
        bot.last_hygiene_run_at = last_run
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
            await check_memory_hygiene()

        # No task created, but schedule advanced
        db.add.assert_not_called()
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


# ---------------------------------------------------------------------------
# Bootstrap schedule
# ---------------------------------------------------------------------------

class TestBootstrapHygieneSchedule:
    @pytest.mark.asyncio
    async def test_sets_next_run(self):
        from app.services.memory_hygiene import bootstrap_hygiene_schedule

        bot_row = MagicMock()
        bot_row.id = "test-bot"
        bot_row.memory_hygiene_interval_hours = 12
        bot_row.next_hygiene_run_at = None

        db = AsyncMock()
        db.commit = AsyncMock()

        now = datetime.now(timezone.utc)
        await bootstrap_hygiene_schedule(bot_row, db)

        assert bot_row.next_hygiene_run_at is not None
        # Should be approximately 12 hours from now
        delta = bot_row.next_hygiene_run_at - now
        assert timedelta(hours=11, minutes=59) < delta < timedelta(hours=12, minutes=1)
        db.commit.assert_awaited_once()
