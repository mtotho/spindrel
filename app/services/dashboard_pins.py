"""CRUD helpers for the ``widget_dashboard_pins`` table.

Keeps the router thin and lets the widget-actions layer reuse the shared
config-patch helper without importing the router module (mirrors
``app/routers/api_v1_channels.py::apply_widget_config_patch``).
"""
from __future__ import annotations

import copy
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import WidgetDashboardPin


DEFAULT_DASHBOARD_KEY = "default"


_VALID_LAYOUT_KEYS = {"x", "y", "w", "h"}


def _default_grid_layout(position: int) -> dict[str, int]:
    """Compute a day-0 layout slot for a pin at the given position.

    Mirrors the backfill formula in migration 211 so newly-created pins
    (which bypass that migration) land on the grid consistently with existing
    rows.
    """
    return {
        "x": (position % 2) * 6,
        "y": (position // 2) * 6,
        "w": 6,
        "h": 6,
    }


def serialize_pin(pin: WidgetDashboardPin) -> dict[str, Any]:
    """Serialize a pin row to a JSON-safe dict for API responses."""
    return {
        "id": str(pin.id),
        "dashboard_key": pin.dashboard_key,
        "position": pin.position,
        "source_kind": pin.source_kind,
        "source_channel_id": str(pin.source_channel_id) if pin.source_channel_id else None,
        "source_bot_id": pin.source_bot_id,
        "tool_name": pin.tool_name,
        "tool_args": pin.tool_args or {},
        "widget_config": pin.widget_config or {},
        "envelope": pin.envelope or {},
        "display_label": pin.display_label,
        "grid_layout": pin.grid_layout or {},
        "pinned_at": pin.pinned_at.isoformat() if pin.pinned_at else None,
        "updated_at": pin.updated_at.isoformat() if pin.updated_at else None,
    }


async def list_pins(
    db: AsyncSession, *, dashboard_key: str = DEFAULT_DASHBOARD_KEY,
) -> list[WidgetDashboardPin]:
    rows = (await db.execute(
        select(WidgetDashboardPin)
        .where(WidgetDashboardPin.dashboard_key == dashboard_key)
        .order_by(WidgetDashboardPin.position.asc(), WidgetDashboardPin.pinned_at.asc())
    )).scalars().all()
    return list(rows)


async def _next_position(
    db: AsyncSession, *, dashboard_key: str,
) -> int:
    max_pos = (await db.execute(
        select(func.max(WidgetDashboardPin.position))
        .where(WidgetDashboardPin.dashboard_key == dashboard_key)
    )).scalar()
    return (max_pos + 1) if max_pos is not None else 0


async def create_pin(
    db: AsyncSession,
    *,
    source_kind: str,
    tool_name: str,
    envelope: dict,
    source_channel_id: uuid.UUID | None = None,
    source_bot_id: str | None = None,
    tool_args: dict | None = None,
    widget_config: dict | None = None,
    display_label: str | None = None,
    dashboard_key: str = DEFAULT_DASHBOARD_KEY,
) -> WidgetDashboardPin:
    if source_kind not in ("channel", "adhoc"):
        raise HTTPException(400, f"Invalid source_kind: {source_kind}")
    if not tool_name:
        raise HTTPException(400, "tool_name is required")
    if not isinstance(envelope, dict) or not envelope:
        raise HTTPException(400, "envelope must be a non-empty object")

    # Validate dashboard exists so we get a clean 404 (not an FK violation).
    # Imported lazily to avoid a module-level cycle with app.services.dashboards
    # which depends on us for DEFAULT_DASHBOARD_KEY.
    #
    # Channel dashboards (``channel:<uuid>``) are lazy-created on first pin —
    # users never "create" a channel dashboard; dropping the first widget on
    # one auto-allocates the WidgetDashboard row.
    from app.services.dashboards import (
        ensure_channel_dashboard,
        get_dashboard,
        is_channel_slug,
    )
    if is_channel_slug(dashboard_key):
        if source_channel_id is None:
            raise HTTPException(
                400,
                "source_channel_id is required when pinning to a channel dashboard",
            )
        await ensure_channel_dashboard(db, source_channel_id)
    await get_dashboard(db, dashboard_key)

    position = await _next_position(db, dashboard_key=dashboard_key)
    pin = WidgetDashboardPin(
        dashboard_key=dashboard_key,
        position=position,
        source_kind=source_kind,
        source_channel_id=source_channel_id,
        source_bot_id=source_bot_id,
        tool_name=tool_name,
        tool_args=tool_args or {},
        widget_config=widget_config or {},
        envelope=envelope,
        display_label=display_label or envelope.get("display_label"),
        grid_layout=_default_grid_layout(position),
    )
    db.add(pin)
    await db.flush()
    await db.commit()
    await db.refresh(pin)
    return pin


async def get_pin(
    db: AsyncSession, pin_id: uuid.UUID,
) -> WidgetDashboardPin:
    pin = (await db.execute(
        select(WidgetDashboardPin).where(WidgetDashboardPin.id == pin_id)
    )).scalar_one_or_none()
    if pin is None:
        raise HTTPException(404, "Dashboard pin not found")
    return pin


async def delete_pin(db: AsyncSession, pin_id: uuid.UUID) -> None:
    pin = await get_pin(db, pin_id)
    await db.delete(pin)
    await db.commit()


async def apply_dashboard_pin_config_patch(
    db: AsyncSession,
    pin_id: uuid.UUID,
    patch: dict,
    *,
    merge: bool = True,
) -> dict:
    """Shallow-merge (or replace) a pin's ``widget_config``.

    Mirrors ``app/routers/api_v1_channels.py::apply_widget_config_patch`` so
    the widget_config dispatch path can route to either surface by scope.
    Returns the serialized pin.
    """
    pin = await get_pin(db, pin_id)
    current = copy.deepcopy(pin.widget_config or {})
    pin.widget_config = {**current, **patch} if merge else dict(patch)
    flag_modified(pin, "widget_config")
    await db.commit()
    await db.refresh(pin)
    return serialize_pin(pin)


async def update_pin_envelope(
    db: AsyncSession,
    pin_id: uuid.UUID,
    envelope: dict,
) -> WidgetDashboardPin:
    pin = await get_pin(db, pin_id)
    pin.envelope = envelope
    pin.display_label = envelope.get("display_label") or pin.display_label
    flag_modified(pin, "envelope")
    await db.commit()
    await db.refresh(pin)
    return pin


async def rename_pin(
    db: AsyncSession,
    pin_id: uuid.UUID,
    display_label: str | None,
) -> dict[str, Any]:
    """Update just the pin's ``display_label`` (a table column, not JSONB).

    ``display_label`` is stored on the row so the dashboard header can show a
    user-chosen name without touching ``widget_config`` (which is widget-
    semantic). Pass ``None`` / empty string to clear it.
    """
    pin = await get_pin(db, pin_id)
    cleaned = (display_label or "").strip() or None
    pin.display_label = cleaned
    await db.commit()
    await db.refresh(pin)
    return serialize_pin(pin)


def _validate_layout_item(item: Any) -> tuple[uuid.UUID, dict[str, int]]:
    if not isinstance(item, dict):
        raise HTTPException(400, "layout item must be an object")
    raw_id = item.get("id")
    if not raw_id:
        raise HTTPException(400, "layout item missing 'id'")
    try:
        pin_id = uuid.UUID(str(raw_id))
    except ValueError as exc:
        raise HTTPException(400, f"Invalid pin id: {raw_id}") from exc
    coords: dict[str, int] = {}
    for key in _VALID_LAYOUT_KEYS:
        value = item.get(key)
        if not isinstance(value, int) or value < 0:
            raise HTTPException(
                400, f"layout item '{key}' must be a non-negative integer",
            )
        coords[key] = value
    return pin_id, coords


async def apply_layout_bulk(
    db: AsyncSession,
    items: list[dict[str, Any]],
    *,
    dashboard_key: str = DEFAULT_DASHBOARD_KEY,
) -> dict[str, Any]:
    """Persist ``{x, y, w, h}`` for a batch of pins in one transaction.

    All ids must belong to ``dashboard_key``; otherwise the whole call fails
    with 400 so we never commit a partial layout.
    """
    if not isinstance(items, list):
        raise HTTPException(400, "items must be a list")
    parsed = [_validate_layout_item(it) for it in items]
    if not parsed:
        return {"ok": True, "updated": 0}

    pin_ids = [pid for pid, _ in parsed]
    rows = (
        await db.execute(
            select(WidgetDashboardPin).where(
                WidgetDashboardPin.id.in_(pin_ids),
                WidgetDashboardPin.dashboard_key == dashboard_key,
            )
        )
    ).scalars().all()
    by_id = {row.id: row for row in rows}
    missing = [str(pid) for pid in pin_ids if pid not in by_id]
    if missing:
        raise HTTPException(400, f"Unknown pin ids: {missing}")

    for pin_id, coords in parsed:
        row = by_id[pin_id]
        row.grid_layout = coords
        flag_modified(row, "grid_layout")
    await db.commit()
    return {"ok": True, "updated": len(parsed)}
