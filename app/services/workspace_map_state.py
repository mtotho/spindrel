"""Workspace map state projection.

Read-only aggregation for the spatial canvas. This intentionally uses the
existing primitives that already operate the workspace: spatial nodes,
channels, bots, widgets, heartbeats, scheduled task rows, recent task rows,
widget cron/event subscriptions, and attention as a warning overlay.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent.bots import get_bot, list_bots
from app.db.models import (
    Channel,
    ChannelBotMember,
    ChannelHeartbeat,
    ChannelIntegration,
    Task,
    TraceEvent,
    WidgetCronSubscription,
    WidgetDashboardPin,
    WidgetEventSubscription,
    WorkspaceAttentionItem,
    WorkspaceSpatialNode,
)
from app.services.channels import apply_channel_visibility
from app.services.upcoming_activity import list_upcoming_activity
from app.services.workspace_spatial import list_nodes


SEVERITY_RANK = {"info": 1, "warning": 2, "error": 3, "critical": 4}
STATUS_RANK = {
    "idle": 0,
    "recent": 1,
    "scheduled": 2,
    "active": 3,
    "running": 4,
    "warning": 5,
    "error": 6,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _truncate(value: str | None, limit: int = 220) -> str | None:
    if not value:
        return None
    text = value.strip()
    return text if len(text) <= limit else f"{text[:limit].rstrip()}..."


def _bot_name(bot_id: str | None) -> str | None:
    if not bot_id:
        return None
    try:
        bot = get_bot(bot_id)
        return getattr(bot, "display_name", None) or getattr(bot, "name", None) or bot_id
    except Exception:
        return bot_id


def _task_title(task: Task) -> str:
    return task.title or _truncate(task.prompt, 80) or task.task_type or "Automation"


def _task_signal(task: Task, channel: Channel | None = None) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "kind": "task",
        "title": _task_title(task),
        "status": task.status,
        "task_type": task.task_type,
        "bot_id": task.bot_id,
        "bot_name": _bot_name(task.bot_id),
        "channel_id": str(task.channel_id) if task.channel_id else None,
        "channel_name": channel.name if channel else None,
        "scheduled_at": _iso(task.scheduled_at),
        "run_at": _iso(task.run_at),
        "completed_at": _iso(task.completed_at),
        "created_at": _iso(task.created_at),
        "error": _truncate(task.error),
        "result": _truncate(task.result),
    }


def _trace_signal(event: TraceEvent) -> dict[str, Any]:
    data = event.data or {}
    return {
        "id": str(event.id),
        "kind": "trace",
        "title": event.event_name or event.event_type or "Trace error",
        "status": "error",
        "severity": "error",
        "message": _truncate(str(data.get("error") or data.get("message") or "")),
        "bot_id": event.bot_id or data.get("bot_id"),
        "channel_id": data.get("channel_id"),
        "created_at": _iso(event.created_at),
        "last_seen_at": _iso(event.created_at),
    }


def _status_from_task(task: Task) -> str:
    if task.error or task.status == "failed":
        return "error"
    if task.status in {"running", "active"} and task.run_at:
        return "running"
    if task.scheduled_at and task.status in {"pending", "active"}:
        return "scheduled"
    if task.completed_at or task.status in {"completed", "done", "success"}:
        return "recent"
    return "active" if task.status in {"pending", "active"} else "recent"


def _merge_state(base: dict[str, Any], *, status: str, severity: str | None = None, reason: str | None = None) -> None:
    if STATUS_RANK.get(status, 0) > STATUS_RANK.get(base["status"], 0):
        base["status"] = status
        if reason:
            base["primary_signal"] = reason
    if severity and SEVERITY_RANK.get(severity, 0) > SEVERITY_RANK.get(base.get("severity") or "info", 0):
        base["severity"] = severity


def _node_kind(node: WorkspaceSpatialNode) -> str:
    if node.channel_id:
        return "channel"
    if node.bot_id:
        return "bot"
    if node.widget_pin_id:
        return "widget"
    if node.landmark_kind:
        return "landmark"
    return "object"


def _node_label(node: WorkspaceSpatialNode, channel_by_id: dict[uuid.UUID, Channel], pin: WidgetDashboardPin | None) -> str:
    if node.channel_id:
        channel = channel_by_id.get(node.channel_id)
        return channel.name if channel else "Channel"
    if node.bot_id:
        return _bot_name(node.bot_id) or node.bot_id
    if pin:
        return pin.display_label or pin.tool_name or "Widget"
    if node.landmark_kind:
        return node.landmark_kind.replace("_", " ")
    return "Object"


def _empty_object(node: WorkspaceSpatialNode, channel_by_id: dict[uuid.UUID, Channel], pin: WidgetDashboardPin | None) -> dict[str, Any]:
    kind = _node_kind(node)
    return {
        "node_id": str(node.id),
        "kind": kind,
        "target_id": str(node.channel_id or node.widget_pin_id or node.bot_id or node.landmark_kind),
        "label": _node_label(node, channel_by_id, pin),
        "status": "idle",
        "severity": None,
        "primary_signal": None,
        "secondary_signal": None,
        "counts": {
            "upcoming": 0,
            "recent": 0,
            "warnings": 0,
            "widgets": 0,
            "integrations": 0,
            "bots": 0,
        },
        "next": None,
        "recent": [],
        "warnings": [],
        "source": {},
        "attached": {},
    }


async def _visible_channels(db: AsyncSession, auth: Any) -> list[Channel]:
    stmt = apply_channel_visibility(select(Channel), auth).options(
        selectinload(Channel.bot_members),
        selectinload(Channel.integrations),
    )
    return list((await db.execute(stmt)).scalars().all())


async def _recent_tasks(
    db: AsyncSession,
    *,
    visible_channel_ids: set[uuid.UUID],
    limit: int,
) -> list[Task]:
    since = _now() - timedelta(hours=72)
    stmt = (
        select(Task)
        .where(or_(Task.channel_id.is_(None), Task.channel_id.in_(visible_channel_ids)))
        .where(or_(Task.created_at >= since, Task.completed_at >= since, Task.run_at >= since))
        .order_by(desc(Task.created_at))
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def _active_attention(
    db: AsyncSession,
    *,
    visible_channel_ids: set[uuid.UUID],
    limit: int = 80,
) -> list[WorkspaceAttentionItem]:
    stmt = (
        select(WorkspaceAttentionItem)
        .where(WorkspaceAttentionItem.status.in_(("open", "responded")))
        .where(
            or_(
                WorkspaceAttentionItem.channel_id.is_(None),
                WorkspaceAttentionItem.channel_id.in_(visible_channel_ids),
            )
        )
        .order_by(desc(WorkspaceAttentionItem.last_seen_at))
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def _recent_trace_errors(
    db: AsyncSession,
    *,
    visible_channel_ids: set[uuid.UUID],
    limit: int = 40,
) -> list[TraceEvent]:
    since = _now() - timedelta(hours=24)
    rows = list((await db.execute(
        select(TraceEvent)
        .where(TraceEvent.created_at >= since)
        .where(TraceEvent.event_type.in_(("error", "llm_error")))
        .order_by(desc(TraceEvent.created_at))
        .limit(limit)
    )).scalars().all())
    if not visible_channel_ids:
        return rows
    filtered: list[TraceEvent] = []
    visible = {str(cid) for cid in visible_channel_ids}
    for row in rows:
        channel_id = str((row.data or {}).get("channel_id") or "")
        if not channel_id or channel_id in visible:
            filtered.append(row)
    return filtered


async def build_workspace_map_state(
    db: AsyncSession,
    *,
    auth: Any,
    recent_limit: int = 80,
    upcoming_limit: int = 100,
) -> dict[str, Any]:
    """Build a map-ready projection over existing workspace primitives."""
    channels = await _visible_channels(db, auth)
    channel_by_id = {channel.id: channel for channel in channels}
    visible_channel_ids = set(channel_by_id)
    node_pairs = await list_nodes(db)
    node_by_channel = {node.channel_id: node for node, _pin in node_pairs if node.channel_id}
    node_by_bot = {node.bot_id: node for node, _pin in node_pairs if node.bot_id}
    node_by_pin = {node.widget_pin_id: node for node, _pin in node_pairs if node.widget_pin_id}
    pin_by_id = {pin.id: pin for _node, pin in node_pairs if pin is not None}
    objects: dict[str, dict[str, Any]] = {
        str(node.id): _empty_object(node, channel_by_id, pin)
        for node, pin in node_pairs
    }

    # Channel room attachments.
    for channel in channels:
        node = node_by_channel.get(channel.id)
        if not node:
            continue
        obj = objects[str(node.id)]
        member_ids = [member.bot_id for member in (channel.bot_members or [])]
        bot_ids = list(dict.fromkeys([channel.bot_id, *member_ids]))
        integrations = [
            {
                "id": str(integration.id),
                "type": integration.integration_type,
                "display_name": integration.display_name,
                "client_id": integration.client_id,
                "activated": bool(integration.activated),
            }
            for integration in (channel.integrations or [])
        ]
        obj["source"] = {
            "channel_id": str(channel.id),
            "channel_name": channel.name,
            "primary_bot_id": channel.bot_id,
            "primary_bot_name": _bot_name(channel.bot_id),
        }
        obj["attached"].update({
            "bot_ids": bot_ids,
            "integrations": integrations,
        })
        obj["counts"]["bots"] = len(bot_ids)
        obj["counts"]["integrations"] = len(integrations)

    # Widget source and subscriptions.
    pin_ids = set(pin_by_id)
    cron_by_pin: dict[uuid.UUID, list[WidgetCronSubscription]] = defaultdict(list)
    event_by_pin: dict[uuid.UUID, list[WidgetEventSubscription]] = defaultdict(list)
    if pin_ids:
        for row in (await db.execute(
            select(WidgetCronSubscription).where(WidgetCronSubscription.pin_id.in_(pin_ids))
        )).scalars().all():
            cron_by_pin[row.pin_id].append(row)
        for row in (await db.execute(
            select(WidgetEventSubscription).where(WidgetEventSubscription.pin_id.in_(pin_ids))
        )).scalars().all():
            event_by_pin[row.pin_id].append(row)

    widgets_by_channel: dict[uuid.UUID, list[dict[str, Any]]] = defaultdict(list)
    for pin_id, pin in pin_by_id.items():
        node = node_by_pin.get(pin_id)
        if not node:
            continue
        obj = objects[str(node.id)]
        crons = sorted(cron_by_pin.get(pin_id, []), key=lambda row: row.next_fire_at or datetime.max.replace(tzinfo=timezone.utc))
        events = event_by_pin.get(pin_id, [])
        next_cron = crons[0] if crons else None
        obj["source"] = {
            "widget_pin_id": str(pin.id),
            "source_channel_id": str(pin.source_channel_id) if pin.source_channel_id else None,
            "source_channel_name": channel_by_id.get(pin.source_channel_id).name if pin.source_channel_id in channel_by_id else None,
            "source_bot_id": pin.source_bot_id,
            "source_bot_name": _bot_name(pin.source_bot_id),
            "tool_name": pin.tool_name,
            "widget_instance_id": str(pin.widget_instance_id) if pin.widget_instance_id else None,
        }
        obj["attached"]["cron_count"] = len(crons)
        obj["attached"]["event_count"] = len(events)
        if next_cron and next_cron.next_fire_at:
            obj["next"] = {
                "kind": "widget_cron",
                "title": next_cron.cron_name,
                "scheduled_at": _iso(next_cron.next_fire_at),
            }
            obj["counts"]["upcoming"] += 1
            _merge_state(obj, status="scheduled", reason=f"{next_cron.cron_name} scheduled")
        if pin.source_channel_id:
            widgets_by_channel[pin.source_channel_id].append({
                "node_id": str(node.id),
                "pin_id": str(pin.id),
                "label": obj["label"],
                "tool_name": pin.tool_name,
            })

    for channel_id, widgets in widgets_by_channel.items():
        node = node_by_channel.get(channel_id)
        if node and str(node.id) in objects:
            objects[str(node.id)]["attached"]["widgets"] = widgets
            objects[str(node.id)]["counts"]["widgets"] = len(widgets)

    # Heartbeat state.
    if visible_channel_ids:
        heartbeats = list((await db.execute(
            select(ChannelHeartbeat).where(ChannelHeartbeat.channel_id.in_(visible_channel_ids))
        )).scalars().all())
        for heartbeat in heartbeats:
            node = node_by_channel.get(heartbeat.channel_id)
            if not node:
                continue
            obj = objects[str(node.id)]
            obj["attached"]["heartbeat"] = {
                "enabled": bool(heartbeat.enabled),
                "interval_minutes": heartbeat.interval_minutes,
                "next_run_at": _iso(heartbeat.next_run_at),
                "last_run_at": _iso(heartbeat.last_run_at),
                "last_error": _truncate(heartbeat.last_error),
                "run_count": heartbeat.run_count,
            }
            if heartbeat.last_error:
                obj["warnings"].append({
                    "kind": "heartbeat",
                    "severity": "error",
                    "title": "Heartbeat failed",
                    "message": _truncate(heartbeat.last_error),
                    "last_seen_at": _iso(heartbeat.last_run_at),
                })
                obj["counts"]["warnings"] += 1
                _merge_state(obj, status="error", severity="error", reason="Heartbeat failed")
            elif heartbeat.enabled and heartbeat.next_run_at:
                if not obj["next"] or str(heartbeat.next_run_at.isoformat()) < str(obj["next"].get("scheduled_at") or "9999"):
                    obj["next"] = {"kind": "heartbeat", "title": "Heartbeat", "scheduled_at": _iso(heartbeat.next_run_at)}
                obj["counts"]["upcoming"] += 1
                _merge_state(obj, status="scheduled", reason="Heartbeat scheduled")

    # Upcoming activity and recent task reality.
    upcoming = await list_upcoming_activity(
        db,
        limit=upcoming_limit,
        auth=auth,
        include_memory_hygiene=True,
        include_channelless_tasks=True,
    )
    for item in upcoming:
        channel_id = item.get("channel_id")
        bot_id = item.get("bot_id")
        candidates: list[WorkspaceSpatialNode] = []
        if channel_id:
            try:
                node = node_by_channel.get(uuid.UUID(str(channel_id)))
                if node:
                    candidates.append(node)
            except ValueError:
                pass
        if bot_id and node_by_bot.get(str(bot_id)):
            candidates.append(node_by_bot[str(bot_id)])
        if item.get("type") == "memory_hygiene":
            landmark = next((node for node, _pin in node_pairs if node.landmark_kind == "memory_observatory"), None)
            if landmark:
                candidates.append(landmark)
        for node in {candidate.id: candidate for candidate in candidates}.values():
            obj = objects.get(str(node.id))
            if not obj:
                continue
            obj["counts"]["upcoming"] += 1
            next_item = {
                "kind": item.get("type"),
                "title": item.get("title"),
                "scheduled_at": item.get("scheduled_at"),
                "task_id": item.get("task_id"),
                "bot_id": bot_id,
                "bot_name": item.get("bot_name"),
                "channel_id": channel_id,
                "channel_name": item.get("channel_name"),
            }
            if not obj["next"] or str(item.get("scheduled_at") or "9999") < str(obj["next"].get("scheduled_at") or "9999"):
                obj["next"] = next_item
            _merge_state(obj, status="scheduled", reason=f"{item.get('title') or item.get('type')} scheduled")

    recent_tasks = await _recent_tasks(db, visible_channel_ids=visible_channel_ids, limit=recent_limit)
    channel_for_task = {channel.id: channel for channel in channels}
    for task in recent_tasks:
        signal = _task_signal(task, channel_for_task.get(task.channel_id) if task.channel_id else None)
        status = _status_from_task(task)
        candidates = []
        if task.channel_id and node_by_channel.get(task.channel_id):
            candidates.append(node_by_channel[task.channel_id])
        if task.bot_id and node_by_bot.get(task.bot_id):
            candidates.append(node_by_bot[task.bot_id])
        for node in {candidate.id: candidate for candidate in candidates}.values():
            obj = objects.get(str(node.id))
            if not obj:
                continue
            obj["recent"].append(signal)
            obj["recent"] = obj["recent"][:6]
            obj["counts"]["recent"] += 1
            if task.error:
                obj["warnings"].append({
                    "kind": "task",
                    "severity": "error",
                    "title": signal["title"],
                    "message": signal["error"],
                    "task_id": signal["id"],
                    "last_seen_at": signal["completed_at"] or signal["created_at"],
                })
                obj["counts"]["warnings"] += 1
            _merge_state(obj, status=status, severity="error" if task.error else None, reason=signal["title"])

    # Attention remains a warning overlay, not the object model.
    for item in await _active_attention(db, visible_channel_ids=visible_channel_ids):
        nodes: list[WorkspaceSpatialNode] = []
        if item.target_kind == "channel":
            try:
                node = node_by_channel.get(uuid.UUID(str(item.target_id)))
                if node:
                    nodes.append(node)
            except ValueError:
                pass
        elif item.target_kind == "bot" and node_by_bot.get(item.target_id):
            nodes.append(node_by_bot[item.target_id])
        elif item.target_kind == "widget":
            try:
                node = node_by_pin.get(uuid.UUID(str(item.target_id)))
                if node:
                    nodes.append(node)
            except ValueError:
                pass
        elif item.channel_id and node_by_channel.get(item.channel_id):
            nodes.append(node_by_channel[item.channel_id])
        for node in {candidate.id: candidate for candidate in nodes}.values():
            obj = objects.get(str(node.id))
            if not obj:
                continue
            warning = {
                "kind": "attention",
                "id": str(item.id),
                "severity": item.severity,
                "title": item.title,
                "message": _truncate(item.message),
                "last_seen_at": _iso(item.last_seen_at),
            }
            obj["warnings"].append(warning)
            obj["counts"]["warnings"] += 1
            _merge_state(
                obj,
                status="error" if item.severity in {"critical", "error"} else "warning",
                severity=item.severity,
                reason=item.title,
            )

    # Trace errors attach to their target objects when the trace already carries
    # channel/bot identity. Only unmapped system errors roll up to Daily Health.
    daily_health = next((node for node, _pin in node_pairs if node.landmark_kind == "daily_health"), None)
    trace_errors = await _recent_trace_errors(db, visible_channel_ids=visible_channel_ids)
    unmapped_trace_errors: list[TraceEvent] = []
    for ev in trace_errors:
        signal = _trace_signal(ev)
        candidates: list[WorkspaceSpatialNode] = []
        channel_id = signal.get("channel_id")
        if channel_id:
            try:
                node = node_by_channel.get(uuid.UUID(str(channel_id)))
                if node:
                    candidates.append(node)
            except ValueError:
                pass
        bot_id = signal.get("bot_id")
        if bot_id and node_by_bot.get(str(bot_id)):
            candidates.append(node_by_bot[str(bot_id)])
        mapped = False
        for node in {candidate.id: candidate for candidate in candidates}.values():
            obj = objects.get(str(node.id))
            if not obj:
                continue
            obj["warnings"].append(signal)
            obj["recent"].append(signal)
            obj["recent"] = obj["recent"][:6]
            obj["counts"]["warnings"] += 1
            obj["counts"]["recent"] += 1
            _merge_state(obj, status="error", severity="error", reason=signal["title"])
            mapped = True
        if not mapped:
            unmapped_trace_errors.append(ev)

    if daily_health and unmapped_trace_errors:
        obj = objects[str(daily_health.id)]
        for ev in unmapped_trace_errors[:8]:
            obj["warnings"].append(_trace_signal(ev))
            obj["counts"]["warnings"] += 1
        _merge_state(obj, status="error", severity="error", reason="Recent system errors")

    # Bot source summaries.
    bot_channel_ids: dict[str, set[str]] = defaultdict(set)
    for channel in channels:
        bot_channel_ids[channel.bot_id].add(str(channel.id))
        for member in channel.bot_members or []:
            bot_channel_ids[member.bot_id].add(str(channel.id))
    for bot in list_bots():
        node = node_by_bot.get(bot.id)
        if node and str(node.id) in objects:
            objects[str(node.id)]["source"] = {
                "bot_id": bot.id,
                "bot_name": getattr(bot, "display_name", None) or bot.name,
                "model": getattr(bot, "model", None),
                "harness_runtime": getattr(bot, "harness_runtime", None),
            }
            objects[str(node.id)]["attached"]["channel_ids"] = sorted(bot_channel_ids.get(bot.id, set()))

    # Landmarks that are not otherwise active still expose their domain.
    for node, _pin in node_pairs:
        if not node.landmark_kind:
            continue
        obj = objects[str(node.id)]
        obj["source"] = {"landmark_kind": node.landmark_kind}
        if node.landmark_kind == "now_well" and upcoming:
            obj["next"] = upcoming[0]
            obj["counts"]["upcoming"] = len(upcoming)
            _merge_state(obj, status="scheduled", reason=f"{upcoming[0].get('title') or 'Work'} upcoming")
        if node.landmark_kind == "attention_hub":
            total_warnings = sum(1 for entry in objects.values() for _warning in entry["warnings"])
            obj["counts"]["warnings"] = total_warnings
            if total_warnings:
                _merge_state(obj, status="warning", severity="warning", reason=f"{total_warnings} warnings")

    rows = sorted(objects.values(), key=lambda item: (STATUS_RANK.get(item["status"], 0), item["label"].lower()), reverse=True)
    summary = {
        "objects": len(rows),
        "channels": sum(1 for item in rows if item["kind"] == "channel"),
        "bots": sum(1 for item in rows if item["kind"] == "bot"),
        "widgets": sum(1 for item in rows if item["kind"] == "widget"),
        "landmarks": sum(1 for item in rows if item["kind"] == "landmark"),
        "warnings": sum(item["counts"]["warnings"] for item in rows),
        "upcoming": len(upcoming),
        "recent": len(recent_tasks),
    }
    return {
        "generated_at": _iso(_now()),
        "summary": summary,
        "objects": rows,
        "objects_by_node_id": {item["node_id"]: item for item in rows},
        "upcoming": upcoming[:upcoming_limit],
        "recent": [_task_signal(task, channel_for_task.get(task.channel_id) if task.channel_id else None) for task in recent_tasks[:recent_limit]],
        "source": "existing_primitives",
    }
