"""Panel-mode promote/demote endpoints + the cascade rules around them.

P10 of the Widget Dashboard track. Panel mode lets a single HTML widget pin
claim the dashboard's main area while every other pin renders in the rail
strip; the constraint "at most one panel pin per dashboard" lives on a
partial unique index in Postgres and is enforced in service code so SQLite
tests still see the same behavior.
"""
from __future__ import annotations

import pytest


AUTH_HEADERS = {"Authorization": "Bearer test-key"}


def _envelope(label: str = "panel widget") -> dict:
    return {
        "content_type": "application/vnd.spindrel.html+interactive",
        "body": "<h1>panel</h1>",
        "plain_body": "panel",
        "display": "inline",
        "truncated": False,
        "record_id": None,
        "byte_size": 12,
        "display_label": label,
    }


async def _create_pin(client, label: str) -> dict:
    r = await client.post(
        "/api/v1/widgets/dashboard/pins",
        json={
            "source_kind": "adhoc",
            "tool_name": "emit_html_widget",
            "envelope": _envelope(label),
        },
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200, r.text
    return r.json()


class TestPromoteDemote:
    @pytest.mark.asyncio
    async def test_promote_sets_panel_flag_and_layout_mode(self, client):
        pin = await _create_pin(client, "primary")

        r = await client.post(
            f"/api/v1/widgets/dashboard/pins/{pin['id']}/promote-panel",
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["is_main_panel"] is True

        # Dashboard's grid_config now reflects panel mode.
        d = await client.get(
            "/api/v1/widgets/dashboards/default",
            headers=AUTH_HEADERS,
        )
        assert d.status_code == 200
        cfg = d.json()["grid_config"] or {}
        assert cfg.get("layout_mode") == "panel"

    @pytest.mark.asyncio
    async def test_promote_clears_other_panel_pin_atomically(self, client):
        first = await _create_pin(client, "first")
        second = await _create_pin(client, "second")

        await client.post(
            f"/api/v1/widgets/dashboard/pins/{first['id']}/promote-panel",
            headers=AUTH_HEADERS,
        )
        promote_second = await client.post(
            f"/api/v1/widgets/dashboard/pins/{second['id']}/promote-panel",
            headers=AUTH_HEADERS,
        )
        assert promote_second.status_code == 200, promote_second.text

        listing = await client.get(
            "/api/v1/widgets/dashboard", headers=AUTH_HEADERS,
        )
        pins = listing.json()["pins"]
        flags = {p["id"]: p["is_main_panel"] for p in pins}
        assert flags[first["id"]] is False
        assert flags[second["id"]] is True

    @pytest.mark.asyncio
    async def test_demote_clears_flag_and_reverts_mode(self, client):
        pin = await _create_pin(client, "primary")
        await client.post(
            f"/api/v1/widgets/dashboard/pins/{pin['id']}/promote-panel",
            headers=AUTH_HEADERS,
        )
        r = await client.delete(
            f"/api/v1/widgets/dashboard/pins/{pin['id']}/promote-panel",
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        assert r.json()["is_main_panel"] is False

        d = await client.get(
            "/api/v1/widgets/dashboards/default",
            headers=AUTH_HEADERS,
        )
        cfg = d.json()["grid_config"] or {}
        # No panel pin remaining → mode reverts so the dashboard renders as
        # a normal grid again instead of an empty main area.
        assert cfg.get("layout_mode") in (None, "grid")

    @pytest.mark.asyncio
    async def test_unpinning_panel_pin_reverts_mode(self, client):
        pin = await _create_pin(client, "primary")
        await client.post(
            f"/api/v1/widgets/dashboard/pins/{pin['id']}/promote-panel",
            headers=AUTH_HEADERS,
        )
        r = await client.delete(
            f"/api/v1/widgets/dashboard/pins/{pin['id']}",
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text

        d = await client.get(
            "/api/v1/widgets/dashboards/default",
            headers=AUTH_HEADERS,
        )
        cfg = d.json()["grid_config"] or {}
        assert cfg.get("layout_mode") in (None, "grid")

    @pytest.mark.asyncio
    async def test_serialized_pin_carries_is_main_panel_default_false(self, client):
        pin = await _create_pin(client, "alpha")
        # Out-of-band default should be False without any promote call.
        listing = await client.get(
            "/api/v1/widgets/dashboard", headers=AUTH_HEADERS,
        )
        rows = listing.json()["pins"]
        assert len(rows) == 1
        assert rows[0]["id"] == pin["id"]
        assert rows[0]["is_main_panel"] is False

    @pytest.mark.asyncio
    async def test_promote_unknown_pin_404(self, client):
        r = await client.post(
            "/api/v1/widgets/dashboard/pins/00000000-0000-0000-0000-000000000000/promote-panel",
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_promote_when_other_pins_exist_keeps_them(self, client):
        # Confirms the other pins still render — promotion only touches the
        # panel flag / layout mode; non-promoted pins are untouched. Catches
        # accidental cascading-delete style mistakes in the service layer.
        panel = await _create_pin(client, "panel")
        rail_a = await _create_pin(client, "rail-a")
        rail_b = await _create_pin(client, "rail-b")

        await client.post(
            f"/api/v1/widgets/dashboard/pins/{panel['id']}/promote-panel",
            headers=AUTH_HEADERS,
        )
        listing = await client.get(
            "/api/v1/widgets/dashboard", headers=AUTH_HEADERS,
        )
        ids = {p["id"] for p in listing.json()["pins"]}
        assert ids == {panel["id"], rail_a["id"], rail_b["id"]}
