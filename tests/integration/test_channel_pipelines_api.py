"""Integration tests for channel-pipeline subscription endpoints (Phase 5)."""
import uuid
from datetime import datetime, timezone

import pytest

from app.db.models import Channel, ChannelPipelineSubscription, Task
from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


async def _make_channel(db_session, name="test-channel", client_id=None):
    ch = Channel(
        id=uuid.uuid4(),
        name=name,
        bot_id="test-bot",
        client_id=client_id,
    )
    db_session.add(ch)
    await db_session.commit()
    return ch


async def _make_pipeline(db_session, title="Test Pipeline", source="user"):
    task = Task(
        id=uuid.uuid4(),
        bot_id="test-bot",
        prompt="[pipeline]",
        title=title,
        status="active",
        task_type="pipeline",
        source=source,
        dispatch_type="none",
        steps=[{"id": "s1", "type": "tool", "tool_name": "noop"}],
        execution_config={"description": title, "featured": source == "system"},
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(task)
    await db_session.commit()
    return task


class TestSubscribeListPatchDelete:
    async def test_subscribe_returns_joined_pipeline(self, client, db_session):
        ch = await _make_channel(db_session)
        p = await _make_pipeline(db_session)

        resp = await client.post(
            f"/api/v1/admin/channels/{ch.id}/pipelines",
            headers=AUTH_HEADERS,
            json={"task_id": str(p.id)},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["channel_id"] == str(ch.id)
        assert body["task_id"] == str(p.id)
        assert body["enabled"] is True
        assert body["pipeline"]["title"] == p.title

    async def test_duplicate_subscribe_conflicts(self, client, db_session):
        ch = await _make_channel(db_session)
        p = await _make_pipeline(db_session)
        await client.post(
            f"/api/v1/admin/channels/{ch.id}/pipelines",
            headers=AUTH_HEADERS,
            json={"task_id": str(p.id)},
        )
        resp = await client.post(
            f"/api/v1/admin/channels/{ch.id}/pipelines",
            headers=AUTH_HEADERS,
            json={"task_id": str(p.id)},
        )
        assert resp.status_code == 409

    async def test_reject_non_pipeline_task(self, client, db_session):
        ch = await _make_channel(db_session)
        plain = Task(
            id=uuid.uuid4(),
            bot_id="test-bot",
            prompt="plain",
            status="active",
            task_type="agent",
            source="user",
            dispatch_type="none",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(plain)
        await db_session.commit()
        resp = await client.post(
            f"/api/v1/admin/channels/{ch.id}/pipelines",
            headers=AUTH_HEADERS,
            json={"task_id": str(plain.id)},
        )
        assert resp.status_code == 400

    async def test_list_subscriptions_for_channel(self, client, db_session):
        ch = await _make_channel(db_session)
        p1 = await _make_pipeline(db_session, "P1")
        p2 = await _make_pipeline(db_session, "P2")
        await client.post(
            f"/api/v1/admin/channels/{ch.id}/pipelines",
            headers=AUTH_HEADERS, json={"task_id": str(p1.id)},
        )
        await client.post(
            f"/api/v1/admin/channels/{ch.id}/pipelines",
            headers=AUTH_HEADERS, json={"task_id": str(p2.id)},
        )
        resp = await client.get(
            f"/api/v1/admin/channels/{ch.id}/pipelines",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["subscriptions"]) == 2

    async def test_enabled_only_filter(self, client, db_session):
        ch = await _make_channel(db_session)
        p = await _make_pipeline(db_session)
        sub_resp = await client.post(
            f"/api/v1/admin/channels/{ch.id}/pipelines",
            headers=AUTH_HEADERS, json={"task_id": str(p.id)},
        )
        sub_id = sub_resp.json()["id"]
        # Disable
        await client.patch(
            f"/api/v1/admin/channels/{ch.id}/pipelines/{sub_id}",
            headers=AUTH_HEADERS, json={"enabled": False},
        )
        resp = await client.get(
            f"/api/v1/admin/channels/{ch.id}/pipelines?enabled=true",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert len(resp.json()["subscriptions"]) == 0

    async def test_patch_schedule_computes_next_fire(self, client, db_session):
        ch = await _make_channel(db_session)
        p = await _make_pipeline(db_session)
        sub = (await client.post(
            f"/api/v1/admin/channels/{ch.id}/pipelines",
            headers=AUTH_HEADERS, json={"task_id": str(p.id)},
        )).json()
        resp = await client.patch(
            f"/api/v1/admin/channels/{ch.id}/pipelines/{sub['id']}",
            headers=AUTH_HEADERS,
            json={"schedule": "0 2 * * *"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["schedule"] == "0 2 * * *"
        assert body["next_fire_at"] is not None

    async def test_patch_clear_schedule(self, client, db_session):
        ch = await _make_channel(db_session)
        p = await _make_pipeline(db_session)
        sub = (await client.post(
            f"/api/v1/admin/channels/{ch.id}/pipelines",
            headers=AUTH_HEADERS,
            json={"task_id": str(p.id), "schedule": "*/15 * * * *"},
        )).json()
        assert sub["schedule"] == "*/15 * * * *"

        resp = await client.patch(
            f"/api/v1/admin/channels/{ch.id}/pipelines/{sub['id']}",
            headers=AUTH_HEADERS,
            json={"clear_schedule": True},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["schedule"] is None
        assert body["next_fire_at"] is None

    async def test_invalid_cron_rejected(self, client, db_session):
        ch = await _make_channel(db_session)
        p = await _make_pipeline(db_session)
        resp = await client.post(
            f"/api/v1/admin/channels/{ch.id}/pipelines",
            headers=AUTH_HEADERS,
            json={"task_id": str(p.id), "schedule": "not a cron"},
        )
        assert resp.status_code == 422

    async def test_featured_resolves_from_override_or_pipeline(self, client, db_session):
        ch = await _make_channel(db_session)
        # system pipeline has featured=True
        sys_p = await _make_pipeline(db_session, "Sys", source="system")
        sub = (await client.post(
            f"/api/v1/admin/channels/{ch.id}/pipelines",
            headers=AUTH_HEADERS, json={"task_id": str(sys_p.id)},
        )).json()
        # No override -> resolved from pipeline default (True)
        assert sub["featured"] is True

        # Override to False
        resp = await client.patch(
            f"/api/v1/admin/channels/{ch.id}/pipelines/{sub['id']}",
            headers=AUTH_HEADERS, json={"featured_override": False},
        )
        assert resp.status_code == 200
        assert resp.json()["featured"] is False

    async def test_unsubscribe(self, client, db_session):
        ch = await _make_channel(db_session)
        p = await _make_pipeline(db_session)
        sub = (await client.post(
            f"/api/v1/admin/channels/{ch.id}/pipelines",
            headers=AUTH_HEADERS, json={"task_id": str(p.id)},
        )).json()
        resp = await client.delete(
            f"/api/v1/admin/channels/{ch.id}/pipelines/{sub['id']}",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 204

        list_resp = await client.get(
            f"/api/v1/admin/channels/{ch.id}/pipelines",
            headers=AUTH_HEADERS,
        )
        assert len(list_resp.json()["subscriptions"]) == 0


class TestTaskSubscriptionsMirror:
    async def test_list_returns_channel_names(self, client, db_session):
        ch1 = await _make_channel(db_session, name="alpha")
        ch2 = await _make_channel(db_session, name="beta")
        p = await _make_pipeline(db_session)
        await client.post(
            f"/api/v1/admin/channels/{ch1.id}/pipelines",
            headers=AUTH_HEADERS, json={"task_id": str(p.id)},
        )
        await client.post(
            f"/api/v1/admin/channels/{ch2.id}/pipelines",
            headers=AUTH_HEADERS, json={"task_id": str(p.id)},
        )
        resp = await client.get(
            f"/api/v1/admin/tasks/{p.id}/subscriptions",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        names = sorted(s["channel"]["name"] for s in resp.json()["subscriptions"])
        assert names == ["alpha", "beta"]


class TestAdminTasksSubscriptionCount:
    async def test_list_includes_subscription_count(self, client, db_session):
        ch = await _make_channel(db_session)
        p = await _make_pipeline(db_session)
        await client.post(
            f"/api/v1/admin/channels/{ch.id}/pipelines",
            headers=AUTH_HEADERS, json={"task_id": str(p.id)},
        )
        resp = await client.get(
            "/api/v1/admin/tasks?task_type=pipeline&definitions_only=true",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        tasks = resp.json()["tasks"]
        target = next(t for t in tasks if t["id"] == str(p.id))
        assert target["subscription_count"] == 1

    async def test_source_filter(self, client, db_session):
        await _make_pipeline(db_session, "User P", source="user")
        await _make_pipeline(db_session, "System P", source="system")

        sys_only = await client.get(
            "/api/v1/admin/tasks?task_type=pipeline&definitions_only=true&source=system",
            headers=AUTH_HEADERS,
        )
        assert sys_only.status_code == 200
        for t in sys_only.json()["tasks"]:
            assert t["source"] == "system"
