"""End-to-end: pinning a widget from the catalog for each source kind.

Smokes the path the Add-widget sheet takes — POSTs a payload shaped the way
``AddFromChannelSheet.onPin`` builds it for ``builtin`` / ``integration`` /
``channel`` entries, against both a user dashboard (``default``) and a
channel dashboard (``channel:<uuid>``). Catches the 400 that comes from
forgetting ``source_channel_id`` on a channel-dashboard pin.
"""
from __future__ import annotations

import uuid

import pytest


AUTH_HEADERS = {"Authorization": "Bearer test-key"}

HTML_INTERACTIVE_CT = "application/vnd.spindrel.html+interactive"


def _builtin_envelope(path: str = "context_tracker/index.html") -> dict:
    """Envelope shape ``HtmlWidgetsTab.envelopeForEntry`` produces for a
    ``source="builtin"`` catalog entry."""
    return {
        "content_type": HTML_INTERACTIVE_CT,
        "body": "",
        "plain_body": "Context Tracker",
        "display": "inline",
        "truncated": False,
        "record_id": None,
        "byte_size": 0,
        "display_label": "Context Tracker",
        "source_path": path,
        "source_kind": "builtin",
        "source_bot_id": None,
    }


def _integration_envelope(
    integration_id: str = "frigate",
    path: str = "custom/dash.html",
) -> dict:
    return {
        "content_type": HTML_INTERACTIVE_CT,
        "body": "",
        "plain_body": "Frigate dashboard",
        "display": "inline",
        "truncated": False,
        "record_id": None,
        "byte_size": 0,
        "display_label": "Frigate dashboard",
        "source_path": path,
        "source_kind": "integration",
        "source_integration_id": integration_id,
        "source_bot_id": None,
    }


def _channel_envelope(channel_id: str, path: str = "data/widgets/foo/index.html") -> dict:
    return {
        "content_type": HTML_INTERACTIVE_CT,
        "body": "",
        "plain_body": "Channel widget",
        "display": "inline",
        "truncated": False,
        "record_id": None,
        "byte_size": 0,
        "display_label": "Channel widget",
        "source_path": path,
        "source_kind": "channel",
        "source_channel_id": channel_id,
        "source_bot_id": None,
    }


async def _ensure_channel(db):
    """Create a channel so channel-dashboard tests have a real FK target.

    Returns (channel_id_str, bot_id_str). Mirrors the pattern in existing
    dashboard pin tests that seed a channel for their fixtures.
    """
    from app.db.models import Bot, Channel

    bot = Bot(
        id="catalog-test-bot",
        name="catalog-test-bot",
        model="noop",
    )
    db.add(bot)
    await db.flush()
    ch = Channel(
        id=uuid.uuid4(),
        bot_id=bot.id,
        name="catalog-test-channel",
    )
    db.add(ch)
    await db.commit()
    return str(ch.id), bot.id


class TestPinFromCatalog_UserDashboard:
    @pytest.mark.asyncio
    async def test_pin_builtin_to_user_dashboard(self, client):
        r = await client.post(
            "/api/v1/widgets/dashboard/pins",
            json={
                "source_kind": "adhoc",
                "source_channel_id": None,
                "source_bot_id": None,
                "tool_name": "emit_html_widget",
                "tool_args": {"source": "builtin", "path": "context_tracker/index.html"},
                "envelope": _builtin_envelope(),
                "display_label": "Context Tracker",
                "dashboard_key": "default",
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        created = r.json()
        assert created["tool_name"] == "emit_html_widget"
        assert created["envelope"]["source_kind"] == "builtin"

    @pytest.mark.asyncio
    async def test_pin_integration_to_user_dashboard(self, client):
        r = await client.post(
            "/api/v1/widgets/dashboard/pins",
            json={
                "source_kind": "adhoc",
                "source_channel_id": None,
                "source_bot_id": None,
                "tool_name": "emit_html_widget",
                "tool_args": {
                    "source": "integration",
                    "integration_id": "frigate",
                    "path": "custom/dash.html",
                },
                "envelope": _integration_envelope(),
                "display_label": "Frigate dashboard",
                "dashboard_key": "default",
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        assert r.json()["envelope"]["source_integration_id"] == "frigate"


class TestPinFromCatalog_ChannelDashboard:
    """The regression we're pinning: pinning a built-in or integration widget
    to a channel dashboard needs ``source_channel_id`` at the pin row level
    (service-layer requirement) even though the envelope doesn't carry one."""

    @pytest.mark.asyncio
    async def test_pin_builtin_to_channel_dashboard_needs_source_channel_id(
        self, client, db_session,
    ):
        channel_id, _bot_id = await _ensure_channel(db_session)

        # Without ``source_channel_id`` at the pin row level the service-layer
        # guard fires: 400.
        bad = await client.post(
            "/api/v1/widgets/dashboard/pins",
            json={
                "source_kind": "adhoc",
                "source_channel_id": None,
                "source_bot_id": None,
                "tool_name": "emit_html_widget",
                "tool_args": {"source": "builtin", "path": "context_tracker/index.html"},
                "envelope": _builtin_envelope(),
                "display_label": "Context Tracker",
                "dashboard_key": f"channel:{channel_id}",
            },
            headers=AUTH_HEADERS,
        )
        assert bad.status_code == 400, bad.text
        assert "source_channel_id" in bad.text

        # With the channel id threaded through (matching the UI's fallback to
        # ``scopeChannelId``), the same pin succeeds.
        good = await client.post(
            "/api/v1/widgets/dashboard/pins",
            json={
                "source_kind": "adhoc",
                "source_channel_id": channel_id,
                "source_bot_id": None,
                "tool_name": "emit_html_widget",
                "tool_args": {"source": "builtin", "path": "context_tracker/index.html"},
                "envelope": _builtin_envelope(),
                "display_label": "Context Tracker",
                "dashboard_key": f"channel:{channel_id}",
            },
            headers=AUTH_HEADERS,
        )
        assert good.status_code == 200, good.text
        assert good.json()["source_channel_id"] == channel_id

    @pytest.mark.asyncio
    async def test_pin_channel_entry_to_channel_dashboard(
        self, client, db_session,
    ):
        """Channel-sourced entries already carry ``source_channel_id`` on the
        envelope — they work on channel dashboards without a fallback."""
        channel_id, _ = await _ensure_channel(db_session)
        r = await client.post(
            "/api/v1/widgets/dashboard/pins",
            json={
                "source_kind": "channel",
                "source_channel_id": channel_id,
                "source_bot_id": None,
                "tool_name": "emit_html_widget",
                "tool_args": {"path": f"/workspace/channels/{channel_id}/foo.html"},
                "envelope": _channel_envelope(channel_id),
                "display_label": "Channel widget",
                "dashboard_key": f"channel:{channel_id}",
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
