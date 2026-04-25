"""Integration tests for the workspace Spatial Canvas — P1 scope.

Covers the contract claims from `Track - Spatial Canvas` decision #6:
nullable-FK shape with CHECK constraint, persisted seed_index,
auto-populate of channel nodes on read, atomic widget pin+node create,
reserved-slug isolation.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models import (
    Bot as BotRow,
    Channel,
    ChannelHeartbeat,
    Task,
    WidgetDashboard,
    WidgetDashboardPin,
    WidgetInstance,
    WorkspaceSpatialNode,
)
from app.services.dashboards import (
    WORKSPACE_SPATIAL_DASHBOARD_KEY,
    list_dashboards,
)
from app.services.workspace_spatial import (
    build_canvas_neighborhood,
    move_bot_node,
    update_channel_bot_spatial_policy,
)
from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


def _envelope(label: str = "x") -> dict:
    return {
        "content_type": "application/vnd.spindrel.components+json",
        "body": "{}",
        "plain_body": "ok",
        "display": "inline",
        "truncated": False,
        "record_id": None,
        "byte_size": 2,
        "display_label": label,
    }


async def _create_channel(client, **overrides) -> dict:
    payload = {
        "bot_id": "test-bot",
        "client_id": f"spatial-{uuid.uuid4().hex[:8]}",
        **overrides,
    }
    resp = await client.post("/api/v1/channels", json=payload, headers=AUTH_HEADERS)
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestReservedSlug:
    async def test_workspace_spatial_dashboard_seeded(self, db_session):
        row = (
            await db_session.execute(
                select(WidgetDashboard).where(
                    WidgetDashboard.slug == WORKSPACE_SPATIAL_DASHBOARD_KEY,
                )
            )
        ).scalar_one_or_none()
        assert row is not None, "migration 247 must seed workspace:spatial"

    async def test_excluded_from_user_list(self, db_session):
        rows = await list_dashboards(db_session, scope="user")
        slugs = [r.slug for r in rows]
        assert WORKSPACE_SPATIAL_DASHBOARD_KEY not in slugs

    async def test_excluded_from_list_dashboards_api(self, client):
        r = await client.get(
            "/api/v1/widgets/dashboards?scope=user", headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        slugs = [d["slug"] for d in r.json()["dashboards"]]
        assert WORKSPACE_SPATIAL_DASHBOARD_KEY not in slugs

    async def test_create_dashboard_rejects_reserved_slug(self, client):
        r = await client.post(
            "/api/v1/widgets/dashboards",
            json={"slug": WORKSPACE_SPATIAL_DASHBOARD_KEY, "name": "Sneaky"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 400


class TestSpatialNodesAutoSeed:
    async def test_get_nodes_creates_channel_rows(self, client, db_session):
        ch1 = await _create_channel(client)
        ch2 = await _create_channel(client)

        r = await client.get("/api/v1/workspace/spatial/nodes", headers=AUTH_HEADERS)
        assert r.status_code == 200, r.text
        nodes = r.json()["nodes"]
        channel_ids = {n["channel_id"] for n in nodes if n["channel_id"]}
        assert ch1["id"] in channel_ids
        assert ch2["id"] in channel_ids

        # Each channel node has a monotonic seed_index.
        seeds = sorted(
            n["seed_index"] for n in nodes if n["channel_id"] is not None
        )
        assert all(s is not None for s in seeds)
        assert len(set(seeds)) == len(seeds)

    async def test_get_nodes_idempotent(self, client):
        await _create_channel(client)
        r1 = await client.get("/api/v1/workspace/spatial/nodes", headers=AUTH_HEADERS)
        r2 = await client.get("/api/v1/workspace/spatial/nodes", headers=AUTH_HEADERS)
        assert r1.status_code == 200 and r2.status_code == 200
        ids_1 = {n["id"] for n in r1.json()["nodes"]}
        ids_2 = {n["id"] for n in r2.json()["nodes"]}
        assert ids_1 == ids_2, "second GET must not create duplicate rows"

    async def test_get_nodes_creates_bot_rows(self, client):
        await _create_channel(client)
        r = await client.get("/api/v1/workspace/spatial/nodes", headers=AUTH_HEADERS)
        assert r.status_code == 200, r.text
        nodes = r.json()["nodes"]
        bot_nodes = [n for n in nodes if n["bot_id"] == "test-bot"]
        assert len(bot_nodes) == 1
        assert bot_nodes[0]["channel_id"] is None
        assert bot_nodes[0]["widget_pin_id"] is None
        assert bot_nodes[0]["bot"]["id"] == "test-bot"

    async def test_channel_spatial_bot_policy_roundtrip(self, client):
        ch = await _create_channel(client)
        r = await client.patch(
            f"/api/v1/channels/{ch['id']}/spatial-bots/test-bot",
            json={
                "enabled": True,
                "allow_movement": True,
                "allow_moving_spatial_objects": True,
                "step_world_units": 32,
                "max_move_steps_per_turn": 2,
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        policy = r.json()["policy"]
        assert policy["enabled"] is True
        assert policy["allow_movement"] is True
        assert policy["step_world_units"] == 32

        r2 = await client.get(
            f"/api/v1/channels/{ch['id']}/spatial-bots/test-bot",
            headers=AUTH_HEADERS,
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["policy"]["allow_moving_spatial_objects"] is True

    async def test_move_bot_node_respects_channel_policy(self, client, db_session):
        ch = await _create_channel(client)
        channel_id = uuid.UUID(ch["id"])
        await update_channel_bot_spatial_policy(
            db_session,
            channel_id,
            "test-bot",
            {"enabled": True, "allow_movement": True, "step_world_units": 32, "max_move_steps_per_turn": 2},
        )
        node = await move_bot_node(
            db_session,
            channel_id=channel_id,
            bot_id="test-bot",
            dx_steps=2,
            dy_steps=0,
            reason="test",
        )
        assert node.bot_id == "test-bot"
        assert node.last_movement["kind"] == "bot_move"
        assert node.last_movement["to"]["x"] - node.last_movement["from"]["x"] == 64

        neighborhood = await build_canvas_neighborhood(
            db_session,
            channel_id=channel_id,
            bot_id="test-bot",
        )
        assert neighborhood["bot"]["bot_id"] == "test-bot"


class TestSpatialUpcomingActivity:
    async def test_workspace_activity_includes_hygiene_and_channelless_tasks(self, client, db_session):
        ch = await _create_channel(client)
        now = datetime.now(timezone.utc)
        db_session.add(
            ChannelHeartbeat(
                channel_id=uuid.UUID(ch["id"]),
                enabled=True,
                interval_minutes=30,
                next_run_at=now + timedelta(minutes=30),
            )
        )
        db_session.add(
            Task(
                bot_id="test-bot",
                channel_id=uuid.UUID(ch["id"]),
                prompt="channel task",
                title="Channel task",
                status="pending",
                scheduled_at=now + timedelta(minutes=45),
            )
        )
        db_session.add(
            Task(
                bot_id="test-bot",
                channel_id=None,
                prompt="admin task",
                title="Admin-only task",
                status="pending",
                scheduled_at=now + timedelta(minutes=50),
            )
        )
        db_session.add(
            BotRow(
                id="hygiene-bot",
                name="Hygiene Bot",
                model="test/model",
                system_prompt="",
                memory_scheme="workspace-files",
                memory_hygiene_enabled=True,
                memory_hygiene_interval_hours=24,
                next_hygiene_run_at=now + timedelta(hours=1),
            )
        )
        await db_session.commit()

        canvas = await client.get(
            "/api/v1/workspace/spatial/upcoming-activity?limit=20",
            headers=AUTH_HEADERS,
        )
        assert canvas.status_code == 200, canvas.text
        canvas_items = canvas.json()["items"]
        assert {item["type"] for item in canvas_items} == {"heartbeat", "task", "memory_hygiene"}
        assert {"Heartbeat", "Channel task", "Admin-only task", "Dreaming"} <= {
            item["title"] for item in canvas_items
        }


class TestUpdateAndDelete:
    async def test_patch_node_position(self, client):
        await _create_channel(client)
        nodes = (await client.get("/api/v1/workspace/spatial/nodes", headers=AUTH_HEADERS)).json()["nodes"]
        node_id = nodes[0]["id"]
        r = await client.patch(
            f"/api/v1/workspace/spatial/nodes/{node_id}",
            json={"world_x": 123.0, "world_y": -45.5, "z_index": 7},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        n = r.json()["node"]
        assert n["world_x"] == 123.0
        assert n["world_y"] == -45.5
        assert n["z_index"] == 7

    async def test_delete_channel_node_resets(self, client):
        await _create_channel(client)
        nodes = (await client.get("/api/v1/workspace/spatial/nodes", headers=AUTH_HEADERS)).json()["nodes"]
        node = next(n for n in nodes if n["channel_id"])
        await client.patch(
            f"/api/v1/workspace/spatial/nodes/{node['id']}",
            json={"world_x": 999.0, "world_y": 999.0},
            headers=AUTH_HEADERS,
        )
        d = await client.delete(
            f"/api/v1/workspace/spatial/nodes/{node['id']}", headers=AUTH_HEADERS,
        )
        assert d.status_code == 204
        # Re-fetching re-seeds with fresh phyllotaxis (monotonic seed_index),
        # not the previous custom position.
        nodes2 = (await client.get("/api/v1/workspace/spatial/nodes", headers=AUTH_HEADERS)).json()["nodes"]
        ch_node = next(n for n in nodes2 if n["channel_id"] == node["channel_id"])
        assert ch_node["id"] != node["id"]
        assert (ch_node["world_x"], ch_node["world_y"]) != (999.0, 999.0)


class TestPinWidgetToCanvas:
    async def test_atomic_pin_and_node_create(self, client, db_session):
        body = {
            "source_kind": "adhoc",
            "tool_name": "echo",
            "envelope": _envelope("hello"),
            "world_x": 50.0,
            "world_y": 60.0,
        }
        r = await client.post(
            "/api/v1/workspace/spatial/widget-pins", json=body, headers=AUTH_HEADERS,
        )
        assert r.status_code == 201, r.text
        payload = r.json()
        assert payload["pin"]["dashboard_key"] == WORKSPACE_SPATIAL_DASHBOARD_KEY
        node = payload["node"]
        assert node["widget_pin_id"] == payload["pin"]["id"]
        assert node["channel_id"] is None
        assert node["world_x"] == 50.0
        assert node["world_y"] == 60.0

        # And one node row in the DB.
        row = (
            await db_session.execute(
                select(WorkspaceSpatialNode).where(
                    WorkspaceSpatialNode.widget_pin_id == uuid.UUID(payload["pin"]["id"])
                )
            )
        ).scalar_one()
        assert row is not None

    async def test_delete_widget_node_removes_pin(self, client, db_session):
        body = {
            "source_kind": "adhoc",
            "tool_name": "echo",
            "envelope": _envelope("bye"),
        }
        r = await client.post(
            "/api/v1/workspace/spatial/widget-pins", json=body, headers=AUTH_HEADERS,
        )
        assert r.status_code == 201
        node_id = r.json()["node"]["id"]
        pin_id = r.json()["pin"]["id"]

        d = await client.delete(
            f"/api/v1/workspace/spatial/nodes/{node_id}", headers=AUTH_HEADERS,
        )
        assert d.status_code == 204

        # Pin row gone — cascade also dropped the node.
        pin_row = (
            await db_session.execute(
                select(WidgetDashboardPin).where(
                    WidgetDashboardPin.id == uuid.UUID(pin_id)
                )
            )
        ).scalar_one_or_none()
        assert pin_row is None
        node_row = (
            await db_session.execute(
                select(WorkspaceSpatialNode).where(
                    WorkspaceSpatialNode.id == uuid.UUID(node_id)
                )
            )
        ).scalar_one_or_none()
        assert node_row is None

    async def test_channel_native_pin_projects_same_instance_to_canvas(self, client, db_session):
        from app.services.dashboard_pins import create_pin, list_pins
        from app.services.native_app_widgets import build_native_widget_preview_envelope

        ch = await _create_channel(client, name="QA")
        channel_id = uuid.UUID(ch["id"])
        source_pin = await create_pin(
            db_session,
            source_kind="adhoc",
            tool_name="core/notes_native",
            envelope=build_native_widget_preview_envelope("core/notes_native"),
            source_channel_id=channel_id,
            display_label="Notes",
            dashboard_key=f"channel:{channel_id}",
        )
        source_instance_id = source_pin.widget_instance_id
        assert source_instance_id is not None

        r = await client.post(
            "/api/v1/workspace/spatial/widget-pins",
            json={
                "source_dashboard_pin_id": str(source_pin.id),
                "world_x": 10.0,
                "world_y": 20.0,
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 201, r.text
        projected = r.json()["pin"]
        canvas_pin_id = projected["id"]
        assert projected["widget_instance_id"] == str(source_instance_id)
        assert projected["display_label"] == "QA Notes"
        assert projected["widget_origin"]["source_dashboard_pin_id"] == str(source_pin.id)

        action = await client.post(
            "/api/v1/widget-actions",
            json={
                "dispatch": "native_widget",
                "dashboard_pin_id": canvas_pin_id,
                "action": "replace_body",
                "args": {"body": "shared from canvas"},
            },
            headers=AUTH_HEADERS,
        )
        assert action.status_code == 200, action.text
        assert action.json()["ok"] is True

        channel_pins = await list_pins(db_session, dashboard_key=f"channel:{channel_id}")
        channel_pin = next(p for p in channel_pins if p.id == source_pin.id)
        assert channel_pin.widget_instance_id == source_instance_id
        assert channel_pin.envelope["body"]["state"]["body"] == "shared from canvas"

    async def test_native_canvas_projection_duplicate_rule_is_per_channel_instance(self, client, db_session):
        from app.services.dashboard_pins import create_pin
        from app.services.native_app_widgets import build_native_widget_preview_envelope

        channels = [
            await _create_channel(client, name="QA"),
            await _create_channel(client, name="Rolland"),
        ]
        source_pins = []
        for ch in channels:
            channel_id = uuid.UUID(ch["id"])
            source_pins.append(
                await create_pin(
                    db_session,
                    source_kind="adhoc",
                    tool_name="core/todo_native",
                    envelope=build_native_widget_preview_envelope("core/todo_native"),
                    source_channel_id=channel_id,
                    display_label="Todo",
                    dashboard_key=f"channel:{channel_id}",
                )
            )

        projected_instances = []
        for source_pin in source_pins:
            r = await client.post(
                "/api/v1/workspace/spatial/widget-pins",
                json={"source_dashboard_pin_id": str(source_pin.id)},
                headers=AUTH_HEADERS,
            )
            assert r.status_code == 201, r.text
            projected_instances.append(r.json()["pin"]["widget_instance_id"])

        assert projected_instances == [str(p.widget_instance_id) for p in source_pins]
        assert len(set(projected_instances)) == 2

    async def test_direct_native_canvas_pins_get_fresh_instances(self, client, db_session):
        from app.services.native_app_widgets import build_native_widget_preview_envelope

        instance_ids = []
        for _ in range(2):
            r = await client.post(
                "/api/v1/workspace/spatial/widget-pins",
                json={
                    "source_kind": "adhoc",
                    "tool_name": "core/notes_native",
                    "envelope": build_native_widget_preview_envelope("core/notes_native"),
                },
                headers=AUTH_HEADERS,
            )
            assert r.status_code == 201, r.text
            instance_ids.append(r.json()["pin"]["widget_instance_id"])

        assert len(set(instance_ids)) == 2
        rows = (
            await db_session.execute(
                select(WidgetInstance).where(
                    WidgetInstance.id.in_([uuid.UUID(i) for i in instance_ids])
                )
            )
        ).scalars().all()
        assert {row.scope_kind for row in rows} == {"dashboard"}
        assert all(row.scope_ref.startswith("notes_native/") for row in rows)
