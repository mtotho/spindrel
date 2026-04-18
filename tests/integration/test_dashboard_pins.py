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
