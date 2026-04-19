"""CRUD helpers for the ``widget_dashboards`` table.

The ``default`` dashboard is pre-seeded by the migration and can't be created
or deleted through this module. Slug is the user-chosen, URL-safe key.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WidgetDashboard
from app.services.dashboard_pins import DEFAULT_DASHBOARD_KEY


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
# Reserved because they collide with existing routes or feel like commands.
RESERVED_SLUGS = {"default", "dev", "new"}


def _validate_slug(slug: str) -> str:
    if not isinstance(slug, str):
        raise HTTPException(400, "slug must be a string")
    slug = slug.strip()
    if not _SLUG_RE.match(slug):
        raise HTTPException(
            400,
            "slug must be 1-48 chars, lowercase letters, digits, or dashes; "
            "must start with a letter or digit",
        )
    return slug


def _validate_name(name: str) -> str:
    if not isinstance(name, str):
        raise HTTPException(400, "name must be a string")
    name = name.strip()
    if not name:
        raise HTTPException(400, "name is required")
    if len(name) > 64:
        raise HTTPException(400, "name must be 64 characters or fewer")
    return name


def serialize_dashboard(row: WidgetDashboard) -> dict[str, Any]:
    return {
        "slug": row.slug,
        "name": row.name,
        "icon": row.icon,
        "pin_to_rail": bool(row.pin_to_rail),
        "rail_position": row.rail_position,
        "last_viewed_at": row.last_viewed_at.isoformat() if row.last_viewed_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def list_dashboards(db: AsyncSession) -> list[WidgetDashboard]:
    rows = (await db.execute(
        select(WidgetDashboard).order_by(
            WidgetDashboard.pin_to_rail.desc(),
            WidgetDashboard.rail_position.asc().nulls_last(),
            WidgetDashboard.name.asc(),
        )
    )).scalars().all()
    return list(rows)


async def get_dashboard(db: AsyncSession, slug: str) -> WidgetDashboard:
    row = (await db.execute(
        select(WidgetDashboard).where(WidgetDashboard.slug == slug)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"Dashboard not found: {slug}")
    return row


async def create_dashboard(
    db: AsyncSession,
    *,
    slug: str,
    name: str,
    icon: str | None = None,
    pin_to_rail: bool = False,
    rail_position: int | None = None,
) -> WidgetDashboard:
    slug = _validate_slug(slug)
    if slug in RESERVED_SLUGS:
        raise HTTPException(400, f"'{slug}' is reserved and can't be used as a slug")
    name = _validate_name(name)

    existing = (await db.execute(
        select(WidgetDashboard).where(WidgetDashboard.slug == slug)
    )).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(409, f"Dashboard '{slug}' already exists")

    row = WidgetDashboard(
        slug=slug,
        name=name,
        icon=(icon or None),
        pin_to_rail=bool(pin_to_rail),
        rail_position=rail_position,
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
            raise HTTPException(400, "icon must be a string or null")
        row.icon = (icon or None)
    if "pin_to_rail" in patch and patch["pin_to_rail"] is not None:
        row.pin_to_rail = bool(patch["pin_to_rail"])
    if "rail_position" in patch:
        pos = patch["rail_position"]
        if pos is not None and (not isinstance(pos, int) or pos < 0):
            raise HTTPException(400, "rail_position must be a non-negative integer or null")
        row.rail_position = pos
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return row


async def delete_dashboard(db: AsyncSession, slug: str) -> None:
    if slug == DEFAULT_DASHBOARD_KEY:
        raise HTTPException(400, "The default dashboard can't be deleted")
    row = await get_dashboard(db, slug)
    # Explicitly delete child pins for parity between SQLite tests (no FK
    # enforcement) and Postgres (ON DELETE CASCADE).
    from app.db.models import WidgetDashboardPin
    from sqlalchemy import delete as sa_delete
    await db.execute(
        sa_delete(WidgetDashboardPin).where(WidgetDashboardPin.dashboard_key == slug)
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
    """
    row = (await db.execute(
        select(WidgetDashboard)
        .where(WidgetDashboard.last_viewed_at.is_not(None))
        .order_by(WidgetDashboard.last_viewed_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if row is not None:
        return row.slug
    return DEFAULT_DASHBOARD_KEY


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
        pin_to_rail=False,
    ))
    await db.commit()
