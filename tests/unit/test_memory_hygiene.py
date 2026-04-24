"""Tests for app.services.memory_hygiene — scheduler, resolution, task creation.

Rewritten 2026-04-17 (Phase 1a of the Test Quality track). Every class that
touches a DB surface now uses the real ``db_session`` fixture + the
``patched_async_sessions`` fixture from ``tests/unit/conftest.py`` + real ORM
rows from ``tests/factories``. The only remaining MagicMock usage is:

- ``TestDiscoveryAuditSnapshot`` — the SQL uses PostgreSQL JSONB functions
  (``jsonb_to_recordset``, ``jsonb_array_elements_text``) that don't run on
  SQLite, so we feed canned execute results. This is an acceptable exception
  per ``testing-python/SKILL.md`` E.1.
- ``TestBotChannelFilter`` — the SQL builder itself is the unit under test.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.db.models import Session, Message, Task
from tests.factories import (
    build_bot,
    build_bot_skill,
    build_bot_skill_enrollment,
    build_channel,
    build_channel_bot_member,
    build_skill,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_session(**overrides) -> Session:
    """Test-local Session factory (no factory file — only used here)."""
    defaults = dict(
        id=uuid.uuid4(),
        client_id="test-client",
        bot_id="test-bot",
        channel_id=None,
    )
    return Session(**{**defaults, **overrides})


def _build_user_message(session_id, *, content: str = "hi", minutes_ago: int = 0) -> Message:
    return Message(
        id=uuid.uuid4(),
        session_id=session_id,
        role="user",
        content=content,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )


# ---------------------------------------------------------------------------
# Resolution helpers (pure, no DB)
# ---------------------------------------------------------------------------

class TestResolveEnabled:
    def test_when_memory_scheme_is_none_then_disabled(self):
        from app.services.memory_hygiene import resolve_enabled
        bot = build_bot(memory_scheme=None, memory_hygiene_enabled=None)
        assert resolve_enabled(bot) is False

    def test_when_memory_scheme_not_workspace_files_then_disabled_even_if_bot_enabled(self):
        from app.services.memory_hygiene import resolve_enabled
        bot = build_bot(memory_scheme="something-else", memory_hygiene_enabled=True)
        assert resolve_enabled(bot) is False

    def test_when_bot_has_no_preference_then_inherits_global(self):
        from app.services.memory_hygiene import resolve_enabled
        bot = build_bot(memory_hygiene_enabled=None)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_ENABLED = True
            assert resolve_enabled(bot) is True
            mock_settings.MEMORY_HYGIENE_ENABLED = False
            assert resolve_enabled(bot) is False

    def test_when_bot_enabled_overrides_global_disabled(self):
        from app.services.memory_hygiene import resolve_enabled
        bot = build_bot(memory_hygiene_enabled=True)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_ENABLED = False
            assert resolve_enabled(bot) is True

    def test_when_bot_disabled_overrides_global_enabled(self):
        from app.services.memory_hygiene import resolve_enabled
        bot = build_bot(memory_hygiene_enabled=False)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_ENABLED = True
            assert resolve_enabled(bot) is False


class TestResolveInterval:
    def test_when_bot_has_no_interval_then_inherits_global(self):
        from app.services.memory_hygiene import resolve_interval
        bot = build_bot(memory_hygiene_interval_hours=None)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_INTERVAL_HOURS = 48
            assert resolve_interval(bot) == 48

    def test_when_bot_sets_interval_then_overrides_global(self):
        from app.services.memory_hygiene import resolve_interval
        bot = build_bot(memory_hygiene_interval_hours=12)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_INTERVAL_HOURS = 48
            assert resolve_interval(bot) == 12


class TestResolveOnlyIfActive:
    def test_when_bot_has_no_preference_then_inherits_global(self):
        from app.services.memory_hygiene import resolve_only_if_active
        bot = build_bot(memory_hygiene_only_if_active=None)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_ONLY_IF_ACTIVE = False
            assert resolve_only_if_active(bot) is False

    def test_when_bot_disabled_only_if_active_overrides_global_enabled(self):
        from app.services.memory_hygiene import resolve_only_if_active
        bot = build_bot(memory_hygiene_only_if_active=False)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_ONLY_IF_ACTIVE = True
            assert resolve_only_if_active(bot) is False


class TestResolvePrompt:
    def test_when_neither_bot_nor_global_set_then_uses_builtin_default(self):
        from app.config import DEFAULT_MEMORY_HYGIENE_PROMPT
        from app.services.memory_hygiene import resolve_prompt
        bot = build_bot(memory_hygiene_prompt=None)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_PROMPT = ""
            assert resolve_prompt(bot) == DEFAULT_MEMORY_HYGIENE_PROMPT

    def test_when_global_set_then_overrides_builtin(self):
        from app.services.memory_hygiene import resolve_prompt
        bot = build_bot(memory_hygiene_prompt=None)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_PROMPT = "global custom"
            assert resolve_prompt(bot) == "global custom"

    def test_when_bot_prompt_set_then_overrides_global(self):
        from app.services.memory_hygiene import resolve_prompt
        bot = build_bot(memory_hygiene_prompt="bot custom")
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_PROMPT = "global custom"
            assert resolve_prompt(bot) == "bot custom"


class TestResolveModel:
    def test_when_bot_model_set_then_overrides_global(self):
        from app.services.memory_hygiene import resolve_model
        bot = build_bot(memory_hygiene_model="gpt-4o")
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_MODEL = "gemini-flash"
            assert resolve_model(bot) == "gpt-4o"

    def test_when_bot_has_no_model_then_inherits_global(self):
        from app.services.memory_hygiene import resolve_model
        bot = build_bot(memory_hygiene_model=None)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_MODEL = "gemini-flash"
            assert resolve_model(bot) == "gemini-flash"

    def test_when_neither_set_then_returns_none(self):
        from app.services.memory_hygiene import resolve_model
        bot = build_bot(memory_hygiene_model=None)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_MODEL = ""
            assert resolve_model(bot) is None


class TestResolveModelProviderId:
    def test_when_bot_provider_set_then_overrides_global(self):
        from app.services.memory_hygiene import resolve_model_provider_id
        bot = build_bot(memory_hygiene_model_provider_id="openai-prod")
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_MODEL_PROVIDER_ID = "openai-dev"
            assert resolve_model_provider_id(bot) == "openai-prod"

    def test_when_bot_has_no_provider_then_inherits_global(self):
        from app.services.memory_hygiene import resolve_model_provider_id
        bot = build_bot(memory_hygiene_model_provider_id=None)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_MODEL_PROVIDER_ID = "openai-dev"
            assert resolve_model_provider_id(bot) == "openai-dev"

    def test_when_neither_set_then_returns_none(self):
        from app.services.memory_hygiene import resolve_model_provider_id
        bot = build_bot(memory_hygiene_model_provider_id=None)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_MODEL_PROVIDER_ID = ""
            assert resolve_model_provider_id(bot) is None


class TestResolveTargetHour:
    def test_when_bot_sets_target_hour_then_overrides_global(self):
        from app.services.memory_hygiene import resolve_target_hour
        bot = build_bot(memory_hygiene_target_hour=3)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_TARGET_HOUR = 5
            assert resolve_target_hour(bot) == 3

    def test_when_bot_has_no_target_hour_then_inherits_global(self):
        from app.services.memory_hygiene import resolve_target_hour
        bot = build_bot(memory_hygiene_target_hour=None)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_TARGET_HOUR = 5
            assert resolve_target_hour(bot) == 5

    def test_when_global_disabled_then_returns_disabled_sentinel(self):
        from app.services.memory_hygiene import resolve_target_hour
        bot = build_bot(memory_hygiene_target_hour=None)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_TARGET_HOUR = -1
            assert resolve_target_hour(bot) == -1

    def test_when_bot_explicitly_disables_then_overrides_global_enabled(self):
        from app.services.memory_hygiene import resolve_target_hour
        bot = build_bot(memory_hygiene_target_hour=-1)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_TARGET_HOUR = 3
            assert resolve_target_hour(bot) == -1


# ---------------------------------------------------------------------------
# Task creation — real DB
# ---------------------------------------------------------------------------

class TestCreateHygieneTask:
    @pytest.mark.asyncio
    async def test_when_creating_hygiene_task_then_task_row_is_pending_with_bot_scope(self, db_session):
        from app.services.memory_hygiene import create_hygiene_task

        bot = build_bot(id="test-bot", memory_scheme="workspace-files", memory_hygiene_prompt=None)
        db_session.add(bot)
        await db_session.commit()

        task_id = await create_hygiene_task(bot.id, db_session)

        task = (await db_session.execute(select(Task).where(Task.id == task_id))).scalar_one()
        assert (task.bot_id, task.task_type, task.status, task.channel_id, task.session_id, task.dispatch_type) == (
            bot.id, "memory_hygiene", "pending", None, None, "none"
        )

    @pytest.mark.asyncio
    async def test_when_bot_missing_then_raises_value_error(self, db_session):
        from app.services.memory_hygiene import create_hygiene_task

        with pytest.raises(ValueError, match="Bot not found"):
            await create_hygiene_task("nonexistent", db_session)


class TestCreateHygieneTaskExecutionConfig:
    @pytest.mark.asyncio
    async def test_when_bot_has_model_and_provider_then_execution_config_populated(self, db_session):
        from app.services.memory_hygiene import create_hygiene_task

        bot = build_bot(
            id="exec-bot-1",
            memory_scheme="workspace-files",
            memory_hygiene_model="gpt-4o-mini",
            memory_hygiene_model_provider_id="openai-prod",
        )
        db_session.add(bot)
        await db_session.commit()

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_PROMPT = ""
            mock_settings.MEMORY_HYGIENE_MODEL = ""
            mock_settings.MEMORY_HYGIENE_MODEL_PROVIDER_ID = ""
            task_id = await create_hygiene_task(bot.id, db_session)

        task = (await db_session.execute(select(Task).where(Task.id == task_id))).scalar_one()
        assert task.execution_config == {
            "model_override": "gpt-4o-mini",
            "model_provider_id_override": "openai-prod",
        }

    @pytest.mark.asyncio
    async def test_when_no_model_overrides_set_then_execution_config_is_none(self, db_session):
        from app.services.memory_hygiene import create_hygiene_task

        bot = build_bot(
            id="exec-bot-2",
            memory_scheme="workspace-files",
            memory_hygiene_model=None,
            memory_hygiene_model_provider_id=None,
        )
        db_session.add(bot)
        await db_session.commit()

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_PROMPT = ""
            mock_settings.MEMORY_HYGIENE_MODEL = ""
            mock_settings.MEMORY_HYGIENE_MODEL_PROVIDER_ID = ""
            task_id = await create_hygiene_task(bot.id, db_session)

        task = (await db_session.execute(select(Task).where(Task.id == task_id))).scalar_one()
        assert task.execution_config is None

    @pytest.mark.asyncio
    async def test_when_only_bot_model_set_then_provider_auto_resolves_or_absent(self, db_session):
        """With just a model set the task must record the model_override. The
        provider side falls through to ``resolve_provider_for_model``; under
        tests the provider registry is empty so the key is omitted."""
        from app.services.memory_hygiene import create_hygiene_task

        bot = build_bot(
            id="exec-bot-3",
            memory_scheme="workspace-files",
            memory_hygiene_model="gpt-4o",
            memory_hygiene_model_provider_id=None,
        )
        db_session.add(bot)
        await db_session.commit()

        with patch("app.services.memory_hygiene.settings") as mock_settings, \
             patch("app.services.providers.resolve_provider_for_model", return_value=None):
            mock_settings.MEMORY_HYGIENE_PROMPT = ""
            mock_settings.MEMORY_HYGIENE_MODEL = ""
            mock_settings.MEMORY_HYGIENE_MODEL_PROVIDER_ID = ""
            task_id = await create_hygiene_task(bot.id, db_session)

        task = (await db_session.execute(select(Task).where(Task.id == task_id))).scalar_one()
        assert task.execution_config == {"model_override": "gpt-4o"}

    @pytest.mark.asyncio
    async def test_when_bot_has_no_model_then_global_model_setting_applies(self, db_session):
        from app.services.memory_hygiene import create_hygiene_task

        bot = build_bot(
            id="exec-bot-4",
            memory_scheme="workspace-files",
            memory_hygiene_model=None,
            memory_hygiene_model_provider_id=None,
        )
        db_session.add(bot)
        await db_session.commit()

        with patch("app.services.memory_hygiene.settings") as mock_settings, \
             patch("app.services.providers.resolve_provider_for_model", return_value=None):
            mock_settings.MEMORY_HYGIENE_PROMPT = ""
            mock_settings.MEMORY_HYGIENE_MODEL = "global-model"
            mock_settings.MEMORY_HYGIENE_MODEL_PROVIDER_ID = ""
            task_id = await create_hygiene_task(bot.id, db_session)

        task = (await db_session.execute(select(Task).where(Task.id == task_id))).scalar_one()
        assert task.execution_config == {"model_override": "global-model"}


# ---------------------------------------------------------------------------
# Scheduler (check_memory_hygiene) — real DB via patched_async_sessions
# ---------------------------------------------------------------------------

class TestCheckMemoryHygiene:
    @pytest.mark.asyncio
    async def test_when_bot_is_due_then_creates_pending_hygiene_task(
        self, db_session, patched_async_sessions
    ):
        from app.services.memory_hygiene import check_memory_hygiene

        now = datetime.now(timezone.utc)
        bot = build_bot(
            id="due-bot",
            memory_scheme="workspace-files",
            memory_hygiene_enabled=True,
            memory_hygiene_interval_hours=24,
            memory_hygiene_only_if_active=False,
            memory_hygiene_target_hour=-1,
            next_hygiene_run_at=now - timedelta(minutes=5),
            skill_review_enabled=False,
        )
        db_session.add(bot)
        await db_session.commit()

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_ENABLED = True
            mock_settings.MEMORY_HYGIENE_INTERVAL_HOURS = 24
            mock_settings.MEMORY_HYGIENE_ONLY_IF_ACTIVE = False
            mock_settings.MEMORY_HYGIENE_PROMPT = ""
            mock_settings.MEMORY_HYGIENE_MODEL = ""
            mock_settings.MEMORY_HYGIENE_MODEL_PROVIDER_ID = ""
            mock_settings.MEMORY_HYGIENE_TARGET_HOUR = -1
            mock_settings.SKILL_REVIEW_ENABLED = False
            await check_memory_hygiene()

        # Pending hygiene task should have been persisted
        tasks = (
            await db_session.execute(
                select(Task).where(Task.bot_id == bot.id, Task.task_type == "memory_hygiene")
            )
        ).scalars().all()
        assert len(tasks) == 1
        assert tasks[0].status == "pending"

        # Bot schedule advanced
        await db_session.refresh(bot)
        assert bot.last_hygiene_run_at is not None
        assert bot.next_hygiene_run_at > now

    @pytest.mark.asyncio
    async def test_when_bot_is_not_due_then_no_task_created(
        self, db_session, patched_async_sessions
    ):
        from app.services.memory_hygiene import check_memory_hygiene

        now = datetime.now(timezone.utc)
        bot = build_bot(
            id="not-due-bot",
            memory_scheme="workspace-files",
            memory_hygiene_enabled=True,
            memory_hygiene_interval_hours=24,
            memory_hygiene_only_if_active=False,
            memory_hygiene_target_hour=-1,
            next_hygiene_run_at=now + timedelta(hours=12),
            skill_review_enabled=False,
        )
        db_session.add(bot)
        await db_session.commit()

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_ENABLED = True
            mock_settings.MEMORY_HYGIENE_INTERVAL_HOURS = 24
            mock_settings.MEMORY_HYGIENE_ONLY_IF_ACTIVE = False
            mock_settings.MEMORY_HYGIENE_PROMPT = ""
            mock_settings.MEMORY_HYGIENE_TARGET_HOUR = -1
            mock_settings.SKILL_REVIEW_ENABLED = False
            await check_memory_hygiene()

        count = (
            await db_session.execute(
                select(Task).where(Task.bot_id == bot.id, Task.task_type == "memory_hygiene")
            )
        ).scalars().all()
        assert count == []

    @pytest.mark.asyncio
    async def test_when_bot_disabled_then_no_task_created(
        self, db_session, patched_async_sessions
    ):
        from app.services.memory_hygiene import check_memory_hygiene

        now = datetime.now(timezone.utc)
        bot = build_bot(
            id="disabled-bot",
            memory_scheme="workspace-files",
            memory_hygiene_enabled=False,
            memory_hygiene_interval_hours=24,
            next_hygiene_run_at=now - timedelta(hours=1),
            skill_review_enabled=False,
        )
        db_session.add(bot)
        await db_session.commit()

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_ENABLED = False
            mock_settings.MEMORY_HYGIENE_INTERVAL_HOURS = 24
            mock_settings.MEMORY_HYGIENE_ONLY_IF_ACTIVE = False
            mock_settings.MEMORY_HYGIENE_PROMPT = ""
            mock_settings.MEMORY_HYGIENE_TARGET_HOUR = -1
            mock_settings.SKILL_REVIEW_ENABLED = False
            await check_memory_hygiene()

        tasks = (
            await db_session.execute(
                select(Task).where(Task.bot_id == bot.id, Task.task_type == "memory_hygiene")
            )
        ).scalars().all()
        assert tasks == []

    @pytest.mark.asyncio
    async def test_when_dedup_finds_in_progress_task_then_no_new_task_created(
        self, db_session, patched_async_sessions
    ):
        from app.services.memory_hygiene import check_memory_hygiene

        now = datetime.now(timezone.utc)
        bot = build_bot(
            id="dedup-bot",
            memory_scheme="workspace-files",
            memory_hygiene_enabled=True,
            memory_hygiene_interval_hours=24,
            memory_hygiene_only_if_active=False,
            memory_hygiene_target_hour=-1,
            next_hygiene_run_at=now - timedelta(minutes=5),
            skill_review_enabled=False,
        )
        pre_existing = Task(
            id=uuid.uuid4(),
            bot_id=bot.id,
            prompt="prior run",
            task_type="memory_hygiene",
            status="pending",
            dispatch_type="none",
        )
        db_session.add_all([bot, pre_existing])
        await db_session.commit()

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_ENABLED = True
            mock_settings.MEMORY_HYGIENE_INTERVAL_HOURS = 24
            mock_settings.MEMORY_HYGIENE_ONLY_IF_ACTIVE = False
            mock_settings.MEMORY_HYGIENE_PROMPT = ""
            mock_settings.MEMORY_HYGIENE_TARGET_HOUR = -1
            mock_settings.SKILL_REVIEW_ENABLED = False
            await check_memory_hygiene()

        tasks = (
            await db_session.execute(
                select(Task).where(Task.bot_id == bot.id, Task.task_type == "memory_hygiene")
            )
        ).scalars().all()
        assert [t.id for t in tasks] == [pre_existing.id]

    @pytest.mark.asyncio
    async def test_when_only_if_active_and_no_activity_then_skipped_task_recorded(
        self, db_session, patched_async_sessions
    ):
        """Activity gate miss: skip task row is persisted so the Learning
        Center surfaces the decision instead of the cycle silently dropping."""
        from app.services.memory_hygiene import check_memory_hygiene

        now = datetime.now(timezone.utc)
        bot = build_bot(
            id="inactive-bot",
            memory_scheme="workspace-files",
            memory_hygiene_enabled=True,
            memory_hygiene_interval_hours=24,
            memory_hygiene_only_if_active=True,
            memory_hygiene_target_hour=-1,
            last_hygiene_run_at=now - timedelta(hours=25),
            next_hygiene_run_at=now - timedelta(minutes=5),
            skill_review_enabled=False,
        )
        db_session.add(bot)
        await db_session.commit()

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_ENABLED = True
            mock_settings.MEMORY_HYGIENE_INTERVAL_HOURS = 24
            mock_settings.MEMORY_HYGIENE_ONLY_IF_ACTIVE = True
            mock_settings.MEMORY_HYGIENE_PROMPT = ""
            mock_settings.MEMORY_HYGIENE_TARGET_HOUR = -1
            mock_settings.SKILL_REVIEW_ENABLED = False
            await check_memory_hygiene()

        tasks = (
            await db_session.execute(
                select(Task).where(Task.bot_id == bot.id, Task.task_type == "memory_hygiene")
            )
        ).scalars().all()
        assert len(tasks) == 1
        skip_task = tasks[0]
        assert skip_task.status == "skipped"
        assert skip_task.completed_at is not None
        assert "No user messages" in (skip_task.result or "")

        await db_session.refresh(bot)
        assert bot.next_hygiene_run_at > now


# ---------------------------------------------------------------------------
# Activity check — real DB (replaces SQL-string inspection)
# ---------------------------------------------------------------------------

class TestHasActivitySince:
    @pytest.mark.asyncio
    async def test_when_primary_channel_has_recent_user_message_then_returns_true(self, db_session):
        from app.services.memory_hygiene import _has_activity_since

        bot = build_bot(id="activity-bot-1")
        channel = build_channel(bot_id=bot.id)
        session = _build_session(bot_id=bot.id, channel_id=channel.id)
        msg = _build_user_message(session.id, minutes_ago=30)
        db_session.add_all([bot, channel, session, msg])
        await db_session.commit()

        since = datetime.now(timezone.utc) - timedelta(hours=24)
        assert await _has_activity_since(bot.id, since, db_session) is True

    @pytest.mark.asyncio
    async def test_when_no_messages_within_window_then_returns_false(self, db_session):
        from app.services.memory_hygiene import _has_activity_since

        bot = build_bot(id="activity-bot-2")
        channel = build_channel(bot_id=bot.id)
        session = _build_session(bot_id=bot.id, channel_id=channel.id)
        old_msg = _build_user_message(session.id, minutes_ago=60 * 48)  # 48 hours ago
        db_session.add_all([bot, channel, session, old_msg])
        await db_session.commit()

        since = datetime.now(timezone.utc) - timedelta(hours=24)
        assert await _has_activity_since(bot.id, since, db_session) is False

    @pytest.mark.asyncio
    async def test_when_message_only_in_member_channel_then_returns_true(self, db_session):
        """Behavioural replacement for the old SQL-string-inspection test.

        Bot A owns no active channels. Bot A is a ChannelBotMember of a
        channel owned by Bot B. A user message posted in that member channel
        must count as activity for Bot A.
        """
        from app.services.memory_hygiene import _has_activity_since

        owner_bot = build_bot(id="owner-bot")
        member_bot = build_bot(id="member-bot")
        channel = build_channel(bot_id=owner_bot.id)
        membership = build_channel_bot_member(channel_id=channel.id, bot_id=member_bot.id)
        session = _build_session(bot_id=owner_bot.id, channel_id=channel.id)
        msg = _build_user_message(session.id, minutes_ago=10)
        db_session.add_all([owner_bot, member_bot, channel, membership, session, msg])
        await db_session.commit()

        since = datetime.now(timezone.utc) - timedelta(hours=24)
        assert await _has_activity_since(member_bot.id, since, db_session) is True

    @pytest.mark.asyncio
    async def test_when_only_assistant_messages_exist_then_returns_false(self, db_session):
        """Only user messages count — assistant/system traffic alone does not."""
        from app.services.memory_hygiene import _has_activity_since

        bot = build_bot(id="assistant-only-bot")
        channel = build_channel(bot_id=bot.id)
        session = _build_session(bot_id=bot.id, channel_id=channel.id)
        assistant_msg = Message(
            id=uuid.uuid4(),
            session_id=session.id,
            role="assistant",
            content="hi there",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        db_session.add_all([bot, channel, session, assistant_msg])
        await db_session.commit()

        since = datetime.now(timezone.utc) - timedelta(hours=24)
        assert await _has_activity_since(bot.id, since, db_session) is False


# ---------------------------------------------------------------------------
# Bootstrap schedule — real DB
# ---------------------------------------------------------------------------

class TestBootstrapHygieneSchedule:
    @pytest.mark.asyncio
    async def test_when_no_target_hour_then_schedules_within_interval_window(self, db_session):
        from app.services.memory_hygiene import bootstrap_hygiene_schedule

        bot = build_bot(
            id="bootstrap-stagger-bot",
            memory_hygiene_interval_hours=12,
            memory_hygiene_target_hour=-1,
            next_hygiene_run_at=None,
        )
        db_session.add(bot)
        await db_session.commit()

        now = datetime.now(timezone.utc)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_INTERVAL_HOURS = 12
            mock_settings.MEMORY_HYGIENE_TARGET_HOUR = -1
            mock_settings.TIMEZONE = "America/New_York"
            await bootstrap_hygiene_schedule(bot, db_session)

        await db_session.refresh(bot)
        assert bot.next_hygiene_run_at is not None
        delta = bot.next_hygiene_run_at - now
        assert timedelta(0) <= delta < timedelta(hours=12)

    @pytest.mark.asyncio
    async def test_when_different_bot_ids_then_stagger_offsets_differ(self, db_session):
        from app.services.memory_hygiene import bootstrap_hygiene_schedule

        alpha = build_bot(
            id="alpha-bot",
            memory_hygiene_interval_hours=24,
            memory_hygiene_target_hour=-1,
            next_hygiene_run_at=None,
        )
        beta = build_bot(
            id="beta-bot",
            memory_hygiene_interval_hours=24,
            memory_hygiene_target_hour=-1,
            next_hygiene_run_at=None,
        )
        db_session.add_all([alpha, beta])
        await db_session.commit()

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_INTERVAL_HOURS = 24
            mock_settings.MEMORY_HYGIENE_TARGET_HOUR = -1
            mock_settings.TIMEZONE = "America/New_York"
            await bootstrap_hygiene_schedule(alpha, db_session)
            await bootstrap_hygiene_schedule(beta, db_session)

        await db_session.refresh(alpha)
        await db_session.refresh(beta)
        assert alpha.next_hygiene_run_at != beta.next_hygiene_run_at


class TestBootstrapWithTargetHour:
    @pytest.mark.asyncio
    async def test_when_target_hour_is_set_then_schedule_lands_on_that_hour(self, db_session):
        from app.services.memory_hygiene import bootstrap_hygiene_schedule

        tz = ZoneInfo("America/New_York")
        bot = build_bot(
            id="target-bot",
            memory_hygiene_interval_hours=24,
            memory_hygiene_target_hour=3,
            next_hygiene_run_at=None,
        )
        db_session.add(bot)
        await db_session.commit()

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_INTERVAL_HOURS = 24
            mock_settings.MEMORY_HYGIENE_TARGET_HOUR = -1
            mock_settings.TIMEZONE = "America/New_York"
            await bootstrap_hygiene_schedule(bot, db_session)

        await db_session.refresh(bot)
        assert bot.next_hygiene_run_at is not None
        local = bot.next_hygiene_run_at.astimezone(tz)
        assert local.hour == 3
        assert 0 <= local.minute < 60

    @pytest.mark.asyncio
    async def test_when_target_hour_disabled_then_falls_back_to_interval_stagger(self, db_session):
        from app.services.memory_hygiene import bootstrap_hygiene_schedule

        bot = build_bot(
            id="fallback-bot",
            memory_hygiene_interval_hours=12,
            memory_hygiene_target_hour=None,
            next_hygiene_run_at=None,
        )
        db_session.add(bot)
        await db_session.commit()

        now = datetime.now(timezone.utc)
        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_INTERVAL_HOURS = 12
            mock_settings.MEMORY_HYGIENE_TARGET_HOUR = -1
            mock_settings.TIMEZONE = "America/New_York"
            await bootstrap_hygiene_schedule(bot, db_session)

        await db_session.refresh(bot)
        delta = bot.next_hygiene_run_at - now
        assert timedelta(0) <= delta < timedelta(hours=12)


# ---------------------------------------------------------------------------
# Bot channel filter helper (SQL builder is the unit under test)
# ---------------------------------------------------------------------------

class TestBotChannelFilter:
    def test_produces_or_with_member_subquery(self):
        from app.services.channels import bot_channel_filter

        clause = bot_channel_filter("my-bot")
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "channel_bot_members" in compiled
        assert "OR" in compiled.upper()
        assert "my-bot" in compiled


# ---------------------------------------------------------------------------
# Prompt content (constants)
# ---------------------------------------------------------------------------

class TestHygienePromptContent:
    def test_maintenance_has_six_steps(self):
        from app.config import DEFAULT_MEMORY_HYGIENE_PROMPT
        for step_num in range(1, 7):
            assert f"## Step {step_num}" in DEFAULT_MEMORY_HYGIENE_PROMPT
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
        # Prompt guides bots to the idempotent single-call archive op
        # instead of the old per-file mkdir + move dance.
        assert 'operation="archive_older_than"' in DEFAULT_MEMORY_HYGIENE_PROMPT
        assert 'older_than_days=14' in DEFAULT_MEMORY_HYGIENE_PROMPT

    def test_maintenance_does_not_have_skill_hygiene(self):
        from app.config import DEFAULT_MEMORY_HYGIENE_PROMPT
        assert "Skill hygiene" not in DEFAULT_MEMORY_HYGIENE_PROMPT
        assert "prune_enrolled_skills" not in DEFAULT_MEMORY_HYGIENE_PROMPT


class TestSkillReviewPromptContent:
    def test_has_three_steps(self):
        from app.config import DEFAULT_SKILL_REVIEW_PROMPT
        for step_num in range(1, 4):
            assert f"## Step {step_num}" in DEFAULT_SKILL_REVIEW_PROMPT

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
# Pure helpers (no DB)
# ---------------------------------------------------------------------------

class TestStaggerOffset:
    def test_when_same_bot_id_called_twice_then_returns_same_offset(self):
        from app.services.memory_hygiene import _stagger_offset_minutes
        assert _stagger_offset_minutes("my-bot", 24) == _stagger_offset_minutes("my-bot", 24)

    def test_when_different_bot_ids_then_different_offsets(self):
        from app.services.memory_hygiene import _stagger_offset_minutes
        assert _stagger_offset_minutes("alpha-bot", 24) != _stagger_offset_minutes("beta-bot", 24)

    def test_when_called_then_offset_stays_within_full_interval_window(self):
        from app.services.memory_hygiene import _stagger_offset_minutes
        for bot_id in ["bot-a", "bot-b", "bot-c", "bot-d", "bot-e"]:
            offset = _stagger_offset_minutes(bot_id, 12)
            assert 0 <= offset < 12 * 60

    def test_when_interval_is_zero_then_offset_is_zero_not_division_error(self):
        from app.services.memory_hygiene import _stagger_offset_minutes
        assert _stagger_offset_minutes("bot-a", 0) == 0


class TestStaggerOffsetTargetMode:
    def test_when_target_mode_then_offset_fits_in_sixty_minute_window(self):
        from app.services.memory_hygiene import _stagger_offset_minutes
        for bot_id in ["bot-a", "bot-b", "bot-c", "bot-d", "bot-e"]:
            offset = _stagger_offset_minutes(bot_id, 24, target_mode=True)
            assert 0 <= offset < 60

    def test_when_target_mode_called_twice_then_deterministic(self):
        from app.services.memory_hygiene import _stagger_offset_minutes
        a = _stagger_offset_minutes("my-bot", 24, target_mode=True)
        b = _stagger_offset_minutes("my-bot", 24, target_mode=True)
        assert a == b

    def test_when_not_target_mode_then_window_is_full_interval(self):
        from app.services.memory_hygiene import _stagger_offset_minutes
        offset = _stagger_offset_minutes("bot-a", 24, target_mode=False)
        assert 0 <= offset < 1440


class TestNextTargetRun:
    def test_when_target_hour_later_today_then_bootstrap_schedules_today(self):
        from app.services.memory_hygiene import _next_target_run

        tz = ZoneInfo("America/New_York")
        now_local = datetime(2026, 4, 6, 1, 0, 0, tzinfo=tz)
        now_utc = now_local.astimezone(timezone.utc)

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.TIMEZONE = "America/New_York"
            result = _next_target_run("test-bot", 3, 24, now_utc, after_run=False)

        result_local = result.astimezone(tz)
        assert result_local.day == 6
        assert result_local.hour == 3
        assert 0 <= result_local.minute < 60

    def test_when_target_hour_already_passed_today_then_bootstrap_schedules_tomorrow(self):
        from app.services.memory_hygiene import _next_target_run

        tz = ZoneInfo("America/New_York")
        now_local = datetime(2026, 4, 6, 5, 0, 0, tzinfo=tz)
        now_utc = now_local.astimezone(timezone.utc)

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.TIMEZONE = "America/New_York"
            result = _next_target_run("test-bot", 3, 24, now_utc, after_run=False)

        result_local = result.astimezone(tz)
        assert result_local.day == 7
        assert result_local.hour == 3

    def test_when_run_completes_slightly_past_target_hour_then_next_run_is_tomorrow(self):
        """Regression: the ``earliest = now + interval_hours`` floor used to
        push runs completing just past the target hour two days out."""
        from app.services.memory_hygiene import _next_target_run

        tz = ZoneInfo("America/New_York")
        now_local = datetime(2026, 4, 6, 3, 30, 0, tzinfo=tz)
        now_utc = now_local.astimezone(timezone.utc)

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.TIMEZONE = "America/New_York"
            result = _next_target_run("test-bot", 3, 24, now_utc, after_run=True)

        result_local = result.astimezone(tz)
        assert result_local.day == 7
        assert result_local.hour == 3

    def test_when_run_completes_at_0436_target_04_then_next_is_tomorrow_04(self):
        """Regression: Bennie Bot finished at 04:36 on 2026-04-11 with
        target_hour=4 and interval=24. Expected next run: 04-12 at 04:XX."""
        from app.services.memory_hygiene import _next_target_run

        tz = ZoneInfo("America/New_York")
        now_local = datetime(2026, 4, 11, 4, 36, 9, tzinfo=tz)
        now_utc = now_local.astimezone(timezone.utc)

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.TIMEZONE = "America/New_York"
            result = _next_target_run("bennie-bot", 4, 24, now_utc, after_run=True)

        result_local = result.astimezone(tz)
        assert result_local.day == 12
        assert result_local.hour == 4

    def test_when_interval_is_48h_then_next_target_runs_two_days_out(self):
        from app.services.memory_hygiene import _next_target_run

        tz = ZoneInfo("America/New_York")
        now_local = datetime(2026, 4, 6, 4, 0, 0, tzinfo=tz)
        now_utc = now_local.astimezone(timezone.utc)

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.TIMEZONE = "America/New_York"
            result = _next_target_run("test-bot", 3, 48, now_utc, after_run=True)

        result_local = result.astimezone(tz)
        assert result_local.day == 8
        assert result_local.hour == 3

    def test_when_run_finishes_exactly_at_target_hour_then_next_runs_tomorrow(self):
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

    def test_when_run_finishes_before_target_hour_then_next_runs_today(self):
        from app.services.memory_hygiene import _next_target_run

        tz = ZoneInfo("America/New_York")
        now_local = datetime(2026, 4, 6, 1, 0, 0, tzinfo=tz)
        now_utc = now_local.astimezone(timezone.utc)

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.TIMEZONE = "America/New_York"
            result = _next_target_run("test-bot", 3, 24, now_utc, after_run=True)

        result_local = result.astimezone(tz)
        assert result_local.day == 6
        assert result_local.hour == 3

    def test_when_two_bots_at_same_target_hour_then_their_minutes_differ(self):
        from app.services.memory_hygiene import _next_target_run

        tz = ZoneInfo("America/New_York")
        now_local = datetime(2026, 4, 6, 1, 0, 0, tzinfo=tz)
        now_utc = now_local.astimezone(timezone.utc)

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.TIMEZONE = "America/New_York"
            r1 = _next_target_run("alpha-bot", 3, 24, now_utc)
            r2 = _next_target_run("beta-bot", 3, 24, now_utc)

        r1_local = r1.astimezone(tz)
        r2_local = r2.astimezone(tz)
        assert r1_local.day == r2_local.day
        assert r1_local.hour == r2_local.hour == 3
        assert r1_local.minute != r2_local.minute


class TestComputeNextRun:
    def test_when_target_hour_is_set_then_result_lands_on_that_hour(self):
        from app.services.memory_hygiene import _compute_next_run

        tz = ZoneInfo("America/New_York")
        now_local = datetime(2026, 4, 6, 1, 0, 0, tzinfo=tz)
        now_utc = now_local.astimezone(timezone.utc)

        bot = build_bot(memory_hygiene_interval_hours=24, memory_hygiene_target_hour=3)

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_INTERVAL_HOURS = 24
            mock_settings.MEMORY_HYGIENE_TARGET_HOUR = -1
            mock_settings.TIMEZONE = "America/New_York"
            result = _compute_next_run(bot, now_utc, after_run=True)

        assert result.astimezone(tz).hour == 3

    def test_when_target_hour_disabled_then_result_is_now_plus_interval(self):
        from app.services.memory_hygiene import _compute_next_run

        now_utc = datetime(2026, 4, 6, 5, 0, 0, tzinfo=timezone.utc)
        bot = build_bot(memory_hygiene_interval_hours=24, memory_hygiene_target_hour=None)

        with patch("app.services.memory_hygiene.settings") as mock_settings:
            mock_settings.MEMORY_HYGIENE_INTERVAL_HOURS = 24
            mock_settings.MEMORY_HYGIENE_TARGET_HOUR = -1
            mock_settings.TIMEZONE = "America/New_York"
            result = _compute_next_run(bot, now_utc)

        assert result == now_utc + timedelta(hours=24)


# ---------------------------------------------------------------------------
# Skill review resolve_config — pure helper with build_bot
# ---------------------------------------------------------------------------

class TestSkillReviewResolveConfig:
    def test_when_bot_has_no_workspace_files_then_skill_review_disabled(self):
        from app.services.memory_hygiene import resolve_config
        bot = build_bot(memory_scheme=None)
        cfg = resolve_config(bot, "skill_review")
        assert cfg.enabled is False

    def test_when_global_enabled_then_bot_without_override_inherits(self):
        from app.services.memory_hygiene import resolve_config
        bot = build_bot()
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

    def test_when_bot_enabled_overrides_global_disabled(self):
        from app.services.memory_hygiene import resolve_config
        bot = build_bot(
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

    def test_when_global_only_if_active_is_false_then_default_is_false(self):
        """Skill review defaults to only_if_active=False — skill rot is not activity-gated."""
        from app.services.memory_hygiene import resolve_config
        bot = build_bot()
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

    def test_when_bot_sets_extra_instructions_then_resolved_config_carries_them(self):
        from app.services.memory_hygiene import resolve_config
        bot = build_bot(skill_review_extra_instructions="Use firecrawl for research")
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
# Cross-job stagger — pure helper
# ---------------------------------------------------------------------------

class TestCrossJobStagger:
    def test_when_other_job_within_thirty_minutes_then_pushes_forward_one_hour(self):
        from app.services.memory_hygiene import _cross_job_stagger
        now = datetime(2026, 4, 15, 10, 0, 0, tzinfo=timezone.utc)
        bot = build_bot(next_hygiene_run_at=now + timedelta(minutes=10))

        result = _cross_job_stagger(bot, "skill_review", now)
        assert result == now + timedelta(minutes=60)

    def test_when_other_job_far_apart_then_no_push(self):
        from app.services.memory_hygiene import _cross_job_stagger
        now = datetime(2026, 4, 15, 10, 0, 0, tzinfo=timezone.utc)
        bot = build_bot(next_hygiene_run_at=now + timedelta(hours=2))

        assert _cross_job_stagger(bot, "skill_review", now) == now

    def test_when_other_job_not_scheduled_then_no_push(self):
        from app.services.memory_hygiene import _cross_job_stagger
        now = datetime(2026, 4, 15, 10, 0, 0, tzinfo=timezone.utc)
        bot = build_bot(next_hygiene_run_at=None)

        assert _cross_job_stagger(bot, "skill_review", now) == now


# ---------------------------------------------------------------------------
# Discovery audit snapshot — PG-specific SQL, mocks acceptable per E.1
# ---------------------------------------------------------------------------

class TestDiscoveryAuditSnapshot:
    """The snapshot's two SQL passes use PostgreSQL JSONB functions
    (``jsonb_to_recordset``, ``jsonb_array_elements_text``) that don't run on
    SQLite. We mock ``db.execute`` with side_effect to feed canned rows for
    each call (rank pass, suggestion pass, name lookup) and assert on the
    rendered markdown shape."""

    @staticmethod
    def _row(**kwargs):
        m = MagicMock()
        for k, v in kwargs.items():
            setattr(m, k, v)
        return m

    @staticmethod
    def _result(rows):
        r = MagicMock()
        r.all.return_value = rows
        return r

    def _make_db(self, rank_rows, sugg_rows, name_rows):
        db = MagicMock()
        # 3 calls: pass1 (rank), pass2 (suggestions), name lookup.
        # When both rank+suggestion are empty the function returns early
        # and never makes the name lookup call.
        results = [self._result(rank_rows), self._result(sugg_rows)]
        if rank_rows or sugg_rows:
            results.append(self._result(name_rows))
        db.execute = AsyncMock(side_effect=results)
        return db

    @pytest.mark.asyncio
    async def test_when_no_rank_or_suggestion_rows_then_returns_empty_string(self):
        from app.services.memory_hygiene import _build_discovery_audit_snapshot
        db = self._make_db(rank_rows=[], sugg_rows=[], name_rows=[])
        assert await _build_discovery_audit_snapshot("test-bot", db) == ""

    @pytest.mark.asyncio
    async def test_when_skill_ranked_but_rarely_fetched_then_appears_in_gap_section(self):
        from app.services.memory_hygiene import _build_discovery_audit_snapshot
        rank_rows = [
            self._row(skill_id="arch_linux", times_ranked=12,
                      times_fetched_after_rank=1, avg_similarity=0.48),
        ]
        name_rows = [self._row(id="arch_linux", name="Arch Linux setup")]
        db = self._make_db(rank_rows=rank_rows, sugg_rows=[], name_rows=name_rows)
        out = await _build_discovery_audit_snapshot("test-bot", db)

        assert "## Discovery Audit" in out
        assert "ranked relevant but rarely fetched" in out
        assert "`arch_linux` (Arch Linux setup)" in out
        assert "ranked 12x" in out
        assert "fetched 1x" in out
        assert "gap 11" in out
        assert "0.48" in out
        assert "repeatedly suggested" not in out

    @pytest.mark.asyncio
    async def test_when_skill_fetched_equals_ranked_then_dropped_from_gap_section(self):
        from app.services.memory_hygiene import _build_discovery_audit_snapshot
        rank_rows = [
            self._row(skill_id="sourdough", times_ranked=5,
                      times_fetched_after_rank=5, avg_similarity=0.62),
        ]
        db = self._make_db(rank_rows=rank_rows, sugg_rows=[], name_rows=[])
        assert await _build_discovery_audit_snapshot("test-bot", db) == ""

    @pytest.mark.asyncio
    async def test_when_suggestions_present_then_suggestion_section_renders_aggregated(self):
        from app.services.memory_hygiene import _build_discovery_audit_snapshot
        sugg_rows = [
            self._row(skill_id="gardening_basics", times_suggested=8),
            self._row(skill_id="home_lab_dns", times_suggested=6),
        ]
        name_rows = [
            self._row(id="gardening_basics", name="Gardening basics"),
            self._row(id="home_lab_dns", name="Home lab DNS"),
        ]
        db = self._make_db(rank_rows=[], sugg_rows=sugg_rows, name_rows=name_rows)
        out = await _build_discovery_audit_snapshot("test-bot", db)

        assert "Catalog skills repeatedly suggested but not enrolled" in out
        assert "`gardening_basics` (Gardening basics) — suggested 8x" in out
        assert "`home_lab_dns` (Home lab DNS) — suggested 6x" in out
        assert "ranked relevant but rarely fetched" not in out

    @pytest.mark.asyncio
    async def test_when_both_rank_and_suggestion_rows_present_then_both_sections_render(self):
        from app.services.memory_hygiene import _build_discovery_audit_snapshot
        rank_rows = [
            self._row(skill_id="weak_skill", times_ranked=10,
                      times_fetched_after_rank=2, avg_similarity=0.44),
        ]
        sugg_rows = [
            self._row(skill_id="useful_catalog", times_suggested=7),
        ]
        name_rows = [
            self._row(id="weak_skill", name="Weak skill"),
            self._row(id="useful_catalog", name="Useful catalog"),
        ]
        db = self._make_db(rank_rows=rank_rows, sugg_rows=sugg_rows, name_rows=name_rows)
        out = await _build_discovery_audit_snapshot("test-bot", db)

        assert "ranked relevant but rarely fetched" in out
        assert "Catalog skills repeatedly suggested" in out
        assert "weak_skill" in out
        assert "useful_catalog" in out

    @pytest.mark.asyncio
    async def test_when_skill_name_lookup_missing_then_renders_unknown_fallback(self):
        from app.services.memory_hygiene import _build_discovery_audit_snapshot
        rank_rows = [
            self._row(skill_id="ghost_skill", times_ranked=8,
                      times_fetched_after_rank=0, avg_similarity=0.50),
        ]
        db = self._make_db(rank_rows=rank_rows, sugg_rows=[], name_rows=[])
        out = await _build_discovery_audit_snapshot("test-bot", db)
        assert "`ghost_skill` ((unknown))" in out
        assert "gap 8" in out


class TestWorkingSetSnapshotEnrichment:
    """The Working Set snapshot must include category / stale / script_count
    for authored skills so the skill-review bot can skip the redundant
    `manage_bot_skill(action="list")` call seen in the 2026-04-23 trace.
    """

    @pytest.mark.asyncio
    async def test_authored_skill_reports_category_stale_scripts(
        self, db_session, patched_async_sessions,
    ):
        from app.services.memory_hygiene import _build_working_set_snapshot

        bot_id = "wstest"
        # Authored skill with frontmatter category and one script.
        body = (
            "---\n"
            "name: Authored Widget Skill\n"
            "category: troubleshooting\n"
            "---\n\n"
            "# Authored Widget Skill\n\n"
            "Actionable steps follow."
        )
        skill = build_bot_skill(
            bot_id=bot_id, name="widget-fixer", content=body,
            category="troubleshooting",
            scripts=[{"name": "noop", "description": "noop", "script": "pass"}],
        )
        db_session.add(skill)
        db_session.add(build_bot_skill_enrollment(
            bot_id=bot_id, skill_id=skill.id, source="authored",
        ))
        await db_session.commit()

        out = await _build_working_set_snapshot(bot_id, db_session)

        # Category from frontmatter, stale rendered lowercase boolean, scripts count.
        assert "category=troubleshooting" in out
        assert "stale=" in out
        assert "scripts=1" in out
        # The old guidance about `action="list"` redundancy appears.
        assert 'manage_bot_skill(action="list")' in out

    @pytest.mark.asyncio
    async def test_catalog_skill_skips_authored_only_fields(
        self, db_session, patched_async_sessions,
    ):
        from app.services.memory_hygiene import _build_working_set_snapshot

        bot_id = "wstest2"
        catalog = build_skill(id="skills/catalog_thing", name="Catalog Thing")
        db_session.add(catalog)
        db_session.add(build_bot_skill_enrollment(
            bot_id=bot_id, skill_id=catalog.id, source="fetched",
        ))
        await db_session.commit()

        out = await _build_working_set_snapshot(bot_id, db_session)

        # Catalog skills don't get category / stale / scripts embedded fields.
        # The line for the catalog skill should not carry them.
        catalog_line = next(
            line for line in out.splitlines()
            if "`skills/catalog_thing`" in line
        )
        assert "category=" not in catalog_line
        assert "stale=" not in catalog_line
        assert "scripts=" not in catalog_line


class TestInjectedSkillsSnapshot:
    """The snapshot inlines stable core-skill bodies into the task prompt so
    scheduled bots don't pay a full iteration re-hydrating them via
    ``get_skill()``."""

    @pytest.mark.asyncio
    async def test_renders_loaded_skills_with_headers_and_do_not_refetch_note(
        self, db_session,
    ):
        from app.services.memory_hygiene import _build_injected_skills_snapshot

        db_session.add(build_skill(
            id="workspace_files", name="Workspace Files",
            content="# Workspace Files\n\nBody A.",
        ))
        db_session.add(build_skill(
            id="context_mastery", name="Context Mastery",
            content="# Context Mastery\n\nBody B.",
        ))
        await db_session.commit()

        out = await _build_injected_skills_snapshot(
            ("workspace_files", "context_mastery"), db_session,
        )

        assert out.startswith("## Pre-Loaded Skills")
        assert "do NOT call `get_skill" in out
        assert "### Workspace Files (`workspace_files`)" in out
        assert "### Context Mastery (`context_mastery`)" in out
        assert "Body A." in out
        assert "Body B." in out

    @pytest.mark.asyncio
    async def test_missing_skill_is_skipped_without_breaking(
        self, db_session,
    ):
        from app.services.memory_hygiene import _build_injected_skills_snapshot

        db_session.add(build_skill(
            id="workspace_files", name="Workspace Files",
            content="present body",
        ))
        await db_session.commit()

        out = await _build_injected_skills_snapshot(
            ("workspace_files", "totally_missing_skill"), db_session,
        )

        assert "### Workspace Files (`workspace_files`)" in out
        assert "totally_missing_skill" not in out
        assert "present body" in out

    @pytest.mark.asyncio
    async def test_archived_skill_is_skipped(self, db_session):
        from datetime import datetime, timezone

        from app.services.memory_hygiene import _build_injected_skills_snapshot

        db_session.add(build_skill(
            id="was_retired", name="Retired Skill",
            content="retired body",
            archived_at=datetime.now(timezone.utc),
        ))
        await db_session.commit()

        out = await _build_injected_skills_snapshot(
            ("was_retired",), db_session,
        )

        assert out == ""

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty_string(self, db_session):
        from app.services.memory_hygiene import _build_injected_skills_snapshot
        assert await _build_injected_skills_snapshot((), db_session) == ""

    @pytest.mark.asyncio
    async def test_all_missing_returns_empty_string(self, db_session):
        """No loaded rows → no snapshot block. Caller can append unconditionally."""
        from app.services.memory_hygiene import _build_injected_skills_snapshot
        out = await _build_injected_skills_snapshot(
            ("nope_a", "nope_b"), db_session,
        )
        assert out == ""


class TestCreateHygieneTaskPreloadsSkills:
    """create_hygiene_task must inline the configured skill bodies for each
    job type, so the bot gets them at t=0 instead of spending iter 2 on
    parallel get_skill() calls."""

    @pytest.mark.asyncio
    async def test_memory_hygiene_task_inlines_core_skills(
        self, db_session, patched_async_sessions,
    ):
        from app.services.memory_hygiene import create_hygiene_task

        bot = build_bot(id="preload-bot-1", memory_scheme="workspace-files")
        db_session.add(bot)
        db_session.add(build_skill(
            id="workspace_files", name="Workspace Files",
            content="WF body present",
        ))
        db_session.add(build_skill(
            id="history_and_memory/memory_hygiene", name="Memory Hygiene",
            content="MH body present",
        ))
        db_session.add(build_skill(
            id="context_mastery", name="Context Mastery",
            content="CM body present",
        ))
        await db_session.commit()

        task_id = await create_hygiene_task(bot.id, db_session)

        task = (await db_session.execute(select(Task).where(Task.id == task_id))).scalar_one()
        assert "## Pre-Loaded Skills" in task.prompt
        assert "WF body present" in task.prompt
        assert "MH body present" in task.prompt
        assert "CM body present" in task.prompt
        # Injected skills sit before dynamic per-run snapshots.
        assert task.prompt.index("## Pre-Loaded Skills") < task.prompt.index("## Channels")

    @pytest.mark.asyncio
    async def test_skill_review_task_inlines_authoring_and_hygiene(
        self, db_session, patched_async_sessions,
    ):
        from app.services.memory_hygiene import create_hygiene_task

        bot = build_bot(id="preload-bot-2", memory_scheme="workspace-files")
        db_session.add(bot)
        db_session.add(build_skill(
            id="skill_authoring", name="Skill Authoring",
            content="SA body present",
        ))
        db_session.add(build_skill(
            id="history_and_memory/memory_hygiene", name="Memory Hygiene",
            content="MH body present",
        ))
        await db_session.commit()

        task_id = await create_hygiene_task(bot.id, db_session, job_type="skill_review")

        task = (await db_session.execute(select(Task).where(Task.id == task_id))).scalar_one()
        assert "## Pre-Loaded Skills" in task.prompt
        assert "SA body present" in task.prompt
        assert "MH body present" in task.prompt

    @pytest.mark.asyncio
    async def test_task_still_creates_when_core_skills_absent_from_db(
        self, db_session, patched_async_sessions,
    ):
        """A fresh DB where the core skills haven't been seeded must not
        break hygiene — the snapshot resolves to empty and the task is
        created normally."""
        from app.services.memory_hygiene import create_hygiene_task

        bot = build_bot(id="preload-bot-3", memory_scheme="workspace-files")
        db_session.add(bot)
        await db_session.commit()

        task_id = await create_hygiene_task(bot.id, db_session)

        task = (await db_session.execute(select(Task).where(Task.id == task_id))).scalar_one()
        assert task.status == "pending"
        # The static prompt mentions "## Pre-Loaded Skills" in its tool-
        # discipline bullet, so we can't assert on the header alone. The
        # rendered snapshot's descriptive paragraph only appears when
        # bodies actually load, so that's the clean signal.
        assert "The full bodies of these skills are inlined below" not in task.prompt
