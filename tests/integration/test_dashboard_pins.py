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


class TestRecentCallsSurfacesTemplatedTools:
    """``GET /api/v1/widgets/recent-calls`` — powers the "Add widget → Recent
    calls" tab. Must surface any tool with a registered widget template, not
    just tools whose raw result happens to be envelope-shaped."""

    @pytest.mark.asyncio
    async def test_template_rendered_tool_call_surfaces(
        self, client, db_session,
    ):
        """A tool call with a raw JSON payload + a registered widget template
        must appear, with the envelope rendered from the template."""
        import json
        from datetime import datetime, timezone
        from app.db.models import ToolCall
        from app.services import widget_templates

        # Register a minimal template so apply_widget_template succeeds.
        tool_name = "fake_weather_tool"
        widget_templates._widget_templates[tool_name] = {
            "content_type": "application/vnd.spindrel.components+json",
            "display": "inline",
            "template": {
                "v": 1,
                "components": [
                    {"type": "heading", "text": "Weather for {{location}}"},
                ],
            },
            "html_template_body": None,
            "transform": None,
            "display_label": "Weather: {{location}}",
            "state_poll": None,
            "default_config": {},
            "source": "test",
        }
        try:
            db_session.add(
                ToolCall(
                    id=uuid.uuid4(),
                    tool_name=tool_name,
                    tool_type="local",
                    arguments={"location": "Portland"},
                    # Raw JSON payload — NOT an envelope, just the data.
                    result=json.dumps({"location": "Portland", "temp_f": 64}),
                    status="done",
                    created_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await db_session.commit()

            r = await client.get(
                "/api/v1/widgets/recent-calls?limit=10",
                headers=AUTH_HEADERS,
            )
            assert r.status_code == 200, r.text
            calls = r.json()["calls"]
            assert any(c["tool_name"] == tool_name for c in calls), (
                "recent-calls should surface tools with registered templates "
                "even when the stored result isn't itself an envelope"
            )
            matching = next(c for c in calls if c["tool_name"] == tool_name)
            assert (
                matching["envelope"]["content_type"]
                == "application/vnd.spindrel.components+json"
            )
            assert matching["display_label"] == "Weather: Portland"
        finally:
            widget_templates._widget_templates.pop(tool_name, None)

    @pytest.mark.asyncio
    async def test_envelope_optin_wrapper_surfaces(self, client, db_session):
        """``emit_html_widget`` and bot-authored widget tools store results
        as ``{"_envelope": {...}, "llm": "..."}`` — must be unwrapped so
        the Recent calls tab surfaces them."""
        import json
        from datetime import datetime, timezone
        from app.db.models import ToolCall

        tool_name = "emit_html_widget"
        envelope_body = {
            "content_type": "application/vnd.spindrel.html+interactive",
            "body": "<div>hi</div>",
            "display": "inline",
            "display_label": "Hello widget",
            "plain_body": "hi",
        }
        db_session.add(
            ToolCall(
                id=uuid.uuid4(),
                tool_name=tool_name,
                tool_type="local",
                arguments={"html": "<div>hi</div>"},
                result=json.dumps({"_envelope": envelope_body, "llm": "Emitted."}),
                status="done",
                created_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
        )
        await db_session.commit()

        r = await client.get(
            "/api/v1/widgets/recent-calls?limit=10",
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        calls = r.json()["calls"]
        matching = [c for c in calls if c["tool_name"] == tool_name]
        assert matching, "_envelope opt-in wrapper must be unwrapped + surfaced"
        assert (
            matching[0]["envelope"]["content_type"]
            == "application/vnd.spindrel.html+interactive"
        )
        assert matching[0]["display_label"] == "Hello widget"

    @pytest.mark.asyncio
    async def test_non_templated_non_envelope_tool_is_skipped(
        self, client, db_session,
    ):
        """Tools without a template AND without envelope-shaped results
        should not appear (they aren't renderable as widgets)."""
        import json
        from datetime import datetime, timezone
        from app.db.models import ToolCall

        tool_name = f"plain_tool_{uuid.uuid4().hex[:8]}"
        db_session.add(
            ToolCall(
                id=uuid.uuid4(),
                tool_name=tool_name,
                tool_type="local",
                arguments={},
                result=json.dumps({"just": "data"}),
                status="done",
                created_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
        )
        await db_session.commit()

        r = await client.get(
            "/api/v1/widgets/recent-calls?limit=10",
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        calls = r.json()["calls"]
        assert not any(c["tool_name"] == tool_name for c in calls)
