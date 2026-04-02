"""Integration tests for GET /api/v1/admin/tasks — schedule classification."""
import uuid
from datetime import datetime, timezone, timedelta

import pytest

from app.db.models import Task
from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


async def _create_task(db_session, **kwargs):
    defaults = {
        "id": uuid.uuid4(),
        "bot_id": "test-bot",
        "prompt": "test",
        "dispatch_type": "none",
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(kwargs)
    task = Task(**defaults)
    db_session.add(task)
    await db_session.commit()
    return task


class TestAdminTaskListScheduleClassification:
    """Disabled (cancelled) schedules must appear in the 'schedules' response,
    not vanish into the concrete tasks list."""

    async def test_active_schedule_in_schedules(self, client, db_session):
        sched = await _create_task(
            db_session,
            status="active",
            recurrence="+1h",
            scheduled_at=datetime.now(timezone.utc),
        )
        resp = await client.get("/api/v1/admin/tasks", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        sched_ids = [s["id"] for s in body["schedules"]]
        task_ids = [t["id"] for t in body["tasks"]]
        assert str(sched.id) in sched_ids
        assert str(sched.id) not in task_ids

    async def test_cancelled_schedule_in_schedules(self, client, db_session):
        """A disabled schedule (cancelled + recurrence) should still be in schedules."""
        sched = await _create_task(
            db_session,
            status="cancelled",
            recurrence="+1h",
            scheduled_at=datetime.now(timezone.utc),
        )
        resp = await client.get("/api/v1/admin/tasks", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        sched_ids = [s["id"] for s in body["schedules"]]
        task_ids = [t["id"] for t in body["tasks"]]
        assert str(sched.id) in sched_ids, "Disabled schedule should appear in schedules list"
        assert str(sched.id) not in task_ids, "Disabled schedule should NOT appear in tasks list"

    async def test_cancelled_task_without_recurrence_in_tasks(self, client, db_session):
        """A cancelled concrete task (no recurrence) should be in tasks, not schedules."""
        task = await _create_task(
            db_session,
            status="cancelled",
            recurrence=None,
        )
        resp = await client.get("/api/v1/admin/tasks", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        sched_ids = [s["id"] for s in body["schedules"]]
        task_ids = [t["id"] for t in body["tasks"]]
        assert str(task.id) in task_ids
        assert str(task.id) not in sched_ids

    async def test_total_excludes_schedule_templates(self, client, db_session):
        """The total count should only count concrete tasks, not schedule templates."""
        await _create_task(db_session, status="active", recurrence="+1h",
                           scheduled_at=datetime.now(timezone.utc))
        await _create_task(db_session, status="cancelled", recurrence="+2h",
                           scheduled_at=datetime.now(timezone.utc))
        await _create_task(db_session, status="pending")
        await _create_task(db_session, status="complete")

        resp = await client.get("/api/v1/admin/tasks", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2, "Total should count only concrete tasks (pending + complete)"
        assert len(body["schedules"]) == 2, "Both active and disabled schedules returned"

    async def test_bot_filter_applies_to_schedules(self, client, db_session):
        await _create_task(db_session, bot_id="bot-a", status="active", recurrence="+1h",
                           scheduled_at=datetime.now(timezone.utc))
        await _create_task(db_session, bot_id="bot-b", status="cancelled", recurrence="+1h",
                           scheduled_at=datetime.now(timezone.utc))

        resp = await client.get("/api/v1/admin/tasks?bot_id=bot-a", headers=AUTH_HEADERS)
        body = resp.json()
        assert len(body["schedules"]) == 1
        assert body["schedules"][0]["bot_id"] == "bot-a"
