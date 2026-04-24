"""Named-board CRUD, rail pin/unpin, redirect target, channel-pins list."""
from __future__ import annotations

import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_scopes
from app.services.dashboard_pins import serialize_pin
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
    update_dashboard,
)

from ._common import auth_identity


logger = logging.getLogger(__name__)
router = APIRouter()


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


@router.get("/dashboards")
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
    user_id, _is_admin = auth_identity(auth)
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


@router.get("/dashboards/{slug}")
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
            uuid.UUID(ch_id)
        except ValueError:
            raise HTTPException(400, f"Invalid channel slug: {slug}")
        await ensure_channel_dashboard(db, ch_id)
    row = await get_dashboard(db, slug)
    user_id, _ = auth_identity(auth)
    rail = await resolved_rail_state(db, row.slug, user_id)
    return serialize_dashboard(row, rail=rail)


@router.post("/dashboards")
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
    user_id, _ = auth_identity(auth)
    rail = await resolved_rail_state(db, row.slug, user_id)
    return serialize_dashboard(row, rail=rail)


@router.patch("/dashboards/{slug}")
async def patch_dashboard(
    slug: str,
    body: UpdateDashboardRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    row = await update_dashboard(db, slug, body.model_dump(exclude_unset=True))
    user_id, _ = auth_identity(auth)
    rail = await resolved_rail_state(db, row.slug, user_id)
    return serialize_dashboard(row, rail=rail)


@router.put("/dashboards/{slug}/rail")
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

    user_id, is_admin = auth_identity(auth)
    await set_rail_pin(
        db, slug,
        scope=body.scope,
        user_id=user_id,
        is_admin=is_admin,
        rail_position=body.rail_position,
    )
    rail = await resolved_rail_state(db, slug, user_id)
    return {"slug": slug, "rail": rail}


@router.delete("/dashboards/{slug}/rail")
async def delete_rail_pin(
    slug: str,
    scope: Literal["everyone", "me"] = Query(...),
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    user_id, is_admin = auth_identity(auth)
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
