"""Mission Control aggregation.

Mission Control is the workspace operations read model over missions, assigned
attention, and spatial placement. It does not own lifecycle state; mission CRUD
stays in ``workspace_missions`` and attention intake stays in Command Center's
legacy API for compatibility.
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import get_bot, list_bots
from app.db.models import Channel, WorkspaceSpatialNode
from app.services.channels import apply_channel_visibility
from app.services.workspace_attention import list_attention_items, serialize_attention_item
from app.services.workspace_missions import list_missions
from app.services.workspace_spatial import (
    get_channel_bot_spatial_policy_sync,
    list_nodes,
    normalize_spatial_policy,
    serialize_node,
)


SEVERITY_RANK = {
    "critical": 4,
    "error": 3,
    "warning": 2,
    "info": 1,
}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _bot_name(bot_id: str) -> str:
    try:
        bot = get_bot(bot_id)
        return getattr(bot, "name", None) or getattr(bot, "display_name", None) or bot_id
    except Exception:
        return bot_id


def _bot_runtime(bot_id: str) -> str | None:
    try:
        return getattr(get_bot(bot_id), "harness_runtime", None)
    except Exception:
        return None


def _node_center(node: WorkspaceSpatialNode) -> tuple[float, float]:
    return (node.world_x + node.world_w / 2, node.world_y + node.world_h / 2)


def _center_distance(a: WorkspaceSpatialNode, b: WorkspaceSpatialNode) -> float:
    ax, ay = _node_center(a)
    bx, by = _node_center(b)
    return math.hypot(ax - bx, ay - by)


def _edge_distance(a: WorkspaceSpatialNode, b: WorkspaceSpatialNode) -> float:
    dx = max(
        b.world_x - (a.world_x + a.world_w),
        a.world_x - (b.world_x + b.world_w),
        0.0,
    )
    dy = max(
        b.world_y - (a.world_y + a.world_h),
        a.world_y - (b.world_y + b.world_h),
        0.0,
    )
    return math.hypot(dx, dy)


def _node_kind(node: WorkspaceSpatialNode) -> str:
    if node.bot_id:
        return "bot"
    if node.channel_id:
        return "channel"
    if node.widget_pin_id:
        return "widget"
    if node.landmark_kind:
        return "landmark"
    return "object"


def _node_label(
    node: WorkspaceSpatialNode,
    *,
    channel_by_id: dict[uuid.UUID, Channel],
    pin_label: str | None = None,
) -> str:
    if node.bot_id:
        return _bot_name(node.bot_id)
    if node.channel_id:
        channel = channel_by_id.get(node.channel_id)
        return f"#{channel.name}" if channel else f"channel {node.channel_id}"
    if pin_label:
        return pin_label
    if node.landmark_kind:
        return node.landmark_kind.replace("_", " ")
    return str(node.id)


def _policy_summary(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(policy.get("enabled")),
        "allow_movement": bool(policy.get("allow_movement")),
        "allow_nearby_inspect": bool(policy.get("allow_nearby_inspect")),
        "allow_moving_spatial_objects": bool(policy.get("allow_moving_spatial_objects")),
        "step_world_units": int(policy.get("step_world_units") or 0),
        "awareness_radius_steps": int(policy.get("awareness_radius_steps") or 0),
        "awareness_radius_world": int(policy.get("awareness_radius_steps") or 0)
        * int(policy.get("step_world_units") or 0),
        "tug_radius_steps": int(policy.get("tug_radius_steps") or 0),
        "tug_radius_world": int(policy.get("tug_radius_steps") or 0)
        * int(policy.get("step_world_units") or 0),
        "minimum_clearance_steps": int(policy.get("minimum_clearance_steps") or 0),
    }


def _nearest_objects(
    bot_node: WorkspaceSpatialNode | None,
    nodes: list[WorkspaceSpatialNode],
    *,
    channel_by_id: dict[uuid.UUID, Channel],
    pin_labels_by_id: dict[uuid.UUID, str],
    limit: int = 3,
) -> list[dict[str, Any]]:
    if bot_node is None:
        return []
    rows: list[dict[str, Any]] = []
    for node in nodes:
        if node.id == bot_node.id or node.landmark_kind:
            continue
        rows.append({
            "node_id": str(node.id),
            "kind": _node_kind(node),
            "label": _node_label(
                node,
                channel_by_id=channel_by_id,
                pin_label=pin_labels_by_id.get(node.widget_pin_id) if node.widget_pin_id else None,
            ),
            "channel_id": str(node.channel_id) if node.channel_id else None,
            "widget_pin_id": str(node.widget_pin_id) if node.widget_pin_id else None,
            "bot_id": node.bot_id,
            "center_distance": round(_center_distance(bot_node, node), 1),
            "edge_distance": round(_edge_distance(bot_node, node), 1),
        })
    rows.sort(key=lambda row: float(row["center_distance"]))
    return rows[:limit]


def _spatial_advisory(
    *,
    bot_id: str,
    assignment: dict[str, Any],
    mission: dict[str, Any],
    bot_node: WorkspaceSpatialNode | None,
    target_node: WorkspaceSpatialNode | None,
    target_channel: Channel | None,
    policy: dict[str, Any],
) -> dict[str, Any]:
    target_channel_id = assignment.get("target_channel_id") or mission.get("channel_id")
    summary = _policy_summary(policy)
    status = "unknown"
    reason = "Workspace mission has no channel target."
    center_distance = None
    edge_distance = None
    if target_channel_id and target_channel is None:
        status = "unknown"
        reason = "Target channel is not visible to this request."
    elif target_channel_id and (bot_node is None or target_node is None):
        status = "blocked"
        reason = "Spatial node is not available yet."
    elif target_channel_id and not summary["enabled"]:
        status = "blocked"
        reason = "Spatial policy is disabled for this bot in the target channel."
    elif target_channel_id and not summary["allow_nearby_inspect"]:
        status = "blocked"
        reason = "Spatial policy does not allow nearby inspection for this bot."
    elif target_channel_id and bot_node is not None and target_node is not None:
        center_distance = round(_center_distance(bot_node, target_node), 1)
        edge_distance = round(_edge_distance(bot_node, target_node), 1)
        if center_distance <= float(summary["awareness_radius_world"]):
            status = "ready"
            reason = "Target is inside awareness radius."
        elif summary["allow_movement"]:
            status = "far"
            reason = "Target is outside awareness radius; movement is allowed."
        else:
            status = "far"
            reason = "Target is outside awareness radius and movement is disabled."
    return {
        "bot_id": bot_id,
        "bot_node_id": str(bot_node.id) if bot_node else None,
        "target_node_id": str(target_node.id) if target_node else None,
        "target_channel_id": str(target_channel.id) if target_channel else (str(target_channel_id) if target_channel_id else None),
        "target_channel_name": target_channel.name if target_channel else None,
        "center_distance": center_distance,
        "edge_distance": edge_distance,
        "policy": summary,
        "status": status,
        "reason": reason,
    }


def _signal_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    severity = str(item.get("severity") or "info")
    updated = str(item.get("assigned_at") or item.get("last_seen_at") or "")
    return (-SEVERITY_RANK.get(severity, 0), updated)


def _compact_attention_signal(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "severity": item.get("severity"),
        "status": item.get("status"),
        "assignment_status": item.get("assignment_status"),
        "channel_id": item.get("channel_id"),
        "channel_name": item.get("channel_name"),
        "latest_correlation_id": item.get("latest_correlation_id"),
        "last_seen_at": item.get("last_seen_at"),
    }


async def _visible_channels(db: AsyncSession, auth: Any) -> list[Channel]:
    stmt = apply_channel_visibility(select(Channel), auth)
    return list((await db.execute(stmt)).scalars().all())


async def build_mission_control(
    db: AsyncSession,
    *,
    auth: Any,
    include_completed: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    channels = await _visible_channels(db, auth)
    channel_by_id = {channel.id: channel for channel in channels}
    missions = await list_missions(db, auth=auth, include_completed=include_completed, limit=limit)

    node_pairs = await list_nodes(db)
    nodes = [node for node, _pin in node_pairs]
    bot_nodes = {node.bot_id: node for node in nodes if node.bot_id}
    channel_nodes = {node.channel_id: node for node in nodes if node.channel_id}
    pin_labels_by_id = {
        pin.id: pin.display_label or pin.tool_name or str(pin.id)
        for _node, pin in node_pairs
        if pin is not None
    }

    attention_rows = await list_attention_items(db, auth=auth, include_resolved=False)
    attention = [await serialize_attention_item(db, row) for row in attention_rows]
    active_attention = [
        item for item in attention
        if item.get("status") not in {"acknowledged", "resolved"}
    ]
    assigned_attention = [
        item
        for item in active_attention
        if item.get("assigned_bot_id") and item.get("assignment_status") in {"assigned", "running"}
    ]
    assigned_attention.sort(key=_signal_sort_key)

    known_bot_ids = {bot.id for bot in list_bots()}
    lane_ids: set[str] = set()
    for mission in missions:
        for assignment in mission.get("assignments", []):
            if assignment.get("status") == "active" and assignment.get("bot_id") in known_bot_ids:
                lane_ids.add(str(assignment["bot_id"]))
    for item in assigned_attention:
        if item.get("assigned_bot_id") in known_bot_ids:
            lane_ids.add(str(item["assigned_bot_id"]))

    lanes: list[dict[str, Any]] = []
    spatial_warning_count = 0
    mission_rows_by_id: dict[str, dict[str, Any]] = {}
    for bot_id in sorted(lane_ids, key=lambda value: _bot_name(value).lower()):
        bot_node = bot_nodes.get(bot_id)
        lane_missions: list[dict[str, Any]] = []
        for mission in missions:
            rows_for_mission = []
            for assignment in mission.get("assignments", []):
                if assignment.get("bot_id") != bot_id or assignment.get("status") != "active":
                    continue
                target_raw = assignment.get("target_channel_id") or mission.get("channel_id")
                target_channel_id = uuid.UUID(str(target_raw)) if target_raw else None
                target_channel = channel_by_id.get(target_channel_id) if target_channel_id else None
                target_node = channel_nodes.get(target_channel_id) if target_channel_id else None
                policy = (
                    get_channel_bot_spatial_policy_sync(target_channel, bot_id)
                    if target_channel_id and target_channel is not None
                    else normalize_spatial_policy(None)
                )
                advisory = _spatial_advisory(
                    bot_id=bot_id,
                    assignment=assignment,
                    mission=mission,
                    bot_node=bot_node,
                    target_node=target_node,
                    target_channel=target_channel,
                    policy=policy,
                )
                if advisory["status"] in {"far", "blocked"}:
                    spatial_warning_count += 1
                latest_update = mission.get("updates", [None])[0] if mission.get("updates") else None
                row = {
                    "mission": mission,
                    "assignment": assignment,
                    "latest_update": latest_update,
                    "spatial_advisory": advisory,
                }
                rows_for_mission.append(row)
                mission_rows_by_id[mission["id"]] = row
            lane_missions.extend(rows_for_mission)
        lane_missions.sort(key=lambda row: str((row["mission"] or {}).get("next_run_at") or "9999"))
        signals = [
            _compact_attention_signal(item)
            for item in assigned_attention
            if item.get("assigned_bot_id") == bot_id
        ][:6]
        warnings = sum(
            1 for row in lane_missions
            if row["spatial_advisory"]["status"] in {"far", "blocked"}
        ) + sum(1 for signal in signals if signal.get("severity") in {"critical", "error", "warning"})
        lanes.append({
            "bot_id": bot_id,
            "bot_name": _bot_name(bot_id),
            "harness_runtime": _bot_runtime(bot_id),
            "bot_node": serialize_node(bot_node) if bot_node else None,
            "nearest_objects": _nearest_objects(
                bot_node,
                nodes,
                channel_by_id=channel_by_id,
                pin_labels_by_id=pin_labels_by_id,
            ),
            "missions": lane_missions,
            "attention_signals": signals,
            "warning_count": warnings,
        })

    recent_updates = [
        {"mission_id": mission["id"], "mission_title": mission["title"], "update": update}
        for mission in missions
        for update in mission.get("updates", [])[:3]
    ]
    recent_updates.sort(key=lambda row: str((row["update"] or {}).get("created_at") or ""), reverse=True)
    from app.services.workspace_mission_ai import latest_mission_control_brief, list_mission_drafts

    return {
        "generated_at": _iso(datetime.now(timezone.utc)),
        "summary": {
            "active_missions": sum(1 for mission in missions if mission.get("status") == "active"),
            "paused_missions": sum(1 for mission in missions if mission.get("status") == "paused"),
            "active_bots": len(lanes),
            "attention_signals": len(active_attention),
            "assigned_attention": len(assigned_attention),
            "spatial_warnings": spatial_warning_count,
            "recent_updates": len(recent_updates),
        },
        "missions": missions,
        "lanes": lanes,
        "attention": active_attention,
        "unassigned_attention": [
            _compact_attention_signal(item)
            for item in active_attention
            if not item.get("assigned_bot_id")
        ][:20],
        "recent_updates": recent_updates[:20],
        "mission_rows": mission_rows_by_id,
        "assistant_brief": await latest_mission_control_brief(db),
        "drafts": await list_mission_drafts(db, auth=auth, include_inactive=False, limit=20),
    }
