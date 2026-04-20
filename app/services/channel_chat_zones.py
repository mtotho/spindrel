"""Resolve channel dashboard pins into chat-side zone buckets.

Zone membership is pure-positional — derived from each pin's `grid_layout`
against the active `GridPreset`. See `classify_pin` for the rules.

Nothing here writes. Moving a pin between zones means rewriting its
`grid_layout` on the dashboard, which is already atomic via
`dashboard_pins.apply_layout_bulk`.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WidgetDashboard, WidgetDashboardPin
from app.services.grid_presets import GridPresetFields, resolve_preset


ChatZone = Literal["rail", "dock_right", "header_chip", "grid"]


def classify_pin(pin: dict[str, Any], preset: GridPresetFields) -> ChatZone:
    """Classify a serialized pin into a chat zone.

    Rule precedence (first match wins):
      1. ``rail``         — ``x < rail_zone_cols``  (existing isRailPin behaviour)
      2. ``dock_right``   — ``x >= cols_lg - dock_right_cols``
      3. ``header_chip``  — ``y == 0 and h == 1`` in the middle band
      4. ``grid``         — anything else (dashboard-only, not on chat)

    A pin with no/empty ``grid_layout`` classifies as ``grid``.
    """
    gl = pin.get("grid_layout") or {}
    if not isinstance(gl, dict):
        return "grid"
    x = gl.get("x")
    y = gl.get("y")
    h = gl.get("h")
    if not isinstance(x, int):
        return "grid"

    if x < preset.rail_zone_cols:
        return "rail"
    if x >= preset.cols_lg - preset.dock_right_cols:
        return "dock_right"
    if isinstance(y, int) and isinstance(h, int) and y == 0 and h == 1:
        return "header_chip"
    return "grid"


def _serialize_pin_for_zone(pin: WidgetDashboardPin) -> dict[str, Any]:
    """Minimal serialization for zone responses — mirrors dashboard_pins.serialize_pin
    fields chat consumers actually need."""
    return {
        "id": str(pin.id),
        "dashboard_key": pin.dashboard_key,
        "position": pin.position,
        "tool_name": pin.tool_name,
        "tool_args": pin.tool_args or {},
        "widget_config": pin.widget_config or {},
        "envelope": pin.envelope or {},
        "display_label": pin.display_label,
        "grid_layout": pin.grid_layout or {},
        "source_channel_id": str(pin.source_channel_id) if pin.source_channel_id else None,
        "source_bot_id": pin.source_bot_id,
        "is_main_panel": bool(pin.is_main_panel),
    }


async def resolve_chat_zones(
    db: AsyncSession, channel_id: uuid.UUID | str,
) -> dict[ChatZone, list[dict[str, Any]]]:
    """Return ``{rail, dock_right, header_chip, grid}`` buckets for a channel.

    ``grid`` is included so callers can report it in debug surfaces; the HTTP
    endpoint strips it before returning to the client.
    """
    slug = f"channel:{channel_id}"

    dashboard = (await db.execute(
        select(WidgetDashboard).where(WidgetDashboard.slug == slug)
    )).scalars().first()
    preset = resolve_preset(dashboard.grid_config if dashboard else None)

    rows = (await db.execute(
        select(WidgetDashboardPin)
        .where(WidgetDashboardPin.dashboard_key == slug)
        .order_by(WidgetDashboardPin.position.asc())
    )).scalars().all()

    buckets: dict[ChatZone, list[dict[str, Any]]] = {
        "rail": [], "dock_right": [], "header_chip": [], "grid": [],
    }
    for row in rows:
        pin = _serialize_pin_for_zone(row)
        zone = classify_pin(pin, preset)
        buckets[zone].append(pin)

    # Per-zone ordering:
    #   rail         — position (preserved from query order)
    #   dock_right   — y then x, stable across ties
    #   header_chip  — x ascending (left-to-right in the header row)
    #   grid         — position (query order)
    buckets["dock_right"].sort(
        key=lambda p: (
            (p["grid_layout"] or {}).get("y", 0),
            (p["grid_layout"] or {}).get("x", 0),
        )
    )
    buckets["header_chip"].sort(
        key=lambda p: (p["grid_layout"] or {}).get("x", 0)
    )
    return buckets
