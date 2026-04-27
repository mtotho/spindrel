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
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import Channel, ChannelBotMember, Message, Session, WidgetDashboardPin, WidgetInstance, WorkspaceSpatialNode
from app.domain.errors import NotFoundError, ValidationError
from app.services.dashboard_pins import create_pin, get_pin
from app.services.dashboards import WORKSPACE_SPATIAL_DASHBOARD_KEY


logger = logging.getLogger(__name__)


# Phyllotaxis (golden-angle) seed parameters — match the prototype + Track
# decision #6. Tuned to keep tiles well-spaced at default tile size.
_GOLDEN_ANGLE = math.pi * (3.0 - math.sqrt(5.0))  # ≈ 137.5°
_PHYLLOTAXIS_RADIUS = 280.0
_DEFAULT_TILE_W = 280.0
_DEFAULT_TILE_H = 180.0
# Widgets host live iframes at close zoom — give them more room than channels
# by default. They're also a visually distinct shape (wider aspect ratio +
# more chrome) so the user reads "this is a widget, not a channel" at any
# zoom level. Existing rows keep their stored size; only new pins use these.
_DEFAULT_WIDGET_W = 360.0
_DEFAULT_WIDGET_H = 240.0
_DEFAULT_BOT_W = 260.0
_DEFAULT_BOT_H = 180.0

# Fixed system landmarks. Default world coords mirror the UI fallbacks in
# ui/src/components/spatial-canvas/spatialGeometry.ts; once the seed row
# exists, the row is the source of truth and the user can drag landmarks
# anywhere on the canvas. world_w/world_h are zero because landmarks size
# themselves in CSS; the row is just the position anchor.
LANDMARK_DEFAULTS: dict[str, tuple[float, float]] = {
    "now_well": (0.0, 2200.0),
    "memory_observatory": (-2800.0, 100.0),
    "attention_hub": (0.0, -650.0),
    "daily_health": (1100.0, -650.0),
}
# Satellite ring around a source channel — first widget sits ~_SAT_RING out
# from the channel's center; subsequent widgets spiral outward by the golden
# angle so they don't pile up at one bearing.
_SAT_RING_RADIUS = 220.0
_SAT_RING_GROWTH = 60.0

# Comet-tail trail retention. Each node keeps a bounded log of recent
# positions so the canvas can render a fading polyline behind it. Older
# entries get pruned by TTL; the list is also capped to bound payload size
# (a chatty bot tugging things at heartbeat shouldn't blow up serialize_node).
MOVEMENT_HISTORY_TTL_HOURS = 72
MAX_HISTORY_POINTS = 30

# Hard sanity bound on world coordinates. Phyllotaxis seeds + tug steps stay
# inside ±5k; even pathological pinch-zoom-mid-drag cases land within ±20k.
# A drag that produces |world_x| or |world_y| beyond this is treated as a
# client glitch and rejected — the tile stays put, recoverable via Cmd+K or
# the right-click "Move … here" picker.
WORLD_COORD_LIMIT = 50_000.0

SPATIAL_POLICY_KEY = "spatial_bots"
DEFAULT_SPATIAL_POLICY: dict[str, Any] = {
    "enabled": False,
    "allow_movement": False,
    "step_world_units": 32,
    "max_move_steps_per_turn": 2,
    "minimum_clearance_steps": 3,
    "awareness_radius_steps": 8,
    "nearest_neighbor_floor": 3,
    "allow_moving_spatial_objects": False,
    "allow_spatial_widget_management": False,
    "allow_attention_beacons": False,
    "allow_map_view": False,
    "tug_radius_steps": 2,
    "max_tug_steps_per_turn": 1,
    "allow_nearby_inspect": False,
    "movement_trace_ttl_minutes": 30,
}


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


def serialize_node(
    node: WorkspaceSpatialNode,
    pin: "WidgetDashboardPin | None" = None,
) -> dict[str, Any]:
    """Serialize a node row. When `pin` is supplied (widget nodes only) the
    pin's full payload is embedded inline so the client can render the
    widget without a second roundtrip — envelope, contract/presentation
    snapshots, source bot, display label, tool name."""
    out: dict[str, Any] = {
        "id": str(node.id),
        "channel_id": str(node.channel_id) if node.channel_id else None,
        "widget_pin_id": str(node.widget_pin_id) if node.widget_pin_id else None,
        "bot_id": node.bot_id,
        "landmark_kind": node.landmark_kind,
        "world_x": node.world_x,
        "world_y": node.world_y,
        "world_w": node.world_w,
        "world_h": node.world_h,
        "z_index": node.z_index,
        "seed_index": node.seed_index,
        "pinned_at": node.pinned_at.isoformat() if node.pinned_at else None,
        "updated_at": node.updated_at.isoformat() if node.updated_at else None,
        "last_movement": node.last_movement,
        "position_history": list(node.position_history or []),
    }
    if node.bot_id:
        try:
            from app.agent.bots import get_bot
            bot = get_bot(node.bot_id)
            out["bot"] = {
                "id": bot.id,
                "name": bot.name,
                "display_name": bot.display_name,
                "avatar_url": bot.avatar_url,
                "avatar_emoji": getattr(bot, "avatar_emoji", None),
            }
        except Exception:
            out["bot"] = {"id": node.bot_id, "name": node.bot_id}
    if pin is not None:
        # Lazy import — keeps the dashboard_pins serializer optional for
        # callers that only need bare-bones channel-node serialization.
        from app.services.dashboard_pins import serialize_pin

        out["pin"] = serialize_pin(pin)
    return out


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


async def _satellite_position_for_channel(
    db: AsyncSession,
    source_channel_id: uuid.UUID,
) -> tuple[float, float] | None:
    """Compute (world_x, world_y) for a new widget pinned from this channel.

    Looks up the channel's spatial node and places the new widget on a
    golden-angle ring around its center. Subsequent widgets from the same
    channel spiral outward so they don't stack on top of each other.

    Returns ``None`` when the channel has no spatial node yet — caller falls
    back to global phyllotaxis. (The channel-node-upsert in
    ``_ensure_channel_nodes`` runs on canvas list, so the row may legitimately
    be missing if the user hasn't opened the canvas yet — we handle that by
    auto-seeding the channel node first; see ``pin_widget_to_canvas``.)
    """
    channel_node = (await db.execute(
        select(WorkspaceSpatialNode).where(
            WorkspaceSpatialNode.channel_id == source_channel_id,
        )
    )).scalar_one_or_none()
    if channel_node is None:
        return None
    # Existing widget pins sourced from this channel (any spatial-node status
    # — counts both placed and yet-to-be-placed; safer than joining on
    # WorkspaceSpatialNode and missing in-flight rows). The dashboard the pin
    # lives on doesn't matter; what matters is "how many widgets the user has
    # already pulled out of this channel."
    existing = (await db.execute(
        select(func.count(WorkspaceSpatialNode.id))
        .join(
            WidgetDashboardPin,
            WorkspaceSpatialNode.widget_pin_id == WidgetDashboardPin.id,
        )
        .where(WidgetDashboardPin.source_channel_id == source_channel_id)
    )).scalar_one()
    cx = channel_node.world_x + _DEFAULT_TILE_W / 2
    cy = channel_node.world_y + _DEFAULT_TILE_H / 2
    angle = (existing + 1) * _GOLDEN_ANGLE
    radius = _SAT_RING_RADIUS + math.sqrt(existing) * _SAT_RING_GROWTH
    sx = cx + math.cos(angle) * radius
    sy = cy + math.sin(angle) * radius
    return (sx - _DEFAULT_TILE_W / 2, sy - _DEFAULT_TILE_H / 2)


async def _ensure_channel_node(
    db: AsyncSession,
    channel_id: uuid.UUID,
) -> WorkspaceSpatialNode | None:
    """Create a spatial node for one channel if it doesn't have one yet.

    Returns the existing or newly-created node, or None if the channel id
    doesn't resolve. Smaller-scope variant of ``_ensure_channel_nodes`` —
    used by ``pin_widget_to_canvas`` so satellite-positioning works even if
    the user hasn't opened the canvas yet.
    """
    existing = (await db.execute(
        select(WorkspaceSpatialNode).where(
            WorkspaceSpatialNode.channel_id == channel_id,
        )
    )).scalar_one_or_none()
    if existing is not None:
        return existing
    # Verify the channel actually exists before seeding — guard against
    # callers passing a stale id that could otherwise create a phantom node.
    ch_exists = (await db.execute(
        select(Channel.id).where(Channel.id == channel_id)
    )).scalar_one_or_none()
    if ch_exists is None:
        return None
    seed = await _next_seed_index(db)
    x, y = phyllotaxis_position(seed)
    node = WorkspaceSpatialNode(
        channel_id=channel_id,
        world_x=x,
        world_y=y,
        world_w=_DEFAULT_TILE_W,
        world_h=_DEFAULT_TILE_H,
        seed_index=seed,
    )
    db.add(node)
    await db.flush()
    return node


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


async def _resolved_primary_channel_for_bot(
    db: AsyncSession,
    bot_id: str,
) -> Channel | None:
    primary = (await db.execute(
        select(Channel)
        .where(Channel.bot_id == bot_id)
        .order_by(Channel.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if primary is not None:
        return primary
    return (await db.execute(
        select(Channel)
        .join(ChannelBotMember, ChannelBotMember.channel_id == Channel.id)
        .where(ChannelBotMember.bot_id == bot_id)
        .order_by(ChannelBotMember.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()


def _rect_edge_clearance(
    *,
    a_x: float,
    a_y: float,
    a_w: float,
    a_h: float,
    b: WorkspaceSpatialNode,
) -> float:
    """Return visual gap between an arbitrary rect and a spatial node."""
    right_a = a_x + a_w
    bottom_a = a_y + a_h
    right_b = b.world_x + b.world_w
    bottom_b = b.world_y + b.world_h
    dx = max(b.world_x - right_a, a_x - right_b, 0.0)
    dy = max(b.world_y - bottom_a, a_y - bottom_b, 0.0)
    return math.hypot(dx, dy)


def _default_min_clearance_world_units() -> float:
    return float(
        DEFAULT_SPATIAL_POLICY["minimum_clearance_steps"]
        * DEFAULT_SPATIAL_POLICY["step_world_units"]
    )


def _candidate_clears_existing_nodes(
    *,
    world_x: float,
    world_y: float,
    world_w: float,
    world_h: float,
    existing_nodes: list[WorkspaceSpatialNode],
    min_clearance: float,
    ignore_node_id: uuid.UUID | None = None,
) -> bool:
    for other in existing_nodes:
        if ignore_node_id is not None and other.id == ignore_node_id:
            continue
        if _rect_edge_clearance(
            a_x=world_x,
            a_y=world_y,
            a_w=world_w,
            a_h=world_h,
            b=other,
        ) < min_clearance:
            return False
    return True


def _bot_spawn_position_near_channel(
    *,
    channel_node: WorkspaceSpatialNode,
    seed: int,
    existing_nodes: list[WorkspaceSpatialNode],
    ignore_node_id: uuid.UUID | None = None,
) -> tuple[float, float]:
    """Pick a deterministic nearby bot spawn that is not born crowded.

    The bot visual is nearly as large as a channel tile. A small center-radius
    orbit makes the rectangles overlap even though the actor looks "near" on
    the map, which then causes the movement guard to reject reasonable first
    moves. Search a few deterministic rings around the source channel and keep
    the first position that satisfies the default clearance from every current
    canvas node.
    """
    min_clearance = _default_min_clearance_world_units()
    cx, cy = _node_center(channel_node)
    half_w = channel_node.world_w / 2 + _DEFAULT_BOT_W / 2
    half_h = channel_node.world_h / 2 + _DEFAULT_BOT_H / 2
    base_radius = max(half_w, half_h) + min_clearance
    start_angle = (seed + 1) * _GOLDEN_ANGLE
    angle_step = math.tau / 16
    ring_step = max(float(DEFAULT_SPATIAL_POLICY["step_world_units"]) * 2, min_clearance / 2)
    fallback: tuple[float, float] | None = None

    for ring in range(8):
        radius = base_radius + ring * ring_step
        for slot in range(16):
            angle = start_angle + slot * angle_step
            world_x = cx + math.cos(angle) * radius - _DEFAULT_BOT_W / 2
            world_y = cy + math.sin(angle) * radius - _DEFAULT_BOT_H / 2
            fallback = (float(world_x), float(world_y))
            if _candidate_clears_existing_nodes(
                world_x=float(world_x),
                world_y=float(world_y),
                world_w=_DEFAULT_BOT_W,
                world_h=_DEFAULT_BOT_H,
                existing_nodes=existing_nodes,
                min_clearance=min_clearance,
                ignore_node_id=ignore_node_id,
            ):
                return (float(world_x), float(world_y))

    assert fallback is not None
    return fallback


async def _ensure_bot_node(
    db: AsyncSession,
    bot_id: str,
    changed_out: list[bool] | None = None,
) -> WorkspaceSpatialNode | None:
    existing = (await db.execute(
        select(WorkspaceSpatialNode).where(WorkspaceSpatialNode.bot_id == bot_id)
    )).scalar_one_or_none()
    if existing is not None:
        changed = False
        if existing.world_w < _DEFAULT_BOT_W or existing.world_h < _DEFAULT_BOT_H:
            cx, cy = _node_center(existing)
            existing.world_w = _DEFAULT_BOT_W
            existing.world_h = _DEFAULT_BOT_H
            existing.world_x = cx - _DEFAULT_BOT_W / 2
            existing.world_y = cy - _DEFAULT_BOT_H / 2
            changed = True
        channel = await _resolved_primary_channel_for_bot(db, bot_id)
        if channel is not None and existing.last_movement is None:
            channel_node = await _ensure_channel_node(db, channel.id)
            if (
                channel_node is not None
                and _edge_clearance(existing, channel_node) < _default_min_clearance_world_units()
                and _distance(existing, channel_node) <= 180.0
            ):
                nodes = list((await db.execute(
                    select(WorkspaceSpatialNode).where(
                        WorkspaceSpatialNode.landmark_kind.is_(None),
                    )
                )).scalars().all())
                existing.world_x, existing.world_y = _bot_spawn_position_near_channel(
                    channel_node=channel_node,
                    seed=existing.seed_index or 0,
                    existing_nodes=nodes,
                    ignore_node_id=existing.id,
                )
                changed = True
        if changed:
            await db.flush()
            if changed_out is not None:
                changed_out[0] = True
        return existing

    seed = await _next_seed_index(db)
    world_x, world_y = phyllotaxis_position(seed)
    channel = await _resolved_primary_channel_for_bot(db, bot_id)
    if channel is not None:
        channel_node = await _ensure_channel_node(db, channel.id)
        if channel_node is not None:
            nodes = list((await db.execute(select(WorkspaceSpatialNode))).scalars().all())
            world_x, world_y = _bot_spawn_position_near_channel(
                channel_node=channel_node,
                seed=seed,
                existing_nodes=nodes,
            )

    node = WorkspaceSpatialNode(
        bot_id=bot_id,
        world_x=float(world_x),
        world_y=float(world_y),
        world_w=_DEFAULT_BOT_W,
        world_h=_DEFAULT_BOT_H,
        seed_index=seed,
    )
    db.add(node)
    await db.flush()
    return node


async def _ensure_landmark_nodes(db: AsyncSession) -> int:
    """Create a row for each fixed system landmark that doesn't have one yet.

    Landmarks (Now Well, Memory Observatory, Attention Hub, Daily Health) are
    stored as ordinary spatial nodes with ``landmark_kind`` set so the user
    can drag them just like channel and widget tiles. First read seeds them
    at the canonical default positions in ``LANDMARK_DEFAULTS``; subsequent
    reads no-op thanks to the partial unique index.
    """
    existing_rows = (await db.execute(
        select(WorkspaceSpatialNode.landmark_kind).where(
            WorkspaceSpatialNode.landmark_kind.is_not(None),
        )
    )).scalars().all()
    existing = {row for row in existing_rows if row}
    inserted = 0
    for kind, (x, y) in LANDMARK_DEFAULTS.items():
        if kind in existing:
            continue
        db.add(WorkspaceSpatialNode(
            landmark_kind=kind,
            world_x=float(x),
            world_y=float(y),
            world_w=0.0,
            world_h=0.0,
        ))
        inserted += 1
    if inserted:
        await db.commit()
    return inserted


async def _ensure_bot_nodes(db: AsyncSession) -> int:
    primary_ids = (await db.execute(
        select(Channel.bot_id).where(Channel.bot_id.is_not(None))
    )).scalars().all()
    member_ids = (await db.execute(
        select(ChannelBotMember.bot_id)
    )).scalars().all()
    bot_ids = sorted({bot_id for bot_id in [*primary_ids, *member_ids] if bot_id})
    count = 0
    changed = False
    for bot_id in bot_ids:
        before = (await db.execute(
            select(WorkspaceSpatialNode.id).where(WorkspaceSpatialNode.bot_id == bot_id)
        )).scalar_one_or_none()
        changed_out = [False]
        await _ensure_bot_node(db, bot_id, changed_out=changed_out)
        if before is None:
            count += 1
        changed = changed or changed_out[0]
    if count or changed:
        await db.commit()
    return count


async def list_nodes(
    db: AsyncSession,
) -> list[tuple[WorkspaceSpatialNode, WidgetDashboardPin | None]]:
    """Return every spatial node paired with its pin (or None for channel
    nodes). Auto-populates channel rows on first read so the canvas is
    never empty for a workspace with channels.

    A single follow-up query loads pins by id for the widget nodes, so the
    response shape stays one-roundtrip from the client perspective.

    Native-widget pin envelopes are rebuilt from the authoritative
    ``WidgetInstance.state`` before the response — without this the
    canvas will hand the UI a stale snapshot from pin-create time after
    every page reload, even though dispatch already mutated the instance.
    """
    await _ensure_channel_nodes(db)
    await _ensure_bot_nodes(db)
    await _ensure_landmark_nodes(db)
    rows = (await db.execute(
        select(WorkspaceSpatialNode).order_by(WorkspaceSpatialNode.pinned_at.asc())
    )).scalars().all()
    nodes = list(rows)
    pin_ids = [n.widget_pin_id for n in nodes if n.widget_pin_id is not None]
    pin_map: dict[uuid.UUID, WidgetDashboardPin] = {}
    if pin_ids:
        pin_rows = (await db.execute(
            select(WidgetDashboardPin).where(WidgetDashboardPin.id.in_(pin_ids))
        )).scalars().all()
        # Rebuild native-app envelopes from their instance state. Same helper
        # the dashboard list path uses; identical drift symptom otherwise.
        from app.services.dashboard_pins import _sync_native_pin_envelopes

        if await _sync_native_pin_envelopes(db, list(pin_rows)):
            await db.commit()
        pin_map = {p.id: p for p in pin_rows}
    missing_pin_nodes = [
        n
        for n in nodes
        if n.widget_pin_id is not None and n.widget_pin_id not in pin_map
    ]
    if missing_pin_nodes:
        for node in missing_pin_nodes:
            await db.delete(node)
        await db.commit()
        missing_ids = {n.id for n in missing_pin_nodes}
        nodes = [n for n in nodes if n.id not in missing_ids]
    return [(n, pin_map.get(n.widget_pin_id) if n.widget_pin_id else None) for n in nodes]


async def get_node(db: AsyncSession, node_id: uuid.UUID) -> WorkspaceSpatialNode:
    row = (await db.execute(
        select(WorkspaceSpatialNode).where(WorkspaceSpatialNode.id == node_id)
    )).scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"Spatial node not found: {node_id}")
    return row


def _coerce_positive_int(value: Any, default: int, *, minimum: int = 0, maximum: int = 1000) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def normalize_spatial_policy(raw: dict | None) -> dict[str, Any]:
    policy = dict(DEFAULT_SPATIAL_POLICY)
    if isinstance(raw, dict):
        policy.update(raw)
    for key in (
        "enabled",
        "allow_movement",
        "allow_moving_spatial_objects",
        "allow_spatial_widget_management",
        "allow_attention_beacons",
        "allow_map_view",
        "allow_nearby_inspect",
    ):
        policy[key] = bool(policy.get(key))
    policy["step_world_units"] = _coerce_positive_int(policy.get("step_world_units"), 32, minimum=1, maximum=1000)
    policy["max_move_steps_per_turn"] = _coerce_positive_int(policy.get("max_move_steps_per_turn"), 2, minimum=0, maximum=100)
    policy["minimum_clearance_steps"] = _coerce_positive_int(policy.get("minimum_clearance_steps"), 3, minimum=0, maximum=100)
    policy["awareness_radius_steps"] = _coerce_positive_int(policy.get("awareness_radius_steps"), 8, minimum=0, maximum=1000)
    policy["nearest_neighbor_floor"] = _coerce_positive_int(policy.get("nearest_neighbor_floor"), 3, minimum=0, maximum=50)
    policy["tug_radius_steps"] = _coerce_positive_int(policy.get("tug_radius_steps"), 2, minimum=0, maximum=100)
    policy["max_tug_steps_per_turn"] = _coerce_positive_int(policy.get("max_tug_steps_per_turn"), 1, minimum=0, maximum=100)
    policy["movement_trace_ttl_minutes"] = _coerce_positive_int(policy.get("movement_trace_ttl_minutes"), 30, minimum=1, maximum=24 * 60)
    return policy


def _spatial_policies_from_channel(channel: Channel) -> dict[str, Any]:
    cfg = channel.config or {}
    raw = cfg.get(SPATIAL_POLICY_KEY)
    return raw if isinstance(raw, dict) else {}


async def get_channel_bot_spatial_policy(
    db: AsyncSession,
    channel_id: uuid.UUID,
    bot_id: str,
) -> dict[str, Any]:
    channel = await db.get(Channel, channel_id)
    if channel is None:
        raise NotFoundError(f"Channel not found: {channel_id}")
    return normalize_spatial_policy(_spatial_policies_from_channel(channel).get(bot_id))


async def update_channel_bot_spatial_policy(
    db: AsyncSession,
    channel_id: uuid.UUID,
    bot_id: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    channel = await db.get(Channel, channel_id)
    if channel is None:
        raise NotFoundError(f"Channel not found: {channel_id}")
    allowed = set(DEFAULT_SPATIAL_POLICY)
    current = get_channel_bot_spatial_policy_sync(channel, bot_id)
    for key, value in updates.items():
        if key in allowed:
            current[key] = value
    normalized = normalize_spatial_policy(current)
    cfg = dict(channel.config or {})
    policies = dict(cfg.get(SPATIAL_POLICY_KEY) or {})
    policies[bot_id] = normalized
    cfg[SPATIAL_POLICY_KEY] = policies
    channel.config = cfg
    flag_modified(channel, "config")
    await db.commit()
    return normalized


def get_channel_bot_spatial_policy_sync(channel: Channel | None, bot_id: str) -> dict[str, Any]:
    if channel is None:
        return normalize_spatial_policy(None)
    return normalize_spatial_policy(_spatial_policies_from_channel(channel).get(bot_id))


def _node_center(node: WorkspaceSpatialNode) -> tuple[float, float]:
    return (node.world_x + node.world_w / 2, node.world_y + node.world_h / 2)


def _distance(a: WorkspaceSpatialNode, b: WorkspaceSpatialNode) -> float:
    ax, ay = _node_center(a)
    bx, by = _node_center(b)
    return math.hypot(ax - bx, ay - by)


def _edge_clearance(
    a: WorkspaceSpatialNode,
    b: WorkspaceSpatialNode,
    *,
    a_x: float | None = None,
    a_y: float | None = None,
) -> float:
    """Return visual gap between node rectangles; 0 means touching/overlap."""
    left_a = a.world_x if a_x is None else a_x
    top_a = a.world_y if a_y is None else a_y
    return _rect_edge_clearance(
        a_x=left_a,
        a_y=top_a,
        a_w=a.world_w,
        a_h=a.world_h,
        b=b,
    )


def _center_distance_from(
    a: WorkspaceSpatialNode,
    b: WorkspaceSpatialNode,
    *,
    a_x: float,
    a_y: float,
) -> float:
    ax = a_x + a.world_w / 2
    ay = a_y + a.world_h / 2
    bx, by = _node_center(b)
    return math.hypot(ax - bx, ay - by)


def _append_position_history(
    node: WorkspaceSpatialNode,
    *,
    prev_x: float,
    prev_y: float,
    new_x: float,
    new_y: float,
    actor: str | None = None,
    ts: datetime | None = None,
) -> None:
    """Append a `(prev_x, prev_y)` entry to ``node.position_history`` and
    prune entries older than ``MOVEMENT_HISTORY_TTL_HOURS`` / beyond
    ``MAX_HISTORY_POINTS``. No-op moves (same coords) are skipped so we
    don't pollute the trail with z-index / size-only updates.

    Reassigns the list back to the column so SQLAlchemy's JSON change
    tracking picks up the mutation (in-place ``.append`` on a JSONB column
    isn't reliable across dialects).
    """
    if prev_x == new_x and prev_y == new_y:
        return
    now = ts or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=MOVEMENT_HISTORY_TTL_HOURS)
    history: list[dict[str, Any]] = list(node.position_history or [])
    pruned: list[dict[str, Any]] = []
    for entry in history:
        raw_ts = entry.get("ts") if isinstance(entry, dict) else None
        if not raw_ts:
            continue
        try:
            entry_ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        if entry_ts.tzinfo is None:
            entry_ts = entry_ts.replace(tzinfo=timezone.utc)
        if entry_ts >= cutoff:
            pruned.append(entry)
    pruned.append({
        "x": float(prev_x),
        "y": float(prev_y),
        "ts": now.isoformat(),
        "actor": actor,
    })
    if len(pruned) > MAX_HISTORY_POINTS:
        pruned = pruned[-MAX_HISTORY_POINTS:]
    node.position_history = pruned
    flag_modified(node, "position_history")


def _movement_payload(
    *,
    actor_bot_id: str,
    channel_id: uuid.UUID,
    kind: str,
    from_x: float,
    from_y: float,
    to_x: float,
    to_y: float,
    reason: str | None,
    ttl_minutes: int,
    target_node_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc)
    return {
        "kind": kind,
        "actor_bot_id": actor_bot_id,
        "channel_id": str(channel_id),
        "target_node_id": str(target_node_id) if target_node_id else None,
        "from": {"x": from_x, "y": from_y},
        "to": {"x": to_x, "y": to_y},
        "reason": reason,
        "created_at": created_at.isoformat(),
        "expires_at": (created_at + timedelta(minutes=int(ttl_minutes))).isoformat(),
        "ttl_minutes": int(ttl_minutes),
    }


async def move_bot_node(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID,
    bot_id: str,
    dx_steps: int,
    dy_steps: int,
    reason: str | None = None,
) -> WorkspaceSpatialNode:
    policy = await get_channel_bot_spatial_policy(db, channel_id, bot_id)
    if not policy["enabled"] or not policy["allow_movement"]:
        raise ValidationError("Spatial movement is not enabled for this bot in this channel.")
    step_count = abs(int(dx_steps)) + abs(int(dy_steps))
    if step_count <= 0:
        raise ValidationError("Movement requires at least one step.")
    if step_count > policy["max_move_steps_per_turn"]:
        raise ValidationError(f"Movement exceeds max_move_steps_per_turn={policy['max_move_steps_per_turn']}.")
    node = await _ensure_bot_node(db, bot_id)
    if node is None:
        raise NotFoundError(f"Bot node not found: {bot_id}")
    from_x, from_y = node.world_x, node.world_y
    step = float(policy["step_world_units"])
    to_x = float(node.world_x + int(dx_steps) * step)
    to_y = float(node.world_y + int(dy_steps) * step)
    min_clearance = float(policy["minimum_clearance_steps"] * policy["step_world_units"])
    if min_clearance > 0:
        nodes, pin_map = await _nodes_with_pins(db)
        for other in nodes:
            if other.id == node.id:
                continue
            before_clearance = _edge_clearance(node, other)
            after_clearance = _edge_clearance(node, other, a_x=to_x, a_y=to_y)
            if after_clearance >= min_clearance:
                continue
            before_center = _distance(node, other)
            after_center = _center_distance_from(node, other, a_x=to_x, a_y=to_y)
            if after_clearance < before_clearance or (
                after_clearance == before_clearance and after_center < before_center
            ):
                pin = pin_map.get(other.widget_pin_id) if other.widget_pin_id else None
                blocker_label = _node_label(other, pin)
                if other.channel_id:
                    channel = await db.get(Channel, other.channel_id)
                    if channel is not None:
                        blocker_label = f"#{channel.name}"
                before_steps = before_clearance / step if step else before_clearance
                after_steps = after_clearance / step if step else after_clearance
                raise ValidationError(
                    "Move would crowd another canvas object; keep at least "
                    f"{policy['minimum_clearance_steps']} step(s) of clearance or move away first. "
                    f"Blocking object: {blocker_label} ({_node_kind(other)}), "
                    f"edge gap {before_steps:.1f} -> {after_steps:.1f} step(s)."
                )
    node.world_x = to_x
    node.world_y = to_y
    node.last_movement = _movement_payload(
        actor_bot_id=bot_id,
        channel_id=channel_id,
        kind="bot_move",
        from_x=from_x,
        from_y=from_y,
        to_x=node.world_x,
        to_y=node.world_y,
        reason=reason,
        ttl_minutes=policy["movement_trace_ttl_minutes"],
        target_node_id=node.id,
    )
    _append_position_history(
        node,
        prev_x=from_x,
        prev_y=from_y,
        new_x=node.world_x,
        new_y=node.world_y,
        actor=None,
    )
    await db.commit()
    await db.refresh(node)
    return node


def _node_label(node: WorkspaceSpatialNode, pin: WidgetDashboardPin | None = None) -> str:
    if node.bot_id:
        try:
            from app.agent.bots import get_bot
            return get_bot(node.bot_id).name
        except Exception:
            return node.bot_id
    if node.channel_id:
        return f"channel {node.channel_id}"
    if pin is not None:
        return pin.display_label or pin.tool_name or str(pin.id)
    return str(node.id)


def _direction_phrase(dx_steps: int, dy_steps: int) -> str:
    parts: list[str] = []
    if dx_steps:
        parts.append(f"{abs(dx_steps)} step{'s' if abs(dx_steps) != 1 else ''} {'right' if dx_steps > 0 else 'left'}")
    if dy_steps:
        parts.append(f"{abs(dy_steps)} step{'s' if abs(dy_steps) != 1 else ''} {'down' if dy_steps > 0 else 'up'}")
    return " and ".join(parts) or "nowhere"


async def _publish_spatial_movement_notice(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID,
    bot_id: str,
    target_label: str,
    dx_steps: int,
    dy_steps: int,
    movement: dict[str, Any],
) -> None:
    channel = await db.get(Channel, channel_id)
    if channel is None or channel.active_session_id is None:
        return
    try:
        from app.agent.bots import get_bot
        bot_name = get_bot(bot_id).name
    except Exception:
        bot_name = bot_id
    content = f"{bot_name} moved {target_label} {_direction_phrase(dx_steps, dy_steps)} on the workspace canvas."
    record = Message(
        session_id=channel.active_session_id,
        role="assistant",
        content=content,
        metadata_={
            "kind": "spatial_movement",
            "spatial_movement": movement,
            "bot_id": bot_id,
        },
        created_at=datetime.now(timezone.utc),
    )
    db.add(record)
    await db.execute(
        update(Session)
        .where(Session.id == channel.active_session_id)
        .values(last_active=datetime.now(timezone.utc))
    )
    await db.commit()
    await db.refresh(record)
    from app.domain.message import Message as DomainMessage
    from app.services.channel_events import publish_message
    from app.services.outbox_publish import enqueue_new_message_for_channel
    domain_msg = DomainMessage.from_orm(record, channel_id=channel_id)
    await enqueue_new_message_for_channel(channel_id, domain_msg)
    publish_message(channel_id, record)


async def tug_spatial_node(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID,
    bot_id: str,
    target_node_id: uuid.UUID,
    dx_steps: int,
    dy_steps: int,
    reason: str | None = None,
) -> WorkspaceSpatialNode:
    policy = await get_channel_bot_spatial_policy(db, channel_id, bot_id)
    if not policy["enabled"] or not policy["allow_moving_spatial_objects"]:
        raise ValidationError("Spatial object movement is not enabled for this bot in this channel.")
    step_count = abs(int(dx_steps)) + abs(int(dy_steps))
    if step_count <= 0:
        raise ValidationError("Tug requires at least one step.")
    if step_count > policy["max_tug_steps_per_turn"]:
        raise ValidationError(f"Tug exceeds max_tug_steps_per_turn={policy['max_tug_steps_per_turn']}.")
    bot_node = await _ensure_bot_node(db, bot_id)
    target = await get_node(db, target_node_id)
    if bot_node is None:
        raise NotFoundError(f"Bot node not found: {bot_id}")
    if target.id == bot_node.id:
        raise ValidationError("Use move_on_canvas to move yourself.")
    radius = float(policy["tug_radius_steps"] * policy["step_world_units"])
    if _distance(bot_node, target) > radius:
        raise ValidationError("Target is outside this bot's tug radius.")
    pin = await db.get(WidgetDashboardPin, target.widget_pin_id) if target.widget_pin_id else None
    from_x, from_y = target.world_x, target.world_y
    step = float(policy["step_world_units"])
    target.world_x = float(target.world_x + int(dx_steps) * step)
    target.world_y = float(target.world_y + int(dy_steps) * step)
    movement = _movement_payload(
        actor_bot_id=bot_id,
        channel_id=channel_id,
        kind="object_tug",
        from_x=from_x,
        from_y=from_y,
        to_x=target.world_x,
        to_y=target.world_y,
        reason=reason,
        ttl_minutes=policy["movement_trace_ttl_minutes"],
        target_node_id=target.id,
    )
    target.last_movement = movement
    _append_position_history(
        target,
        prev_x=from_x,
        prev_y=from_y,
        new_x=target.world_x,
        new_y=target.world_y,
        actor=bot_id,
    )
    await db.commit()
    await db.refresh(target)
    await _publish_spatial_movement_notice(
        db,
        channel_id=channel_id,
        bot_id=bot_id,
        target_label=_node_label(target, pin),
        dx_steps=dx_steps,
        dy_steps=dy_steps,
        movement=movement,
    )
    return target


async def _nodes_with_pins(
    db: AsyncSession,
) -> tuple[list[WorkspaceSpatialNode], dict[uuid.UUID, WidgetDashboardPin]]:
    await _ensure_channel_nodes(db)
    await _ensure_bot_nodes(db)
    await _ensure_landmark_nodes(db)
    # Landmarks are visual chrome (zero-sized world rects), not collision
    # targets — exclude them from neighborhood/movement reasoning.
    nodes = list((await db.execute(
        select(WorkspaceSpatialNode)
        .where(WorkspaceSpatialNode.landmark_kind.is_(None))
        .order_by(WorkspaceSpatialNode.pinned_at.asc())
    )).scalars().all())
    pin_ids = [n.widget_pin_id for n in nodes if n.widget_pin_id is not None]
    pin_map: dict[uuid.UUID, WidgetDashboardPin] = {}
    if pin_ids:
        pins = (await db.execute(
            select(WidgetDashboardPin).where(WidgetDashboardPin.id.in_(pin_ids))
        )).scalars().all()
        pin_map = {p.id: p for p in pins}
    return nodes, pin_map


def _node_kind(node: WorkspaceSpatialNode) -> str:
    if node.bot_id:
        return "bot"
    if node.channel_id:
        return "channel"
    return "widget"


async def build_canvas_neighborhood(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID,
    bot_id: str,
) -> dict[str, Any]:
    policy = await get_channel_bot_spatial_policy(db, channel_id, bot_id)
    bot_node = await _ensure_bot_node(db, bot_id)
    if bot_node is None:
        raise NotFoundError(f"Bot node not found: {bot_id}")
    nodes, pin_map = await _nodes_with_pins(db)
    radius = float(policy["awareness_radius_steps"] * policy["step_world_units"])
    min_clearance = float(policy["minimum_clearance_steps"] * policy["step_world_units"])
    floor = int(policy["nearest_neighbor_floor"])
    rows: list[dict[str, Any]] = []
    for node in nodes:
        if node.id == bot_node.id:
            continue
        pin = pin_map.get(node.widget_pin_id) if node.widget_pin_id else None
        dist = _distance(bot_node, node)
        edge = _edge_clearance(bot_node, node)
        rows.append({
            "id": str(node.id),
            "kind": _node_kind(node),
            "label": _node_label(node, pin),
            "distance": round(dist, 1),
            "edge_distance": round(edge, 1),
            "overlapping": edge <= 0,
            "too_close": min_clearance > 0 and edge < min_clearance,
            "within_radius": dist <= radius,
            "tuggable": (
                bool(policy["allow_moving_spatial_objects"])
                and dist <= float(policy["tug_radius_steps"] * policy["step_world_units"])
            ),
            "channel_id": str(node.channel_id) if node.channel_id else None,
            "bot_id": node.bot_id,
            "widget_pin_id": str(node.widget_pin_id) if node.widget_pin_id else None,
            "manageable": (
                bool(policy["allow_spatial_widget_management"])
                and pin is not None
                and pin.source_bot_id == bot_id
            ),
        })
    rows.sort(key=lambda r: float(r["distance"]))
    nearby = [r for r in rows if r["within_radius"]]
    seen = {r["id"] for r in nearby}
    for r in rows[:floor]:
        if r["id"] not in seen:
            nearby.append({**r, "fallback_nearest": True})
            seen.add(r["id"])
    return {
        "policy": policy,
        "bot": serialize_node(bot_node),
        "neighbors": nearby,
        "hot_alerts": await _attention_hot_alerts(db, channel_id=channel_id, bot_id=bot_id),
    }


async def _attention_hot_alerts(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID,
    bot_id: str,
) -> list[dict[str, Any]]:
    try:
        from app.services.workspace_attention import list_bot_neighborhood_attention
        return await list_bot_neighborhood_attention(db, channel_id=channel_id, bot_id=bot_id)
    except Exception:
        logger.debug("Failed to load spatial attention alerts", exc_info=True)
        return []


async def build_canvas_neighborhood_block(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID,
    bot_id: str,
) -> str | None:
    neighborhood = await build_canvas_neighborhood(db, channel_id=channel_id, bot_id=bot_id)
    policy = neighborhood["policy"]
    if not policy["enabled"]:
        return None
    bot = neighborhood["bot"]
    lines = [
        "[spatial canvas]",
        f"your canvas node: {bot['id']} at ({bot['world_x']:.0f}, {bot['world_y']:.0f})",
        (
            f"movement: step={policy['step_world_units']} world units, "
            f"move_budget={policy['max_move_steps_per_turn']} step(s), "
            f"minimum_clearance={policy['minimum_clearance_steps']} step(s), "
            f"awareness_radius={policy['awareness_radius_steps']} step(s), "
            f"tug_radius={policy['tug_radius_steps']} step(s)"
        ),
    ]
    if policy["allow_movement"]:
        lines.append("You may use move_on_canvas to move your bot node within the movement budget.")
    if policy["allow_moving_spatial_objects"]:
        lines.append("You may use tug_spatial_object on tuggable nearby objects only.")
    if policy["allow_nearby_inspect"]:
        lines.append("You may use inspect_nearby_spatial_object for nearby object details.")
    if policy["allow_map_view"]:
        lines.append("You may use view_spatial_canvas for read-only whole-map viewport summaries and focus targets.")
    if policy["allow_spatial_widget_management"]:
        lines.append("You may use pin_spatial_widget plus move/resize/remove spatial-widget tools for widgets you own.")
    if policy.get("allow_attention_beacons"):
        lines.append("You may use place_attention_beacon for human-visible warnings and resolve_attention_beacon for your own resolved beacons.")
    lines.append(
        f"If memory/file tools are available, keep current spatial memory in bot workspace "
        f"/workspace/bots/{bot_id}/memory/reference/spatial.md "
        "(landmarks, layout intent, active widget placement notes, and next spatial follow-ups). "
        f"Archive stale or historical spatial notes into /workspace/bots/{bot_id}/memory/logs/ "
        "alongside other memory."
    )
    lines.append("")
    lines.append("nearby objects:")
    for row in neighborhood["neighbors"][:12]:
        flags: list[str] = []
        if row.get("fallback_nearest"):
            flags.append("nearest")
        if row.get("tuggable"):
            flags.append("tuggable")
        if row.get("manageable"):
            flags.append("manageable")
        if row.get("overlapping"):
            flags.append("overlapping")
        elif row.get("too_close"):
            flags.append("too-close")
        flag_text = f" [{' '.join(flags)}]" if flags else ""
        lines.append(
            f"  - {row['label']} ({row['kind']}) id={row['id']} "
            f"center_dist={row['distance']} edge_gap={row['edge_distance']}{flag_text}"
        )
    if not neighborhood["neighbors"]:
        lines.append("  - none")
    alerts = neighborhood.get("hot_alerts") or []
    lines.append("")
    lines.append("attention beacons:")
    if alerts:
        for alert in alerts[:8]:
            own = " own" if alert.get("own") else ""
            response = " requires-response" if alert.get("requires_response") else ""
            lines.append(
                f"  - {alert['title']} id={alert['id']} severity={alert['severity']} "
                f"status={alert['status']} target={alert['target_kind']}:{alert['target_id']}{own}{response}"
            )
    else:
        lines.append("  - none")
    return "\n".join(lines)


async def inspect_nearby_spatial_object(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID,
    bot_id: str,
    target_node_id: uuid.UUID,
) -> dict[str, Any]:
    policy = await get_channel_bot_spatial_policy(db, channel_id, bot_id)
    if not policy["enabled"] or not policy["allow_nearby_inspect"]:
        raise ValidationError("Nearby spatial inspection is not enabled for this bot in this channel.")
    bot_node = await _ensure_bot_node(db, bot_id)
    target = await get_node(db, target_node_id)
    if bot_node is None:
        raise NotFoundError(f"Bot node not found: {bot_id}")
    radius = float(policy["awareness_radius_steps"] * policy["step_world_units"])
    dist = _distance(bot_node, target)
    edge = _edge_clearance(bot_node, target)
    if dist > radius:
        raise ValidationError("Target is outside this bot's awareness radius.")
    payload = serialize_node(target)
    payload["distance"] = round(dist, 1)
    payload["edge_distance"] = round(edge, 1)
    payload["overlapping"] = edge <= 0
    payload["too_close"] = edge < float(policy["minimum_clearance_steps"] * policy["step_world_units"])
    if target.channel_id:
        ch = await db.get(Channel, target.channel_id)
        payload["summary"] = {
            "name": ch.name if ch else str(target.channel_id),
            "bot_id": ch.bot_id if ch else None,
            "active_session_id": str(ch.active_session_id) if ch and ch.active_session_id else None,
        }
    elif target.widget_pin_id:
        pin = await db.get(WidgetDashboardPin, target.widget_pin_id)
        if pin is not None:
            from app.services.dashboard_pins import serialize_pin
            pin_dict = serialize_pin(pin)
            try:
                from app.services.widget_context import enrich_pins_for_context_export
                enriched = await enrich_pins_for_context_export(
                    db,
                    [pin_dict],
                    bot_id=bot_id,
                    channel_id=str(pin.source_channel_id) if pin.source_channel_id else None,
                )
                pin_dict = enriched[0] if enriched else pin_dict
            except Exception:
                logger.debug("Failed to enrich nearby widget pin %s", pin.id, exc_info=True)
            payload["summary"] = {
                "label": pin_dict.get("display_label") or pin_dict.get("tool_name"),
                "tool_name": pin_dict.get("tool_name"),
                "source_channel_id": pin_dict.get("source_channel_id"),
                "context_summary": pin_dict.get("context_summary"),
            }
    elif target.bot_id:
        payload["summary"] = {"bot_id": target.bot_id, "label": _node_label(target)}
    return payload


async def update_node_position(
    db: AsyncSession,
    node_id: uuid.UUID,
    *,
    world_x: float | None = None,
    world_y: float | None = None,
    world_w: float | None = None,
    world_h: float | None = None,
    z_index: int | None = None,
    last_movement: dict | None = None,
) -> WorkspaceSpatialNode:
    node = await get_node(db, node_id)
    prev_x, prev_y = node.world_x, node.world_y
    if world_x is not None:
        wx = float(world_x)
        if not math.isfinite(wx) or abs(wx) > WORLD_COORD_LIMIT:
            raise ValidationError(
                f"world_x out of range: {wx} (limit ±{WORLD_COORD_LIMIT})"
            )
        node.world_x = wx
    if world_y is not None:
        wy = float(world_y)
        if not math.isfinite(wy) or abs(wy) > WORLD_COORD_LIMIT:
            raise ValidationError(
                f"world_y out of range: {wy} (limit ±{WORLD_COORD_LIMIT})"
            )
        node.world_y = wy
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
    if last_movement is not None:
        node.last_movement = last_movement
    if world_x is not None or world_y is not None:
        _append_position_history(
            node,
            prev_x=prev_x,
            prev_y=prev_y,
            new_x=node.world_x,
            new_y=node.world_y,
            actor=None,
        )
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
    pin_display_label: str | None = None,
    world_x: float | None = None,
    world_y: float | None = None,
    world_w: float = _DEFAULT_WIDGET_W,
    world_h: float = _DEFAULT_WIDGET_H,
    override_widget_instance: WidgetInstance | None = None,
) -> tuple[WidgetDashboardPin, WorkspaceSpatialNode]:
    """Atomically create a widget pin on the workspace:spatial dashboard
    AND its matching workspace_spatial_nodes row.

    Both writes commit together. If the spatial node insert fails, the pin
    is dropped (compensating delete). No orphan pins.
    """
    # Native widgets pinned to the canvas always get a fresh WidgetInstance
    # so multiple Notes/Todo/Blockyard tiles can coexist with independent
    # state. The default get-or-create path would singleton them all to the
    # same workspace:spatial scope_ref. (Channel-scoped pins keep the
    # one-per-channel singleton — that's intentional.)
    override_instance = override_widget_instance
    from app.services.native_app_widgets import (
        NATIVE_APP_CONTENT_TYPE,
        create_unique_native_widget_instance,
        extract_native_widget_ref_from_envelope,
    )
    if (
        override_instance is None
        and isinstance(envelope, dict)
        and envelope.get("content_type") == NATIVE_APP_CONTENT_TYPE
    ):
        widget_ref = extract_native_widget_ref_from_envelope(envelope)
        if widget_ref:
            override_instance = await create_unique_native_widget_instance(
                db,
                widget_ref=widget_ref,
                config=widget_config or {},
            )

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
        override_widget_instance=override_instance,
        commit=False,
    )
    if pin_display_label:
        pin.display_label = pin_display_label

    try:
        # Position priority:
        #   1. Caller-supplied world_x/world_y wins (admin tools, drag-drop
        #      from a known anchor, etc.).
        #   2. Satellite ring around the source channel — the typical case.
        #      Auto-seeds the channel's spatial node if it doesn't exist yet
        #      so satellite-positioning works even before the user opens the
        #      canvas.
        #   3. Global phyllotaxis fallback (adhoc widgets with no source
        #      channel — they spiral into open space).
        if (world_x is None or world_y is None) and source_channel_id is not None:
            await _ensure_channel_node(db, source_channel_id)
            sat = await _satellite_position_for_channel(db, source_channel_id)
            if sat is not None:
                if world_x is None:
                    world_x = sat[0]
                if world_y is None:
                    world_y = sat[1]
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


def _source_widget_label(pin: WidgetDashboardPin) -> str:
    envelope = pin.envelope or {}
    label = (
        pin.display_label
        or envelope.get("display_label")
        or pin.tool_name
        or "Widget"
    )
    return str(label).strip() or "Widget"


async def _channel_widget_label(
    db: AsyncSession,
    *,
    source_channel_id: uuid.UUID | None,
    widget_label: str,
) -> str:
    if source_channel_id is None:
        return widget_label
    channel = await db.get(Channel, source_channel_id)
    channel_label = (channel.name if channel is not None else "").strip()
    if not channel_label:
        return widget_label
    lower_widget = widget_label.lower()
    if lower_widget.startswith(channel_label.lower()):
        return widget_label
    return f"{channel_label} {widget_label}"


async def pin_dashboard_pin_to_canvas(
    db: AsyncSession,
    *,
    source_dashboard_pin_id: uuid.UUID,
    world_x: float | None = None,
    world_y: float | None = None,
    world_w: float = _DEFAULT_WIDGET_W,
    world_h: float = _DEFAULT_WIDGET_H,
) -> tuple[WidgetDashboardPin, WorkspaceSpatialNode]:
    """Project an existing dashboard pin onto the workspace canvas.

    For native widgets, the canvas pin reuses the source pin's
    ``WidgetInstance`` so channel dashboard and spatial tile edit the same
    Notes/Todo state. Direct canvas catalog pins still use
    ``pin_widget_to_canvas`` and get fresh instances.
    """
    source_pin = await get_pin(db, source_dashboard_pin_id)
    if source_pin.dashboard_key == WORKSPACE_SPATIAL_DASHBOARD_KEY:
        raise ValidationError("source_dashboard_pin_id already belongs to the workspace canvas")

    existing_rows = (
        await db.execute(
            select(WidgetDashboardPin, WorkspaceSpatialNode)
            .join(WorkspaceSpatialNode, WorkspaceSpatialNode.widget_pin_id == WidgetDashboardPin.id)
            .where(WidgetDashboardPin.dashboard_key == WORKSPACE_SPATIAL_DASHBOARD_KEY)
        )
    ).all()
    for existing_pin, existing_node in existing_rows:
        origin = existing_pin.widget_origin or {}
        if origin.get("source_dashboard_pin_id") == str(source_pin.id):
            return existing_pin, existing_node

    override_instance = None
    if source_pin.widget_instance_id is not None:
        instance = await db.get(WidgetInstance, source_pin.widget_instance_id)
        if instance is not None and instance.widget_kind == "native_app":
            override_instance = instance

    widget_origin = dict(source_pin.widget_origin or {})
    prior_instantiation = widget_origin.get("instantiation_kind")
    if isinstance(prior_instantiation, str) and prior_instantiation:
        widget_origin["projected_from_instantiation_kind"] = prior_instantiation
    widget_origin["source_dashboard_pin_id"] = str(source_pin.id)
    widget_origin["instantiation_kind"] = "channel_dashboard_projection"

    base_label = _source_widget_label(source_pin)
    canvas_label = await _channel_widget_label(
        db,
        source_channel_id=source_pin.source_channel_id,
        widget_label=base_label,
    )

    return await pin_widget_to_canvas(
        db,
        source_kind=source_pin.source_kind,
        tool_name=source_pin.tool_name,
        envelope=source_pin.envelope or {},
        source_channel_id=source_pin.source_channel_id,
        source_bot_id=source_pin.source_bot_id,
        tool_args=source_pin.tool_args or {},
        widget_config=source_pin.widget_config or {},
        widget_origin=widget_origin,
        display_label=base_label,
        pin_display_label=canvas_label,
        world_x=world_x,
        world_y=world_y,
        world_w=world_w,
        world_h=world_h,
        override_widget_instance=override_instance,
    )
