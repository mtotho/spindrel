"""Integration tests for the widget-dashboard pin endpoints (Phase 2).

Covers the GET/POST/DELETE/PATCH endpoints under
``/api/v1/widgets/dashboard`` plus the refresh round-trip through the
existing state_poll machinery.
"""
from __future__ import annotations

import uuid

import pytest


AUTH_HEADERS = {"Authorization": "Bearer test-key"}


def _make_envelope(display_label: str = "Living Room Light") -> dict:
    return {
        "content_type": "application/vnd.spindrel.components+json",
        "body": "{\"v\":1,\"components\":[{\"type\":\"status\",\"text\":\"on\"}]}",
        "plain_body": "on",
        "display": "inline",
        "truncated": False,
        "record_id": None,
        "byte_size": 42,
        "display_label": display_label,
        "refreshable": True,
    }


class TestCRUD:
    @pytest.mark.asyncio
    async def test_empty_dashboard(self, client):
        r = await client.get("/api/v1/widgets/dashboard", headers=AUTH_HEADERS)
        assert r.status_code == 200, r.text
        assert r.json() == {"pins": []}

    @pytest.mark.asyncio
    async def test_create_and_list(self, client):
        create = await client.post(
            "/api/v1/widgets/dashboard/pins",
            json={
                "source_kind": "adhoc",
                "tool_name": "HassTurnOn",
                "envelope": _make_envelope("Kitchen Light"),
                "tool_args": {"entity_id": "light.kitchen"},
                "widget_config": {"show_forecast": False},
            },
            headers=AUTH_HEADERS,
        )
        assert create.status_code == 200, create.text
        created = create.json()
        assert created["source_kind"] == "adhoc"
        assert created["position"] == 0
        assert created["display_label"] == "Kitchen Light"
        assert created["widget_config"] == {"show_forecast": False}

        listing = await client.get("/api/v1/widgets/dashboard", headers=AUTH_HEADERS)
        pins = listing.json()["pins"]
        assert len(pins) == 1
        assert pins[0]["id"] == created["id"]

    @pytest.mark.asyncio
    async def test_positions_increment(self, client):
        for i in range(3):
            r = await client.post(
                "/api/v1/widgets/dashboard/pins",
                json={
                    "source_kind": "adhoc",
                    "tool_name": f"tool_{i}",
                    "envelope": _make_envelope(f"pin-{i}"),
                },
                headers=AUTH_HEADERS,
            )
            assert r.status_code == 200
            assert r.json()["position"] == i

    @pytest.mark.asyncio
    async def test_rejects_bad_source_kind(self, client):
        r = await client.post(
            "/api/v1/widgets/dashboard/pins",
            json={
                "source_kind": "garbage",
                "tool_name": "x",
                "envelope": _make_envelope(),
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_rejects_empty_envelope(self, client):
        r = await client.post(
            "/api/v1/widgets/dashboard/pins",
            json={"source_kind": "adhoc", "tool_name": "x", "envelope": {}},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_delete(self, client):
        create = await client.post(
            "/api/v1/widgets/dashboard/pins",
            json={
                "source_kind": "adhoc",
                "tool_name": "t",
                "envelope": _make_envelope(),
            },
            headers=AUTH_HEADERS,
        )
        pin_id = create.json()["id"]

        r = await client.delete(
            f"/api/v1/widgets/dashboard/pins/{pin_id}",
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

        listing = await client.get("/api/v1/widgets/dashboard", headers=AUTH_HEADERS)
        assert listing.json()["pins"] == []

    @pytest.mark.asyncio
    async def test_delete_404(self, client):
        r = await client.delete(
            f"/api/v1/widgets/dashboard/pins/{uuid.uuid4()}",
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 404


class TestConfigPatch:
    @pytest.mark.asyncio
    async def test_merges_config(self, client):
        create = await client.post(
            "/api/v1/widgets/dashboard/pins",
            json={
                "source_kind": "adhoc",
                "tool_name": "OpenWeather",
                "envelope": _make_envelope("Paris"),
                "widget_config": {"show_forecast": False, "units": "metric"},
            },
            headers=AUTH_HEADERS,
        )
        pin_id = create.json()["id"]

        patched = await client.patch(
            f"/api/v1/widgets/dashboard/pins/{pin_id}/config",
            json={"config": {"show_forecast": True}, "merge": True},
            headers=AUTH_HEADERS,
        )
        assert patched.status_code == 200
        body = patched.json()
        assert body["widget_config"] == {"show_forecast": True, "units": "metric"}

    @pytest.mark.asyncio
    async def test_replace_config(self, client):
        create = await client.post(
            "/api/v1/widgets/dashboard/pins",
            json={
                "source_kind": "adhoc",
                "tool_name": "OpenWeather",
                "envelope": _make_envelope(),
                "widget_config": {"a": 1, "b": 2},
            },
            headers=AUTH_HEADERS,
        )
        pin_id = create.json()["id"]

        patched = await client.patch(
            f"/api/v1/widgets/dashboard/pins/{pin_id}/config",
            json={"config": {"c": 3}, "merge": False},
            headers=AUTH_HEADERS,
        )
        assert patched.status_code == 200
        assert patched.json()["widget_config"] == {"c": 3}


class TestMetadataPatch:
    @pytest.mark.asyncio
    async def test_rename_pin(self, client):
        create = await client.post(
            "/api/v1/widgets/dashboard/pins",
            json={
                "source_kind": "adhoc",
                "tool_name": "t",
                "envelope": _make_envelope("Old Label"),
            },
            headers=AUTH_HEADERS,
        )
        pin_id = create.json()["id"]

        r = await client.patch(
            f"/api/v1/widgets/dashboard/pins/{pin_id}",
            json={"display_label": "New Label"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        assert r.json()["display_label"] == "New Label"

    @pytest.mark.asyncio
    async def test_rename_empty_clears(self, client):
        create = await client.post(
            "/api/v1/widgets/dashboard/pins",
            json={
                "source_kind": "adhoc",
                "tool_name": "t",
                "envelope": _make_envelope("Kept"),
            },
            headers=AUTH_HEADERS,
        )
        pin_id = create.json()["id"]

        r = await client.patch(
            f"/api/v1/widgets/dashboard/pins/{pin_id}",
            json={"display_label": "   "},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        assert r.json()["display_label"] is None


class TestLayoutBulk:
    @pytest.mark.asyncio
    async def test_layout_round_trip(self, client):
        # Seed 3 pins.
        ids = []
        for i in range(3):
            r = await client.post(
                "/api/v1/widgets/dashboard/pins",
                json={
                    "source_kind": "adhoc",
                    "tool_name": f"t{i}",
                    "envelope": _make_envelope(f"p{i}"),
                },
                headers=AUTH_HEADERS,
            )
            ids.append(r.json()["id"])

        items = [
            {"id": ids[0], "x": 0, "y": 0, "w": 4, "h": 3},
            {"id": ids[1], "x": 4, "y": 0, "w": 4, "h": 3},
            {"id": ids[2], "x": 0, "y": 3, "w": 8, "h": 6},
        ]
        r = await client.post(
            "/api/v1/widgets/dashboard/pins/layout",
            json={"items": items},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True, "updated": 3}

        listing = await client.get("/api/v1/widgets/dashboard", headers=AUTH_HEADERS)
        pins_by_id = {p["id"]: p for p in listing.json()["pins"]}
        for item in items:
            layout = pins_by_id[item["id"]]["grid_layout"]
            assert layout == {"x": item["x"], "y": item["y"], "w": item["w"], "h": item["h"]}

    @pytest.mark.asyncio
    async def test_layout_rejects_unknown_ids(self, client):
        create = await client.post(
            "/api/v1/widgets/dashboard/pins",
            json={
                "source_kind": "adhoc",
                "tool_name": "t",
                "envelope": _make_envelope(),
            },
            headers=AUTH_HEADERS,
        )
        pin_id = create.json()["id"]

        r = await client.post(
            "/api/v1/widgets/dashboard/pins/layout",
            json={
                "items": [
                    {"id": pin_id, "x": 0, "y": 0, "w": 4, "h": 4},
                    {"id": str(uuid.uuid4()), "x": 4, "y": 0, "w": 4, "h": 4},
                ],
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 400
        assert "Unknown pin ids" in r.text

        # Nothing was committed for the valid id either (atomic failure).
        listing = await client.get("/api/v1/widgets/dashboard", headers=AUTH_HEADERS)
        assert listing.json()["pins"][0]["grid_layout"] != {"x": 0, "y": 0, "w": 4, "h": 4}

    @pytest.mark.asyncio
    async def test_new_pin_has_default_layout(self, client):
        r = await client.post(
            "/api/v1/widgets/dashboard/pins",
            json={
                "source_kind": "adhoc",
                "tool_name": "t",
                "envelope": _make_envelope(),
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        layout = r.json()["grid_layout"]
        # First pin lands at origin with a 6x6 tile.
        assert layout == {"x": 0, "y": 0, "w": 6, "h": 6}


class TestRefresh:
    @pytest.mark.asyncio
    async def test_refresh_without_state_poll_400(self, client):
        create = await client.post(
            "/api/v1/widgets/dashboard/pins",
            json={
                "source_kind": "adhoc",
                "tool_name": "nonexistent_tool_xyz",
                "envelope": _make_envelope(),
            },
            headers=AUTH_HEADERS,
        )
        pin_id = create.json()["id"]

        r = await client.post(
            f"/api/v1/widgets/dashboard/pins/{pin_id}/refresh",
            headers=AUTH_HEADERS,
        )
        # No state_poll registered for a made-up tool → 400.
        assert r.status_code == 400


class TestChannelPinsBatchEndpoint:
    """``GET /api/v1/widgets/dashboards/channel-pins`` — powers the
    "Add widget → From channel" tab on the global dashboard."""

    @pytest.mark.asyncio
    async def test_empty(self, client):
        r = await client.get(
            "/api/v1/widgets/dashboards/channel-pins", headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"channels": []}

    @pytest.mark.asyncio
    async def test_groups_and_names_channels(self, client, db_session):
        from app.db.models import Channel

        ch_a = Channel(id=uuid.uuid4(), name="Bravo Channel", bot_id="test-bot")
        ch_b = Channel(id=uuid.uuid4(), name="Alpha Channel", bot_id="test-bot")
        db_session.add_all([ch_a, ch_b])
        await db_session.commit()

        # Seed the channel dashboards by pinning to their slugs.
        for ch in (ch_a, ch_b):
            r = await client.post(
                "/api/v1/widgets/dashboard/pins?",
                params={"slug": f"channel:{ch.id}"},
                json={
                    "source_kind": "channel",
                    "source_channel_id": str(ch.id),
                    "tool_name": "HassTurnOn",
                    "envelope": _make_envelope(f"{ch.name} pin"),
                    "dashboard_key": f"channel:{ch.id}",
                },
                headers=AUTH_HEADERS,
            )
            assert r.status_code == 200, r.text

        r = await client.get(
            "/api/v1/widgets/dashboards/channel-pins", headers=AUTH_HEADERS,
        )
        data = r.json()
        assert len(data["channels"]) == 2
        # Alpha sorts before Bravo case-insensitively.
        assert data["channels"][0]["channel_name"] == "Alpha Channel"
        assert data["channels"][1]["channel_name"] == "Bravo Channel"
        assert data["channels"][0]["dashboard_slug"] == f"channel:{ch_b.id}"
        assert len(data["channels"][0]["pins"]) == 1
        assert data["channels"][0]["pins"][0]["tool_name"] == "HassTurnOn"

    @pytest.mark.asyncio
    async def test_excludes_empty_channel_dashboards(self, client, db_session):
        from app.db.models import Channel
        from app.services.dashboards import ensure_channel_dashboard

        ch = Channel(id=uuid.uuid4(), name="Empty Channel", bot_id="test-bot")
        db_session.add(ch)
        await db_session.commit()
        # Create the dashboard row but no pins on it.
        await ensure_channel_dashboard(db_session, str(ch.id))
        await db_session.commit()

        r = await client.get(
            "/api/v1/widgets/dashboards/channel-pins", headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        assert r.json() == {"channels": []}

    @pytest.mark.asyncio
    async def test_excludes_user_dashboards(self, client):
        # Pin to the default (non-channel) dashboard — the batch endpoint
        # must filter it out.
        r = await client.post(
            "/api/v1/widgets/dashboard/pins",
            json={
                "source_kind": "adhoc",
                "tool_name": "HassTurnOn",
                "envelope": _make_envelope("default pin"),
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200

        r = await client.get(
            "/api/v1/widgets/dashboards/channel-pins", headers=AUTH_HEADERS,
        )
        assert r.json() == {"channels": []}
