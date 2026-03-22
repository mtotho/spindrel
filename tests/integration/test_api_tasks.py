"""Integration tests for /api/v1/tasks endpoints."""
import uuid
from datetime import datetime, timezone

import pytest

from app.db.models import Task
from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


class TestGetTask:
    async def test_get_task(self, client, db_session):
        task = Task(
            id=uuid.uuid4(),
            bot_id="test-bot",
            prompt="Do something",
            status="completed",
            result="Done!",
            dispatch_type="none",
            created_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        db_session.add(task)
        await db_session.commit()

        resp = await client.get(
            f"/api/v1/tasks/{task.id}",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == str(task.id)
        assert body["status"] == "completed"
        assert body["result"] == "Done!"
        assert body["bot_id"] == "test-bot"
        assert body["prompt"] == "Do something"
        assert body["dispatch_type"] == "none"

    async def test_get_task_pending(self, client, db_session):
        task = Task(
            id=uuid.uuid4(),
            bot_id="test-bot",
            prompt="Pending task",
            status="pending",
            dispatch_type="none",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(task)
        await db_session.commit()

        resp = await client.get(f"/api/v1/tasks/{task.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "pending"
        assert body["result"] is None
        assert body["error"] is None
        assert body["run_at"] is None
        assert body["completed_at"] is None

    async def test_get_task_failed(self, client, db_session):
        task = Task(
            id=uuid.uuid4(),
            bot_id="test-bot",
            prompt="Failing task",
            status="failed",
            error="Something went wrong",
            dispatch_type="none",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(task)
        await db_session.commit()

        resp = await client.get(f"/api/v1/tasks/{task.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"
        assert resp.json()["error"] == "Something went wrong"

    async def test_get_task_not_found(self, client):
        resp = await client.get(
            f"/api/v1/tasks/{uuid.uuid4()}",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404
        assert "Task not found" in resp.json()["detail"]
