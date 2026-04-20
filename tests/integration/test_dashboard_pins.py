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


def _html_envelope(source_bot_id: str | None = None) -> dict:
    env = {
        "content_type": "application/vnd.spindrel.html+interactive",
        "body": "<div>hi</div>",
        "plain_body": "hi",
        "display": "inline",
        "truncated": False,
        "record_id": None,
        "byte_size": 12,
        "display_label": "HTML widget",
        "refreshable": True,
    }
    if source_bot_id is not None:
        env["source_bot_id"] = source_bot_id
    return env


async def _seed_bot(db_session, *, bot_id: str, with_api_key: bool = True, scopes=None):
    """Insert a minimal Bot row (+ ApiKey) for pin-identity tests."""
    from app.db.models import ApiKey, Bot
    key_id = None
    if with_api_key:
        from app.services.api_keys import create_api_key
        key, _ = await create_api_key(
            db_session,
            name=f"{bot_id}-key",
            scopes=list(scopes or ["chat"]),
            store_key_value=True,
        )
        key_id = key.id
    bot = Bot(
        id=bot_id,
        name=bot_id,
        display_name=bot_id,
        model="test/model",
        system_prompt="",
        api_key_id=key_id,
    )
    db_session.add(bot)
    await db_session.commit()
    await db_session.refresh(bot)
    return bot


class TestPinIdentityValidation:
    """Create-time guards on source_bot_id. Pin identity is write-once;
    create must validate, refresh must not mutate (see
    ``test_widget_actions_state_poll.TestRefreshIdentityGuard``)."""

    @pytest.mark.asyncio
    async def test_rejects_unknown_bot_id(self, client):
        r = await client.post(
            "/api/v1/widgets/dashboard/pins",
            json={
                "source_kind": "adhoc",
                "tool_name": "t",
                "envelope": _html_envelope(source_bot_id="ghost-bot"),
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 400, r.text
        assert "ghost-bot" in r.text

    @pytest.mark.asyncio
    async def test_rejects_html_pin_for_bot_without_api_key(
        self, client, db_session,
    ):
        await _seed_bot(db_session, bot_id="keyless-bot", with_api_key=False)
        r = await client.post(
            "/api/v1/widgets/dashboard/pins",
            json={
                "source_kind": "adhoc",
                "tool_name": "t",
                "envelope": _html_envelope(source_bot_id="keyless-bot"),
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 400, r.text
        assert "no API permissions" in r.text

    @pytest.mark.asyncio
    async def test_envelope_source_bot_id_wins_over_body(
        self, client, db_session, caplog,
    ):
        import logging
        await _seed_bot(db_session, bot_id="body-bot", with_api_key=True)
        await _seed_bot(db_session, bot_id="envelope-bot", with_api_key=True)
        caplog.set_level(logging.WARNING, logger="app.services.dashboard_pins")
        r = await client.post(
            "/api/v1/widgets/dashboard/pins",
            json={
                "source_kind": "adhoc",
                "tool_name": "t",
                "source_bot_id": "body-bot",
                "envelope": _html_envelope(source_bot_id="envelope-bot"),
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        assert r.json()["source_bot_id"] == "envelope-bot"
        assert any(
            "source_bot_id mismatch" in rec.message
            for rec in caplog.records
        )

    @pytest.mark.asyncio
    async def test_allows_null_source_bot_id(self, client):
        """Non-interactive pins without a bot identity stay allowed —
        matches the handoff decision that NULL is legitimate (pin with
        no iframe auth needs)."""
        r = await client.post(
            "/api/v1/widgets/dashboard/pins",
            json={
                "source_kind": "adhoc",
                "tool_name": "t",
                "envelope": _make_envelope("no-bot"),
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        assert r.json()["source_bot_id"] is None


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


class TestScopePatch:
    """``PATCH /dashboard/pins/{id}/scope`` flips a pin between user scope
    (``source_bot_id: null``) and bot scope (``source_bot_id: "<id>"``).

    Writes both the column and the envelope so the renderer's scope chip
    and the widget-token-mint path stay in lockstep.
    """

    @pytest.mark.asyncio
    async def test_flip_user_scope_to_bot(self, client, db_session):
        """User-scoped pin can be rescoped to a bot. Envelope updates too."""
        from app.db.models import ApiKey, Bot
        api_key = ApiKey(
            id=uuid.uuid4(),
            name="scope-key",
            key_hash="scope-hash",
            key_prefix="scope-",
            scopes=["chat"],
            is_active=True,
        )
        db_session.add(api_key)
        await db_session.flush()
        db_session.add(Bot(
            id="scope-bot",
            name="Scope Bot",
            display_name="Scope Bot",
            model="test/model",
            system_prompt="",
            api_key_id=api_key.id,
        ))
        await db_session.commit()

        create = await client.post(
            "/api/v1/widgets/dashboard/pins",
            json={
                "source_kind": "adhoc",
                "tool_name": "emit_html_widget",
                "envelope": _html_envelope(),
            },
            headers=AUTH_HEADERS,
        )
        pin_id = create.json()["id"]
        assert create.json()["source_bot_id"] is None

        r = await client.patch(
            f"/api/v1/widgets/dashboard/pins/{pin_id}/scope",
            json={"source_bot_id": "scope-bot"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        assert r.json()["source_bot_id"] == "scope-bot"
        assert r.json()["envelope"]["source_bot_id"] == "scope-bot"

    @pytest.mark.asyncio
    async def test_flip_bot_scope_to_user(self, client, db_session):
        """Bot-scoped pin can drop back to user scope. Envelope field is removed."""
        from app.db.models import ApiKey, Bot
        api_key = ApiKey(
            id=uuid.uuid4(),
            name="scope-key-2",
            key_hash="scope-hash-2",
            key_prefix="scope2-",
            scopes=["chat"],
            is_active=True,
        )
        db_session.add(api_key)
        await db_session.flush()
        db_session.add(Bot(
            id="drop-bot",
            name="Drop Bot",
            display_name="Drop Bot",
            model="test/model",
            system_prompt="",
            api_key_id=api_key.id,
        ))
        await db_session.commit()

        create = await client.post(
            "/api/v1/widgets/dashboard/pins",
            json={
                "source_kind": "adhoc",
                "tool_name": "emit_html_widget",
                "envelope": _html_envelope(source_bot_id="drop-bot"),
                "source_bot_id": "drop-bot",
            },
            headers=AUTH_HEADERS,
        )
        assert create.status_code == 200, create.text
        pin_id = create.json()["id"]
        assert create.json()["source_bot_id"] == "drop-bot"

        r = await client.patch(
            f"/api/v1/widgets/dashboard/pins/{pin_id}/scope",
            json={"source_bot_id": None},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        assert r.json()["source_bot_id"] is None
        assert "source_bot_id" not in r.json()["envelope"]

    @pytest.mark.asyncio
    async def test_unknown_bot_rejected(self, client):
        create = await client.post(
            "/api/v1/widgets/dashboard/pins",
            json={
                "source_kind": "adhoc",
                "tool_name": "emit_html_widget",
                "envelope": _html_envelope(),
            },
            headers=AUTH_HEADERS,
        )
        pin_id = create.json()["id"]

        r = await client.patch(
            f"/api/v1/widgets/dashboard/pins/{pin_id}/scope",
            json={"source_bot_id": "no-such-bot"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 404


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
        # First pin lands at origin with a 6x10 tile (half-width, ~300px tall).
        assert layout == {"x": 0, "y": 0, "w": 6, "h": 10}


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
