"""Per-user rail pinning for widget dashboards.

``dashboard_rail_pins`` rows with ``user_id IS NULL`` mean "pinned for
everyone" (admin-only write). Rows with a concrete ``user_id`` mean
"pinned just for this user". A user's effective rail state is their
personal row if present, else the everyone row.

Service API is primitive-in (``user_id: uuid | None`` + ``is_admin: bool``)
so routers can translate User objects once at the boundary and keep the
service easy to unit-test.
"""
from __future__ import annotations

import uuid as uuid_mod
from typing import Any, Iterable, Literal

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DashboardRailPin
from app.domain.errors import ForbiddenError, ValidationError


Scope = Literal["everyone", "me"]


def _require_admin_for_everyone(scope: Scope, is_admin: bool) -> None:
    if scope == "everyone" and not is_admin:
        raise ForbiddenError("Only admins can pin dashboards 'for everyone'")


async def _get_row(
    db: AsyncSession, slug: str, user_id: uuid_mod.UUID | None,
) -> DashboardRailPin | None:
    stmt = select(DashboardRailPin).where(
        DashboardRailPin.dashboard_slug == slug,
    )
    if user_id is None:
        stmt = stmt.where(DashboardRailPin.user_id.is_(None))
    else:
        stmt = stmt.where(DashboardRailPin.user_id == user_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def set_rail_pin(
    db: AsyncSession,
    slug: str,
    *,
    scope: Scope,
    user_id: uuid_mod.UUID | None,
    is_admin: bool,
    rail_position: int | None = None,
) -> DashboardRailPin:
    """Upsert a rail pin.

    ``scope='everyone'`` → ``user_id=NULL`` in the row (admin-only).
    ``scope='me'`` → ``user_id=<current user>`` (requires a concrete id).
    """
    _require_admin_for_everyone(scope, is_admin)

    if scope == "me":
        if user_id is None:
            raise ValidationError("scope='me' requires an authenticated user")
        row_user_id: uuid_mod.UUID | None = user_id
    else:
        row_user_id = None

    if rail_position is not None and (
        not isinstance(rail_position, int) or rail_position < 0
    ):
        raise ValidationError("rail_position must be a non-negative integer")

    existing = await _get_row(db, slug, row_user_id)
    if existing is not None:
        existing.rail_position = rail_position
        await db.commit()
        await db.refresh(existing)
        return existing

    row = DashboardRailPin(
        dashboard_slug=slug,
        user_id=row_user_id,
        rail_position=rail_position,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def unset_rail_pin(
    db: AsyncSession,
    slug: str,
    *,
    scope: Scope,
    user_id: uuid_mod.UUID | None,
    is_admin: bool,
) -> bool:
    """Delete the matching rail row. Returns True if a row was removed."""
    _require_admin_for_everyone(scope, is_admin)
    if scope == "me" and user_id is None:
        raise ValidationError("scope='me' requires an authenticated user")

    target_user = None if scope == "everyone" else user_id
    stmt = sa_delete(DashboardRailPin).where(
        DashboardRailPin.dashboard_slug == slug,
    )
    if target_user is None:
        stmt = stmt.where(DashboardRailPin.user_id.is_(None))
    else:
        stmt = stmt.where(DashboardRailPin.user_id == target_user)
    result = await db.execute(stmt)
    await db.commit()
    return bool(result.rowcount)


async def resolved_rail_state(
    db: AsyncSession,
    slug: str,
    user_id: uuid_mod.UUID | None,
) -> dict[str, Any]:
    """Return ``{me_pinned, everyone_pinned, effective_position}`` for one slug.

    Personal row wins for ``effective_position`` when both exist.
    """
    rows = (await db.execute(
        select(DashboardRailPin).where(DashboardRailPin.dashboard_slug == slug)
    )).scalars().all()
    everyone = next((r for r in rows if r.user_id is None), None)
    me = next(
        (r for r in rows if user_id is not None and r.user_id == user_id),
        None,
    )
    effective_position: int | None = None
    if me is not None:
        effective_position = me.rail_position
    elif everyone is not None:
        effective_position = everyone.rail_position
    return {
        "me_pinned": me is not None,
        "everyone_pinned": everyone is not None,
        "effective_position": effective_position,
    }


async def resolved_rail_state_bulk(
    db: AsyncSession,
    slugs: Iterable[str],
    user_id: uuid_mod.UUID | None,
) -> dict[str, dict[str, Any]]:
    """Batch version of :func:`resolved_rail_state` for the dashboard list view."""
    slugs = list(slugs)
    if not slugs:
        return {}
    rows = (await db.execute(
        select(DashboardRailPin).where(DashboardRailPin.dashboard_slug.in_(slugs))
    )).scalars().all()
    by_slug: dict[str, dict[str, DashboardRailPin | None]] = {
        s: {"everyone": None, "me": None} for s in slugs
    }
    for r in rows:
        bucket = by_slug.get(r.dashboard_slug)
        if bucket is None:
            continue
        if r.user_id is None:
            bucket["everyone"] = r
        elif user_id is not None and r.user_id == user_id:
            bucket["me"] = r
    out: dict[str, dict[str, Any]] = {}
    for slug, bucket in by_slug.items():
        me = bucket["me"]
        everyone = bucket["everyone"]
        if me is not None:
            effective = me.rail_position
        elif everyone is not None:
            effective = everyone.rail_position
        else:
            effective = None
        out[slug] = {
            "me_pinned": me is not None,
            "everyone_pinned": everyone is not None,
            "effective_position": effective,
        }
    return out
