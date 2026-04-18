"""Integration tests for POST /api/v1/admin/tasks/{id}/steps/{i}/resolve
and for /tasks/{id}/run params support (Phase 1 + 2a plumbing)."""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import Task
from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


def _pipeline_with_user_prompt() -> list[dict]:
    return [
        {
            "id": "gate",
            "type": "user_prompt",
            "widget_template": {"kind": "review"},
            "widget_args": {},
            "response_schema": {"type": "binary"},
        }
    ]


class TestResolveEndpoint:
    async def test_happy_path_fills_result_and_schedules_resume(self, client, db_session):
        task_id = uuid.uuid4()
        task = Task(
            id=task_id,
            bot_id="test-bot",
            prompt="[pipeline]",
            status="running",
            task_type="pipeline",
            dispatch_type="none",
            steps=_pipeline_with_user_prompt(),
            step_states=[{
                "status": "awaiting_user_input",
                "widget_envelope": {"template": {}, "args": {}, "title": None},
                "response_schema": {"type": "binary"},
                "result": None,
                "error": None,
            }],
        )
        db_session.add(task)
        await db_session.commit()

        # The endpoint dispatches the resume via safe_create_task so the HTTP
        # request returns immediately — long apply phases (foreach over many
        # call_api sub-steps) used to block the connection synchronously.
        # Patch safe_create_task to capture the scheduled coroutine without
        # actually running it (no event loop drift, no fresh-session races).
        scheduled = []

        def _capture(coro, *, name=""):
            scheduled.append((coro, name))
            coro.close()  # don't leak a never-awaited coroutine warning

            class _DummyTask:
                def add_done_callback(self, _cb): pass
            return _DummyTask()

        with patch(
            "app.routers.api_v1_admin.tasks.safe_create_task", side_effect=_capture
        ):
            resp = await client.post(
                f"/api/v1/admin/tasks/{task_id}/steps/0/resolve",
                json={"response": {"decision": "approve"}},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        step = body["step_states"][0]
        assert step["status"] == "done"
        # result is intentionally serialized to a JSON string — the admin editor
        # UI reads stepState.result with .slice() and crashes on raw dicts.
        # See app/routers/api_v1_admin/tasks.py:855-857.
        assert json.loads(step["result"]) == {"decision": "approve"}
        # Background resume scheduled exactly once with the right name.
        assert len(scheduled) == 1
        assert scheduled[0][1] == f"resolve-resume-{task_id}"

    async def test_404_on_unknown_task(self, client):
        resp = await client.post(
            f"/api/v1/admin/tasks/{uuid.uuid4()}/steps/0/resolve",
            json={"response": {"decision": "approve"}},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404

    async def test_404_on_out_of_range_step(self, client, db_session):
        task_id = uuid.uuid4()
        task = Task(
            id=task_id, bot_id="test-bot", prompt="p", status="running",
            task_type="pipeline", dispatch_type="none",
            steps=_pipeline_with_user_prompt(),
            step_states=[{"status": "awaiting_user_input", "response_schema": {"type": "binary"}}],
        )
        db_session.add(task)
        await db_session.commit()

        resp = await client.post(
            f"/api/v1/admin/tasks/{task_id}/steps/99/resolve",
            json={"response": {"decision": "approve"}},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404

    async def test_409_when_not_awaiting(self, client, db_session):
        task_id = uuid.uuid4()
        task = Task(
            id=task_id, bot_id="test-bot", prompt="p", status="running",
            task_type="pipeline", dispatch_type="none",
            steps=_pipeline_with_user_prompt(),
            step_states=[{"status": "done", "result": {"decision": "approve"}}],
        )
        db_session.add(task)
        await db_session.commit()

        resp = await client.post(
            f"/api/v1/admin/tasks/{task_id}/steps/0/resolve",
            json={"response": {"decision": "approve"}},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 409

    async def test_422_on_schema_violation(self, client, db_session):
        task_id = uuid.uuid4()
        task = Task(
            id=task_id, bot_id="test-bot", prompt="p", status="running",
            task_type="pipeline", dispatch_type="none",
            steps=_pipeline_with_user_prompt(),
            step_states=[{
                "status": "awaiting_user_input",
                "response_schema": {"type": "binary"},
                "widget_envelope": {},
            }],
        )
        db_session.add(task)
        await db_session.commit()

        resp = await client.post(
            f"/api/v1/admin/tasks/{task_id}/steps/0/resolve",
            json={"response": {"decision": "maybe"}},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 422


class TestRunWithParams:
    async def test_run_accepts_params_and_merges(self, client, db_session):
        task_id = uuid.uuid4()
        parent = Task(
            id=task_id,
            bot_id="test-bot",
            prompt="pipeline",
            task_type="pipeline",
            dispatch_type="none",
            status="ready",
            steps=[{"id": "s1", "type": "exec", "prompt": "echo {{params.bot_id}}"}],
            execution_config={"params": {"bot_id": "seed"}},
        )
        db_session.add(parent)
        await db_session.commit()

        resp = await client.post(
            f"/api/v1/admin/tasks/{task_id}/run",
            json={"params": {"bot_id": "default"}},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["execution_config"]["params"]["bot_id"] == "default"
        assert body["parent_task_id"] == str(task_id)

    async def test_run_without_body_still_works(self, client, db_session):
        task_id = uuid.uuid4()
        parent = Task(
            id=task_id, bot_id="test-bot", prompt="p", task_type="pipeline",
            dispatch_type="none", status="ready",
            steps=[{"id": "s1", "type": "exec", "prompt": "echo hi"}],
        )
        db_session.add(parent)
        await db_session.commit()

        resp = await client.post(
            f"/api/v1/admin/tasks/{task_id}/run",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 201, resp.text
