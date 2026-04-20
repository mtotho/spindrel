"""Integration tests for the chat-zones resolver and HTTP endpoint."""
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


async def _set_layout(client, ch_id, pin_id: str, x: int, y: int, w: int, h: int):
    r = await client.post(
        "/api/v1/widgets/dashboard/pins/layout",
        json={
            "dashboard_key": f"channel:{ch_id}",
            "items": [{"id": pin_id, "x": x, "y": y, "w": w, "h": h}],
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
        assert data == {"rail": [], "dock_right": [], "header_chip": []}

    @pytest.mark.asyncio
    async def test_pin_in_rail_zone(self, client, db_session):
        ch = await _make_channel(db_session)
        pin_id = await _pin_on_channel(client, ch.id, "rail-a")
        # standard preset: railZoneCols=3 — x=1 is inside the rail band.
        await _set_layout(client, ch.id, pin_id, x=1, y=0, w=3, h=6)

        r = await client.get(
            f"/api/v1/channels/{ch.id}/chat-zones", headers=AUTH_HEADERS,
        )
        data = r.json()
        assert len(data["rail"]) == 1
        assert data["rail"][0]["id"] == pin_id
        assert data["dock_right"] == []
        assert data["header_chip"] == []

    @pytest.mark.asyncio
    async def test_pin_in_dock_zone(self, client, db_session):
        ch = await _make_channel(db_session)
        pin_id = await _pin_on_channel(client, ch.id, "dock-a")
        # standard preset: dock band starts at 12-3=9.
        await _set_layout(client, ch.id, pin_id, x=9, y=2, w=3, h=6)

        r = await client.get(
            f"/api/v1/channels/{ch.id}/chat-zones", headers=AUTH_HEADERS,
        )
        data = r.json()
        assert data["rail"] == []
        assert len(data["dock_right"]) == 1
        assert data["dock_right"][0]["id"] == pin_id

    @pytest.mark.asyncio
    async def test_pin_in_header_zone(self, client, db_session):
        ch = await _make_channel(db_session)
        pin_id = await _pin_on_channel(client, ch.id, "chip-a")
        # Top row (y=0, h=1) between rail and dock: x in [3,9)
        await _set_layout(client, ch.id, pin_id, x=5, y=0, w=2, h=1)

        r = await client.get(
            f"/api/v1/channels/{ch.id}/chat-zones", headers=AUTH_HEADERS,
        )
        data = r.json()
        assert data["rail"] == []
        assert data["dock_right"] == []
        assert len(data["header_chip"]) == 1
        assert data["header_chip"][0]["id"] == pin_id

    @pytest.mark.asyncio
    async def test_grid_pins_excluded(self, client, db_session):
        ch = await _make_channel(db_session)
        pin_id = await _pin_on_channel(client, ch.id, "grid-a")
        # Middle of the dashboard, y > 0: plain grid.
        await _set_layout(client, ch.id, pin_id, x=5, y=4, w=3, h=4)

        r = await client.get(
            f"/api/v1/channels/{ch.id}/chat-zones", headers=AUTH_HEADERS,
        )
        data = r.json()
        assert data == {"rail": [], "dock_right": [], "header_chip": []}

    @pytest.mark.asyncio
    async def test_moving_pin_shifts_zone(self, client, db_session):
        """Zone membership recomputes on every read — no stored `chat_zone` state."""
        ch = await _make_channel(db_session)
        pin_id = await _pin_on_channel(client, ch.id, "mover")

        # Start in dock
        await _set_layout(client, ch.id, pin_id, x=10, y=0, w=2, h=4)
        data = (await client.get(
            f"/api/v1/channels/{ch.id}/chat-zones", headers=AUTH_HEADERS,
        )).json()
        assert len(data["dock_right"]) == 1

        # Move to rail
        await _set_layout(client, ch.id, pin_id, x=0, y=0, w=3, h=4)
        data = (await client.get(
            f"/api/v1/channels/{ch.id}/chat-zones", headers=AUTH_HEADERS,
        )).json()
        assert len(data["rail"]) == 1
        assert data["dock_right"] == []

    @pytest.mark.asyncio
    async def test_header_chip_ordering_by_x(self, client, db_session):
        ch = await _make_channel(db_session)
        pin_a = await _pin_on_channel(client, ch.id, "a")
        pin_b = await _pin_on_channel(client, ch.id, "b")
        pin_c = await _pin_on_channel(client, ch.id, "c")
        # Drop them in header band out of order: x=7, x=4, x=5.
        await _set_layout(client, ch.id, pin_a, x=7, y=0, w=1, h=1)
        await _set_layout(client, ch.id, pin_b, x=4, y=0, w=1, h=1)
        await _set_layout(client, ch.id, pin_c, x=5, y=0, w=1, h=1)

        data = (await client.get(
            f"/api/v1/channels/{ch.id}/chat-zones", headers=AUTH_HEADERS,
        )).json()
        chips = data["header_chip"]
        assert [c["id"] for c in chips] == [pin_b, pin_c, pin_a]
