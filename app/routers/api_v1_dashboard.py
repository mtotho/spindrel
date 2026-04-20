"""Widget dashboards — chat-less homes for pinned widgets.

Endpoints live under ``/api/v1/widgets``:
- ``/api/v1/widgets/dashboards`` — list/create/update/delete named dashboards
- ``/api/v1/widgets/dashboards/{slug}/rail`` — per-user + everyone rail pins
- ``/api/v1/widgets/dashboard`` — pin CRUD scoped by ``?slug=``
"""
from __future__ import annotations

import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import ApiKeyAuth, get_db, require_scopes
from app.services.dashboard_pins import (
    DEFAULT_DASHBOARD_KEY,
    apply_dashboard_pin_config_patch,
    apply_layout_bulk,
    create_pin,
    delete_pin,
    demote_pin_from_panel,
    get_pin,
    list_pins,
    promote_pin_to_panel,
    rename_pin,
    serialize_pin,
    update_pin_envelope,
)
from app.services.dashboard_rail import (
    resolved_rail_state,
    resolved_rail_state_bulk,
    set_rail_pin,
    unset_rail_pin,
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


def _auth_identity(auth) -> tuple[uuid.UUID | None, bool]:
    """Extract ``(user_id, is_admin)`` from a ``require_scopes`` return value.

    - ``ApiKeyAuth`` has no user identity (``user_id=None``). ``is_admin`` is
      true only when the key carries the ``admin`` scope — a non-admin
      scoped key with ``channels:write`` can still pass the route guard but
      must not be allowed to pin dashboards "for everyone".
    - ``User`` → ``(user.id, user.is_admin)``.
    """
    from app.db.models import User
    if isinstance(auth, ApiKeyAuth):
        return (None, "admin" in auth.scopes)
    if isinstance(auth, User):
        return (auth.id, bool(auth.is_admin))
    return (None, False)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/widgets", tags=["widget-dashboard"])


# ---------------------------------------------------------------------------
# Dashboards (named board CRUD)
# ---------------------------------------------------------------------------
class CreateDashboardRequest(BaseModel):
    slug: str
    name: str
    icon: str | None = None
    grid_config: dict | None = None


class UpdateDashboardRequest(BaseModel):
    name: str | None = None
    icon: str | None = None
    grid_config: dict | None = None


class SetRailPinRequest(BaseModel):
    scope: Literal["everyone", "me"]
    rail_position: int | None = None


@router.get(
    "/dashboards",
)
async def list_all_dashboards(
    scope: str = Query(
        default="user",
        description="One of 'user' | 'channel' | 'all'. "
                    "Defaults to 'user' (tab-bar friendly).",
    ),
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    if scope not in ("user", "channel", "all"):
        raise HTTPException(400, "scope must be one of 'user', 'channel', 'all'")
    rows = await list_dashboards(db, scope=scope)  # type: ignore[arg-type]
    user_id, _is_admin = _auth_identity(auth)
    rail_by_slug = await resolved_rail_state_bulk(
        db, [r.slug for r in rows], user_id,
    )
    return {
        "dashboards": [
            serialize_dashboard(r, rail=rail_by_slug.get(r.slug))
            for r in rows
        ],
    }


@router.get(
    "/dashboards/redirect-target",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def get_redirect_target(db: AsyncSession = Depends(get_db)):
    return {"slug": await redirect_target_slug(db)}


@router.get(
    "/dashboards/channel-pins",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def list_channel_dashboard_pins(db: AsyncSession = Depends(get_db)):
    """Pins grouped by channel — used by the "Add widget → From channel" tab.

    Returns every ``channel:<uuid>`` dashboard that has ≥1 pin, with the
    channel's display name resolved from the Channel table. Pin rows use the
    same shape as ``/dashboard`` for drop-in reuse on the frontend.
    """
    from sqlalchemy import select
    from app.db.models import (
        Channel,
        WidgetDashboard,
        WidgetDashboardPin,
    )

    # Single query: channel dashboards with their pins + channel metadata.
    # Outer-join to Channel so pins whose channel got deleted still surface
    # (client can render "deleted channel" gracefully).
    stmt = (
        select(WidgetDashboardPin, WidgetDashboard.slug, Channel.id, Channel.name)
        .join(
            WidgetDashboard,
            WidgetDashboard.slug == WidgetDashboardPin.dashboard_key,
        )
        .join(
            Channel,
            Channel.id == WidgetDashboardPin.source_channel_id,
            isouter=True,
        )
        .where(WidgetDashboard.slug.like(f"{CHANNEL_SLUG_PREFIX}%"))
        .order_by(
            Channel.name.asc().nulls_last(),
            WidgetDashboardPin.position.asc(),
        )
    )
    rows = (await db.execute(stmt)).all()

    groups: dict[str, dict] = {}
    for pin, slug, channel_id, channel_name in rows:
        key = slug
        if key not in groups:
            groups[key] = {
                "dashboard_slug": slug,
                "channel_id": str(channel_id) if channel_id else None,
                "channel_name": channel_name or "(deleted channel)",
                "pins": [],
            }
        groups[key]["pins"].append(serialize_pin(pin))

    # Skip dashboards with zero pins (shouldn't appear in the query, but
    # guard defensively) and sort by channel name for stable display.
    out = [g for g in groups.values() if g["pins"]]
    out.sort(key=lambda g: (g["channel_name"].lower(), g["dashboard_slug"]))
    return {"channels": out}


@router.get(
    "/dashboards/{slug}",
)
async def get_single_dashboard(
    slug: str,
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
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
    user_id, _ = _auth_identity(auth)
    rail = await resolved_rail_state(db, row.slug, user_id)
    return serialize_dashboard(row, rail=rail)


@router.post(
    "/dashboards",
)
async def create_new_dashboard(
    body: CreateDashboardRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    row = await create_dashboard(
        db,
        slug=body.slug,
        name=body.name,
        icon=body.icon,
        grid_config=body.grid_config,
    )
    logger.info("Widget dashboard created: slug=%s name=%s", row.slug, row.name)
    user_id, _ = _auth_identity(auth)
    rail = await resolved_rail_state(db, row.slug, user_id)
    return serialize_dashboard(row, rail=rail)


@router.patch(
    "/dashboards/{slug}",
)
async def patch_dashboard(
    slug: str,
    body: UpdateDashboardRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    row = await update_dashboard(db, slug, body.model_dump(exclude_unset=True))
    user_id, _ = _auth_identity(auth)
    rail = await resolved_rail_state(db, row.slug, user_id)
    return serialize_dashboard(row, rail=rail)


@router.put(
    "/dashboards/{slug}/rail",
)
async def put_rail_pin(
    slug: str,
    body: SetRailPinRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    """Pin a dashboard to the sidebar rail.

    ``scope='everyone'`` is admin-only and shows the dashboard in every
    user's rail. ``scope='me'`` adds it to the current user's rail only.
    """
    # Lazy-create channel dashboards so the UI can pin a channel dashboard
    # before a pin ever lands on it.
    if is_channel_slug(slug):
        ch_id = slug[len(CHANNEL_SLUG_PREFIX):]
        try:
            uuid.UUID(ch_id)
        except ValueError:
            raise HTTPException(400, f"Invalid channel slug: {slug}")
        await ensure_channel_dashboard(db, ch_id)
    # Touches get_dashboard to raise 404 if the slug doesn't exist.
    await get_dashboard(db, slug)

    user_id, is_admin = _auth_identity(auth)
    await set_rail_pin(
        db, slug,
        scope=body.scope,
        user_id=user_id,
        is_admin=is_admin,
        rail_position=body.rail_position,
    )
    rail = await resolved_rail_state(db, slug, user_id)
    return {"slug": slug, "rail": rail}


@router.delete(
    "/dashboards/{slug}/rail",
)
async def delete_rail_pin(
    slug: str,
    scope: Literal["everyone", "me"] = Query(...),
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    user_id, is_admin = _auth_identity(auth)
    await unset_rail_pin(
        db, slug,
        scope=scope,
        user_id=user_id,
        is_admin=is_admin,
    )
    rail = await resolved_rail_state(db, slug, user_id)
    return {"slug": slug, "rail": rail}


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
    """List recent tool calls that can be rendered as a widget.

    A call qualifies if either:
    - the tool's stored ``result`` already IS an envelope (``_envelope``
      opt-in tools like ``emit_html_widget``), OR
    - a registered widget template for the tool produces one when applied
      to the stored ``result``.

    The rendered envelope is returned in each row so the UI can pin it
    directly without a second round-trip through the preview endpoints.
    """
    import json
    from sqlalchemy import select
    from app.db.models import Session as SessionModel, ToolCall, Channel
    from app.services.widget_templates import apply_widget_template

    # Pull more than `limit` up front since we filter out non-widget
    # envelopes after rendering — otherwise a page full of text results
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
        raw = tool_call.result
        if not raw:
            continue

        envelope: dict | None = None

        # Path 1: template-rendered envelope (works for every tool with a
        # registered .widgets.yaml template). Cheap — dict lookup + a JSON
        # parse that succeeds fast on the 95% of tools that return JSON.
        try:
            rendered = apply_widget_template(tool_call.tool_name, raw)
        except Exception:
            rendered = None
        if rendered is not None:
            envelope = rendered.compact_dict()

        # Path 2: tool-shipped envelope via the ``_envelope`` opt-in wrapper
        # (``emit_html_widget`` and any bot-authored widget tool). Stored
        # shape is ``{"_envelope": {...content_type, body, ...}, "llm": "..."}``
        # — we unwrap and accept if the inner envelope is a widget type.
        if envelope is None:
            try:
                parsed = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if not isinstance(parsed, dict):
                continue
            inner = parsed.get("_envelope")
            if isinstance(inner, dict) and inner.get("content_type") in _WIDGET_CONTENT_TYPES:
                envelope = inner
            elif parsed.get("content_type") in _WIDGET_CONTENT_TYPES:
                # Legacy shape — result itself IS the envelope.
                envelope = parsed
            else:
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
    "/dashboard/pins/{pin_id}/promote-panel",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def promote_dashboard_pin_to_panel(
    pin_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Make this pin the dashboard's main panel.

    Atomically clears any other panel pin in the same dashboard and flips
    ``grid_config.layout_mode`` to ``"panel"``. Other pins keep their grid
    coordinates and surface in the rail strip alongside the panel.
    """
    return await promote_pin_to_panel(db, pin_id)


@router.delete(
    "/dashboard/pins/{pin_id}/promote-panel",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def demote_dashboard_pin_from_panel(
    pin_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Clear ``is_main_panel`` on this pin.

    If this leaves the dashboard with no panel pin the layout mode reverts to
    ``"grid"`` so the dashboard renders as a normal RGL canvas again.
    """
    return await demote_pin_from_panel(db, pin_id)


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
