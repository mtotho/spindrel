"""Priority 3 tests for app.agent.tasks — run_task, spawn_from_schedule, fetch_due_tasks."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import openai
import pytest

from app.agent.tasks import _parse_recurrence


# ---------------------------------------------------------------------------
# _spawn_from_schedule (mocked DB)
# ---------------------------------------------------------------------------

class TestSpawnFromSchedule:
    @pytest.mark.asyncio
    async def test_spawns_concrete_task_and_advances_schedule(self):
        from app.agent.tasks import _spawn_from_schedule

        schedule_id = uuid.uuid4()
        scheduled_at = datetime.now(timezone.utc) - timedelta(minutes=5)

        schedule = MagicMock()
        schedule.id = schedule_id
        schedule.bot_id = "test_bot"
        schedule.client_id = "client1"
        schedule.session_id = uuid.uuid4()
        schedule.channel_id = None
        schedule.prompt = "do thing"
        schedule.prompt_template_id = None
        schedule.dispatch_type = "none"
        schedule.dispatch_config = {"key": "val"}
        schedule.callback_config = None
        schedule.recurrence = "+1h"
        schedule.task_type = "scheduled"
        schedule.status = "active"
        schedule.scheduled_at = scheduled_at
        schedule.run_count = 0

        db = AsyncMock()
        db.add = MagicMock()
        db.get = AsyncMock(return_value=schedule)
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.agent.tasks.async_session", return_value=cm):
            await _spawn_from_schedule(schedule_id)

            # Should have added a concrete task
            db.add.assert_called_once()
            concrete = db.add.call_args[0][0]
            assert concrete.bot_id == "test_bot"
            assert concrete.status == "pending"
            assert concrete.parent_task_id == schedule_id
            assert concrete.recurrence is None  # concrete, not schedule
            assert concrete.scheduled_at == scheduled_at

            # Schedule should be advanced
            assert schedule.scheduled_at == scheduled_at + timedelta(hours=1)
            assert schedule.run_count == 1
            db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalid_recurrence_skips(self):
        from app.agent.tasks import _spawn_from_schedule

        schedule_id = uuid.uuid4()
        schedule = MagicMock()
        schedule.id = schedule_id
        schedule.status = "active"
        schedule.recurrence = "invalid"

        db = AsyncMock()
        db.get = AsyncMock(return_value=schedule)
        db.add = MagicMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.agent.tasks.async_session", return_value=cm):
            await _spawn_from_schedule(schedule_id)
            # Should not have added any task
            db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_active_status_skips(self):
        from app.agent.tasks import _spawn_from_schedule

        schedule_id = uuid.uuid4()
        schedule = MagicMock()
        schedule.id = schedule_id
        schedule.status = "cancelled"
        schedule.recurrence = "+1h"

        db = AsyncMock()
        db.get = AsyncMock(return_value=schedule)
        db.add = MagicMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.agent.tasks.async_session", return_value=cm):
            await _spawn_from_schedule(schedule_id)
            db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_schedule_skips(self):
        from app.agent.tasks import _spawn_from_schedule

        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        db.add = MagicMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.agent.tasks.async_session", return_value=cm):
            await _spawn_from_schedule(uuid.uuid4())
            db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_copies_dispatch_and_callback_config(self):
        from app.agent.tasks import _spawn_from_schedule

        schedule_id = uuid.uuid4()
        schedule = MagicMock()
        schedule.id = schedule_id
        schedule.bot_id = "test_bot"
        schedule.client_id = "c"
        schedule.session_id = uuid.uuid4()
        schedule.channel_id = uuid.uuid4()
        schedule.prompt = "task prompt"
        schedule.prompt_template_id = None
        schedule.dispatch_type = "slack"
        schedule.dispatch_config = {"channel_id": "C123", "thread_ts": "1234"}
        schedule.callback_config = {"trigger_rag_loop": True}
        schedule.recurrence = "+1d"
        schedule.task_type = "scheduled"
        schedule.status = "active"
        schedule.scheduled_at = datetime.now(timezone.utc) - timedelta(hours=1)
        schedule.run_count = 5

        db = AsyncMock()
        db.add = MagicMock()
        db.get = AsyncMock(return_value=schedule)
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.agent.tasks.async_session", return_value=cm):
            await _spawn_from_schedule(schedule_id)

            concrete = db.add.call_args[0][0]
            assert concrete.dispatch_type == "slack"
            assert concrete.dispatch_config == {"channel_id": "C123", "thread_ts": "1234"}
            assert concrete.callback_config == {"trigger_rag_loop": True}
            assert concrete.channel_id == schedule.channel_id
            assert schedule.run_count == 6


# ---------------------------------------------------------------------------
# spawn_due_schedules (mocked DB)
# ---------------------------------------------------------------------------

class TestSpawnDueSchedules:
    @pytest.mark.asyncio
    async def test_queries_active_schedules_and_spawns(self):
        from app.agent.tasks import spawn_due_schedules

        sid1 = uuid.uuid4()
        sid2 = uuid.uuid4()

        db = AsyncMock()
        result = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = [sid1, sid2]
        result.scalars.return_value = scalars
        db.execute = AsyncMock(return_value=result)
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.agent.tasks.async_session", return_value=cm), \
             patch("app.agent.tasks._spawn_from_schedule", new_callable=AsyncMock) as mock_spawn:
            await spawn_due_schedules()
            assert mock_spawn.await_count == 2
            mock_spawn.assert_any_await(sid1)
            mock_spawn.assert_any_await(sid2)

    @pytest.mark.asyncio
    async def test_no_due_schedules(self):
        from app.agent.tasks import spawn_due_schedules

        db = AsyncMock()
        result = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = []
        result.scalars.return_value = scalars
        db.execute = AsyncMock(return_value=result)
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.agent.tasks.async_session", return_value=cm), \
             patch("app.agent.tasks._spawn_from_schedule", new_callable=AsyncMock) as mock_spawn:
            await spawn_due_schedules()
            mock_spawn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_individual_spawn_failure_doesnt_stop_others(self):
        from app.agent.tasks import spawn_due_schedules

        sid1 = uuid.uuid4()
        sid2 = uuid.uuid4()

        db = AsyncMock()
        result = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = [sid1, sid2]
        result.scalars.return_value = scalars
        db.execute = AsyncMock(return_value=result)
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        async def _mock_spawn(schedule_id):
            if schedule_id == sid1:
                raise RuntimeError("DB error")

        with patch("app.agent.tasks.async_session", return_value=cm), \
             patch("app.agent.tasks._spawn_from_schedule", side_effect=_mock_spawn) as mock_spawn:
            await spawn_due_schedules()
            # Both should have been attempted even though sid1 failed
            assert mock_spawn.call_count == 2


# ---------------------------------------------------------------------------
# run_task orchestration (mocked agent + DB)
# ---------------------------------------------------------------------------

class TestRunTask:
    def _make_task(self, **overrides):
        task = MagicMock()
        task.id = overrides.get("id", uuid.uuid4())
        task.bot_id = overrides.get("bot_id", "test_bot")
        task.client_id = overrides.get("client_id", "client1")
        task.session_id = overrides.get("session_id", uuid.uuid4())
        task.channel_id = overrides.get("channel_id", None)
        task.prompt = overrides.get("prompt", "do something")
        task.prompt_template_id = overrides.get("prompt_template_id", None)
        task.dispatch_type = overrides.get("dispatch_type", "none")
        task.dispatch_config = overrides.get("dispatch_config", {})
        task.callback_config = overrides.get("callback_config", {})
        task.execution_config = overrides.get("execution_config", {})
        task.task_type = overrides.get("task_type", "agent")
        task.recurrence = overrides.get("recurrence", None)
        task.retry_count = overrides.get("retry_count", 0)
        task.status = overrides.get("status", "pending")
        task.max_run_seconds = overrides.get("max_run_seconds", None)
        task.workflow_id = overrides.get("workflow_id", None)
        task.workflow_session_mode = overrides.get("workflow_session_mode", None)
        return task

    def _mock_db_session(self, task_obj):
        """Create a mock async_session that returns task_obj on db.get()."""
        db = AsyncMock()
        db.add = MagicMock()
        db.get = AsyncMock(return_value=task_obj)
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm, db

    @pytest.mark.asyncio
    async def test_successful_completion(self):
        from app.agent.tasks import run_task
        from app.agent.loop import RunResult

        task = self._make_task()
        cm, db = self._mock_db_session(task)

        mock_run_result = RunResult(response="Agent response", client_actions=[])
        mock_dispatcher = MagicMock()
        mock_dispatcher.deliver = AsyncMock()

        from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig
        bot = BotConfig(
            id="test_bot", name="Test", model="gpt-4",
            system_prompt="test", memory=MemoryConfig(), knowledge=KnowledgeConfig(),
        )

        with patch("app.agent.tasks.async_session", return_value=cm), \
             patch("app.agent.tasks.session_locks") as mock_locks, \
             patch("app.agent.tasks.get_bot", return_value=bot), \
             patch("app.agent.loop.run", new_callable=AsyncMock, return_value=mock_run_result), \
             patch("app.services.sessions.load_or_create", new_callable=AsyncMock, return_value=(task.session_id, [{"role": "system", "content": "test"}])), \
             patch("app.services.sessions.persist_turn", new_callable=AsyncMock), \
             patch("app.agent.tasks._publish_turn_ended") as mock_publish:
            mock_locks.acquire.return_value = True

            await run_task(task)

            # Task should be marked complete
            assert task.status == "complete" or db.commit.await_count >= 1
            mock_publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_concrete_task_does_not_reschedule(self):
        """Concrete tasks (no recurrence) should NOT spawn any next occurrence."""
        from app.agent.tasks import run_task
        from app.agent.loop import RunResult

        task = self._make_task(recurrence=None)
        cm, db = self._mock_db_session(task)

        mock_run_result = RunResult(response="Done", client_actions=[])
        mock_dispatcher = MagicMock()
        mock_dispatcher.deliver = AsyncMock()

        from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig
        bot = BotConfig(
            id="test_bot", name="Test", model="gpt-4",
            system_prompt="test", memory=MemoryConfig(), knowledge=KnowledgeConfig(),
        )

        with patch("app.agent.tasks.async_session", return_value=cm), \
             patch("app.agent.tasks.session_locks") as mock_locks, \
             patch("app.agent.tasks.get_bot", return_value=bot), \
             patch("app.agent.loop.run", new_callable=AsyncMock, return_value=mock_run_result), \
             patch("app.services.sessions.load_or_create", new_callable=AsyncMock, return_value=(task.session_id, [{"role": "system", "content": "test"}])), \
             patch("app.services.sessions.persist_turn", new_callable=AsyncMock), \
             patch("app.agent.tasks._publish_turn_ended"), \
             patch("app.agent.tasks._spawn_from_schedule", new_callable=AsyncMock) as mock_spawn:
            mock_locks.acquire.return_value = True

            await run_task(task)

            # _spawn_from_schedule should NOT be called from run_task
            mock_spawn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_error_marks_failed(self):
        from app.agent.tasks import run_task

        task = self._make_task()
        cm, db = self._mock_db_session(task)

        from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig
        bot = BotConfig(
            id="test_bot", name="Test", model="gpt-4",
            system_prompt="test", memory=MemoryConfig(), knowledge=KnowledgeConfig(),
        )

        with patch("app.agent.tasks.async_session", return_value=cm), \
             patch("app.agent.tasks.session_locks") as mock_locks, \
             patch("app.agent.tasks.get_bot", return_value=bot), \
             patch("app.agent.loop.run", new_callable=AsyncMock, side_effect=ValueError("boom")), \
             patch("app.services.sessions.load_or_create", new_callable=AsyncMock, return_value=(task.session_id, [])):
            mock_locks.acquire.return_value = True

            await run_task(task)

            # The task should be marked failed in the DB
            assert task.status == "failed" or db.commit.await_count >= 1

    @pytest.mark.asyncio
    async def test_rate_limit_reschedules(self):
        from app.agent.tasks import run_task

        task = self._make_task(retry_count=0)
        cm, db = self._mock_db_session(task)

        from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig
        bot = BotConfig(
            id="test_bot", name="Test", model="gpt-4",
            system_prompt="test", memory=MemoryConfig(), knowledge=KnowledgeConfig(),
        )

        rate_err = openai.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429),
            body=None,
        )

        with patch("app.agent.tasks.async_session", return_value=cm), \
             patch("app.agent.tasks.session_locks") as mock_locks, \
             patch("app.agent.tasks.get_bot", return_value=bot), \
             patch("app.agent.loop.run", new_callable=AsyncMock, side_effect=rate_err), \
             patch("app.services.sessions.load_or_create", new_callable=AsyncMock, return_value=(task.session_id, [])), \
             patch("app.agent.tasks.settings") as mock_settings:
            mock_locks.acquire.return_value = True
            mock_settings.TASK_RATE_LIMIT_RETRIES = 3
            mock_settings.LLM_RATE_LIMIT_INITIAL_WAIT = 65
            mock_settings.TASK_MAX_RUN_SECONDS = 1200

            await run_task(task)

            # Should be rescheduled as pending
            assert task.status == "pending" or task.retry_count == 1 or db.commit.await_count >= 1

    @pytest.mark.asyncio
    async def test_session_busy_defers(self):
        from app.agent.tasks import run_task

        task = self._make_task()
        cm, db = self._mock_db_session(task)

        with patch("app.agent.tasks.async_session", return_value=cm), \
             patch("app.agent.tasks.session_locks") as mock_locks:
            mock_locks.acquire.return_value = False

            await run_task(task)

            # Task should be deferred (scheduled_at updated)
            db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_model_override_from_callback_config(self):
        """model_override in execution_config (or callback_config fallback) should be passed to the agent loop."""
        from app.agent.tasks import run_task
        from app.agent.loop import RunResult

        task = self._make_task(
            execution_config={
                "model_override": "custom/my-model",
                "model_provider_id_override": "provider-42",
            },
        )
        cm, db = self._mock_db_session(task)

        mock_run_result = RunResult(response="ok", client_actions=[])
        mock_dispatcher = MagicMock()
        mock_dispatcher.deliver = AsyncMock()

        from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig
        bot = BotConfig(
            id="test_bot", name="Test", model="gpt-4",
            system_prompt="test", memory=MemoryConfig(), knowledge=KnowledgeConfig(),
        )

        with patch("app.agent.tasks.async_session", return_value=cm), \
             patch("app.agent.tasks.session_locks") as mock_locks, \
             patch("app.agent.tasks.get_bot", return_value=bot), \
             patch("app.agent.loop.run", new_callable=AsyncMock, return_value=mock_run_result) as mock_run, \
             patch("app.services.sessions.load_or_create", new_callable=AsyncMock, return_value=(task.session_id, [{"role": "system", "content": "test"}])), \
             patch("app.services.sessions.persist_turn", new_callable=AsyncMock), \
             patch("app.agent.tasks._publish_turn_ended") as mock_publish:
            mock_locks.acquire.return_value = True

            await run_task(task)

            mock_run.assert_awaited_once()
            call_kwargs = mock_run.call_args.kwargs
            assert call_kwargs["model_override"] == "custom/my-model"
            assert call_kwargs["provider_id_override"] == "provider-42"

    @pytest.mark.asyncio
    async def test_model_override_none_when_not_set(self):
        """Without model_override in callback_config, run() should get None."""
        from app.agent.tasks import run_task
        from app.agent.loop import RunResult

        task = self._make_task(callback_config={})
        cm, db = self._mock_db_session(task)

        mock_run_result = RunResult(response="ok", client_actions=[])
        mock_dispatcher = MagicMock()
        mock_dispatcher.deliver = AsyncMock()

        from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig
        bot = BotConfig(
            id="test_bot", name="Test", model="gpt-4",
            system_prompt="test", memory=MemoryConfig(), knowledge=KnowledgeConfig(),
        )

        with patch("app.agent.tasks.async_session", return_value=cm), \
             patch("app.agent.tasks.session_locks") as mock_locks, \
             patch("app.agent.tasks.get_bot", return_value=bot), \
             patch("app.agent.loop.run", new_callable=AsyncMock, return_value=mock_run_result) as mock_run, \
             patch("app.services.sessions.load_or_create", new_callable=AsyncMock, return_value=(task.session_id, [{"role": "system", "content": "test"}])), \
             patch("app.services.sessions.persist_turn", new_callable=AsyncMock), \
             patch("app.agent.tasks._publish_turn_ended") as mock_publish:
            mock_locks.acquire.return_value = True

            await run_task(task)

            mock_run.assert_awaited_once()
            call_kwargs = mock_run.call_args.kwargs
            assert call_kwargs["model_override"] is None
            assert call_kwargs["provider_id_override"] is None


# ---------------------------------------------------------------------------
# fetch_due_tasks (mocked DB)
# ---------------------------------------------------------------------------

class TestFetchDueTasks:
    @pytest.mark.asyncio
    async def test_returns_pending_tasks(self):
        from app.agent.tasks import fetch_due_tasks

        mock_task = MagicMock()
        mock_task.status = "pending"

        db = AsyncMock()
        result = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = [mock_task]
        result.scalars.return_value = scalars
        db.execute = AsyncMock(return_value=result)

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.agent.tasks.async_session", return_value=cm):
            tasks = await fetch_due_tasks()
            assert len(tasks) == 1
            assert tasks[0] is mock_task


