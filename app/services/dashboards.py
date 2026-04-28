"""CRUD helpers for the ``widget_dashboards`` table.

The ``default`` dashboard is pre-seeded by the migration and can't be created
or deleted through this module. Slug is the user-chosen, URL-safe key.

Channel dashboards use the reserved prefix ``channel:<uuid>``. They are
lazy-created by :func:`ensure_channel_dashboard` (never via user-facing
create), hidden from the generic tab bar via ``scope="user"``, and
cascade-deleted when their owning channel is removed.
"""
from __future__ import annotations

import copy
import re
import uuid as uuid_mod
from datetime import datetime, timezone
from typing import Any, Literal

from app.domain.errors import ConflictError, NotFoundError, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import Channel, WidgetDashboard, WidgetDashboardPin
from app.services.dashboard_pins import DEFAULT_DASHBOARD_KEY
from app.services.dashboard_grid import (
    DEFAULT_PRESET,
    GRID_PRESETS,
    resolve_preset_name as _extract_preset,
    scale_ratio as _scale_ratio,
    valid_preset as _valid_preset,
)


def _rescale_pin_layout(layout: dict[str, Any], ratio: int) -> dict[str, Any]:
    """Scale a single pin's ``{x, y, w, h}`` by the ratio.

    Positive ratio multiplies; negative ratio divides. Uses integer math so
    layouts stay grid-aligned.
    """
    if not layout or not isinstance(layout, dict):
        return layout
    out = copy.deepcopy(layout)
    for key in ("x", "y", "w", "h"):
        if key in out and isinstance(out[key], (int, float)):
            v = int(out[key])
            if ratio > 0:
                out[key] = v * ratio
            elif ratio < 0:
                out[key] = max(1, v // (-ratio))
    return out


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
# Reserved because they collide with existing routes or feel like commands.
RESERVED_SLUGS = {"default", "dev", "new"}
# Channel-scoped dashboards. Never user-created; `channel_slug()` builds them
# and `list_dashboards(scope="user")` filters them out of the generic tab bar.
CHANNEL_SLUG_PREFIX = "channel:"
# Workspace-scope Spatial Canvas. Singleton dashboard seeded by migration
# 247 — hosts world-pinned widgets so the canvas reuses the existing pin
# host plumbing. Never user-created; never visible in any dashboard-listing
# surface (tabs, picker, recents, sidebar). Mirror of the frontend constant
# in ``ui/src/stores/dashboards.ts``.
WORKSPACE_SPATIAL_DASHBOARD_KEY = "workspace:spatial"


def channel_slug(channel_id: uuid_mod.UUID | str) -> str:
    """Return the reserved dashboard slug for a channel.

    Lazy-created by :func:`ensure_channel_dashboard` the first time a pin
    lands on it or the dashboard is viewed.
    """
    return f"{CHANNEL_SLUG_PREFIX}{channel_id}"


def is_channel_slug(slug: str) -> bool:
    return isinstance(slug, str) and slug.startswith(CHANNEL_SLUG_PREFIX)


def is_workspace_spatial_slug(slug: str) -> bool:
    return slug == WORKSPACE_SPATIAL_DASHBOARD_KEY


def is_reserved_listing_slug(slug: str) -> bool:
    """Slugs that exist in ``widget_dashboards`` but should never appear in
    user-facing dashboard listings (tabs, picker, recents, sidebar)."""
    return is_channel_slug(slug) or is_workspace_spatial_slug(slug)


def _validate_slug(slug: str) -> str:
    if not isinstance(slug, str):
        raise ValidationError("slug must be a string")
    slug = slug.strip()
    if not _SLUG_RE.match(slug):
        raise ValidationError(
            "slug must be 1-48 chars, lowercase letters, digits, or dashes; "
            "must start with a letter or digit",
        )
    return slug


def _validate_name(name: str) -> str:
    if not isinstance(name, str):
        raise ValidationError("name must be a string")
    name = name.strip()
    if not name:
        raise ValidationError("name is required")
    if len(name) > 64:
        raise ValidationError("name must be 64 characters or fewer")
    return name


def serialize_dashboard(
    row: WidgetDashboard,
    *,
    rail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialize a dashboard row.

    ``rail`` is the caller-resolved ``{me_pinned, everyone_pinned,
    effective_position}`` block for the current viewer — routers pass it in
    so the sidebar doesn't need a second round-trip. Service-level callers
    that don't care about rail state (seeding, tests) can omit it.
    """
    return {
        "slug": row.slug,
        "name": row.name,
        "icon": row.icon,
        "rail": rail or {
            "me_pinned": False,
            "everyone_pinned": False,
            "effective_position": None,
        },
        "grid_config": row.grid_config,
        "last_viewed_at": row.last_viewed_at.isoformat() if row.last_viewed_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def list_dashboards(
    db: AsyncSession,
    *,
    scope: Literal["user", "channel", "all"] = "user",
) -> list[WidgetDashboard]:
    """List dashboards for a given surface.

    ``scope="user"`` (default) returns everything the global ``/widgets``
    tab bar should show — user-created dashboards plus ``default``, never
    channel-scoped ones. ``scope="channel"`` returns only ``channel:*``
    rows. ``scope="all"`` returns everything.
    """
    stmt = select(WidgetDashboard)
    if scope == "user":
        stmt = stmt.where(
            ~WidgetDashboard.slug.like(f"{CHANNEL_SLUG_PREFIX}%"),
            WidgetDashboard.slug != WORKSPACE_SPATIAL_DASHBOARD_KEY,
        )
    elif scope == "channel":
        stmt = stmt.where(WidgetDashboard.slug.like(f"{CHANNEL_SLUG_PREFIX}%"))
    # Rail ordering is per-viewer and lives on ``dashboard_rail_pins`` —
    # see ``app/services/dashboard_rail.py``. Here we sort alphabetically so
    # the non-rail tab bar stays stable regardless of who's viewing.
    stmt = stmt.order_by(WidgetDashboard.name.asc())
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)


async def get_dashboard(db: AsyncSession, slug: str) -> WidgetDashboard:
    row = (await db.execute(
        select(WidgetDashboard).where(WidgetDashboard.slug == slug)
    )).scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"Dashboard not found: {slug}")
    return row


async def create_dashboard(
    db: AsyncSession,
    *,
    slug: str,
    name: str,
    icon: str | None = None,
    grid_config: dict[str, Any] | None = None,
) -> WidgetDashboard:
    slug = _validate_slug(slug)
    if slug in RESERVED_SLUGS:
        raise ValidationError(f"'{slug}' is reserved and can't be used as a slug")
    # User-facing create can never land on a channel-scoped slug — those are
    # allocated by ``ensure_channel_dashboard`` only. ``_validate_slug`` would
    # reject the colon anyway, but this gives a clearer error than "invalid slug".
    if slug.startswith(CHANNEL_SLUG_PREFIX):
        raise ValidationError(f"'{CHANNEL_SLUG_PREFIX}*' slugs are reserved for channels")
    if slug == WORKSPACE_SPATIAL_DASHBOARD_KEY:
        raise ValidationError(
            f"'{WORKSPACE_SPATIAL_DASHBOARD_KEY}' is reserved for the Spatial Canvas",
        )
    name = _validate_name(name)

    existing = (await db.execute(
        select(WidgetDashboard).where(WidgetDashboard.slug == slug)
    )).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"Dashboard '{slug}' already exists")

    if grid_config is not None:
        _valid_preset(grid_config.get("preset") if isinstance(grid_config, dict) else None)

    row = WidgetDashboard(
        slug=slug,
        name=name,
        icon=(icon or None),
        grid_config=grid_config,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def update_dashboard(
    db: AsyncSession,
    slug: str,
    patch: dict[str, Any],
) -> WidgetDashboard:
    row = await get_dashboard(db, slug)
    if "name" in patch and patch["name"] is not None:
        row.name = _validate_name(patch["name"])
    if "icon" in patch:
        icon = patch["icon"]
        if icon is not None and not isinstance(icon, str):
            raise ValidationError("icon must be a string or null")
        row.icon = (icon or None)
    if "grid_config" in patch:
        new_cfg = patch["grid_config"]
        if new_cfg is not None and not isinstance(new_cfg, dict):
            raise ValidationError("grid_config must be an object or null")
        new_preset = _extract_preset(new_cfg)
        old_preset = _extract_preset(row.grid_config)
        if new_preset != old_preset:
            # Rescale every pin's grid_layout so the visual arrangement
            # carries over to the new grid unit system.
            ratio = _scale_ratio(old_preset, new_preset)
            pins = (await db.execute(
                select(WidgetDashboardPin).where(
                    WidgetDashboardPin.dashboard_key == slug,
                )
            )).scalars().all()
            for pin in pins:
                scaled = _rescale_pin_layout(pin.grid_layout or {}, ratio)
                if scaled != pin.grid_layout:
                    pin.grid_layout = scaled
                    flag_modified(pin, "grid_layout")
        row.grid_config = new_cfg
        flag_modified(row, "grid_config")
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return row


async def delete_dashboard(db: AsyncSession, slug: str) -> None:
    if slug == DEFAULT_DASHBOARD_KEY:
        raise ValidationError("The default dashboard can't be deleted")
    row = await get_dashboard(db, slug)
    # Explicitly delete child pins for parity between SQLite tests (no FK
    # enforcement) and Postgres (ON DELETE CASCADE).
    from app.db.models import DashboardRailPin, WidgetDashboardPin
    from sqlalchemy import delete as sa_delete
    await db.execute(
        sa_delete(WidgetDashboardPin).where(WidgetDashboardPin.dashboard_key == slug)
    )
    await db.execute(
        sa_delete(DashboardRailPin).where(DashboardRailPin.dashboard_slug == slug)
    )
    await db.delete(row)
    await db.commit()


async def touch_last_viewed(db: AsyncSession, slug: str) -> None:
    row = (await db.execute(
        select(WidgetDashboard).where(WidgetDashboard.slug == slug)
    )).scalar_one_or_none()
    if row is None:
        return
    row.last_viewed_at = datetime.now(timezone.utc)
    await db.commit()


async def redirect_target_slug(db: AsyncSession) -> str:
    """Return the slug the user should land on when visiting ``/widgets``.

    Prefers the most recently viewed dashboard; falls back to ``default``.
    Channel-scoped dashboards are skipped — the generic ``/widgets`` page
    never auto-lands on a channel dashboard (those are reached from a
    channel or via the palette).
    """
    row = (await db.execute(
        select(WidgetDashboard)
        .where(
            WidgetDashboard.last_viewed_at.is_not(None),
            ~WidgetDashboard.slug.like(f"{CHANNEL_SLUG_PREFIX}%"),
            WidgetDashboard.slug != WORKSPACE_SPATIAL_DASHBOARD_KEY,
        )
        .order_by(WidgetDashboard.last_viewed_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if row is not None:
        return row.slug
    return DEFAULT_DASHBOARD_KEY


async def ensure_channel_dashboard(
    db: AsyncSession,
    channel_id: uuid_mod.UUID | str,
) -> WidgetDashboard:
    """Return the dashboard for ``channel_id``, creating it on first use.

    Copies the channel's current name/icon onto the dashboard row so the
    channel-dashboard breadcrumb and palette entries read naturally.
    Idempotent — subsequent calls return the existing row unchanged.
    """
    slug = channel_slug(channel_id)
    existing = (await db.execute(
        select(WidgetDashboard).where(WidgetDashboard.slug == slug)
    )).scalar_one_or_none()
    if existing is not None:
        return existing

    ch = (await db.execute(
        select(Channel).where(Channel.id == channel_id)
    )).scalar_one_or_none()
    if ch is None:
        raise NotFoundError(f"Channel not found: {channel_id}")

    row = WidgetDashboard(
        slug=slug,
        name=ch.name or f"Channel {str(channel_id)[:8]}",
        icon=None,  # channels don't carry icons today; inherit via breadcrumb
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def ensure_default_exists(db: AsyncSession) -> None:
    """Idempotent safety net — creates 'default' if it's somehow missing.

    The migration seeds it, but test fixtures that bypass migrations (Base.
    metadata.create_all) may skip the seed. Call this before any operation
    that relies on the FK being satisfiable.
    """
    existing = (await db.execute(
        select(func.count()).select_from(WidgetDashboard)
        .where(WidgetDashboard.slug == DEFAULT_DASHBOARD_KEY)
    )).scalar()
    if existing:
        return
    db.add(WidgetDashboard(
        slug=DEFAULT_DASHBOARD_KEY,
        name="Default",
        icon="LayoutDashboard",
    ))
    await db.commit()
