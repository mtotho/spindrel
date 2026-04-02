"""Integration tests for workflow_run_id filter on task list endpoint."""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Session, Task
from tests.integration.conftest import AUTH_HEADERS, engine, db_session, client


@pytest.fixture
def run_id():
    return str(uuid.uuid4())


class TestWorkflowRunIdFilter:
    """GET /api/v1/admin/tasks?workflow_run_id=... filter."""

    @pytest.mark.asyncio
    async def test_filter_returns_matching_tasks(self, client, db_session, run_id):
        """Only tasks whose callback_config.workflow_run_id matches are returned."""
        sid = uuid.uuid4()
        db_session.add(Session(id=sid, client_id="c", bot_id="test-bot"))

        # Two tasks belonging to the workflow run
        t1_id = uuid.uuid4()
        t2_id = uuid.uuid4()
        db_session.add(Task(
            id=t1_id, bot_id="test-bot", session_id=sid,
            prompt="step-0", status="complete", dispatch_type="none",
            task_type="workflow",
            callback_config=({"workflow_run_id": run_id, "workflow_step_index": 0}),
        ))
        db_session.add(Task(
            id=t2_id, bot_id="test-bot", session_id=sid,
            prompt="step-1", status="running", dispatch_type="none",
            task_type="workflow",
            callback_config=({"workflow_run_id": run_id, "workflow_step_index": 1}),
        ))

        # Unrelated task
        db_session.add(Task(
            bot_id="test-bot", session_id=sid,
            prompt="unrelated", status="pending", dispatch_type="none",
        ))
        await db_session.commit()

        resp = await client.get(
            f"/api/v1/admin/tasks?workflow_run_id={run_id}",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        task_ids = {t["id"] for t in data["tasks"]}
        assert str(t1_id) in task_ids
        assert str(t2_id) in task_ids
        assert len(data["tasks"]) == 2

    @pytest.mark.asyncio
    async def test_filter_nonexistent_returns_empty(self, client, db_session):
        """Non-existent workflow_run_id returns no tasks."""
        sid = uuid.uuid4()
        db_session.add(Session(id=sid, client_id="c", bot_id="test-bot"))
        db_session.add(Task(
            bot_id="test-bot", session_id=sid,
            prompt="some task", status="pending", dispatch_type="none",
            callback_config=({"workflow_run_id": str(uuid.uuid4())}),
        ))
        await db_session.commit()

        fake_id = str(uuid.uuid4())
        resp = await client.get(
            f"/api/v1/admin/tasks?workflow_run_id={fake_id}",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tasks"]) == 0

    @pytest.mark.asyncio
    async def test_response_includes_workflow_fields(self, client, db_session, run_id):
        """workflow_run_id and workflow_step_index are surfaced in the response dict."""
        sid = uuid.uuid4()
        db_session.add(Session(id=sid, client_id="c", bot_id="test-bot"))
        db_session.add(Task(
            bot_id="test-bot", session_id=sid,
            prompt="wf-step", status="pending", dispatch_type="none",
            task_type="workflow",
            callback_config=({"workflow_run_id": run_id, "workflow_step_index": 2}),
        ))
        await db_session.commit()

        resp = await client.get(
            f"/api/v1/admin/tasks?workflow_run_id={run_id}",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        task = resp.json()["tasks"][0]
        assert task["workflow_run_id"] == run_id
        assert task["workflow_step_index"] == 2

    @pytest.mark.asyncio
    async def test_filter_includes_child_tasks(self, client, db_session, run_id):
        """workflow_run_id filter auto-includes child tasks (parent_task_id set)."""
        sid = uuid.uuid4()
        parent_id = uuid.uuid4()
        child_id = uuid.uuid4()
        db_session.add(Session(id=sid, client_id="c", bot_id="test-bot"))
        db_session.add(Task(
            id=parent_id, bot_id="test-bot", session_id=sid,
            prompt="parent", status="complete", dispatch_type="none",
            task_type="workflow",
            callback_config=({"workflow_run_id": run_id, "workflow_step_index": 0}),
        ))
        db_session.add(Task(
            id=child_id, bot_id="test-bot", session_id=sid,
            prompt="child", status="pending", dispatch_type="none",
            task_type="workflow",
            parent_task_id=parent_id,
            callback_config=({"workflow_run_id": run_id, "workflow_step_index": 0}),
        ))
        await db_session.commit()

        resp = await client.get(
            f"/api/v1/admin/tasks?workflow_run_id={run_id}",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        task_ids = {t["id"] for t in resp.json()["tasks"]}
        assert str(parent_id) in task_ids
        assert str(child_id) in task_ids
