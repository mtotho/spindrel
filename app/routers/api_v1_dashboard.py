"""Widget dashboards — chat-less homes for pinned widgets.

Endpoints live under ``/api/v1/widgets``:
- ``/api/v1/widgets/dashboards`` — list/create/update/delete named dashboards
- ``/api/v1/widgets/dashboard`` — pin CRUD scoped by ``?slug=``
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_scopes
from app.services.dashboard_pins import (
    DEFAULT_DASHBOARD_KEY,
    apply_dashboard_pin_config_patch,
    apply_layout_bulk,
    create_pin,
    delete_pin,
    get_pin,
    list_pins,
    rename_pin,
    serialize_pin,
    update_pin_envelope,
)
from app.services.dashboards import (
    create_dashboard,
    delete_dashboard,
    get_dashboard,
    list_dashboards,
    redirect_target_slug,
    serialize_dashboard,
    touch_last_viewed,
    update_dashboard,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/widgets", tags=["widget-dashboard"])


# ---------------------------------------------------------------------------
# Dashboards (named board CRUD)
# ---------------------------------------------------------------------------
class CreateDashboardRequest(BaseModel):
    slug: str
    name: str
    icon: str | None = None
    pin_to_rail: bool = False
    rail_position: int | None = None


class UpdateDashboardRequest(BaseModel):
    name: str | None = None
    icon: str | None = None
    pin_to_rail: bool | None = None
    rail_position: int | None = None


@router.get(
    "/dashboards",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def list_all_dashboards(db: AsyncSession = Depends(get_db)):
    rows = await list_dashboards(db)
    return {"dashboards": [serialize_dashboard(r) for r in rows]}


@router.get(
    "/dashboards/redirect-target",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def get_redirect_target(db: AsyncSession = Depends(get_db)):
    return {"slug": await redirect_target_slug(db)}


@router.get(
    "/dashboards/{slug}",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def get_single_dashboard(slug: str, db: AsyncSession = Depends(get_db)):
    row = await get_dashboard(db, slug)
    return serialize_dashboard(row)


@router.post(
    "/dashboards",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def create_new_dashboard(
    body: CreateDashboardRequest,
    db: AsyncSession = Depends(get_db),
):
    row = await create_dashboard(
        db,
        slug=body.slug,
        name=body.name,
        icon=body.icon,
        pin_to_rail=body.pin_to_rail,
        rail_position=body.rail_position,
    )
    logger.info("Widget dashboard created: slug=%s name=%s", row.slug, row.name)
    return serialize_dashboard(row)


@router.patch(
    "/dashboards/{slug}",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def patch_dashboard(
    slug: str,
    body: UpdateDashboardRequest,
    db: AsyncSession = Depends(get_db),
):
    row = await update_dashboard(db, slug, body.model_dump(exclude_unset=True))
    return serialize_dashboard(row)


@router.delete(
    "/dashboards/{slug}",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def remove_dashboard(slug: str, db: AsyncSession = Depends(get_db)):
    await delete_dashboard(db, slug)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Pins (scoped by ?slug= query param — defaults to 'default')
# ---------------------------------------------------------------------------
class CreatePinRequest(BaseModel):
    source_kind: str  # 'channel' | 'adhoc'
    tool_name: str
    envelope: dict
    source_channel_id: uuid.UUID | None = None
    source_bot_id: str | None = None
    tool_args: dict | None = None
    widget_config: dict | None = None
    display_label: str | None = None
    dashboard_key: str | None = None


class WidgetConfigPatch(BaseModel):
    config: dict
    merge: bool = True


class LayoutItem(BaseModel):
    id: uuid.UUID
    x: int
    y: int
    w: int
    h: int


class LayoutBulkRequest(BaseModel):
    items: list[LayoutItem]
    dashboard_key: str | None = None


class PinMetadataPatch(BaseModel):
    display_label: str | None = None


@router.get(
    "/dashboard",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def get_dashboard_pins(
    slug: str = Query(default=DEFAULT_DASHBOARD_KEY),
    db: AsyncSession = Depends(get_db),
):
    """Return pins for ``slug`` (defaults to ``'default'``).

    Also records ``last_viewed_at`` on the dashboard so the redirect-target
    endpoint can send the user back to their most recent board.
    """
    # 404s if the dashboard doesn't exist.
    await get_dashboard(db, slug)
    pins = await list_pins(db, dashboard_key=slug)
    await touch_last_viewed(db, slug)
    return {"pins": [serialize_pin(p) for p in pins]}


@router.post(
    "/dashboard/pins",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def create_dashboard_pin(
    body: CreatePinRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new pin. Position is auto-assigned within the dashboard."""
    pin = await create_pin(
        db,
        source_kind=body.source_kind,
        tool_name=body.tool_name,
        envelope=body.envelope,
        source_channel_id=body.source_channel_id,
        source_bot_id=body.source_bot_id,
        tool_args=body.tool_args,
        widget_config=body.widget_config,
        display_label=body.display_label,
        dashboard_key=body.dashboard_key or DEFAULT_DASHBOARD_KEY,
    )
    logger.info(
        "Dashboard pin created: id=%s dashboard=%s tool=%s source=%s",
        pin.id, pin.dashboard_key, pin.tool_name, pin.source_kind,
    )
    return serialize_pin(pin)


@router.delete(
    "/dashboard/pins/{pin_id}",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def delete_dashboard_pin(
    pin_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    await delete_pin(db, pin_id)
    return {"ok": True}


@router.patch(
    "/dashboard/pins/{pin_id}/config",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def patch_dashboard_pin_config(
    pin_id: uuid.UUID,
    body: WidgetConfigPatch,
    db: AsyncSession = Depends(get_db),
):
    return await apply_dashboard_pin_config_patch(
        db, pin_id, body.config, merge=body.merge,
    )


@router.patch(
    "/dashboard/pins/{pin_id}",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def patch_dashboard_pin_metadata(
    pin_id: uuid.UUID,
    body: PinMetadataPatch,
    db: AsyncSession = Depends(get_db),
):
    return await rename_pin(db, pin_id, body.display_label)


@router.post(
    "/dashboard/pins/layout",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def patch_dashboard_pin_layout(
    body: LayoutBulkRequest,
    db: AsyncSession = Depends(get_db),
):
    """Bulk-commit grid coordinates after a drag/resize session.

    All ids must belong to ``body.dashboard_key`` (defaults to 'default');
    otherwise the whole call fails with 400 so we never commit a partial
    layout across dashboards.
    """
    slug = body.dashboard_key or DEFAULT_DASHBOARD_KEY
    items = [item.model_dump(mode="json") for item in body.items]
    return await apply_layout_bulk(db, items, dashboard_key=slug)


@router.post(
    "/dashboard/pins/{pin_id}/refresh",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def refresh_dashboard_pin(
    pin_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Re-run the pin's state_poll and update its envelope.

    Imports the widget-actions internals lazily to avoid a module-level
    cycle (widget_actions may later import from here if we expose refresh
    helpers the other direction).
    """
    from app.routers.api_v1_widget_actions import (
        _do_state_poll,
        _evict_stale_cache,
        _resolve_tool_name,
        invalidate_poll_cache_for,
    )
    from app.services.widget_templates import get_state_poll_config

    _evict_stale_cache()
    pin = await get_pin(db, pin_id)
    resolved = _resolve_tool_name(pin.tool_name)
    poll_cfg = get_state_poll_config(resolved)
    if not poll_cfg:
        raise HTTPException(400, f"No state_poll config for {pin.tool_name}")

    # Force fresh call when the caller explicitly asked to refresh.
    invalidate_poll_cache_for(poll_cfg)
    envelope = await _do_state_poll(
        tool_name=resolved,
        display_label=pin.display_label or (pin.envelope or {}).get("display_label") or "",
        poll_cfg=poll_cfg,
        widget_config=pin.widget_config or {},
    )
    if envelope is None:
        raise HTTPException(502, "State poll failed to produce an envelope")

    env_dict = envelope.compact_dict()
    await update_pin_envelope(db, pin.id, env_dict)
    return {"ok": True, "envelope": env_dict}
