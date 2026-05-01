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
    """Pin the 5-widget flagship dashboard for ``widget-dashboard.png``.

    The channel-scoped dashboard renders ``ChannelDashboardMultiCanvas``,
    which reserves a fixed-width rail on the left and dock on the right
    regardless of pin contents. A pure-grid layout reads as "the dashboard
    is squeezed in the middle" because the rail and dock zones sit empty
    on either side. This layout pins widgets into all three zones so the
    full viewport reads as a populated dashboard:

      RAIL (left, fixed width):  Todos                — running checklist
      GRID (center, 12-col):     Notes (12w) + Standing order (12w) stacked
      DOCK (right, fixed width): Usage forecast + Upcoming activity stacked

    Every tile has a populated state seeded by
    ``_seed_widget_states_for_channel`` (see ``flagship.py``). Machine
    control is intentionally dropped — it's channel-session-scoped and
    renders a "no active session" placeholder until a chat session opens.
    """
    dashboard_key = dashboard_key_for_channel(channel_id)
    existing = {p.get("display_label"): p for p in client.list_pins(dashboard_key=dashboard_key)}

    # Drop pins that the prior layout placed but the current one doesn't
    # ship. Without this, reruns leak old "Machine control" placeholder tiles
    # into the screenshot.
    obsolete_labels = {"Machine control"}
    for label in obsolete_labels:
        pin = existing.get(label)
        if pin and pin.get("id"):
            try:
                client.delete_pin(str(pin["id"]))
            except Exception:
                pass
            existing.pop(label, None)

    # (label, envelope, zone, grid_layout)
    # Rail/dock are 1-col tracks — width is fixed by ``CHANNEL_PANEL_DEFAULT_WIDTH``,
    # so ``w`` doesn't matter (set to 1 by convention). Grid is the 12-col
    # center; full-width tiles use w=12.
    specs = [
        ("Todos",              env.todos(),              "rail", {"x": 0, "y": 0,  "w": 1, "h": 16}),
        ("Notes",              env.notes(),              "grid", {"x": 0, "y": 0,  "w": 12, "h": 16}),
        ("Standing order",     env.standing_order_poll(),"grid", {"x": 0, "y": 16, "w": 12, "h": 12}),
        ("Usage forecast",     env.usage_forecast(),     "dock", {"x": 0, "y": 0,  "w": 1, "h": 12}),
        ("Upcoming activity",  env.upcoming_activity(),  "dock", {"x": 0, "y": 12, "w": 1, "h": 12}),
    ]

    ids: list[str] = []
    layout_patches: list[dict] = []
    for label, envelope, zone, grid in specs:
        if label in existing:
            pin_id = str(existing[label]["id"])
            ids.append(pin_id)
            layout_patches.append({"id": pin_id, "zone": zone, **grid})
            continue
        pin = client.create_pin(
            dashboard_key=dashboard_key,
            tool_name=envelope["body"]["widget_ref"].split("/", 1)[-1],
            envelope=envelope,
            source_kind="channel",
            source_channel_id=channel_id,
            source_bot_id=source_bot_id,
            display_label=label,
            zone=zone,
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
        ("Notes", env.notes(), {"x": 0, "y": 0, "w": 12, "h": 8}),
        ("Todos", env.todos(), {"x": 0, "y": 8, "w": 12, "h": 8}),
    ]
    legacy_labels = {
        "Notes": "Rail notes",
        "Todos": "Rail todos",
    }
    ids: list[str] = []
    layout_patches: list[dict] = []
    for label, envelope, grid in specs:
        if label in existing:
            pin_id = str(existing[label]["id"])
            ids.append(pin_id)
            layout_patches.append({"id": pin_id, "zone": "rail", **grid})
            continue
        legacy = existing.get(legacy_labels[label])
        if legacy:
            pin_id = str(legacy["id"])
            client.rename_pin(pin_id, label)
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
