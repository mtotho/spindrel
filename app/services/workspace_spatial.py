"""Workspace Spatial Canvas — node placements.

The canvas is a workspace-scope infinite plane. Each tile has a single row
in ``workspace_spatial_nodes`` — the only source of truth for world
position. Two node target shapes:

* **Channel nodes** (``channel_id`` set) — auto-created on read for every
  channel that doesn't yet have a row. Position seeded by phyllotaxis from
  a persisted ``seed_index`` (monotonic, never recomputed) so layout is
  stable across tabs and re-renders.

* **Widget nodes** (``widget_pin_id`` set) — created via the atomic
  :func:`pin_widget_to_canvas` helper, which writes a
  ``widget_dashboard_pins`` row on the reserved ``workspace:spatial``
  dashboard and the matching ``workspace_spatial_nodes`` row in one
  transaction. Cascade-on-delete handles cleanup.

Channel and widget pins are independent — a widget can be on a channel
dashboard AND on the canvas; the two pin rows are separate.
"""
from __future__ import annotations

import logging
import math
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, WidgetDashboardPin, WorkspaceSpatialNode
from app.domain.errors import NotFoundError, ValidationError
from app.services.dashboard_pins import create_pin
from app.services.dashboards import WORKSPACE_SPATIAL_DASHBOARD_KEY


logger = logging.getLogger(__name__)


# Phyllotaxis (golden-angle) seed parameters — match the prototype + Track
# decision #6. Tuned to keep tiles well-spaced at default tile size.
_GOLDEN_ANGLE = math.pi * (3.0 - math.sqrt(5.0))  # ≈ 137.5°
_PHYLLOTAXIS_RADIUS = 280.0
_DEFAULT_TILE_W = 220.0
_DEFAULT_TILE_H = 140.0


def phyllotaxis_position(seed_index: int) -> tuple[float, float]:
    """Return the deterministic (world_x, world_y) for a given seed index.

    Centers the tile box on the computed point so the visual center of the
    tile matches the phyllotaxis spiral.
    """
    if seed_index < 0:
        seed_index = 0
    radius = _PHYLLOTAXIS_RADIUS * math.sqrt(seed_index)
    angle = seed_index * _GOLDEN_ANGLE
    cx = radius * math.cos(angle)
    cy = radius * math.sin(angle)
    return (cx - _DEFAULT_TILE_W / 2, cy - _DEFAULT_TILE_H / 2)


def serialize_node(node: WorkspaceSpatialNode) -> dict[str, Any]:
    return {
        "id": str(node.id),
        "channel_id": str(node.channel_id) if node.channel_id else None,
        "widget_pin_id": str(node.widget_pin_id) if node.widget_pin_id else None,
        "world_x": node.world_x,
        "world_y": node.world_y,
        "world_w": node.world_w,
        "world_h": node.world_h,
        "z_index": node.z_index,
        "seed_index": node.seed_index,
        "pinned_at": node.pinned_at.isoformat() if node.pinned_at else None,
        "updated_at": node.updated_at.isoformat() if node.updated_at else None,
    }


async def _next_seed_index(db: AsyncSession) -> int:
    """Allocate the next monotonic seed_index.

    Reads MAX(seed_index) and returns +1. Tab races aren't guaranteed
    collision-free under naive max-read — but the seed_index is only used
    for visual placement, not as a uniqueness constraint, so a duplicate
    just means two tiles spawn on the same phyllotaxis slot until the user
    drags one. Acceptable for visual-only metadata.
    """
    row = (await db.execute(
        select(func.max(WorkspaceSpatialNode.seed_index))
    )).scalar_one_or_none()
    return (row or 0) + 1 if row is not None else 0


async def _ensure_channel_nodes(db: AsyncSession) -> int:
    """Create a node row for every channel that doesn't have one yet.

    Returns the number of new rows inserted. The seed_index is allocated
    monotonically so newly-discovered channels land on fresh phyllotaxis
    slots without disturbing existing pinned positions.
    """
    # Channels missing a node row.
    missing_stmt = (
        select(Channel.id)
        .outerjoin(
            WorkspaceSpatialNode,
            WorkspaceSpatialNode.channel_id == Channel.id,
        )
        .where(WorkspaceSpatialNode.id.is_(None))
    )
    missing_ids = [r[0] for r in (await db.execute(missing_stmt)).all()]
    if not missing_ids:
        return 0

    next_seed = await _next_seed_index(db)
    for ch_id in missing_ids:
        x, y = phyllotaxis_position(next_seed)
        db.add(WorkspaceSpatialNode(
            channel_id=ch_id,
            world_x=x,
            world_y=y,
            world_w=_DEFAULT_TILE_W,
            world_h=_DEFAULT_TILE_H,
            seed_index=next_seed,
        ))
        next_seed += 1
    await db.commit()
    return len(missing_ids)


async def list_nodes(db: AsyncSession) -> list[WorkspaceSpatialNode]:
    """Return every spatial node, auto-populating channel rows on first
    read so the canvas is never empty for a workspace with channels."""
    await _ensure_channel_nodes(db)
    rows = (await db.execute(
        select(WorkspaceSpatialNode).order_by(WorkspaceSpatialNode.pinned_at.asc())
    )).scalars().all()
    return list(rows)


async def get_node(db: AsyncSession, node_id: uuid.UUID) -> WorkspaceSpatialNode:
    row = (await db.execute(
        select(WorkspaceSpatialNode).where(WorkspaceSpatialNode.id == node_id)
    )).scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"Spatial node not found: {node_id}")
    return row


async def update_node_position(
    db: AsyncSession,
    node_id: uuid.UUID,
    *,
    world_x: float | None = None,
    world_y: float | None = None,
    world_w: float | None = None,
    world_h: float | None = None,
    z_index: int | None = None,
) -> WorkspaceSpatialNode:
    node = await get_node(db, node_id)
    if world_x is not None:
        node.world_x = float(world_x)
    if world_y is not None:
        node.world_y = float(world_y)
    if world_w is not None:
        if world_w <= 0:
            raise ValidationError("world_w must be > 0")
        node.world_w = float(world_w)
    if world_h is not None:
        if world_h <= 0:
            raise ValidationError("world_h must be > 0")
        node.world_h = float(world_h)
    if z_index is not None:
        node.z_index = int(z_index)
    await db.commit()
    await db.refresh(node)
    return node


async def delete_node(db: AsyncSession, node_id: uuid.UUID) -> None:
    """Remove a spatial node.

    For widget nodes, also deletes the underlying ``widget_dashboard_pins``
    row so the world pin is fully cleaned up. (Cascade goes the other way:
    deleting the pin removes the node. We don't want to leave a phantom
    widget pin on ``workspace:spatial`` with no canvas position.)

    For channel nodes, only removes the spatial row; the channel itself is
    untouched. The next ``list_nodes`` call will re-seed it at a new
    phyllotaxis slot — this is the "reset position" gesture.
    """
    node = await get_node(db, node_id)
    if node.widget_pin_id is not None:
        pin = await db.get(WidgetDashboardPin, node.widget_pin_id)
        # Explicit child-then-parent delete keeps SQLite test parity. In
        # production (Postgres) the FK cascade would handle the node row,
        # but SQLite tests don't enable PRAGMA foreign_keys.
        await db.delete(node)
        if pin is not None:
            await db.delete(pin)
        await db.commit()
        return
    await db.delete(node)
    await db.commit()


async def pin_widget_to_canvas(
    db: AsyncSession,
    *,
    source_kind: str,
    tool_name: str,
    envelope: dict,
    source_channel_id: uuid.UUID | None = None,
    source_bot_id: str | None = None,
    tool_args: dict | None = None,
    widget_config: dict | None = None,
    widget_origin: dict | None = None,
    display_label: str | None = None,
    world_x: float | None = None,
    world_y: float | None = None,
    world_w: float = _DEFAULT_TILE_W,
    world_h: float = _DEFAULT_TILE_H,
) -> tuple[WidgetDashboardPin, WorkspaceSpatialNode]:
    """Atomically create a widget pin on the workspace:spatial dashboard
    AND its matching workspace_spatial_nodes row.

    Both writes commit together. If the spatial node insert fails, the pin
    is dropped (compensating delete). No orphan pins.
    """
    pin = await create_pin(
        db,
        source_kind=source_kind,
        tool_name=tool_name,
        envelope=envelope,
        source_channel_id=source_channel_id,
        source_bot_id=source_bot_id,
        tool_args=tool_args,
        widget_config=widget_config,
        widget_origin=widget_origin,
        display_label=display_label,
        dashboard_key=WORKSPACE_SPATIAL_DASHBOARD_KEY,
        zone="grid",
        commit=False,
    )

    try:
        seed = await _next_seed_index(db)
        if world_x is None or world_y is None:
            seeded_x, seeded_y = phyllotaxis_position(seed)
            if world_x is None:
                world_x = seeded_x
            if world_y is None:
                world_y = seeded_y
        node = WorkspaceSpatialNode(
            widget_pin_id=pin.id,
            world_x=float(world_x),
            world_y=float(world_y),
            world_w=float(world_w),
            world_h=float(world_h),
            seed_index=seed,
        )
        db.add(node)
        await db.commit()
        await db.refresh(pin)
        await db.refresh(node)
    except Exception:
        # Pin write was flushed but never committed — the rollback drops
        # both. Defensive in case the failure happens after a partial
        # commit on a dialect that auto-commits on flush.
        await db.rollback()
        logger.exception("pin_widget_to_canvas failed; rolled back pin %s", pin.id)
        raise

    # Post-commit registration mirrors create_pin's tail. Best-effort.
    try:
        from app.services.widget_cron import register_pin_crons
        await register_pin_crons(db, pin)
    except Exception:
        logger.exception("register_pin_crons failed for canvas pin %s", pin.id)
    try:
        from app.services.widget_events import register_pin_events
        await register_pin_events(db, pin)
    except Exception:
        logger.exception("register_pin_events failed for canvas pin %s", pin.id)

    return pin, node
