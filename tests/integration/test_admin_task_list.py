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

    async def test_one_shot_pipeline_surfaces_last_run_from_self(self, client, db_session):
        """A one-shot pipeline runs as itself (no child spawn) so run_count stays 0.
        The Definitions view must still see last_run_at from the task's own completed_at."""
        completed = datetime.now(timezone.utc)
        task = await _create_task(
            db_session,
            task_type="pipeline",
            status="complete",
            recurrence=None,
            steps=[{"id": "s", "type": "exec", "prompt": "echo hi"}],
            run_at=completed - timedelta(seconds=5),
            completed_at=completed,
            run_count=0,
        )
        resp = await client.get("/api/v1/admin/tasks", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        row = next(t for t in body["tasks"] if t["id"] == str(task.id))
        assert row["last_run_at"] is not None, "one-shot pipeline should surface last_run_at"
        assert row["last_run_status"] == "complete"
