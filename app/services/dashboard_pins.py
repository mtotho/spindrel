"""CRUD helpers for the ``widget_dashboard_pins`` table.

Keeps the router thin and lets the widget-actions layer reuse the shared
config-patch helper without importing the router module (mirrors
``app/routers/api_v1_channels.py::apply_widget_config_patch``).
"""
from __future__ import annotations

import copy
import logging
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import ApiKey, Bot, WidgetDashboardPin

logger = logging.getLogger(__name__)


DEFAULT_DASHBOARD_KEY = "default"

# Envelope content_type that renders inside the bot-authenticated iframe.
# Pins of this type need a resolvable bot with an active API key; any other
# content_type renders without needing ``/widget-auth/mint``.
_HTML_INTERACTIVE_CT = "application/vnd.spindrel.html+interactive"


_VALID_LAYOUT_KEYS = {"x", "y", "w", "h"}


def _default_grid_layout(position: int, *, channel: bool = False) -> dict[str, int]:
    """Compute a day-0 layout slot for a pin at the given position.

    User dashboards alternate two columns (mirrors migration 211's backfill
    formula). Channel dashboards stack pins vertically at ``x=0`` — chat
    pins are almost always intended to surface in the channel sidebar,
    and the OmniPanel's rail rule (`x < railZoneCols`) picks up anything
    whose left edge is in the left half of the grid. Width stays at the
    standard 6 cols so the widget renders the same on the dashboard as
    every other pin; the user can drag it out of the rail later.
    """
    if channel:
        return {"x": 0, "y": position * 6, "w": 6, "h": 6}
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
        "is_main_panel": bool(pin.is_main_panel),
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

    # Pin identity rule: the envelope's source_bot_id is stamped from
    # current_bot_id at emission time — that's the authoritative bot. Any
    # source_bot_id arg passed separately is a UI signal that can lag
    # behind (stale store, missing field, fallback literal). Prefer the
    # envelope; warn on mismatch so future UI drift is visible in logs.
    envelope_bot_id = envelope.get("source_bot_id")
    if envelope_bot_id and source_bot_id and envelope_bot_id != source_bot_id:
        logger.warning(
            "create_pin source_bot_id mismatch: envelope=%s body=%s — using envelope",
            envelope_bot_id, source_bot_id,
        )
    resolved_bot_id: str | None = envelope_bot_id or source_bot_id

    # Validate the bot. NULL is allowed (pin without iframe auth needs). A
    # non-null value must resolve to a real bot; interactive-HTML pins also
    # require an active API key (otherwise /widget-auth/mint 400s on every
    # refresh forever — silent-persist of a permanently broken pin).
    if resolved_bot_id is not None:
        bot = await db.get(Bot, resolved_bot_id)
        if bot is None:
            raise HTTPException(400, f"Unknown source_bot_id: {resolved_bot_id!r}")
        if envelope.get("content_type") == _HTML_INTERACTIVE_CT:
            bot_label = bot.display_name or bot.name or bot.id
            if bot.api_key_id is None:
                raise HTTPException(
                    400,
                    f"Bot '{bot_label}' has no API permissions — interactive "
                    "widgets need an API key to mint iframe tokens. Grant "
                    f"scopes under Admin → Bots → {bot_label} → Permissions.",
                )
            api_key = await db.get(ApiKey, bot.api_key_id)
            if api_key is None or not api_key.is_active:
                raise HTTPException(
                    400,
                    f"Bot '{bot_label}' has an inactive API key — interactive "
                    "widgets need one to mint iframe tokens. Re-enable under "
                    f"Admin → Bots → {bot_label} → Permissions.",
                )
    source_bot_id = resolved_bot_id

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
    is_channel = is_channel_slug(dashboard_key)
    if is_channel:
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
        grid_layout=_default_grid_layout(position, channel=is_channel),
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
    was_panel = bool(pin.is_main_panel)
    dashboard_key = pin.dashboard_key
    await db.delete(pin)
    await db.flush()
    if was_panel:
        # Removing the dashboard's only panel pin reverts it to normal grid
        # mode — otherwise the renderer would show an empty main area.
        await _set_dashboard_layout_mode(db, dashboard_key, None)
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


async def _set_dashboard_layout_mode(
    db: AsyncSession, dashboard_key: str, mode: str | None,
) -> None:
    """Read-modify-write ``WidgetDashboard.grid_config.layout_mode``.

    ``mode=None`` removes the key entirely (treated as default ``"grid"``).
    Lazy import of dashboards service to avoid the module-level cycle.
    """
    from app.db.models import WidgetDashboard
    row = (await db.execute(
        select(WidgetDashboard).where(WidgetDashboard.slug == dashboard_key)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"Dashboard not found: {dashboard_key}")
    cfg = copy.deepcopy(row.grid_config or {})
    if mode is None:
        cfg.pop("layout_mode", None)
    else:
        cfg["layout_mode"] = mode
    row.grid_config = cfg or None
    flag_modified(row, "grid_config")
    await db.flush()


async def promote_pin_to_panel(
    db: AsyncSession, pin_id: uuid.UUID,
) -> dict[str, Any]:
    """Make ``pin_id`` the panel pin for its dashboard.

    Atomic: clears ``is_main_panel`` on every other pin in the same dashboard
    first, then sets it on this pin, then flips ``grid_config.layout_mode`` to
    ``"panel"``. Returns the serialized promoted pin.
    """
    pin = await get_pin(db, pin_id)
    # Clear any existing panel pin in this dashboard (the partial unique
    # index would otherwise reject the SET below on Postgres).
    others = (await db.execute(
        select(WidgetDashboardPin)
        .where(
            WidgetDashboardPin.dashboard_key == pin.dashboard_key,
            WidgetDashboardPin.is_main_panel == True,  # noqa: E712 - SQL boolean
            WidgetDashboardPin.id != pin.id,
        )
    )).scalars().all()
    for other in others:
        other.is_main_panel = False
    # Flush the clears before setting the new one so the partial unique
    # index never sees two TRUE rows in the same statement window.
    if others:
        await db.flush()
    pin.is_main_panel = True
    await _set_dashboard_layout_mode(db, pin.dashboard_key, "panel")
    await db.commit()
    await db.refresh(pin)
    return serialize_pin(pin)


async def demote_pin_from_panel(
    db: AsyncSession, pin_id: uuid.UUID,
) -> dict[str, Any]:
    """Clear ``is_main_panel`` on ``pin_id``.

    If this leaves the dashboard with no panel pin, ``grid_config.layout_mode``
    is reverted to ``"grid"`` (so the dashboard renders as a normal RGL grid
    again instead of an empty panel area).
    """
    pin = await get_pin(db, pin_id)
    pin.is_main_panel = False
    await db.flush()

    remaining = (await db.execute(
        select(func.count())
        .select_from(WidgetDashboardPin)
        .where(
            WidgetDashboardPin.dashboard_key == pin.dashboard_key,
            WidgetDashboardPin.is_main_panel == True,  # noqa: E712
        )
    )).scalar() or 0
    if remaining == 0:
        await _set_dashboard_layout_mode(db, pin.dashboard_key, None)
    await db.commit()
    await db.refresh(pin)
    return serialize_pin(pin)


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
