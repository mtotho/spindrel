"""Integration tests for `Task.layout` round-trip through the admin tasks API.

`layout` carries Pipeline Canvas tab position metadata. The runtime never
reads it; the admin API must round-trip it verbatim and protect system
pipelines from non-layout edits.
"""
import uuid
from datetime import datetime, timezone

import pytest

from app.db.models import Task
from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


SAMPLE_LAYOUT = {
    "version": 1,
    "nodes": {
        "step_1": {"x": 320, "y": 180},
        "step_2": {"x": 320, "y": 320},
    },
    "camera": {"x": 0, "y": 0, "scale": 1},
}

SAMPLE_STEPS = [
    {"id": "step_1", "type": "agent", "prompt": "do thing", "on_failure": "abort"},
    {"id": "step_2", "type": "tool", "tool_name": "noop", "on_failure": "abort"},
]


async def _create_user_pipeline(db_session, **overrides) -> Task:
    fields = {
        "id": uuid.uuid4(),
        "bot_id": "test-bot",
        "prompt": "[Pipeline]",
        "task_type": "pipeline",
        "source": "user",
        "dispatch_type": "none",
        "created_at": datetime.now(timezone.utc),
        "steps": SAMPLE_STEPS,
        "layout": {},
    }
    fields.update(overrides)
    task = Task(**fields)
    db_session.add(task)
    await db_session.commit()
    return task


class TestLayoutRoundTrip:
    async def test_post_with_layout_round_trips(self, client):
        resp = await client.post(
            "/api/v1/admin/tasks",
            headers=AUTH_HEADERS,
            json={
                "bot_id": "test-bot",
                "prompt": "",
                "task_type": "pipeline",
                "steps": SAMPLE_STEPS,
                "layout": SAMPLE_LAYOUT,
            },
        )
        assert resp.status_code == 201, resp.text
        task_id = resp.json()["id"]

        get_resp = await client.get(f"/api/v1/admin/tasks/{task_id}", headers=AUTH_HEADERS)
        assert get_resp.status_code == 200
        # Structural equality — Postgres JSONB normalizes key order.
        assert get_resp.json()["layout"] == SAMPLE_LAYOUT

    async def test_patch_layout_only_preserves_steps(self, client, db_session):
        task = await _create_user_pipeline(db_session, layout={})
        new_layout = {"version": 1, "nodes": {"step_1": {"x": 999, "y": 999}}}

        resp = await client.patch(
            f"/api/v1/admin/tasks/{task.id}",
            headers=AUTH_HEADERS,
            json={"layout": new_layout},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["layout"] == new_layout
        assert body["steps"] == SAMPLE_STEPS

    async def test_patch_steps_only_preserves_layout(self, client, db_session):
        task = await _create_user_pipeline(db_session, layout=SAMPLE_LAYOUT)
        new_steps = [{"id": "only", "type": "agent", "prompt": "x", "on_failure": "abort"}]

        resp = await client.patch(
            f"/api/v1/admin/tasks/{task.id}",
            headers=AUTH_HEADERS,
            json={"steps": new_steps},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["steps"] == new_steps
        assert body["layout"] == SAMPLE_LAYOUT

    async def test_patch_omitting_layout_preserves_existing(self, client, db_session):
        task = await _create_user_pipeline(db_session, layout=SAMPLE_LAYOUT)

        resp = await client.patch(
            f"/api/v1/admin/tasks/{task.id}",
            headers=AUTH_HEADERS,
            json={"title": "renamed"},
        )
        assert resp.status_code == 200
        assert resp.json()["layout"] == SAMPLE_LAYOUT


class TestSystemPipelineLayoutGuard:
    async def test_system_pipeline_accepts_layout_only_patch(self, client, db_session):
        task = await _create_user_pipeline(db_session, source="system", layout={})

        resp = await client.patch(
            f"/api/v1/admin/tasks/{task.id}",
            headers=AUTH_HEADERS,
            json={"layout": SAMPLE_LAYOUT},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["layout"] == SAMPLE_LAYOUT

    async def test_system_pipeline_rejects_steps_patch(self, client, db_session):
        task = await _create_user_pipeline(db_session, source="system", layout={})

        resp = await client.patch(
            f"/api/v1/admin/tasks/{task.id}",
            headers=AUTH_HEADERS,
            json={"steps": [{"id": "x", "type": "agent", "prompt": "y", "on_failure": "abort"}]},
        )
        assert resp.status_code == 422, resp.text
        assert "system pipelines are read-only" in resp.text.lower()

    async def test_system_pipeline_rejects_mixed_patch(self, client, db_session):
        task = await _create_user_pipeline(db_session, source="system", layout={})

        resp = await client.patch(
            f"/api/v1/admin/tasks/{task.id}",
            headers=AUTH_HEADERS,
            json={"layout": SAMPLE_LAYOUT, "title": "should-be-rejected"},
        )
        assert resp.status_code == 422

        # And the original layout/title must be unchanged.
        get_resp = await client.get(f"/api/v1/admin/tasks/{task.id}", headers=AUTH_HEADERS)
        assert get_resp.json()["layout"] == {}
