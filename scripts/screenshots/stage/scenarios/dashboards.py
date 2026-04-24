"""Dashboard pin seeders.

Uses the friendly dashboard slug ``channel:<uuid>`` to target a channel's
implicit dashboard — the route ``/widgets/channel/<uuid>`` renders the same
underlying dashboard row.
"""
from __future__ import annotations

from .. import envelopes as env
from ..client import SpindrelClient


def dashboard_key_for_channel(channel_id: str) -> str:
    return f"channel:{channel_id}"


def pin_full_dashboard(
    client: SpindrelClient,
    *,
    channel_id: str,
    source_bot_id: str,
) -> list[str]:
    """Pin the 6-widget flagship dashboard for ``widget-dashboard.png``.

    Layout: 12-col grid, each pin 4 wide × 3 tall, two rows of three.
    """
    dashboard_key = dashboard_key_for_channel(channel_id)
    existing = {p.get("display_label"): p for p in client.list_pins(dashboard_key=dashboard_key)}

    specs = [
        ("Weather",            env.weather_sunny(),      {"x": 0, "y": 0, "w": 4, "h": 3}),
        ("Cameras",            env.frigate_cameras(),    {"x": 4, "y": 0, "w": 4, "h": 3}),
        ("Web search",         env.web_search_panel(),   {"x": 8, "y": 0, "w": 4, "h": 3}),
        ("Image",              env.image_card(),         {"x": 0, "y": 3, "w": 4, "h": 3}),
        ("Standing order",     env.standing_order_poll(),{"x": 4, "y": 3, "w": 4, "h": 3}),
        ("Architecture diagram", env.excalidraw_diagram(),{"x": 8, "y": 3, "w": 4, "h": 3}),
    ]

    ids: list[str] = []
    for label, envelope, grid in specs:
        if label in existing:
            ids.append(str(existing[label]["id"]))
            continue
        pin = client.create_pin(
            dashboard_key=dashboard_key,
            tool_name=envelope["widget_ref"].split("/", 1)[-1],
            envelope=envelope,
            source_kind="channel",
            source_channel_id=channel_id,
            source_bot_id=source_bot_id,
            display_label=label,
            zone="grid",
            grid_layout=grid,
        )
        ids.append(str(pin["id"]))
    return ids


def pin_chat_rail_widgets(
    client: SpindrelClient,
    *,
    channel_id: str,
    source_bot_id: str,
) -> list[str]:
    """Two rail-zone widgets for ``chat-main.png``/``omnipanel-mobile.png``."""
    dashboard_key = dashboard_key_for_channel(channel_id)
    existing = {p.get("display_label"): p for p in client.list_pins(dashboard_key=dashboard_key)}

    specs = [
        ("Rail weather", env.weather_sunny(),   {"x": 0, "y": 0, "w": 3, "h": 3}),
        ("Rail cameras", env.frigate_cameras(), {"x": 0, "y": 3, "w": 3, "h": 3}),
    ]
    ids: list[str] = []
    for label, envelope, grid in specs:
        if label in existing:
            ids.append(str(existing[label]["id"]))
            continue
        pin = client.create_pin(
            dashboard_key=dashboard_key,
            tool_name=envelope["widget_ref"].split("/", 1)[-1],
            envelope=envelope,
            source_kind="channel",
            source_channel_id=channel_id,
            source_bot_id=source_bot_id,
            display_label=label,
            zone="rail",
            grid_layout=grid,
        )
        ids.append(str(pin["id"]))
    return ids
