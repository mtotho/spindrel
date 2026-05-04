"""Pin CRUD, layout, panel-mode, db-status, state refresh."""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, release_db_read_transaction, require_scopes
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
    update_pin_scope,
)
from app.services.dashboards import (
    CHANNEL_SLUG_PREFIX,
    ensure_channel_dashboard,
    get_dashboard,
    is_channel_slug,
    touch_last_viewed,
)


logger = logging.getLogger(__name__)
router = APIRouter()


class CreatePinRequest(BaseModel):
    source_kind: str  # 'channel' | 'adhoc'
    tool_name: str
    envelope: dict
    source_channel_id: uuid.UUID | None = None
    source_bot_id: str | None = None
    tool_args: dict | None = None
    widget_config: dict | None = None
    widget_origin: dict | None = None
    display_label: str | None = None
    dashboard_key: str | None = None
    zone: str | None = None
    grid_layout: dict | None = None


class WidgetConfigPatch(BaseModel):
    config: dict
    merge: bool = True


class LayoutItem(BaseModel):
    id: uuid.UUID
    x: int
    y: int
    w: int
    h: int
    # Optional chat-side zone for cross-canvas moves on channel dashboards.
    # Omit to keep the pin's current zone (same-canvas reorders). Allowed:
    # 'rail' | 'header' | 'dock' | 'grid'. Validation lives in
    # ``dashboard_pins._validate_layout_item`` so the error shape stays
    # consistent with the rest of the layout API.
    zone: str | None = None


class LayoutBulkRequest(BaseModel):
    items: list[LayoutItem]
    dashboard_key: str | None = None


class PinMetadataPatch(BaseModel):
    display_label: str | None = None


class PinScopePatch(BaseModel):
    # Explicit Optional[str] — ``null`` means "flip to user scope", a string
    # means "rescope to this bot." A separate endpoint (rather than folding
    # into PinMetadataPatch) avoids ambiguity between "field omitted" and
    # "field explicitly null" on the rename path.
    source_bot_id: str | None = None


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
            uuid.UUID(ch_id)
        except ValueError:
            raise HTTPException(400, f"Invalid channel slug: {slug}")
        await ensure_channel_dashboard(db, ch_id)

    # 404s if the dashboard doesn't exist (and isn't a channel slug).
    await get_dashboard(db, slug)
    pins = await list_pins(db, dashboard_key=slug)
    await touch_last_viewed(db, slug)
    serialized = [serialize_pin(p) for p in pins]
    try:
        from app.services.widget_health import latest_health_for_pins

        latest_health = await latest_health_for_pins(db, [pin["id"] for pin in serialized])
        for pin in serialized:
            health = latest_health.get(str(pin.get("id")))
            if health:
                pin["widget_health"] = health
    except Exception:
        logger.debug("Failed to attach latest widget health summaries", exc_info=True)
    await release_db_read_transaction(db, context="dashboard pin list")
    return {"pins": serialized}


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
        widget_origin=body.widget_origin,
        display_label=body.display_label,
        dashboard_key=body.dashboard_key or DEFAULT_DASHBOARD_KEY,
        zone=body.zone,
        grid_layout=body.grid_layout,
    )
    logger.info(
        "Dashboard pin created: id=%s dashboard=%s tool=%s source=%s",
        pin.id, pin.dashboard_key, pin.tool_name, pin.source_kind,
    )
    return serialize_pin(pin)


@router.get(
    "/dashboard/pins/{pin_id}",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def get_dashboard_pin(
    pin_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Return a single dashboard pin by id."""
    pin = await get_pin(db, pin_id)
    data = serialize_pin(pin)
    try:
        from app.services.widget_health import latest_health_for_pins

        latest = await latest_health_for_pins(db, [pin_id])
        health = latest.get(str(pin_id))
        if health:
            data["widget_health"] = health
    except Exception:
        logger.debug("Failed to attach latest widget health summary", exc_info=True)
    await release_db_read_transaction(db, context="dashboard pin detail")
    return data


@router.get(
    "/dashboard/pins/{pin_id}/db-status",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def get_pin_db_status(
    pin_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Check whether the pin's widget bundle has a SQLite DB with content.

    Used by the unpin flow: the UI calls this first, and if ``has_content`` is
    True it surfaces a confirmation before deleting.

    Returns ``{has_content: false}`` for inline widgets and empty/absent DBs.
    """
    pin = await get_pin(db, pin_id)
    from app.services.dashboard_pins import check_pin_db_content
    info = await check_pin_db_content(pin)
    if info is None:
        return {"has_content": False}
    return info


@router.delete(
    "/dashboard/pins/{pin_id}",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def delete_dashboard_pin(
    pin_id: uuid.UUID,
    delete_bundle_data: bool = Query(
        default=False,
        description="When true, also unlinks the pin's bundle data.sqlite file.",
    ),
    db: AsyncSession = Depends(get_db),
):
    result = await delete_pin(db, pin_id, delete_bundle_data=delete_bundle_data)
    return {"ok": True, **result}


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


@router.patch(
    "/dashboard/pins/{pin_id}/scope",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def patch_dashboard_pin_scope(
    pin_id: uuid.UUID,
    body: PinScopePatch,
    db: AsyncSession = Depends(get_db),
):
    """Switch a pin between user-scope (``source_bot_id: null``) and
    bot-scope (``source_bot_id: "<bot_id>"``).

    Updates both the column and the envelope so the renderer's scope chip
    and the widget-token-mint path stay in lockstep. 404 if the named bot
    doesn't exist.
    """
    return await update_pin_scope(db, pin_id, body.source_bot_id)


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

    Imports the widget-action state-poll service lazily to avoid a module-level
    cycle with dashboard pin helpers.
    """
    from app.services.widget_action_state_poll import (
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
