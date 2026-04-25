"""Tests for the Task.title field across backend layers."""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Agent tool: create_task with title
# ---------------------------------------------------------------------------
class TestCreateTaskTitle:
    @pytest.mark.asyncio
    @patch("app.tools.local.tasks.async_session")
    async def test_create_task_with_title(self, mock_session):
        from app.tools.local.tasks import schedule_prompt as create_task

        captured_task = {}

        async def _fake_commit():
            pass

        async def _fake_refresh(obj):
            obj.id = uuid.uuid4()
            obj.scheduled_at = None

        mock_db = AsyncMock()
        mock_db.add = MagicMock(side_effect=lambda t: captured_task.update({"title": t.title, "prompt": t.prompt}))
        mock_db.commit = _fake_commit
        mock_db.refresh = _fake_refresh
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_session.return_value = mock_db

        with patch("app.tools.local.tasks.current_bot_id") as mock_bot_id, \
             patch("app.tools.local.tasks.current_client_id") as mock_client_id, \
             patch("app.tools.local.tasks.current_session_id") as mock_session_id, \
             patch("app.tools.local.tasks.current_channel_id") as mock_channel_id, \
             patch("app.tools.local.tasks.current_dispatch_type") as mock_dt, \
             patch("app.tools.local.tasks.current_dispatch_config") as mock_dc:
            mock_bot_id.get.return_value = "test-bot"
            mock_client_id.get.return_value = "client-1"
            mock_session_id.get.return_value = uuid.uuid4()
            mock_channel_id.get.return_value = uuid.uuid4()
            mock_dt.get.return_value = "none"
            mock_dc.get.return_value = {}

            result = await create_task(prompt="Do something", title="My Task")

        assert captured_task["title"] == "My Task"
        assert captured_task["prompt"] == "Do something"
        parsed = json.loads(result)
        assert parsed["status"] == "pending"
        assert parsed["title"] == "My Task"

    @pytest.mark.asyncio
    @patch("app.tools.local.tasks.async_session")
    async def test_create_task_without_title(self, mock_session):
        from app.tools.local.tasks import schedule_prompt as create_task

        captured_task = {}

        mock_db = AsyncMock()
        mock_db.add = MagicMock(side_effect=lambda t: captured_task.update({"title": t.title}))
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "id", uuid.uuid4()))
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_session.return_value = mock_db

        with patch("app.tools.local.tasks.current_bot_id") as mock_bot_id, \
             patch("app.tools.local.tasks.current_client_id") as mock_client_id, \
             patch("app.tools.local.tasks.current_session_id") as mock_session_id, \
             patch("app.tools.local.tasks.current_channel_id") as mock_channel_id, \
             patch("app.tools.local.tasks.current_dispatch_type") as mock_dt, \
             patch("app.tools.local.tasks.current_dispatch_config") as mock_dc:
            mock_bot_id.get.return_value = "test-bot"
            mock_client_id.get.return_value = "client-1"
            mock_session_id.get.return_value = uuid.uuid4()
            mock_channel_id.get.return_value = uuid.uuid4()
            mock_dt.get.return_value = "none"
            mock_dc.get.return_value = {}

            result = await create_task(prompt="Do something")

        assert captured_task["title"] is None


# ---------------------------------------------------------------------------
# Agent tool: update_task with title
# ---------------------------------------------------------------------------
class TestUpdateTaskTitle:
    @pytest.mark.asyncio
    @patch("app.tools.local.tasks.async_session")
    async def test_update_task_title(self, mock_session):
        from app.tools.local.tasks import update_task

        task = MagicMock()
        task.id = uuid.uuid4()
        task.status = "pending"
        task.title = None
        task.prompt = "original"

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=task)
        mock_db.commit = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_session.return_value = mock_db

        result = await update_task(task_id=str(task.id), title="New Title")

        assert task.title == "New Title"
        assert "title updated" in result

    @pytest.mark.asyncio
    @patch("app.tools.local.tasks.async_session")
    async def test_update_task_clear_title(self, mock_session):
        from app.tools.local.tasks import update_task

        task = MagicMock()
        task.id = uuid.uuid4()
        task.status = "active"
        task.title = "Old Title"
        task.recurrence = "+1h"

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=task)
        mock_db.commit = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_session.return_value = mock_db

        result = await update_task(task_id=str(task.id), title=None)

        assert task.title is None
        assert "title updated" in result


# ---------------------------------------------------------------------------
# Agent tool: list_tasks includes title
# ---------------------------------------------------------------------------
class TestListTasksTitle:
    @pytest.mark.asyncio
    @patch("app.tools.local.tasks.async_session")
    async def test_detail_includes_title(self, mock_session):
        from app.tools.local.tasks import list_tasks

        task = MagicMock()
        task.id = uuid.uuid4()
        task.status = "complete"
        task.bot_id = "test-bot"
        task.title = "My Title"
        task.prompt = "Do stuff"
        task.scheduled_at = datetime(2026, 3, 26, tzinfo=timezone.utc)
        task.run_at = None
        task.completed_at = None
        task.dispatch_type = "none"
        task.recurrence = None
        task.run_count = 0
        task.prompt_template_id = None
        task.result = None
        task.error = None

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=task)
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_session.return_value = mock_db

        result = await list_tasks(task_id=str(task.id))
        data = json.loads(result)

        assert data["title"] == "My Title"

    @pytest.mark.asyncio
    @patch("app.tools.local.tasks.async_session")
    @patch("app.tools.local.tasks.current_session_id")
    @patch("app.tools.local.tasks.current_channel_id")
    async def test_list_shows_title_over_prompt(self, mock_channel, mock_session_cv, mock_session):
        from app.tools.local.tasks import list_tasks

        mock_channel.get.return_value = uuid.uuid4()
        mock_session_cv.get.return_value = uuid.uuid4()

        task = MagicMock()
        task.id = uuid.uuid4()
        task.status = "pending"
        task.bot_id = "test-bot"
        task.title = "Short Title"
        task.prompt = "A very long prompt that should not appear in the list output because there is a title"
        task.scheduled_at = datetime(2026, 3, 26, tzinfo=timezone.utc)
        task.run_at = None
        task.completed_at = None
        task.recurrence = None
        task.run_count = 0
        task.prompt_template_id = None
        task.result = None
        task.error = None
        task.channel_id = mock_channel.get.return_value
        task.session_id = mock_session_cv.get.return_value

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [task]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_session.return_value = mock_db

        result = await list_tasks()

        assert "Short Title" in result
        assert "A very long prompt" not in result


# ---------------------------------------------------------------------------
# _spawn_from_schedule copies title
# ---------------------------------------------------------------------------
class TestSpawnFromScheduleTitle:
    @pytest.mark.asyncio
    @patch("app.agent.tasks.async_session")
    async def test_spawn_copies_title(self, mock_session):
        from app.agent.tasks import _spawn_from_schedule

        schedule = MagicMock()
        schedule.id = uuid.uuid4()
        schedule.status = "active"
        schedule.recurrence = "+1h"
        schedule.title = "Hourly Check"
        schedule.prompt = "Check things"
        schedule.prompt_template_id = None
        schedule.bot_id = "test-bot"
        schedule.client_id = "c1"
        schedule.session_id = uuid.uuid4()
        schedule.channel_id = uuid.uuid4()
        schedule.task_type = "scheduled"
        schedule.dispatch_type = "none"
        schedule.dispatch_config = None
        schedule.callback_config = None
        schedule.scheduled_at = datetime(2026, 3, 26, 10, 0, tzinfo=timezone.utc)
        schedule.run_count = 0

        captured = {}

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=schedule)
        mock_db.add = MagicMock(side_effect=lambda t: captured.update({"title": t.title, "prompt": t.prompt}))
        mock_db.commit = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_session.return_value = mock_db

        await _spawn_from_schedule(schedule.id)

        assert captured["title"] == "Hourly Check"
        assert captured["prompt"] == "Check things"


# ---------------------------------------------------------------------------
# Admin API schema includes title
# ---------------------------------------------------------------------------
class TestAdminApiSchemas:
    def test_task_detail_out_includes_title(self):
        from app.routers.api_v1_admin.tasks import TaskDetailOut

        fields = TaskDetailOut.model_fields
        assert "title" in fields

    def test_task_create_in_includes_title(self):
        from app.routers.api_v1_admin.tasks import TaskCreateIn

        fields = TaskCreateIn.model_fields
        assert "title" in fields

    def test_task_update_in_includes_title(self):
        from app.routers.api_v1_admin.tasks import TaskUpdateIn

        fields = TaskUpdateIn.model_fields
        assert "title" in fields

    def test_create_payload_with_title(self):
        from app.routers.api_v1_admin.tasks import TaskCreateIn

        payload = TaskCreateIn(prompt="test", bot_id="bot1", title="My Task")
        assert payload.title == "My Task"

    def test_create_payload_without_title(self):
        from app.routers.api_v1_admin.tasks import TaskCreateIn

        payload = TaskCreateIn(prompt="test", bot_id="bot1")
        assert payload.title is None
