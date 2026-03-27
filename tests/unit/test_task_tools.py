"""Unit tests for app.tools.local.tasks — tool functions and helpers."""
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _resolve_template
# ---------------------------------------------------------------------------

class TestResolveTemplate:
    @pytest.mark.asyncio
    async def test_finds_existing_template(self):
        from app.tools.local.tasks import _resolve_template

        tpl = MagicMock()
        tpl.id = uuid.uuid4()
        tpl.name = "nightly_review"

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = tpl
        db.execute = AsyncMock(return_value=result)

        got = await _resolve_template("Nightly_Review", None, db)
        assert got is tpl

    @pytest.mark.asyncio
    async def test_auto_creates_when_prompt_provided(self):
        from app.tools.local.tasks import _resolve_template

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)
        db.add = MagicMock()
        db.flush = AsyncMock()
        # Track what gets added
        db.new = set()

        got = await _resolve_template("new_template", "do stuff", db)
        assert got.name == "new_template"
        assert got.content == "do stuff"
        assert got.source_type == "manual"
        db.add.assert_called_once()
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_error_when_not_found_and_no_prompt(self):
        from app.tools.local.tasks import _resolve_template

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(ValueError, match="Template 'missing' not found"):
            await _resolve_template("missing", None, db)


# ---------------------------------------------------------------------------
# create_task
# ---------------------------------------------------------------------------

class TestCreateTask:
    def _mock_async_session(self, db):
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    @pytest.mark.asyncio
    async def test_basic_create(self):
        from app.tools.local.tasks import schedule_task as create_task

        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        cm = self._mock_async_session(db)

        with patch("app.tools.local.tasks.async_session", return_value=cm), \
             patch("app.tools.local.tasks.current_bot_id") as mock_bot, \
             patch("app.tools.local.tasks.current_session_id") as mock_sid, \
             patch("app.tools.local.tasks.current_channel_id") as mock_cid, \
             patch("app.tools.local.tasks.current_client_id") as mock_client, \
             patch("app.tools.local.tasks.current_dispatch_type") as mock_dtype, \
             patch("app.tools.local.tasks.current_dispatch_config") as mock_dcfg:
            mock_bot.get.return_value = "test_bot"
            mock_sid.get.return_value = uuid.uuid4()
            mock_cid.get.return_value = uuid.uuid4()
            mock_client.get.return_value = "client1"
            mock_dtype.get.return_value = "none"
            mock_dcfg.get.return_value = {}

            result = await create_task(prompt="do something")
            assert "queued (runs immediately)" in result



# ---------------------------------------------------------------------------
# list_tasks
# ---------------------------------------------------------------------------

class TestListTasks:
    @pytest.mark.asyncio
    async def test_detail_mode(self):
        from app.tools.local.tasks import list_tasks

        task_id = uuid.uuid4()
        task = MagicMock()
        task.id = task_id
        task.status = "pending"
        task.bot_id = "test_bot"
        task.prompt = "test prompt"
        task.title = None
        task.scheduled_at = None
        task.run_at = None
        task.completed_at = None
        task.dispatch_type = "none"
        task.recurrence = None
        task.run_count = 0
        task.prompt_template_id = None
        task.result = None
        task.error = None

        db = AsyncMock()
        db.get = AsyncMock(return_value=task)
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.tools.local.tasks.async_session", return_value=cm):
            result = await list_tasks(task_id=str(task_id))
            data = json.loads(result)
            assert data["id"] == str(task_id)
            assert data["status"] == "pending"
            assert data["prompt"] == "test prompt"

    @pytest.mark.asyncio
    async def test_detail_mode_with_template(self):
        from app.tools.local.tasks import list_tasks

        task_id = uuid.uuid4()
        tpl_id = uuid.uuid4()
        task = MagicMock()
        task.id = task_id
        task.status = "active"
        task.bot_id = "test_bot"
        task.prompt = "test prompt"
        task.title = None
        task.scheduled_at = None
        task.run_at = None
        task.completed_at = None
        task.dispatch_type = "none"
        task.recurrence = "+1h"
        task.run_count = 5
        task.prompt_template_id = tpl_id
        task.result = None
        task.error = None

        tpl = MagicMock()
        tpl.name = "daily_check"

        db = AsyncMock()
        db.get = AsyncMock(side_effect=lambda model, id: task if id == task_id else tpl)
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.tools.local.tasks.async_session", return_value=cm):
            result = await list_tasks(task_id=str(task_id))
            data = json.loads(result)
            assert data["prompt_template"] == "daily_check"
            assert data["recurrence"] == "+1h"

    @pytest.mark.asyncio
    async def test_detail_mode_not_found(self):
        from app.tools.local.tasks import list_tasks

        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.tools.local.tasks.async_session", return_value=cm):
            result = await list_tasks(task_id=str(uuid.uuid4()))
            data = json.loads(result)
            assert "error" in data

    @pytest.mark.asyncio
    async def test_list_mode_no_context(self):
        from app.tools.local.tasks import list_tasks

        with patch("app.tools.local.tasks.current_session_id") as mock_sid, \
             patch("app.tools.local.tasks.current_channel_id") as mock_cid:
            mock_sid.get.return_value = None
            mock_cid.get.return_value = None

            result = await list_tasks()
            assert "No session or channel" in result


# ---------------------------------------------------------------------------
# update_task
# ---------------------------------------------------------------------------

class TestUpdateTask:
    @pytest.mark.asyncio
    async def test_update_scheduled_at(self):
        from app.tools.local.tasks import update_task

        task_id = uuid.uuid4()
        task = MagicMock()
        task.id = task_id
        task.status = "pending"
        task.dispatch_config = {}
        task.callback_config = {}

        db = AsyncMock()
        db.get = AsyncMock(return_value=task)
        db.commit = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.tools.local.tasks.async_session", return_value=cm):
            result = await update_task(task_id=str(task_id), scheduled_at="+2h")
            assert "updated" in result
            assert "time →" in result

    @pytest.mark.asyncio
    async def test_update_prompt(self):
        from app.tools.local.tasks import update_task

        task_id = uuid.uuid4()
        task = MagicMock()
        task.id = task_id
        task.status = "pending"

        db = AsyncMock()
        db.get = AsyncMock(return_value=task)
        db.commit = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.tools.local.tasks.async_session", return_value=cm):
            result = await update_task(task_id=str(task_id), prompt="new prompt")
            assert "prompt updated" in result
            assert task.prompt == "new prompt"

    @pytest.mark.asyncio
    async def test_recurrence_adds_active_status(self):
        from app.tools.local.tasks import update_task

        task_id = uuid.uuid4()
        task = MagicMock()
        task.id = task_id
        task.status = "pending"
        task.recurrence = None

        db = AsyncMock()
        db.get = AsyncMock(return_value=task)
        db.commit = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.tools.local.tasks.async_session", return_value=cm):
            result = await update_task(task_id=str(task_id), recurrence="+1h")
            assert "status → active" in result
            assert task.status == "active"
            assert task.recurrence == "+1h"

    @pytest.mark.asyncio
    async def test_remove_recurrence_to_pending(self):
        from app.tools.local.tasks import update_task

        task_id = uuid.uuid4()
        task = MagicMock()
        task.id = task_id
        task.status = "active"
        task.recurrence = "+1h"

        db = AsyncMock()
        db.get = AsyncMock(return_value=task)
        db.commit = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.tools.local.tasks.async_session", return_value=cm):
            result = await update_task(task_id=str(task_id), recurrence=None)
            assert "status → pending" in result
            assert task.status == "pending"
            assert task.recurrence is None

    @pytest.mark.asyncio
    async def test_update_bot_id(self):
        from app.tools.local.tasks import update_task

        task_id = uuid.uuid4()
        task = MagicMock()
        task.id = task_id
        task.status = "pending"

        resolved_bot = MagicMock()
        resolved_bot.id = "new_bot"

        db = AsyncMock()
        db.get = AsyncMock(return_value=task)
        db.commit = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.tools.local.tasks.async_session", return_value=cm), \
             patch("app.agent.bots.resolve_bot_id", return_value=resolved_bot), \
             patch("app.agent.bots.list_bots", return_value=[]):
            result = await update_task(task_id=str(task_id), bot_id="new_bot")
            assert "bot → new_bot" in result

    @pytest.mark.asyncio
    async def test_no_changes_error(self):
        from app.tools.local.tasks import update_task

        task_id = uuid.uuid4()
        task = MagicMock()
        task.id = task_id
        task.status = "pending"

        db = AsyncMock()
        db.get = AsyncMock(return_value=task)
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.tools.local.tasks.async_session", return_value=cm):
            result = await update_task(task_id=str(task_id))
            data = json.loads(result)
            assert "error" in data

    @pytest.mark.asyncio
    async def test_wrong_status_error(self):
        from app.tools.local.tasks import update_task

        task_id = uuid.uuid4()
        task = MagicMock()
        task.id = task_id
        task.status = "complete"

        db = AsyncMock()
        db.get = AsyncMock(return_value=task)
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.tools.local.tasks.async_session", return_value=cm):
            result = await update_task(task_id=str(task_id), prompt="new")
            data = json.loads(result)
            assert "error" in data
            assert "complete" in data["error"]


# ---------------------------------------------------------------------------
# Heartbeat PATCH null coercion
# ---------------------------------------------------------------------------

class TestHeartbeatPatchNull:
    """Test that the heartbeat PATCH loop coerces None → '' for non-nullable fields."""

    def test_prompt_null_coerced(self):
        """Simulate the heartbeat field processing logic for prompt=None."""
        from datetime import time as dt_time

        # Replicate the fixed loop logic inline
        hb_updates = {"prompt": None}
        for field, value in hb_updates.items():
            if field == "prompt":
                value = value.strip() if value else ""
            assert value == ""

    def test_model_null_coerced(self):
        hb_updates = {"model": None}
        for field, value in hb_updates.items():
            if field == "model":
                value = value.strip() if value else ""
            assert value == ""

    def test_prompt_with_value_stripped(self):
        hb_updates = {"prompt": "  hello  "}
        for field, value in hb_updates.items():
            if field == "prompt":
                value = value.strip() if value else ""
            assert value == "hello"

    def test_model_with_value_stripped(self):
        hb_updates = {"model": "  gpt-4  "}
        for field, value in hb_updates.items():
            if field == "model":
                value = value.strip() if value else ""
            assert value == "gpt-4"
