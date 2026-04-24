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

    Layout: standard preset (12-col grid, 30px rows). Each tile is 4 wide ×
    10 tall — matches the ``M``/``L`` size-preset region (`ui/src/lib/
    dashboardGrid.ts`). Two rows of three; widgets get enough vertical room to
    render their body instead of clipping to the header.
    """
    dashboard_key = dashboard_key_for_channel(channel_id)
    existing = {p.get("display_label"): p for p in client.list_pins(dashboard_key=dashboard_key)}

    specs = [
        ("Notes",              env.notes(),              {"x": 0, "y": 0,  "w": 4, "h": 10}),
        ("Todos",              env.todos(),              {"x": 4, "y": 0,  "w": 4, "h": 10}),
        ("Usage forecast",     env.usage_forecast(),     {"x": 8, "y": 0,  "w": 4, "h": 10}),
        ("Upcoming activity",  env.upcoming_activity(),  {"x": 0, "y": 10, "w": 4, "h": 10}),
        ("Standing order",     env.standing_order_poll(),{"x": 4, "y": 10, "w": 4, "h": 10}),
        ("Machine control",    env.machine_control(),    {"x": 8, "y": 10, "w": 4, "h": 10}),
    ]

    ids: list[str] = []
    layout_patches: list[dict] = []
    for label, envelope, grid in specs:
        if label in existing:
            pin_id = str(existing[label]["id"])
            ids.append(pin_id)
            layout_patches.append({"id": pin_id, "zone": "grid", **grid})
            continue
        pin = client.create_pin(
            dashboard_key=dashboard_key,
            tool_name=envelope["body"]["widget_ref"].split("/", 1)[-1],
            envelope=envelope,
            source_kind="channel",
            source_channel_id=channel_id,
            source_bot_id=source_bot_id,
            display_label=label,
            zone="grid",
            grid_layout=grid,
        )
        ids.append(str(pin["id"]))
    # Reconcile existing-pin layouts — POST /pins doesn't update grid_layout
    # when the label already exists, so the first-run sizes can get stuck.
    if layout_patches:
        client.patch_pins_layout(dashboard_key=dashboard_key, items=layout_patches)
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
        ("Rail notes", env.notes(), {"x": 0, "y": 0, "w": 12, "h": 8}),
        ("Rail todos", env.todos(), {"x": 0, "y": 8, "w": 12, "h": 8}),
    ]
    ids: list[str] = []
    layout_patches: list[dict] = []
    for label, envelope, grid in specs:
        if label in existing:
            pin_id = str(existing[label]["id"])
            ids.append(pin_id)
            layout_patches.append({"id": pin_id, "zone": "rail", **grid})
            continue
        pin = client.create_pin(
            dashboard_key=dashboard_key,
            tool_name=envelope["body"]["widget_ref"].split("/", 1)[-1],
            envelope=envelope,
            source_kind="channel",
            source_channel_id=channel_id,
            source_bot_id=source_bot_id,
            display_label=label,
            zone="rail",
            grid_layout=grid,
        )
        ids.append(str(pin["id"]))
    if layout_patches:
        client.patch_pins_layout(dashboard_key=dashboard_key, items=layout_patches)
    return ids
