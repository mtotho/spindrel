"""Integration tests for app.agent.tasks — task scheduling, execution, fetch_due_tasks."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig
from app.db.models import Message, Session, Task
from tests.integration.conftest import engine, db_session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bot(**overrides) -> BotConfig:
    defaults = dict(
        id="test-bot", name="Test Bot", model="test/model",
        system_prompt="System prompt.",
        memory=MemoryConfig(enabled=False),
        knowledge=KnowledgeConfig(enabled=False),
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


# ---------------------------------------------------------------------------
# _spawn_from_schedule
# ---------------------------------------------------------------------------

class TestSpawnFromSchedule:
    @pytest.mark.asyncio
    async def test_spawns_concrete_task(self, engine):
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        schedule_id = uuid.uuid4()
        scheduled_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        async with factory() as db:
            sid = uuid.uuid4()
            db.add(Session(id=sid, client_id="c", bot_id="test-bot"))
            db.add(Task(
                id=schedule_id, bot_id="test-bot", client_id="c", session_id=sid,
                prompt="do something", status="active", recurrence="+1h",
                scheduled_at=scheduled_at,
                dispatch_type="none",
            ))
            await db.commit()

        with patch("app.agent.tasks.async_session", factory):
            from app.agent.tasks import _spawn_from_schedule
            await _spawn_from_schedule(schedule_id)

        async with factory() as db:
            # Check concrete task was created
            result = await db.execute(
                select(Task).where(Task.parent_task_id == schedule_id)
            )
            child = result.scalar_one_or_none()
            assert child is not None
            assert child.status == "pending"
            assert child.recurrence is None  # concrete, not schedule
            assert child.bot_id == "test-bot"
            assert child.scheduled_at is not None

            # Check schedule was advanced
            schedule = await db.get(Task, schedule_id)
            assert schedule.status == "active"
            assert schedule.run_count == 1
            # scheduled_at should have advanced by 1 hour
            assert schedule.scheduled_at is not None

    @pytest.mark.asyncio
    async def test_invalid_recurrence_skips(self, engine):
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        schedule_id = uuid.uuid4()
        async with factory() as db:
            sid = uuid.uuid4()
            db.add(Session(id=sid, client_id="c", bot_id="test-bot"))
            db.add(Task(
                id=schedule_id, bot_id="test-bot", client_id="c", session_id=sid,
                prompt="do something", status="active", recurrence="invalid",
                dispatch_type="none",
            ))
            await db.commit()

        with patch("app.agent.tasks.async_session", factory):
            from app.agent.tasks import _spawn_from_schedule
            await _spawn_from_schedule(schedule_id)

        async with factory() as db:
            result = await db.execute(
                select(Task).where(Task.parent_task_id == schedule_id)
            )
            assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_non_active_schedule_skips(self, engine):
        """Cancelled schedules should not spawn tasks."""
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        schedule_id = uuid.uuid4()
        async with factory() as db:
            sid = uuid.uuid4()
            db.add(Session(id=sid, client_id="c", bot_id="test-bot"))
            db.add(Task(
                id=schedule_id, bot_id="test-bot", client_id="c", session_id=sid,
                prompt="cancelled", status="cancelled", recurrence="+1h",
                dispatch_type="none",
            ))
            await db.commit()

        with patch("app.agent.tasks.async_session", factory):
            from app.agent.tasks import _spawn_from_schedule
            await _spawn_from_schedule(schedule_id)

        async with factory() as db:
            result = await db.execute(
                select(Task).where(Task.parent_task_id == schedule_id)
            )
            assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_multiple_spawns_increment_run_count(self, engine):
        """Multiple calls increment run_count correctly."""
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        schedule_id = uuid.uuid4()
        base_time = datetime.now(timezone.utc) - timedelta(hours=3)
        async with factory() as db:
            sid = uuid.uuid4()
            db.add(Session(id=sid, client_id="c", bot_id="test-bot"))
            db.add(Task(
                id=schedule_id, bot_id="test-bot", client_id="c", session_id=sid,
                prompt="recurring", status="active", recurrence="+1h",
                scheduled_at=base_time,
                dispatch_type="none",
            ))
            await db.commit()

        with patch("app.agent.tasks.async_session", factory):
            from app.agent.tasks import _spawn_from_schedule
            await _spawn_from_schedule(schedule_id)
            await _spawn_from_schedule(schedule_id)
            await _spawn_from_schedule(schedule_id)

        async with factory() as db:
            schedule = await db.get(Task, schedule_id)
            assert schedule.run_count == 3

            result = await db.execute(
                select(Task).where(Task.parent_task_id == schedule_id)
            )
            children = result.scalars().all()
            assert len(children) == 3
            # All children should be pending one-off tasks
            for child in children:
                assert child.status == "pending"
                assert child.recurrence is None


# ---------------------------------------------------------------------------
# spawn_due_schedules
# ---------------------------------------------------------------------------

class TestSpawnDueSchedules:
    @pytest.mark.asyncio
    async def test_spawns_due_schedules(self, engine):
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        now = datetime.now(timezone.utc)

        async with factory() as db:
            sid = uuid.uuid4()
            db.add(Session(id=sid, client_id="c", bot_id="test-bot"))

            # Due schedule (scheduled_at in past)
            db.add(Task(
                bot_id="test-bot", client_id="c", session_id=sid,
                prompt="due-schedule", status="active", recurrence="+1h",
                scheduled_at=now - timedelta(minutes=5),
                dispatch_type="none",
            ))
            # Future schedule (should not be picked up)
            db.add(Task(
                bot_id="test-bot", client_id="c", session_id=sid,
                prompt="future-schedule", status="active", recurrence="+1h",
                scheduled_at=now + timedelta(hours=1),
                dispatch_type="none",
            ))
            # Regular pending task (not a schedule, should not be affected)
            db.add(Task(
                bot_id="test-bot", client_id="c", session_id=sid,
                prompt="regular-pending", status="pending",
                scheduled_at=now - timedelta(minutes=5),
                dispatch_type="none",
            ))
            await db.commit()

        with patch("app.agent.tasks.async_session", factory):
            from app.agent.tasks import spawn_due_schedules
            await spawn_due_schedules()

        async with factory() as db:
            # Should have spawned 1 concrete task from the due schedule
            all_tasks = (await db.execute(select(Task))).scalars().all()
            concrete = [t for t in all_tasks if t.parent_task_id is not None]
            assert len(concrete) == 1
            assert concrete[0].prompt == "due-schedule"
            assert concrete[0].status == "pending"
            assert concrete[0].recurrence is None

    @pytest.mark.asyncio
    async def test_does_not_pick_up_non_active(self, engine):
        """Only active schedules should be processed."""
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        now = datetime.now(timezone.utc)

        async with factory() as db:
            sid = uuid.uuid4()
            db.add(Session(id=sid, client_id="c", bot_id="test-bot"))
            # Cancelled schedule
            db.add(Task(
                bot_id="test-bot", client_id="c", session_id=sid,
                prompt="cancelled-sched", status="cancelled", recurrence="+1h",
                scheduled_at=now - timedelta(minutes=5),
                dispatch_type="none",
            ))
            # Pending task (not active, no recurrence)
            db.add(Task(
                bot_id="test-bot", client_id="c", session_id=sid,
                prompt="regular-pending", status="pending",
                scheduled_at=now - timedelta(minutes=5),
                dispatch_type="none",
            ))
            await db.commit()

        with patch("app.agent.tasks.async_session", factory):
            from app.agent.tasks import spawn_due_schedules
            await spawn_due_schedules()

        async with factory() as db:
            all_tasks = (await db.execute(select(Task))).scalars().all()
            concrete = [t for t in all_tasks if t.parent_task_id is not None]
            assert len(concrete) == 0


# ---------------------------------------------------------------------------
# fetch_due_tasks
# ---------------------------------------------------------------------------

class TestFetchDueTasks:
    @pytest.mark.asyncio
    async def test_returns_pending_due_tasks(self, engine):
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        now = datetime.now(timezone.utc)

        async with factory() as db:
            sid = uuid.uuid4()
            db.add(Session(id=sid, client_id="c", bot_id="test-bot"))

            db.add(Task(
                bot_id="test-bot", session_id=sid, prompt="due",
                status="pending", scheduled_at=now - timedelta(minutes=5),
                dispatch_type="none",
            ))
            db.add(Task(
                bot_id="test-bot", session_id=sid, prompt="future",
                status="pending", scheduled_at=now + timedelta(hours=1),
                dispatch_type="none",
            ))
            db.add(Task(
                bot_id="test-bot", session_id=sid, prompt="done",
                status="complete", scheduled_at=now - timedelta(minutes=10),
                dispatch_type="none",
            ))
            db.add(Task(
                bot_id="test-bot", session_id=sid, prompt="null-sched",
                status="pending",
                dispatch_type="none",
            ))
            await db.commit()

        with patch("app.agent.tasks.async_session", factory):
            from app.agent.tasks import fetch_due_tasks
            due = await fetch_due_tasks()

        prompts = [t.prompt for t in due]
        assert "due" in prompts
        assert "null-sched" in prompts
        assert "future" not in prompts
        assert "done" not in prompts

    @pytest.mark.asyncio
    async def test_active_schedules_not_fetched_as_due(self, engine):
        """Active schedule templates should NOT be picked up by fetch_due_tasks."""
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        now = datetime.now(timezone.utc)

        async with factory() as db:
            sid = uuid.uuid4()
            db.add(Session(id=sid, client_id="c", bot_id="test-bot"))
            db.add(Task(
                bot_id="test-bot", session_id=sid, prompt="schedule",
                status="active", recurrence="+1h",
                scheduled_at=now - timedelta(minutes=5),
                dispatch_type="none",
            ))
            await db.commit()

        with patch("app.agent.tasks.async_session", factory):
            from app.agent.tasks import fetch_due_tasks
            due = await fetch_due_tasks()

        # Active schedules should never appear in fetch_due_tasks
        assert len(due) == 0

    @pytest.mark.asyncio
    async def test_limits_to_20(self, engine):
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        now = datetime.now(timezone.utc)

        async with factory() as db:
            sid = uuid.uuid4()
            db.add(Session(id=sid, client_id="c", bot_id="test-bot"))
            for i in range(25):
                db.add(Task(
                    bot_id="test-bot", session_id=sid, prompt=f"task-{i}",
                    status="pending", scheduled_at=now - timedelta(minutes=1),
                    dispatch_type="none",
                ))
            await db.commit()

        with patch("app.agent.tasks.async_session", factory):
            from app.agent.tasks import fetch_due_tasks
            due = await fetch_due_tasks()

        assert len(due) <= 20


# ---------------------------------------------------------------------------
# run_task (orchestration)
# ---------------------------------------------------------------------------

class TestRunTask:
    @pytest.mark.asyncio
    async def test_success_flow(self, engine):
        """Task runs agent, stores result, marks complete."""
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        bot = _bot()

        task_id = uuid.uuid4()
        sid = uuid.uuid4()
        async with factory() as db:
            db.add(Session(id=sid, client_id="task", bot_id="test-bot"))
            db.add(Message(session_id=sid, role="system", content="System prompt."))
            db.add(Task(
                id=task_id, bot_id="test-bot", client_id="task", session_id=sid,
                prompt="Say hello", status="pending", dispatch_type="none",
            ))
            await db.commit()

        async with factory() as db:
            task = await db.get(Task, task_id)

        from app.agent.loop import RunResult
        mock_run_result = RunResult(response="Hello!", transcript="", client_actions=[])

        mock_dispatcher = MagicMock()
        mock_dispatcher.deliver = AsyncMock()

        with (
            patch("app.agent.tasks.async_session", factory),
            patch("app.agent.tasks.get_bot", return_value=bot),
            patch("app.agent.tasks.session_locks") as mock_locks,
            # These are deferred imports inside run_task — patch at source
            patch("app.agent.loop.run", new_callable=AsyncMock, return_value=mock_run_result),
            patch("app.agent.persona.get_persona", new_callable=AsyncMock, return_value=None),
            patch("app.services.sessions.load_or_create", new_callable=AsyncMock, return_value=(sid, [{"role": "system", "content": "sp"}])),
            patch("app.services.sessions.persist_turn", new_callable=AsyncMock),
            patch("app.agent.tasks.dispatchers") as mock_dispatchers,
        ):
            mock_locks.acquire.return_value = True
            mock_dispatchers.get.return_value = mock_dispatcher
            from app.agent.tasks import run_task
            await run_task(task)

        async with factory() as db:
            t = await db.get(Task, task_id)
            assert t.status == "complete"
            assert t.result == "Hello!"
            assert t.completed_at is not None

    @pytest.mark.asyncio
    async def test_error_marks_failed(self, engine):
        """Task that raises marks status as failed."""
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        bot = _bot()

        task_id = uuid.uuid4()
        sid = uuid.uuid4()
        async with factory() as db:
            db.add(Session(id=sid, client_id="task", bot_id="test-bot"))
            db.add(Task(
                id=task_id, bot_id="test-bot", client_id="task", session_id=sid,
                prompt="fail", status="pending", dispatch_type="none",
            ))
            await db.commit()

        async with factory() as db:
            task = await db.get(Task, task_id)

        with (
            patch("app.agent.tasks.async_session", factory),
            patch("app.agent.tasks.get_bot", return_value=bot),
            patch("app.agent.tasks.session_locks") as mock_locks,
            patch("app.agent.loop.run", new_callable=AsyncMock, side_effect=RuntimeError("LLM crashed")),
            patch("app.agent.persona.get_persona", new_callable=AsyncMock, return_value=None),
            patch("app.services.sessions.load_or_create", new_callable=AsyncMock, return_value=(sid, [{"role": "system", "content": "sp"}])),
        ):
            mock_locks.acquire.return_value = True
            from app.agent.tasks import run_task
            await run_task(task)

        async with factory() as db:
            t = await db.get(Task, task_id)
            assert t.status == "failed"
            assert "LLM crashed" in t.error

    @pytest.mark.asyncio
    async def test_rate_limit_reschedules(self, engine):
        """RateLimitError reschedules with exponential backoff."""
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        bot = _bot()

        task_id = uuid.uuid4()
        sid = uuid.uuid4()
        async with factory() as db:
            db.add(Session(id=sid, client_id="task", bot_id="test-bot"))
            db.add(Task(
                id=task_id, bot_id="test-bot", client_id="task", session_id=sid,
                prompt="rate limit me", status="pending", dispatch_type="none",
            ))
            await db.commit()

        async with factory() as db:
            task = await db.get(Task, task_id)

        rate_error = openai.RateLimitError(
            message="rate limited", response=MagicMock(status_code=429), body=None,
        )

        with (
            patch("app.agent.tasks.async_session", factory),
            patch("app.agent.tasks.get_bot", return_value=bot),
            patch("app.agent.tasks.session_locks") as mock_locks,
            patch("app.agent.loop.run", new_callable=AsyncMock, side_effect=rate_error),
            patch("app.agent.persona.get_persona", new_callable=AsyncMock, return_value=None),
            patch("app.services.sessions.load_or_create", new_callable=AsyncMock, return_value=(sid, [{"role": "system", "content": "sp"}])),
            patch("app.agent.tasks.settings") as mock_settings,
        ):
            mock_locks.acquire.return_value = True
            mock_settings.TASK_RATE_LIMIT_RETRIES = 3
            mock_settings.LLM_RATE_LIMIT_INITIAL_WAIT = 60
            from app.agent.tasks import run_task
            await run_task(task)

        async with factory() as db:
            t = await db.get(Task, task_id)
            assert t.status == "pending"
            assert t.retry_count == 1
            assert "rate_limited" in t.error

    @pytest.mark.asyncio
    async def test_session_busy_defers(self, engine):
        """When session lock can't be acquired, task is deferred."""
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        task_id = uuid.uuid4()
        sid = uuid.uuid4()
        original_scheduled = datetime.now(timezone.utc)
        async with factory() as db:
            db.add(Session(id=sid, client_id="task", bot_id="test-bot"))
            db.add(Task(
                id=task_id, bot_id="test-bot", session_id=sid,
                prompt="deferred", status="pending", dispatch_type="none",
                scheduled_at=original_scheduled,
            ))
            await db.commit()

        async with factory() as db:
            task = await db.get(Task, task_id)

        with (
            patch("app.agent.tasks.async_session", factory),
            patch("app.agent.tasks.session_locks") as mock_locks,
        ):
            mock_locks.acquire.return_value = False
            from app.agent.tasks import run_task
            await run_task(task)

        async with factory() as db:
            t = await db.get(Task, task_id)
            # scheduled_at was updated (deferred by 10s)
            assert t.scheduled_at is not None
            assert t.scheduled_at != original_scheduled

    @pytest.mark.asyncio
    async def test_concrete_task_failure_does_not_break_schedule(self, engine):
        """A concrete task failing should not affect the parent schedule template."""
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        bot = _bot()

        schedule_id = uuid.uuid4()
        task_id = uuid.uuid4()
        sid = uuid.uuid4()
        next_run = datetime.now(timezone.utc) + timedelta(hours=1)

        async with factory() as db:
            db.add(Session(id=sid, client_id="task", bot_id="test-bot"))
            # The schedule template
            db.add(Task(
                id=schedule_id, bot_id="test-bot", client_id="task", session_id=sid,
                prompt="recurring work", status="active", recurrence="+1h",
                scheduled_at=next_run, dispatch_type="none",
            ))
            # A concrete task spawned from it
            db.add(Task(
                id=task_id, bot_id="test-bot", client_id="task", session_id=sid,
                prompt="recurring work", status="pending", recurrence=None,
                parent_task_id=schedule_id, dispatch_type="none",
            ))
            await db.commit()

        async with factory() as db:
            task = await db.get(Task, task_id)

        with (
            patch("app.agent.tasks.async_session", factory),
            patch("app.agent.tasks.get_bot", return_value=bot),
            patch("app.agent.tasks.session_locks") as mock_locks,
            patch("app.agent.loop.run", new_callable=AsyncMock, side_effect=RuntimeError("boom")),
            patch("app.agent.persona.get_persona", new_callable=AsyncMock, return_value=None),
            patch("app.services.sessions.load_or_create", new_callable=AsyncMock, return_value=(sid, [{"role": "system", "content": "sp"}])),
        ):
            mock_locks.acquire.return_value = True
            from app.agent.tasks import run_task
            await run_task(task)

        async with factory() as db:
            # Concrete task failed
            t = await db.get(Task, task_id)
            assert t.status == "failed"

            # Schedule template should be unaffected
            schedule = await db.get(Task, schedule_id)
            assert schedule.status == "active"
            assert schedule.recurrence == "+1h"
            # SQLite strips tz, just compare naive values
            assert schedule.scheduled_at.replace(tzinfo=None) == next_run.replace(tzinfo=None)
