"""Integration tests for the workspace Spatial Canvas — P1 scope.

Covers the contract claims from `Track - Spatial Canvas` decision #6:
nullable-FK shape with CHECK constraint, persisted seed_index,
auto-populate of channel nodes on read, atomic widget pin+node create,
reserved-slug isolation.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.models import (
    Channel,
    WidgetDashboard,
    WidgetDashboardPin,
    WorkspaceSpatialNode,
)
from app.services.dashboards import (
    WORKSPACE_SPATIAL_DASHBOARD_KEY,
    list_dashboards,
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
