"""Integration tests for the chat shelf resolver and HTTP endpoint.

New pins opt into chat via ``widget_config.show_in_chat_shelf``. Legacy
``rail/header/dock`` zones still map into the single shelf bucket so older
dashboard rows keep appearing beside chat until they are normalized.
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


async def _set_chat_shelf(client, pin_id: str, enabled: bool = True):
    r = await client.patch(
        f"/api/v1/widgets/dashboard/pins/{pin_id}/config",
        json={"config": {"show_in_chat_shelf": enabled}, "merge": True},
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
        """New pins are canvas-only until explicitly shown in the chat shelf."""
        ch = await _make_channel(db_session)
        pin_id = await _pin_on_channel(client, ch.id, "auto-grid")
        r = await client.get(
            f"/api/v1/channels/{ch.id}/chat-zones", headers=AUTH_HEADERS,
        )
        data = r.json()
        assert data == {"rail": [], "header": [], "dock": []}
        _ = pin_id

    @pytest.mark.asyncio
    async def test_pin_marked_for_chat_shelf_appears_in_rail_bucket(self, client, db_session):
        ch = await _make_channel(db_session)
        pin_id = await _pin_on_channel(client, ch.id, "shelf-a")
        await _set_chat_shelf(client, pin_id)
        r = await client.get(
            f"/api/v1/channels/{ch.id}/chat-zones", headers=AUTH_HEADERS,
        )
        data = r.json()
        assert [p["id"] for p in data["rail"]] == [pin_id]
        assert data["dock"] == []
        assert data["header"] == []

    @pytest.mark.asyncio
    async def test_legacy_panel_zones_fold_into_chat_shelf(self, client, db_session):
        ch = await _make_channel(db_session)
        header_id = await _pin_on_channel(client, ch.id, "header-a")
        dock_id = await _pin_on_channel(client, ch.id, "dock-a")
        await _move_to_zone(client, ch.id, header_id, "header", x=2, y=0, w=1, h=1)
        await _move_to_zone(client, ch.id, dock_id, "dock", x=0, y=1, w=1, h=6)
        r = await client.get(
            f"/api/v1/channels/{ch.id}/chat-zones", headers=AUTH_HEADERS,
        )
        data = r.json()
        assert data["header"] == []
        assert data["dock"] == []
        assert [p["id"] for p in data["rail"]] == [header_id, dock_id]

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
    async def test_legacy_move_to_grid_removes_from_chat_shelf(self, client, db_session):
        ch = await _make_channel(db_session)
        pin_id = await _pin_on_channel(client, ch.id, "mover")

        await _move_to_zone(client, ch.id, pin_id, "dock")
        data = (await client.get(
            f"/api/v1/channels/{ch.id}/chat-zones", headers=AUTH_HEADERS,
        )).json()
        assert len(data["rail"]) == 1

        await _move_to_zone(client, ch.id, pin_id, "grid")
        data = (await client.get(
            f"/api/v1/channels/{ch.id}/chat-zones", headers=AUTH_HEADERS,
        )).json()
        assert data["rail"] == []
        assert data["dock"] == []

    @pytest.mark.asyncio
    async def test_chat_shelf_ordering_by_y_then_position(self, client, db_session):
        ch = await _make_channel(db_session)
        pin_a = await _pin_on_channel(client, ch.id, "a")
        pin_b = await _pin_on_channel(client, ch.id, "b")
        pin_c = await _pin_on_channel(client, ch.id, "c")
        await _move_to_zone(client, ch.id, pin_a, "rail", x=0, y=7, w=1, h=1)
        await _move_to_zone(client, ch.id, pin_b, "rail", x=0, y=4, w=1, h=1)
        await _move_to_zone(client, ch.id, pin_c, "rail", x=0, y=5, w=1, h=1)

        shelf = (await client.get(
            f"/api/v1/channels/{ch.id}/chat-zones", headers=AUTH_HEADERS,
        )).json()["rail"]
        assert [p["id"] for p in shelf] == [pin_b, pin_c, pin_a]

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
