"""Resolve channel dashboard pins into chat-side zone buckets.

Zone membership is stored directly on each pin (``widget_dashboard_pins.zone``)
and authored via the multi-canvas editor at ``/widgets/channel/:id``. This
module just groups pins by that column — the positional ``classify_pin``
classifier from earlier iterations is gone (see migration 226).
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WidgetDashboardPin


ChatZone = Literal["rail", "header", "dock", "grid"]


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
        "zone": pin.zone or "grid",
        "source_channel_id": str(pin.source_channel_id) if pin.source_channel_id else None,
        "source_bot_id": pin.source_bot_id,
        "is_main_panel": bool(pin.is_main_panel),
    }


async def resolve_chat_zones(
    db: AsyncSession, channel_id: uuid.UUID | str,
) -> dict[ChatZone, list[dict[str, Any]]]:
    """Return ``{rail, header, dock, grid}`` buckets for a channel.

    ``grid`` is included so callers can report it in debug surfaces; the HTTP
    endpoint strips it before returning to the client.

    Per-zone ordering:
      rail   — ``grid_layout.y`` then pin ``position``
      header — ``grid_layout.x`` (left-to-right in the chip row)
      dock   — ``grid_layout.y``
      grid   — pin ``position``
    """
    slug = f"channel:{channel_id}"

    rows = (await db.execute(
        select(WidgetDashboardPin)
        .where(WidgetDashboardPin.dashboard_key == slug)
        .order_by(WidgetDashboardPin.position.asc())
    )).scalars().all()

    buckets: dict[ChatZone, list[dict[str, Any]]] = {
        "rail": [], "header": [], "dock": [], "grid": [],
    }
    for row in rows:
        pin = _serialize_pin_for_zone(row)
        zone = pin["zone"] if pin["zone"] in buckets else "grid"
        buckets[zone].append(pin)

    def _y(p: dict[str, Any]) -> int:
        gl = p.get("grid_layout") or {}
        return gl.get("y", 0) if isinstance(gl, dict) else 0

    def _x(p: dict[str, Any]) -> int:
        gl = p.get("grid_layout") or {}
        return gl.get("x", 0) if isinstance(gl, dict) else 0

    buckets["rail"].sort(key=lambda p: (_y(p), p["position"]))
    buckets["dock"].sort(key=lambda p: (_y(p), p["position"]))
    buckets["header"].sort(key=lambda p: _x(p))
    return buckets
