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
    CHANNEL_SLUG_PREFIX,
    create_dashboard,
    delete_dashboard,
    ensure_channel_dashboard,
    get_dashboard,
    is_channel_slug,
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
    grid_config: dict | None = None


class UpdateDashboardRequest(BaseModel):
    name: str | None = None
    icon: str | None = None
    pin_to_rail: bool | None = None
    rail_position: int | None = None
    grid_config: dict | None = None


@router.get(
    "/dashboards",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def list_all_dashboards(
    scope: str = Query(
        default="user",
        description="One of 'user' | 'channel' | 'all'. "
                    "Defaults to 'user' (tab-bar friendly).",
    ),
    db: AsyncSession = Depends(get_db),
):
    if scope not in ("user", "channel", "all"):
        raise HTTPException(400, "scope must be one of 'user', 'channel', 'all'")
    rows = await list_dashboards(db, scope=scope)  # type: ignore[arg-type]
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
    # Channel dashboards lazy-create on read so the channel UI can ask for
    # metadata (name, icon) without having to seed the row first.
    if is_channel_slug(slug):
        ch_id = slug[len(CHANNEL_SLUG_PREFIX):]
        try:
            import uuid as _uuid
            _uuid.UUID(ch_id)
        except ValueError:
            raise HTTPException(400, f"Invalid channel slug: {slug}")
        await ensure_channel_dashboard(db, ch_id)
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
        grid_config=body.grid_config,
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
# Recent widget-producing tool calls
# ---------------------------------------------------------------------------
# Used by the "Add widget" sheet's "Recent calls" tab — surfaces tool calls
# whose result is a renderable widget envelope (components, html-interactive,
# html, etc.) so users can pin them straight to a dashboard without having
# to first pin them to a channel's OmniPanel rail.
_WIDGET_CONTENT_TYPES = {
    "application/vnd.spindrel.components+json",
    "application/vnd.spindrel.html+interactive",
    "application/vnd.spindrel.diff+text",
    "application/vnd.spindrel.file-listing+json",
    "text/html",
}


@router.get(
    "/recent-calls",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def list_recent_widget_calls(
    channel_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List recent tool calls whose result is a widget-renderable envelope.

    When ``channel_id`` is provided, filters to calls whose session belongs
    to that channel. Otherwise returns calls across all channels. Callers
    feed these results into the `POST /dashboard` pin endpoint verbatim.
    """
    import json
    from sqlalchemy import select
    from app.db.models import Session as SessionModel, ToolCall, Channel

    # Pull more than `limit` up front since we filter out non-widget
    # envelopes after parsing — otherwise a page full of text results
    # would leave the user with an empty list.
    over_limit = limit * 4

    stmt = (
        select(ToolCall, SessionModel.channel_id, Channel.name)
        .join(SessionModel, SessionModel.id == ToolCall.session_id, isouter=True)
        .join(Channel, Channel.id == SessionModel.channel_id, isouter=True)
        .where(ToolCall.status == "done")
        .where(ToolCall.result.isnot(None))
        .order_by(ToolCall.created_at.desc())
    )
    if channel_id is not None:
        stmt = stmt.where(SessionModel.channel_id == channel_id)
    stmt = stmt.limit(over_limit)

    rows = (await db.execute(stmt)).all()

    out: list[dict] = []
    seen_identities: set[str] = set()
    for tool_call, row_channel_id, row_channel_name in rows:
        if len(out) >= limit:
            break
        if not tool_call.result:
            continue
        try:
            envelope = json.loads(tool_call.result)
        except (ValueError, TypeError):
            continue
        if not isinstance(envelope, dict):
            continue
        content_type = envelope.get("content_type")
        if content_type not in _WIDGET_CONTENT_TYPES:
            continue
        # De-dupe: tool_name + first 120 chars of body is a good-enough
        # identity for "is this the same widget I already saw 3 calls up".
        body = envelope.get("body")
        body_str = body if isinstance(body, str) else json.dumps(body or "")
        identity = f"{tool_call.tool_name}::{body_str[:120]}"
        if identity in seen_identities:
            continue
        seen_identities.add(identity)
        out.append({
            "id": str(tool_call.id),
            "tool_name": tool_call.tool_name,
            "bot_id": tool_call.bot_id,
            "channel_id": str(row_channel_id) if row_channel_id else None,
            "channel_name": row_channel_name,
            "tool_args": tool_call.arguments or {},
            "envelope": envelope,
            "display_label": envelope.get("display_label"),
            "created_at": tool_call.created_at.isoformat() if tool_call.created_at else None,
        })
    return {"calls": out}


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
    endpoint can send the user back to their most recent board. Channel
    dashboards (``channel:<uuid>``) are lazy-created on first read so a
    just-opened channel's side-panel can always fetch cleanly.
    """
    if is_channel_slug(slug):
        ch_id = slug[len(CHANNEL_SLUG_PREFIX):]
        # Raises 404 if the underlying channel doesn't exist.
        try:
            import uuid as _uuid
            _uuid.UUID(ch_id)
        except ValueError:
            raise HTTPException(400, f"Invalid channel slug: {slug}")
        await ensure_channel_dashboard(db, ch_id)

    # 404s if the dashboard doesn't exist (and isn't a channel slug).
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
