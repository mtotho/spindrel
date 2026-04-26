"""Read-only Spatial Canvas viewport summaries for bot tools and heartbeats."""
from __future__ import annotations

import base64
import json
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, TraceEvent, WidgetDashboardPin, WorkspaceSpatialNode
from app.domain.errors import NotFoundError, ValidationError
from app.services.workspace_spatial import get_channel_bot_spatial_policy, list_nodes


MapPreset = Literal["whole_map", "cluster", "dot", "preview", "snapshot"]
ActivityWindow = Literal["24h", "7d", "30d"]

CLUSTER_ENTER_SCALE = 0.22
DOT_THRESHOLD = 0.4
CHANNEL_SNAPSHOT_THRESHOLD = 1.0
WIDGET_TITLE_THRESHOLD = 0.4
WIDGET_CARD_THRESHOLD = 0.6
CLUSTER_SCREEN_RADIUS = 92.0

WINDOW_HOURS: dict[str, int] = {"24h": 24, "7d": 24 * 7, "30d": 24 * 30}
PRESET_SCALES: dict[str, float] = {
    "cluster": 0.18,
    "dot": 0.32,
    "preview": 0.65,
    "snapshot": 1.1,
}


@dataclass(frozen=True)
class Camera:
    x: float
    y: float
    scale: float


@dataclass(frozen=True)
class ChannelCandidate:
    node: WorkspaceSpatialNode
    channel: Channel
    screen_x: float
    screen_y: float
    tokens: int
    calls: int
    recency: float


def _channel_hue(channel_id: str) -> int:
    h = 0
    for ch in channel_id:
        h = ((h * 31) + ord(ch)) & 0xFFFFFFFF
    return h % 360


def _focus_token(bounds: dict[str, float], scale: float) -> str:
    raw = json.dumps({"b": bounds, "s": scale}, sort_keys=True, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_focus_token(token: str) -> tuple[dict[str, float], float]:
    try:
        padded = token + ("=" * ((4 - len(token) % 4) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        b = payload["b"]
        bounds = {
            "x": float(b["x"]),
            "y": float(b["y"]),
            "w": max(1.0, float(b["w"])),
            "h": max(1.0, float(b["h"])),
        }
        scale = float(payload.get("s") or 0.32)
        return bounds, scale
    except Exception as exc:
        raise ValidationError("Invalid focus_token.") from exc


def _node_bounds(node: WorkspaceSpatialNode) -> dict[str, float]:
    return {
        "x": float(node.world_x),
        "y": float(node.world_y),
        "w": float(node.world_w),
        "h": float(node.world_h),
    }


def _bbox(bounds: list[dict[str, float]]) -> dict[str, float]:
    if not bounds:
        return {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    min_x = min(b["x"] for b in bounds)
    min_y = min(b["y"] for b in bounds)
    max_x = max(b["x"] + b["w"] for b in bounds)
    max_y = max(b["y"] + b["h"] for b in bounds)
    return {"x": min_x, "y": min_y, "w": max_x - min_x, "h": max_y - min_y}


def _camera_for_bounds(bounds: dict[str, float], viewport_w: int, viewport_h: int, *, max_scale: float = 1.2) -> Camera:
    margin = 0.16
    scale = min(
        max_scale,
        viewport_w / max(1.0, bounds["w"] * (1 + margin * 2)),
        viewport_h / max(1.0, bounds["h"] * (1 + margin * 2)),
    )
    scale = max(0.05, scale)
    cx = bounds["x"] + bounds["w"] / 2
    cy = bounds["y"] + bounds["h"] / 2
    return Camera(x=viewport_w / 2 - cx * scale, y=viewport_h / 2 - cy * scale, scale=scale)


def _camera_for_center(center_x: float, center_y: float, scale: float, viewport_w: int, viewport_h: int) -> Camera:
    scale = max(0.05, min(3.0, scale))
    return Camera(x=viewport_w / 2 - center_x * scale, y=viewport_h / 2 - center_y * scale, scale=scale)


def _screen(camera: Camera, world_x: float, world_y: float, viewport_w: int, viewport_h: int) -> dict[str, float]:
    sx = camera.x + world_x * camera.scale
    sy = camera.y + world_y * camera.scale
    return {
        "x": round(sx, 1),
        "y": round(sy, 1),
        "rx": round(sx / viewport_w, 4) if viewport_w else 0.0,
        "ry": round(sy / viewport_h, 4) if viewport_h else 0.0,
    }


def _intersects_view(node: WorkspaceSpatialNode, camera: Camera, viewport_w: int, viewport_h: int) -> bool:
    left = camera.x + node.world_x * camera.scale
    top = camera.y + node.world_y * camera.scale
    right = camera.x + (node.world_x + node.world_w) * camera.scale
    bottom = camera.y + (node.world_y + node.world_h) * camera.scale
    return right >= 0 and left <= viewport_w and bottom >= 0 and top <= viewport_h


def _channel_label(channel: Channel) -> str:
    return channel.display_name or channel.name


def _pin_label(pin: WidgetDashboardPin | None) -> str:
    if pin is None:
        return "widget"
    return pin.display_label or pin.tool_name or str(pin.id)


def _bot_label(bot_id: str | None) -> str:
    if not bot_id:
        return "bot"
    try:
        from app.agent.bots import get_bot
        return get_bot(bot_id).name
    except Exception:
        return bot_id


def _channel_tier(scale: float) -> str:
    if scale < CLUSTER_ENTER_SCALE:
        return "cluster"
    if scale < DOT_THRESHOLD:
        return "dot"
    if scale < CHANNEL_SNAPSHOT_THRESHOLD:
        return "preview"
    return "snapshot"


def _widget_tier(scale: float) -> str:
    if scale < WIDGET_TITLE_THRESHOLD:
        return "chip"
    if scale < WIDGET_CARD_THRESHOLD:
        return "title"
    return "card"


async def _channel_activity(
    db: AsyncSession,
    *,
    window: ActivityWindow,
) -> dict[str, dict[str, int]]:
    before = datetime.now(timezone.utc)
    after = before - timedelta(hours=WINDOW_HOURS.get(window, 24))
    rows = (await db.execute(
        select(TraceEvent).where(
            TraceEvent.event_type == "token_usage",
            TraceEvent.created_at >= after,
            TraceEvent.created_at <= before,
        )
    )).scalars().all()
    out: dict[str, dict[str, int]] = {}
    for ev in rows:
        data = ev.data or {}
        channel_id = data.get("channel_id")
        if not channel_id:
            continue
        bucket = out.setdefault(str(channel_id), {"tokens": 0, "calls": 0})
        bucket["tokens"] += int(data.get("total_tokens") or 0)
        bucket["calls"] += 1
    return out


def _recency(channel: Channel) -> float:
    raw = getattr(channel, "last_message_at", None) or channel.updated_at or channel.created_at
    if not raw:
        return 0.0
    try:
        return raw.timestamp()
    except AttributeError:
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0


def _candidate_sort_key(c: ChannelCandidate) -> tuple[int, float, str]:
    return (-c.tokens, -c.recency, str(c.channel.id))


def _build_channel_clusters(candidates: list[ChannelCandidate]) -> list[list[ChannelCandidate]]:
    ordered = sorted(candidates, key=_candidate_sort_key)
    claimed: set[uuid.UUID] = set()
    clusters: list[list[ChannelCandidate]] = []
    for seed in ordered:
        if seed.node.id in claimed:
            continue
        members = [
            c
            for c in ordered
            if c.node.id not in claimed
            and math.hypot(c.screen_x - seed.screen_x, c.screen_y - seed.screen_y) <= CLUSTER_SCREEN_RADIUS
        ]
        members.sort(key=_candidate_sort_key)
        if len(members) < 2:
            continue
        for member in members:
            claimed.add(member.node.id)
        clusters.append(members)
    return clusters


async def build_spatial_map_view(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID,
    bot_id: str,
    preset: MapPreset = "whole_map",
    center_world_x: float | None = None,
    center_world_y: float | None = None,
    scale: float | None = None,
    viewport_w: int = 1400,
    viewport_h: int = 900,
    focus_token: str | None = None,
    activity_window: ActivityWindow = "24h",
) -> dict[str, Any]:
    policy = await get_channel_bot_spatial_policy(db, channel_id, bot_id)
    if not policy["enabled"] or not policy["allow_map_view"]:
        raise ValidationError("Spatial map view is not enabled for this bot in this channel.")

    viewport_w = max(320, min(int(viewport_w or 1400), 4000))
    viewport_h = max(240, min(int(viewport_h or 900), 2400))
    node_pairs = await list_nodes(db)
    nodes = [node for node, _pin in node_pairs]
    bounds_all = _bbox([_node_bounds(node) for node in nodes])

    if focus_token:
        focus_bounds, focus_scale = _decode_focus_token(focus_token)
        camera = _camera_for_bounds(focus_bounds, viewport_w, viewport_h, max_scale=focus_scale)
    elif preset == "whole_map":
        camera = _camera_for_bounds(bounds_all, viewport_w, viewport_h, max_scale=CLUSTER_ENTER_SCALE - 0.02)
    else:
        target_scale = scale if scale is not None else PRESET_SCALES.get(preset, 0.32)
        if center_world_x is None or center_world_y is None:
            bot_node = next((node for node in nodes if node.bot_id == bot_id), None)
            if bot_node is not None:
                center_world_x = bot_node.world_x + bot_node.world_w / 2
                center_world_y = bot_node.world_y + bot_node.world_h / 2
            else:
                center_world_x = bounds_all["x"] + bounds_all["w"] / 2
                center_world_y = bounds_all["y"] + bounds_all["h"] / 2
        camera = _camera_for_center(float(center_world_x), float(center_world_y), float(target_scale), viewport_w, viewport_h)

    channel_ids = [node.channel_id for node in nodes if node.channel_id]
    channels: dict[uuid.UUID, Channel] = {}
    if channel_ids:
        rows = (await db.execute(select(Channel).where(Channel.id.in_(channel_ids)))).scalars().all()
        channels = {row.id: row for row in rows}
    activity = await _channel_activity(db, window=activity_window)

    items: list[dict[str, Any]] = []
    focus_targets: list[dict[str, Any]] = []
    suppressed_channel_node_ids: set[uuid.UUID] = set()
    suppressed_channel_ids: set[uuid.UUID] = set()
    channel_candidates: list[ChannelCandidate] = []

    for node in nodes:
        if not node.channel_id:
            continue
        channel = channels.get(node.channel_id)
        if channel is None:
            continue
        cx = node.world_x + node.world_w / 2
        cy = node.world_y + node.world_h / 2
        a = activity.get(str(channel.id), {"tokens": 0, "calls": 0})
        channel_candidates.append(ChannelCandidate(
            node=node,
            channel=channel,
            screen_x=camera.x + cx * camera.scale,
            screen_y=camera.y + cy * camera.scale,
            tokens=int(a["tokens"]),
            calls=int(a["calls"]),
            recency=_recency(channel),
        ))

    if camera.scale < CLUSTER_ENTER_SCALE:
        for members in _build_channel_clusters(channel_candidates):
            winner = members[0]
            bounds = _bbox([_node_bounds(m.node) for m in members])
            token = _focus_token(bounds, DOT_THRESHOLD + 0.04)
            for member in members:
                suppressed_channel_node_ids.add(member.node.id)
                suppressed_channel_ids.add(member.channel.id)
            hidden_count = len(members) - 1
            cx = winner.node.world_x + winner.node.world_w / 2
            cy = winner.node.world_y + winner.node.world_h / 2
            item = {
                "kind": "channel_cluster",
                "tier": "cluster",
                "label": _channel_label(winner.channel),
                "hidden_count": hidden_count,
                "satellite_hues": [_channel_hue(str(m.channel.id)) for m in members[1:5]],
                "activity": {
                    "tokens": sum(m.tokens for m in members),
                    "calls": sum(m.calls for m in members),
                },
                "world_bounds": bounds,
                "screen": _screen(camera, cx, cy, viewport_w, viewport_h),
                "focus_token": token,
            }
            items.append(item)
            focus_targets.append({
                "kind": "channel_cluster",
                "label": item["label"],
                "focus_token": token,
                "next_camera": {"preset": "dot", "focus_token": token},
                "screen": item["screen"],
            })

    pin_by_node_id = {node.id: pin for node, pin in node_pairs}
    for node in nodes:
        if not _intersects_view(node, camera, viewport_w, viewport_h):
            continue
        cx = node.world_x + node.world_w / 2
        cy = node.world_y + node.world_h / 2
        bounds = _node_bounds(node)
        if node.channel_id:
            if node.id in suppressed_channel_node_ids:
                continue
            channel = channels.get(node.channel_id)
            if channel is None:
                continue
            token = _focus_token(bounds, 0.75)
            a = activity.get(str(channel.id), {"tokens": 0, "calls": 0})
            item = {
                "kind": "channel",
                "tier": _channel_tier(camera.scale),
                "label": _channel_label(channel),
                "hue": _channel_hue(str(channel.id)),
                "activity": {"tokens": int(a["tokens"]), "calls": int(a["calls"])},
                "world_bounds": bounds,
                "screen": _screen(camera, cx, cy, viewport_w, viewport_h),
                "focus_token": token,
            }
        elif node.widget_pin_id:
            pin = pin_by_node_id.get(node.id)
            token = _focus_token(bounds, 0.72)
            item = {
                "kind": "widget",
                "tier": _widget_tier(camera.scale),
                "label": _pin_label(pin),
                "world_bounds": bounds,
                "screen": _screen(camera, cx, cy, viewport_w, viewport_h),
                "focus_token": token,
            }
        elif node.bot_id:
            token = _focus_token(bounds, 0.62)
            item = {
                "kind": "bot",
                "tier": "compact" if camera.scale < 0.55 else "avatar",
                "label": _bot_label(node.bot_id),
                "world_bounds": bounds,
                "screen": _screen(camera, cx, cy, viewport_w, viewport_h),
                "focus_token": token,
            }
        else:
            continue
        items.append(item)
        focus_targets.append({
            "kind": item["kind"],
            "label": item["label"],
            "focus_token": item["focus_token"],
            "next_camera": {"preset": "preview", "focus_token": item["focus_token"]},
            "screen": item["screen"],
        })

    connections: list[dict[str, Any]] = []
    channel_label_by_id = {str(ch.id): _channel_label(ch) for ch in channels.values()}
    for node, pin in node_pairs:
        if pin is None or not pin.source_channel_id:
            continue
        if pin.source_channel_id in suppressed_channel_ids:
            continue
        source_label = channel_label_by_id.get(str(pin.source_channel_id))
        if not source_label:
            continue
        connections.append({
            "widget": _pin_label(pin),
            "source_channel": source_label,
        })

    visible_tier = "cluster" if camera.scale < CLUSTER_ENTER_SCALE else "dot" if camera.scale < DOT_THRESHOLD else "preview" if camera.scale < 1.0 else "snapshot"
    return {
        "policy": {"allow_map_view": True},
        "activity_window": activity_window,
        "viewport": {"w": viewport_w, "h": viewport_h},
        "camera": {"x": round(camera.x, 2), "y": round(camera.y, 2), "scale": round(camera.scale, 4)},
        "world_bounds": bounds_all,
        "visible_tier": visible_tier,
        "items": items,
        "connections": connections[:40],
        "focus_targets": focus_targets[:60],
        "summary": {
            "item_count": len(items),
            "cluster_count": sum(1 for item in items if item["kind"] == "channel_cluster"),
            "hidden_channel_count": len(suppressed_channel_ids),
        },
    }


async def build_spatial_map_overview_block(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID,
    bot_id: str,
) -> str | None:
    try:
        payload = await build_spatial_map_view(
            db,
            channel_id=channel_id,
            bot_id=bot_id,
            preset="whole_map",
            activity_window="24h",
        )
    except (NotFoundError, ValidationError):
        return None
    lines = [
        "[spatial canvas map overview]",
        (
            f"far zoom tier={payload['visible_tier']} "
            f"items={payload['summary']['item_count']} "
            f"clusters={payload['summary']['cluster_count']} "
            f"hidden_channels={payload['summary']['hidden_channel_count']}"
        ),
    ]
    clusters = [item for item in payload["items"] if item["kind"] == "channel_cluster"]
    if clusters:
        lines.append("major channel clusters:")
        for item in sorted(clusters, key=lambda i: i.get("activity", {}).get("tokens", 0), reverse=True)[:8]:
            activity = item.get("activity", {})
            lines.append(
                f"  - {item['label']} +{item['hidden_count']} "
                f"at screen({item['screen']['rx']:.2f},{item['screen']['ry']:.2f}) "
                f"tokens={activity.get('tokens', 0)} focus={item['focus_token']}"
            )
    targets = payload["focus_targets"][:8]
    if targets:
        lines.append("focus targets use view_spatial_canvas(focus_token=...):")
        for target in targets:
            lines.append(
                f"  - {target['label']} ({target['kind']}) focus={target['focus_token']}"
            )
    return "\n".join(lines)
