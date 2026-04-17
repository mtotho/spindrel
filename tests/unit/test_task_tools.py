"""Unit tests for app.tools.local.tasks — tool functions and helpers.

Every DB-touching test here uses the real SQLite `db_session` fixture plus
`patched_async_sessions` to redirect the module-level `async_session` alias
at the test engine. `agent_context` sets the per-turn ContextVars that the
tool entry points read.

Kept out of scope: fuzzy bot resolution (`resolve_bot_id`) runs against an
in-memory registry, not the DB. Patching it is a legitimate external-dep
seam per SKILL.md E.1.
"""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from app.db.models import PromptTemplate, Task
from app.tools.local.tasks import (
    _resolve_template,
    list_tasks,
    schedule_task,
    update_task,
)
from tests.factories import build_prompt_template, build_task


class TestResolveTemplate:
    @pytest.mark.asyncio
    async def test_when_template_exists_then_returns_existing_row(self, db_session):
        tpl = build_prompt_template(name="nightly_review")
        db_session.add(tpl)
        await db_session.commit()

        got = await _resolve_template("Nightly_Review", None, db_session)

        assert got.id == tpl.id
        assert got.name == "nightly_review"

    @pytest.mark.asyncio
    async def test_when_missing_and_prompt_provided_then_auto_creates_manual_template(self, db_session):
        got = await _resolve_template("new_template", "do stuff", db_session)
        await db_session.commit()

        row = (
            await db_session.execute(
                select(PromptTemplate).where(PromptTemplate.name == "new_template")
            )
        ).scalar_one()
        assert row.id == got.id
        assert row.content == "do stuff"
        assert row.source_type == "manual"

    @pytest.mark.asyncio
    async def test_when_missing_and_no_prompt_then_raises_value_error(self, db_session):
        with pytest.raises(ValueError, match="Template 'missing' not found"):
            await _resolve_template("missing", None, db_session)


class TestScheduleTask:
    @pytest.mark.asyncio
    async def test_when_scheduling_task_with_bot_context_then_persists_pending_scheduled_task(
        self, db_session, patched_async_sessions, agent_context
    ):
        agent_context(
            bot_id="test_bot",
            session_id=uuid.uuid4(),
            channel_id=uuid.uuid4(),
            client_id="client1",
            dispatch_type="none",
            dispatch_config={},
        )

        result = json.loads(await schedule_task(prompt="do something"))

        assert {k: result[k] for k in ("status", "task_type", "bot_id")} == {
            "status": "pending",
            "task_type": "scheduled",
            "bot_id": "test_bot",
        }
        row = (
            await db_session.execute(select(Task).where(Task.id == uuid.UUID(result["id"])))
        ).scalar_one()
        assert row.bot_id == "test_bot"
        assert row.prompt == "do something"
        assert row.status == "pending"

    @pytest.mark.asyncio
    async def test_when_no_prompt_or_steps_or_workspace_file_then_returns_error(
        self, patched_async_sessions, agent_context
    ):
        agent_context(bot_id="test_bot")

        result = json.loads(await schedule_task())

        assert "error" in result
        assert "prompt" in result["error"]


class TestListTasksDetailMode:
    @pytest.mark.asyncio
    async def test_when_task_exists_then_returns_detail_payload(
        self, db_session, patched_async_sessions
    ):
        task = build_task(
            bot_id="test_bot",
            status="pending",
            task_type="scheduled",
            prompt="test prompt",
        )
        db_session.add(task)
        await db_session.commit()

        data = json.loads(await list_tasks(task_id=str(task.id)))

        assert {
            "id": data["id"],
            "status": data["status"],
            "task_type": data["task_type"],
            "prompt": data["prompt"],
        } == {
            "id": str(task.id),
            "status": "pending",
            "task_type": "scheduled",
            "prompt": "test prompt",
        }

    @pytest.mark.asyncio
    async def test_when_task_linked_to_template_then_includes_template_name_and_recurrence(
        self, db_session, patched_async_sessions
    ):
        tpl = build_prompt_template(name="daily_check")
        task = build_task(
            status="active",
            prompt_template_id=tpl.id,
            recurrence="+1h",
            run_count=5,
        )
        db_session.add_all([tpl, task])
        await db_session.commit()

        data = json.loads(await list_tasks(task_id=str(task.id)))

        assert data["prompt_template"] == "daily_check"
        assert data["recurrence"] == "+1h"
        assert data["run_count"] == 5

    @pytest.mark.asyncio
    async def test_when_task_id_not_found_then_returns_error(
        self, patched_async_sessions
    ):
        data = json.loads(await list_tasks(task_id=str(uuid.uuid4())))

        assert "error" in data
        assert "not found" in data["error"]

    @pytest.mark.asyncio
    async def test_when_task_id_malformed_then_returns_error(
        self, patched_async_sessions
    ):
        data = json.loads(await list_tasks(task_id="not-a-uuid"))

        assert "error" in data
        assert "Invalid task_id" in data["error"]


class TestListTasksListMode:
    @pytest.mark.asyncio
    async def test_when_no_tasks_exist_then_returns_empty_list_with_message(
        self, patched_async_sessions, agent_context
    ):
        agent_context(bot_id=None, session_id=None, channel_id=None)

        data = json.loads(await list_tasks())

        assert data == {
            "tasks": [],
            "message": (
                "No pending/running/active tasks. "
                "Use include_completed=true to see completed/failed tasks."
            ),
        }

    @pytest.mark.asyncio
    async def test_when_pending_tasks_exist_then_returns_them_hiding_internals(
        self, db_session, patched_async_sessions, agent_context
    ):
        agent_context(bot_id=None)
        visible = build_task(
            bot_id="test_bot",
            status="pending",
            task_type="scheduled",
            title="Visible task",
        )
        internal = build_task(
            bot_id="test_bot",
            status="pending",
            task_type="callback",
            title="Internal",
        )
        db_session.add_all([visible, internal])
        await db_session.commit()

        data = json.loads(await list_tasks())

        assert data["count"] == 1
        assert data["tasks"][0]["id"] == str(visible.id)


class TestUpdateTask:
    @pytest.mark.asyncio
    async def test_when_updating_scheduled_at_then_sets_new_time_and_persists(
        self, db_session, patched_async_sessions
    ):
        task = build_task(status="pending")
        db_session.add(task)
        await db_session.commit()

        before = datetime.now(timezone.utc)
        result = await update_task(task_id=str(task.id), scheduled_at="+2h")

        assert "time →" in result
        await db_session.refresh(task)
        assert task.scheduled_at is not None
        assert task.scheduled_at > before

    @pytest.mark.asyncio
    async def test_when_updating_prompt_then_replaces_prompt_text(
        self, db_session, patched_async_sessions
    ):
        task = build_task(status="pending", prompt="old")
        db_session.add(task)
        await db_session.commit()

        result = await update_task(task_id=str(task.id), prompt="new prompt")

        assert "prompt updated" in result
        await db_session.refresh(task)
        assert task.prompt == "new prompt"

    @pytest.mark.asyncio
    async def test_when_adding_recurrence_to_pending_task_then_status_flips_to_active(
        self, db_session, patched_async_sessions
    ):
        task = build_task(status="pending", recurrence=None)
        db_session.add(task)
        await db_session.commit()

        result = await update_task(task_id=str(task.id), recurrence="+1h")

        assert "status → active" in result
        await db_session.refresh(task)
        assert task.status == "active"
        assert task.recurrence == "+1h"

    @pytest.mark.asyncio
    async def test_when_clearing_recurrence_on_active_task_then_status_flips_to_pending(
        self, db_session, patched_async_sessions
    ):
        task = build_task(status="active", recurrence="+1h")
        db_session.add(task)
        await db_session.commit()

        result = await update_task(task_id=str(task.id), recurrence=None)

        assert "status → pending" in result
        await db_session.refresh(task)
        assert task.status == "pending"
        assert task.recurrence is None

    @pytest.mark.asyncio
    async def test_when_changing_bot_id_to_resolved_bot_then_row_bot_id_updates(
        self, db_session, patched_async_sessions
    ):
        task = build_task(status="pending", bot_id="old_bot")
        db_session.add(task)
        await db_session.commit()

        resolved = MagicMock()
        resolved.id = "new_bot"
        with patch("app.agent.bots.resolve_bot_id", return_value=resolved), \
             patch("app.agent.bots.list_bots", return_value=[]):
            result = await update_task(task_id=str(task.id), bot_id="new_bot")

        assert "bot → new_bot" in result
        await db_session.refresh(task)
        assert task.bot_id == "new_bot"

    @pytest.mark.asyncio
    async def test_when_no_fields_provided_then_returns_error(
        self, db_session, patched_async_sessions
    ):
        task = build_task(status="pending")
        db_session.add(task)
        await db_session.commit()

        data = json.loads(await update_task(task_id=str(task.id)))

        assert "error" in data
        assert "at least one field" in data["error"]

    @pytest.mark.asyncio
    async def test_when_task_is_complete_then_update_returns_error(
        self, db_session, patched_async_sessions
    ):
        task = build_task(status="complete")
        db_session.add(task)
        await db_session.commit()

        data = json.loads(await update_task(task_id=str(task.id), prompt="new"))

        assert "error" in data
        assert "complete" in data["error"]
