"""Integration tests for the chat-zones resolver and HTTP endpoint.

Zone membership is now stored directly on each pin (``widget_dashboard_pins.zone``)
and authored via the multi-canvas channel dashboard editor. The resolver is a
trivial group-by; these tests drive the moves through the layout API (which
accepts a ``zone`` field per-item).
"""
from __future__ import annotations

import uuid

import pytest

from app.db.models import Channel


AUTH_HEADERS = {"Authorization": "Bearer test-key"}


def _make_envelope(label: str = "pin") -> dict:
    return {
        "content_type": "application/vnd.spindrel.components+json",
        "body": "{\"v\":1,\"components\":[{\"type\":\"status\",\"text\":\"ok\"}]}",
        "plain_body": "ok",
        "display": "inline",
        "truncated": False,
        "record_id": None,
        "byte_size": 42,
        "display_label": label,
        "refreshable": True,
    }


async def _make_channel(db_session, name: str = "ch-zones") -> Channel:
    ch = Channel(id=uuid.uuid4(), name=name, bot_id="test-bot")
    db_session.add(ch)
    await db_session.commit()
    return ch


async def _pin_on_channel(client, ch_id, label: str = "pin") -> str:
    r = await client.post(
        "/api/v1/widgets/dashboard/pins",
        json={
            "source_kind": "channel",
            "source_channel_id": str(ch_id),
            "tool_name": "HassTurnOn",
            "envelope": _make_envelope(label),
            "dashboard_key": f"channel:{ch_id}",
        },
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _move_to_zone(
    client, ch_id, pin_id: str, zone: str,
    x: int = 0, y: int = 0, w: int = 1, h: int = 6,
):
    r = await client.post(
        "/api/v1/widgets/dashboard/pins/layout",
        json={
            "dashboard_key": f"channel:{ch_id}",
            "items": [{"id": pin_id, "zone": zone, "x": x, "y": y, "w": w, "h": h}],
        },
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200, r.text


class TestChatZonesEndpoint:
    @pytest.mark.asyncio
    async def test_404_on_unknown_channel(self, client):
        r = await client.get(
            f"/api/v1/channels/{uuid.uuid4()}/chat-zones", headers=AUTH_HEADERS,
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_empty_channel(self, client, db_session):
        ch = await _make_channel(db_session)
        r = await client.get(
            f"/api/v1/channels/{ch.id}/chat-zones", headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data == {"rail": [], "header": [], "dock": []}

    @pytest.mark.asyncio
    async def test_new_channel_pins_default_to_grid(self, client, db_session):
        """Creating a pin on a channel dashboard lands it in the Grid (main)
        canvas by default — "Add widget" drops into the page the user is
        looking at; moves to Rail / Dock / Header happen via the zone chip."""
        ch = await _make_channel(db_session)
        pin_id = await _pin_on_channel(client, ch.id, "auto-grid")
        r = await client.get(
            f"/api/v1/channels/{ch.id}/chat-zones", headers=AUTH_HEADERS,
        )
        data = r.json()
        # Grid-zoned pins are dashboard-only — absent from the chat-zones
        # response across all three chat-side buckets.
        assert data == {"rail": [], "header": [], "dock": []}
        # The pin itself still exists on the dashboard, just not surfaced in
        # chat.
        _ = pin_id

    @pytest.mark.asyncio
    async def test_pin_in_header_zone(self, client, db_session):
        ch = await _make_channel(db_session)
        pin_id = await _pin_on_channel(client, ch.id, "chip-a")
        await _move_to_zone(client, ch.id, pin_id, "header", x=0, y=0, w=1, h=1)
        r = await client.get(
            f"/api/v1/channels/{ch.id}/chat-zones", headers=AUTH_HEADERS,
        )
        data = r.json()
        assert data["rail"] == []
        assert data["dock"] == []
        assert [p["id"] for p in data["header"]] == [pin_id]

    @pytest.mark.asyncio
    async def test_pin_in_dock_zone(self, client, db_session):
        ch = await _make_channel(db_session)
        pin_id = await _pin_on_channel(client, ch.id, "dock-a")
        await _move_to_zone(client, ch.id, pin_id, "dock", x=0, y=0, w=1, h=6)
        r = await client.get(
            f"/api/v1/channels/{ch.id}/chat-zones", headers=AUTH_HEADERS,
        )
        data = r.json()
        assert data["rail"] == []
        assert data["header"] == []
        assert [p["id"] for p in data["dock"]] == [pin_id]

    @pytest.mark.asyncio
    async def test_grid_zone_excluded(self, client, db_session):
        """Pins with zone='grid' are dashboard-only and absent from the response."""
        ch = await _make_channel(db_session)
        pin_id = await _pin_on_channel(client, ch.id, "grid-a")
        await _move_to_zone(client, ch.id, pin_id, "grid", x=0, y=0, w=3, h=6)
        r = await client.get(
            f"/api/v1/channels/{ch.id}/chat-zones", headers=AUTH_HEADERS,
        )
        assert r.json() == {"rail": [], "header": [], "dock": []}

    @pytest.mark.asyncio
    async def test_moving_pin_shifts_zone(self, client, db_session):
        ch = await _make_channel(db_session)
        pin_id = await _pin_on_channel(client, ch.id, "mover")

        await _move_to_zone(client, ch.id, pin_id, "dock")
        data = (await client.get(
            f"/api/v1/channels/{ch.id}/chat-zones", headers=AUTH_HEADERS,
        )).json()
        assert len(data["dock"]) == 1

        await _move_to_zone(client, ch.id, pin_id, "rail")
        data = (await client.get(
            f"/api/v1/channels/{ch.id}/chat-zones", headers=AUTH_HEADERS,
        )).json()
        assert len(data["rail"]) == 1
        assert data["dock"] == []

    @pytest.mark.asyncio
    async def test_header_chip_ordering_by_x(self, client, db_session):
        ch = await _make_channel(db_session)
        pin_a = await _pin_on_channel(client, ch.id, "a")
        pin_b = await _pin_on_channel(client, ch.id, "b")
        pin_c = await _pin_on_channel(client, ch.id, "c")
        await _move_to_zone(client, ch.id, pin_a, "header", x=7, y=0, w=1, h=1)
        await _move_to_zone(client, ch.id, pin_b, "header", x=4, y=0, w=1, h=1)
        await _move_to_zone(client, ch.id, pin_c, "header", x=5, y=0, w=1, h=1)

        chips = (await client.get(
            f"/api/v1/channels/{ch.id}/chat-zones", headers=AUTH_HEADERS,
        )).json()["header"]
        assert [c["id"] for c in chips] == [pin_b, pin_c, pin_a]

    @pytest.mark.asyncio
    async def test_invalid_zone_rejected(self, client, db_session):
        """The layout API rejects unknown zone values with 400."""
        ch = await _make_channel(db_session)
        pin_id = await _pin_on_channel(client, ch.id, "zp")
        r = await client.post(
            "/api/v1/widgets/dashboard/pins/layout",
            json={
                "dashboard_key": f"channel:{ch.id}",
                "items": [{"id": pin_id, "zone": "bogus", "x": 0, "y": 0, "w": 1, "h": 6}],
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 400
