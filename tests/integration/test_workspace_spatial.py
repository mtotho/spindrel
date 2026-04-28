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
    TraceEvent,
    WidgetCronSubscription,
    WidgetDashboard,
    WidgetDashboardPin,
    WidgetInstance,
    WorkspaceAttentionItem,
    WorkspaceSpatialNode,
)
from app.services.dashboards import (
    WORKSPACE_SPATIAL_DASHBOARD_KEY,
    list_dashboards,
)
from app.services.workspace_spatial import (
    DEFAULT_SPATIAL_POLICY,
    build_canvas_neighborhood,
    move_bot_node,
    update_channel_bot_spatial_policy,
)
from app.services.spatial_map_view import build_spatial_map_view
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


def _edge_gap(a: dict, b: dict) -> float:
    dx = max(
        b["world_x"] - (a["world_x"] + a["world_w"]),
        a["world_x"] - (b["world_x"] + b["world_w"]),
        0.0,
    )
    dy = max(
        b["world_y"] - (a["world_y"] + a["world_h"]),
        a["world_y"] - (b["world_y"] + b["world_h"]),
        0.0,
    )
    return (dx * dx + dy * dy) ** 0.5


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

    async def test_bot_rows_spawn_outside_default_channel_clearance(self, client):
        ch = await _create_channel(client)
        r = await client.get("/api/v1/workspace/spatial/nodes", headers=AUTH_HEADERS)
        assert r.status_code == 200, r.text
        nodes = r.json()["nodes"]
        channel_node = next(n for n in nodes if n["channel_id"] == ch["id"])
        bot_node = next(n for n in nodes if n["bot_id"] == "test-bot")

        min_gap = (
            DEFAULT_SPATIAL_POLICY["minimum_clearance_steps"]
            * DEFAULT_SPATIAL_POLICY["step_world_units"]
        )
        assert _edge_gap(bot_node, channel_node) >= min_gap

    async def test_channel_spatial_bot_policy_roundtrip(self, client):
        ch = await _create_channel(client)
        r = await client.patch(
            f"/api/v1/channels/{ch['id']}/spatial-bots/test-bot",
            json={
                "enabled": True,
                "allow_movement": True,
                "allow_moving_spatial_objects": True,
                "allow_attention_beacons": True,
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
        assert r2.json()["policy"]["allow_attention_beacons"] is True

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

    async def test_map_view_requires_policy(self, client, db_session):
        ch = await _create_channel(client)
        with pytest.raises(Exception) as exc:
            await build_spatial_map_view(
                db_session,
                channel_id=uuid.UUID(ch["id"]),
                bot_id="test-bot",
            )
        assert "Spatial map view is not enabled" in str(exc.value)

    async def test_map_view_cluster_exposes_surface_only(self, client, db_session):
        ch1 = await _create_channel(client, name="Alpha")
        ch2 = await _create_channel(client, name="Beta")
        channel_id = uuid.UUID(ch1["id"])
        await update_channel_bot_spatial_policy(
            db_session,
            channel_id,
            "test-bot",
            {"enabled": True, "allow_map_view": True},
        )
        db_session.add(
            TraceEvent(
                event_type="token_usage",
                bot_id="test-bot",
                data={"channel_id": ch2["id"], "total_tokens": 2000},
            )
        )
        await db_session.commit()

        view = await build_spatial_map_view(
            db_session,
            channel_id=channel_id,
            bot_id="test-bot",
            preset="whole_map",
        )
        clusters = [item for item in view["items"] if item["kind"] == "channel_cluster"]
        assert clusters
        assert clusters[0]["label"] == "Beta"
        assert clusters[0]["hidden_count"] >= 1
        encoded = str(view)
        assert "Alpha" not in encoded
        assert "focus_token" in clusters[0]


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


class TestWorkspaceMapState:
    async def test_map_state_uses_existing_room_actor_and_warning_primitives(self, client, db_session):
        ch = await _create_channel(client, name="Ops")
        channel_id = uuid.UUID(ch["id"])
        now = datetime.now(timezone.utc)

        # Seed channel + bot nodes. Map state should treat the
        # bot as an actor, not require any Mission/Mission Control rows.
        nodes_resp = await client.get("/api/v1/workspace/spatial/nodes", headers=AUTH_HEADERS)
        assert nodes_resp.status_code == 200
        channel_node = next(n for n in nodes_resp.json()["nodes"] if n["channel_id"] == ch["id"])
        assert any(n["bot_id"] == "test-bot" for n in nodes_resp.json()["nodes"])
        db_session.add(ChannelHeartbeat(
            channel_id=channel_id,
            enabled=True,
            interval_minutes=30,
            next_run_at=now + timedelta(minutes=30),
            last_run_at=now - timedelta(hours=1),
            run_count=3,
        ))
        failed = Task(
            bot_id="test-bot",
            channel_id=channel_id,
            prompt="Check the deploy",
            title="Deploy check",
            status="failed",
            task_type="scheduled",
            error="deploy probe failed",
            created_at=now - timedelta(minutes=10),
            completed_at=now - timedelta(minutes=9),
        )
        db_session.add(failed)
        db_session.add(WorkspaceAttentionItem(
            source_type="system",
            source_id="test",
            channel_id=channel_id,
            target_kind="channel",
            target_id=str(channel_id),
            dedupe_key="ops-warning",
            severity="critical",
            title="Ops needs attention",
            message="critical signal",
            status="open",
            last_seen_at=now,
        ))
        await db_session.commit()

        resp = await client.get("/api/v1/workspace/spatial/map-state", headers=AUTH_HEADERS)
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        by_node = payload["objects_by_node_id"]
        room = by_node[channel_node["id"]]
        actor = next(obj for obj in payload["objects"] if obj["kind"] == "bot" and obj["target_id"] == "test-bot")

        assert payload["source"] == "existing_primitives"
        assert room["kind"] == "channel"
        assert room["source"]["primary_bot_id"] == "test-bot"
        assert room["attached"]["heartbeat"]["enabled"] is True
        assert room["counts"]["upcoming"] >= 1
        assert room["counts"]["warnings"] >= 2
        assert room["severity"] == "critical"
        assert any(w["kind"] == "attention" for w in room["warnings"])
        assert any(r["title"] == "Deploy check" for r in room["recent"])
        assert actor["kind"] == "bot"
        assert actor["source"]["bot_id"] == "test-bot"
        assert any(r["title"] == "Deploy check" for r in actor["recent"])

    async def test_map_state_maps_trace_errors_to_channel_and_bot_objects(self, client, db_session):
        ch = await _create_channel(client, name="Quality")
        now = datetime.now(timezone.utc)

        nodes_resp = await client.get("/api/v1/workspace/spatial/nodes", headers=AUTH_HEADERS)
        assert nodes_resp.status_code == 200
        channel_node = next(n for n in nodes_resp.json()["nodes"] if n["channel_id"] == ch["id"])

        db_session.add(
            TraceEvent(
                event_type="error",
                event_name="mermaid_to_excalidraw failed",
                bot_id="test-bot",
                data={
                    "channel_id": ch["id"],
                    "bot_id": "test-bot",
                    "error": "tool bridge failed",
                },
                created_at=now - timedelta(minutes=3),
            )
        )
        db_session.add(
            TraceEvent(
                event_type="error",
                event_name="unmapped system failure",
                data={"error": "background loop failed"},
                created_at=now - timedelta(minutes=2),
            )
        )
        await db_session.commit()

        resp = await client.get("/api/v1/workspace/spatial/map-state", headers=AUTH_HEADERS)
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        room = payload["objects_by_node_id"][channel_node["id"]]
        actor = next(obj for obj in payload["objects"] if obj["kind"] == "bot" and obj["target_id"] == "test-bot")
        daily_health = next(obj for obj in payload["objects"] if obj["kind"] == "landmark" and obj["target_id"] == "daily_health")

        assert any(w["kind"] == "trace" and w["title"] == "mermaid_to_excalidraw failed" for w in room["warnings"])
        assert any(r["kind"] == "trace" and r["title"] == "mermaid_to_excalidraw failed" for r in actor["recent"])
        assert not any(w["title"] == "mermaid_to_excalidraw failed" for w in daily_health["warnings"])
        assert any(w["title"] == "unmapped system failure" for w in daily_health["warnings"])

    async def test_map_state_describes_workspace_widget_sources_and_crons(self, client, db_session):
        ch = await _create_channel(client, name="Widgets")
        now = datetime.now(timezone.utc)
        r = await client.post(
            "/api/v1/workspace/spatial/widget-pins",
            json={
                "source_kind": "channel",
                "tool_name": "core/test_widget",
                "source_channel_id": ch["id"],
                "display_label": "Widget Probe",
                "envelope": _envelope("Widget Probe"),
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 201, r.text
        pin_id = uuid.UUID(r.json()["pin"]["id"])
        node_id = r.json()["node"]["id"]
        db_session.add(WidgetCronSubscription(
            pin_id=pin_id,
            cron_name="refresh",
            schedule="*/15 * * * *",
            handler="refresh",
            enabled=True,
            next_fire_at=now + timedelta(minutes=15),
        ))
        await db_session.commit()

        resp = await client.get("/api/v1/workspace/spatial/map-state", headers=AUTH_HEADERS)
        assert resp.status_code == 200, resp.text
        widget = resp.json()["objects_by_node_id"][node_id]
        assert widget["kind"] == "widget"
        assert widget["source"]["source_channel_id"] == ch["id"]
        assert widget["source"]["source_channel_name"] == "Widgets"
        assert widget["source"]["source_bot_id"] is None
        assert widget["source"]["tool_name"] == "core/test_widget"
        assert widget["attached"]["cron_count"] == 1
        assert widget["next"]["kind"] == "widget_cron"
        assert widget["status"] == "scheduled"

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

    async def test_channel_native_projection_is_idempotent_for_same_source_pin(self, client, db_session):
        from app.services.dashboard_pins import create_pin
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

        responses = []
        for _ in range(2):
            r = await client.post(
                "/api/v1/workspace/spatial/widget-pins",
                json={"source_dashboard_pin_id": str(source_pin.id)},
                headers=AUTH_HEADERS,
            )
            assert r.status_code == 201, r.text
            responses.append(r.json())

        assert responses[0]["pin"]["id"] == responses[1]["pin"]["id"]
        assert responses[0]["node"]["id"] == responses[1]["node"]["id"]

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


class TestPositionHistory:
    """Comet-tail trail data — every coordinate-changing mutation appends a
    pruned history entry; size/z-only updates do not."""

    async def test_drag_appends_history(self, client):
        await _create_channel(client)
        nodes = (await client.get("/api/v1/workspace/spatial/nodes", headers=AUTH_HEADERS)).json()["nodes"]
        node_id = nodes[0]["id"]
        prev_x = nodes[0]["world_x"]
        prev_y = nodes[0]["world_y"]
        r = await client.patch(
            f"/api/v1/workspace/spatial/nodes/{node_id}",
            json={"world_x": prev_x + 100.0, "world_y": prev_y + 50.0},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        history = r.json()["node"]["position_history"]
        assert len(history) == 1
        assert history[0]["x"] == prev_x
        assert history[0]["y"] == prev_y
        assert history[0]["actor"] is None
        assert "ts" in history[0]

    async def test_no_op_move_skipped(self, client):
        await _create_channel(client)
        nodes = (await client.get("/api/v1/workspace/spatial/nodes", headers=AUTH_HEADERS)).json()["nodes"]
        node = nodes[0]
        # Z-index only — no coord change → no history.
        r = await client.patch(
            f"/api/v1/workspace/spatial/nodes/{node['id']}",
            json={"z_index": 9},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        assert r.json()["node"]["position_history"] == []
        # Same coords → still no history.
        r2 = await client.patch(
            f"/api/v1/workspace/spatial/nodes/{node['id']}",
            json={"world_x": node["world_x"], "world_y": node["world_y"]},
            headers=AUTH_HEADERS,
        )
        assert r2.status_code == 200
        assert r2.json()["node"]["position_history"] == []

    async def test_history_caps_length(self, client, db_session):
        await _create_channel(client)
        nodes = (await client.get("/api/v1/workspace/spatial/nodes", headers=AUTH_HEADERS)).json()["nodes"]
        node_id = nodes[0]["id"]
        # Drive 35 distinct moves; expect cap at MAX_HISTORY_POINTS = 30.
        for i in range(35):
            await client.patch(
                f"/api/v1/workspace/spatial/nodes/{node_id}",
                json={"world_x": float(i * 11), "world_y": float(i * 7)},
                headers=AUTH_HEADERS,
            )
        from app.services.workspace_spatial import MAX_HISTORY_POINTS
        row = (await db_session.execute(
            select(WorkspaceSpatialNode).where(WorkspaceSpatialNode.id == uuid.UUID(node_id))
        )).scalar_one()
        assert len(row.position_history) == MAX_HISTORY_POINTS
        # Newest entry is the position right before the latest write — i.e.
        # the previous iteration's coords (i=33 wrote (363, 231) and the
        # history entry from the i=34 write captured that).
        assert row.position_history[-1]["x"] == 33 * 11

    async def test_history_prunes_old_entries(self, client, db_session):
        await _create_channel(client)
        nodes = (await client.get("/api/v1/workspace/spatial/nodes", headers=AUTH_HEADERS)).json()["nodes"]
        node_id = nodes[0]["id"]
        # Plant a stale (>72h ago) entry directly in the DB.
        row = (await db_session.execute(
            select(WorkspaceSpatialNode).where(WorkspaceSpatialNode.id == uuid.UUID(node_id))
        )).scalar_one()
        stale_ts = (datetime.now(timezone.utc) - timedelta(hours=80)).isoformat()
        row.position_history = [{"x": 1.0, "y": 2.0, "ts": stale_ts, "actor": None}]
        await db_session.commit()
        # A live move should drop the stale entry and keep only the new one.
        await client.patch(
            f"/api/v1/workspace/spatial/nodes/{node_id}",
            json={"world_x": 500.0, "world_y": 600.0},
            headers=AUTH_HEADERS,
        )
        await db_session.refresh(row)
        assert len(row.position_history) == 1
        assert row.position_history[0]["x"] != 1.0  # old entry pruned

    async def test_world_coord_clamp_rejects_pathological_drag(self, client):
        """A glitched drag that produces |world_x| or |world_y| beyond the
        sanity limit must be refused — the tile stays put rather than being
        flung to ~1e9 world units, where it'd be unreachable without the
        Cmd+K palette."""
        await _create_channel(client)
        nodes = (await client.get("/api/v1/workspace/spatial/nodes", headers=AUTH_HEADERS)).json()["nodes"]
        node = nodes[0]
        prev_x, prev_y = node["world_x"], node["world_y"]
        # Out-of-range x — refused.
        r = await client.patch(
            f"/api/v1/workspace/spatial/nodes/{node['id']}",
            json={"world_x": 1.0e9, "world_y": 0.0},
            headers=AUTH_HEADERS,
        )
        assert r.status_code in (400, 422), r.text
        # Tile still at original coords.
        nodes2 = (await client.get("/api/v1/workspace/spatial/nodes", headers=AUTH_HEADERS)).json()["nodes"]
        cur = next(n for n in nodes2 if n["id"] == node["id"])
        assert cur["world_x"] == prev_x
        assert cur["world_y"] == prev_y
        # Out-of-range y — refused.
        r2 = await client.patch(
            f"/api/v1/workspace/spatial/nodes/{node['id']}",
            json={"world_y": -1.0e9},
            headers=AUTH_HEADERS,
        )
        assert r2.status_code in (400, 422), r2.text


class TestSpatialLandmarks:
    async def test_get_nodes_seeds_all_landmarks(self, client):
        from app.services.workspace_spatial import LANDMARK_DEFAULTS

        r = await client.get("/api/v1/workspace/spatial/nodes", headers=AUTH_HEADERS)
        assert r.status_code == 200, r.text
        nodes = r.json()["nodes"]
        landmarks = {n["landmark_kind"]: n for n in nodes if n["landmark_kind"]}
        assert set(landmarks.keys()) == set(LANDMARK_DEFAULTS.keys())
        for kind, (x, y) in LANDMARK_DEFAULTS.items():
            assert landmarks[kind]["world_x"] == x
            assert landmarks[kind]["world_y"] == y
            assert landmarks[kind]["channel_id"] is None
            assert landmarks[kind]["widget_pin_id"] is None
            assert landmarks[kind]["bot_id"] is None

    async def test_landmark_seed_idempotent(self, client):
        r1 = await client.get("/api/v1/workspace/spatial/nodes", headers=AUTH_HEADERS)
        r2 = await client.get("/api/v1/workspace/spatial/nodes", headers=AUTH_HEADERS)
        ids_1 = {n["id"] for n in r1.json()["nodes"] if n["landmark_kind"]}
        ids_2 = {n["id"] for n in r2.json()["nodes"] if n["landmark_kind"]}
        assert ids_1 == ids_2 and len(ids_1) == 4

    async def test_landmark_position_is_patchable(self, client):
        r = await client.get("/api/v1/workspace/spatial/nodes", headers=AUTH_HEADERS)
        hub = next(n for n in r.json()["nodes"] if n["landmark_kind"] == "attention_hub")
        patch = await client.patch(
            f"/api/v1/workspace/spatial/nodes/{hub['id']}",
            json={"world_x": 1234.0, "world_y": -567.0},
            headers=AUTH_HEADERS,
        )
        assert patch.status_code == 200, patch.text
        moved = patch.json()["node"]
        assert moved["landmark_kind"] == "attention_hub"
        assert moved["world_x"] == 1234.0
        assert moved["world_y"] == -567.0
        # Re-read confirms persistence.
        r2 = await client.get("/api/v1/workspace/spatial/nodes", headers=AUTH_HEADERS)
        again = next(n for n in r2.json()["nodes"] if n["landmark_kind"] == "attention_hub")
        assert (again["world_x"], again["world_y"]) == (1234.0, -567.0)
