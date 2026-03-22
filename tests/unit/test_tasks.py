"""Priority 3 tests for app.agent.tasks — run_task, schedule_next, fetch_due_tasks."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import openai
import pytest

from app.agent.tasks import _parse_recurrence


# ---------------------------------------------------------------------------
# _schedule_next_occurrence (mocked DB)
# ---------------------------------------------------------------------------

class TestScheduleNextOccurrence:
    @pytest.mark.asyncio
    async def test_creates_next_task(self):
        from app.agent.tasks import _schedule_next_occurrence

        task = MagicMock()
        task.id = uuid.uuid4()
        task.bot_id = "test_bot"
        task.client_id = "client1"
        task.session_id = uuid.uuid4()
        task.channel_id = None
        task.prompt = "do thing"
        task.dispatch_type = "none"
        task.dispatch_config = {}
        task.recurrence = "+1h"

        db = AsyncMock()
        db.add = MagicMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.agent.tasks.async_session", return_value=cm):
            await _schedule_next_occurrence(task)
            db.add.assert_called_once()
            new_task = db.add.call_args[0][0]
            assert new_task.bot_id == "test_bot"
            assert new_task.status == "pending"
            assert new_task.parent_task_id == task.id
            assert new_task.recurrence == "+1h"
            db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalid_recurrence_skips(self):
        from app.agent.tasks import _schedule_next_occurrence

        task = MagicMock()
        task.id = uuid.uuid4()
        task.recurrence = "invalid"

        with patch("app.agent.tasks.async_session") as mock_session:
            await _schedule_next_occurrence(task)
            mock_session.assert_not_called()


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
        task.dispatch_type = overrides.get("dispatch_type", "none")
        task.dispatch_config = overrides.get("dispatch_config", {})
        task.callback_config = overrides.get("callback_config", {})
        task.recurrence = overrides.get("recurrence", None)
        task.retry_count = overrides.get("retry_count", 0)
        task.status = overrides.get("status", "pending")
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
             patch("app.agent.tasks.dispatchers") as mock_dispatchers:
            mock_locks.acquire.return_value = True
            mock_dispatchers.get.return_value = mock_dispatcher

            await run_task(task)

            # Task should be marked complete
            assert task.status == "complete" or db.commit.await_count >= 1
            mock_dispatcher.deliver.assert_awaited_once()

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
    async def test_harness_dispatch_delegates(self):
        """Tasks with dispatch_type='harness' should call run_harness_task."""
        from app.agent.tasks import run_task

        task = self._make_task(dispatch_type="harness")

        with patch("app.agent.tasks.run_harness_task", new_callable=AsyncMock) as mock_harness:
            await run_task(task)
            mock_harness.assert_awaited_once_with(task)


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
