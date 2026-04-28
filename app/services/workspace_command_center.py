"""Workspace Command Center aggregation.

Command Center is an operations read model over existing domain state:
Attention Items, channel heartbeats, scheduled tasks, and recent run results.
It does not own lifecycle state itself.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent.bots import get_bot, list_bots
from app.db.models import Channel, ChannelHeartbeat, HeartbeatRun, Task
from app.domain.errors import NotFoundError, ValidationError
from app.services.channels import apply_channel_visibility
from app.services.upcoming_activity import list_upcoming_activity
from app.services.workspace_attention import (
    assign_attention_item,
    create_user_attention_item,
    list_attention_items,
    serialize_attention_item,
)


SEVERITY_RANK = {
    "critical": 4,
    "error": 3,
    "warning": 2,
    "info": 1,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _event_time(event: dict[str, Any]) -> str:
    return str(event.get("occurred_at") or "")


async def _visible_channels(db: AsyncSession, auth: Any) -> list[Channel]:
    stmt = apply_channel_visibility(select(Channel), auth)
    return list((await db.execute(stmt)).scalars().all())


def _assignment_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    severity = str(item.get("severity") or "info")
    assigned_at = str(item.get("assigned_at") or item.get("last_seen_at") or "")
    return (-SEVERITY_RANK.get(severity, 0), assigned_at)


async def _heartbeat_recent_events(
    db: AsyncSession,
    *,
    visible_channel_ids: set[uuid.UUID],
    since: datetime,
) -> list[dict[str, Any]]:
    if not visible_channel_ids:
        return []
    stmt = (
        select(HeartbeatRun, ChannelHeartbeat, Channel)
        .join(ChannelHeartbeat, HeartbeatRun.heartbeat_id == ChannelHeartbeat.id)
        .join(Channel, ChannelHeartbeat.channel_id == Channel.id)
        .where(
            Channel.id.in_(visible_channel_ids),
            HeartbeatRun.completed_at.isnot(None),
            HeartbeatRun.completed_at >= since,
        )
        .order_by(desc(HeartbeatRun.completed_at))
        .limit(80)
    )
    rows = (await db.execute(stmt)).all()
    events: list[dict[str, Any]] = []
    for run, heartbeat, channel in rows:
        events.append({
            "type": "heartbeat",
            "status": run.status,
            "title": "Heartbeat completed" if run.status == "complete" else "Heartbeat needs review",
            "summary": run.error or (run.result or "")[:240],
            "bot_id": channel.bot_id,
            "bot_name": _bot_name(channel.bot_id),
            "channel_id": str(channel.id),
            "channel_name": channel.name,
            "occurred_at": _iso(run.completed_at),
            "correlation_id": str(run.correlation_id) if run.correlation_id else None,
            "heartbeat_id": str(heartbeat.id),
        })
    return events


async def _task_recent_events(
    db: AsyncSession,
    *,
    visible_channel_ids: set[uuid.UUID],
    since: datetime,
) -> list[dict[str, Any]]:
    stmt = (
        select(Task)
        .where(
            Task.completed_at.isnot(None),
            Task.completed_at >= since,
            Task.status.in_(["complete", "failed", "cancelled"]),
        )
        .order_by(desc(Task.completed_at))
        .limit(80)
    )
    stmt = stmt.where(
        or_(
            Task.channel_id.is_(None),
            Task.channel_id.in_(visible_channel_ids),
        )
    )
    tasks = list((await db.execute(stmt)).scalars().all())
    channel_ids = {task.channel_id for task in tasks if task.channel_id}
    channels = {}
    if channel_ids:
        rows = (await db.execute(select(Channel).where(Channel.id.in_(channel_ids)))).scalars().all()
        channels = {channel.id: channel for channel in rows}

    events: list[dict[str, Any]] = []
    for task in tasks:
        channel = channels.get(task.channel_id)
        title = task.title or task.prompt[:80] or "Task"
        events.append({
            "type": "task",
            "status": task.status,
            "title": title,
            "summary": task.error or (task.result or "")[:240],
            "bot_id": task.bot_id,
            "bot_name": _bot_name(task.bot_id),
            "channel_id": str(task.channel_id) if task.channel_id else None,
            "channel_name": channel.name if channel else None,
            "occurred_at": _iso(task.completed_at),
            "task_id": str(task.id),
            "task_type": task.task_type,
            "correlation_id": str(task.correlation_id) if task.correlation_id else None,
        })
    return events


def _attention_recent_event(item: dict[str, Any], since: datetime) -> dict[str, Any] | None:
    candidates = [
        item.get("assignment_reported_at"),
        item.get("responded_at"),
        item.get("resolved_at"),
        item.get("last_seen_at"),
    ]
    occurred_at = next((value for value in candidates if value), None)
    if not occurred_at:
        return None
    try:
        parsed = datetime.fromisoformat(str(occurred_at))
    except ValueError:
        return None
    if parsed < since:
        return None
    if item.get("assignment_report"):
        event_type = "assignment_report"
        title = "Assignment reported"
        summary = str(item.get("assignment_report") or "")[:240]
    else:
        event_type = "attention"
        title = f"Attention {item.get('status') or 'updated'}"
        summary = str(item.get("message") or "")[:240]
    return {
        "type": event_type,
        "status": item.get("assignment_status") or item.get("status"),
        "title": title,
        "summary": summary,
        "bot_id": item.get("assigned_bot_id"),
        "bot_name": _bot_name(str(item.get("assigned_bot_id"))) if item.get("assigned_bot_id") else None,
        "channel_id": item.get("channel_id"),
        "channel_name": item.get("channel_name"),
        "occurred_at": occurred_at,
        "attention_item_id": item.get("id"),
        "correlation_id": item.get("latest_correlation_id"),
    }


async def build_command_center(
    db: AsyncSession,
    *,
    auth: Any,
    recent_hours: int = 24,
    upcoming_hours: int = 24,
) -> dict[str, Any]:
    recent_since = _now() - timedelta(hours=max(1, min(recent_hours, 168)))
    upcoming_until = _now() + timedelta(hours=max(1, min(upcoming_hours, 168)))

    channels = await _visible_channels(db, auth)
    channel_by_id = {channel.id: channel for channel in channels}
    visible_channel_ids = set(channel_by_id)
    heartbeat_rows = list((await db.execute(
        select(ChannelHeartbeat)
        .options(selectinload(ChannelHeartbeat.channel))
        .where(ChannelHeartbeat.channel_id.in_(visible_channel_ids))
    )).scalars().all()) if visible_channel_ids else []
    heartbeat_by_channel = {heartbeat.channel_id: heartbeat for heartbeat in heartbeat_rows}

    attention_rows = await list_attention_items(db, auth=auth, include_resolved=True)
    attention_items = [await serialize_attention_item(db, item) for item in attention_rows]
    active_attention = [
        item for item in attention_items
        if item.get("status") not in {"acknowledged", "resolved"}
    ]
    assignments = [
        item for item in active_attention
        if item.get("assigned_bot_id") and item.get("assignment_status") in {"assigned", "running"}
    ]
    assignments.sort(key=_assignment_sort_key)

    upcoming = await list_upcoming_activity(
        db,
        limit=200,
        auth=auth,
        include_memory_hygiene=True,
        include_channelless_tasks=True,
    )
    upcoming = [
        item for item in upcoming
        if item.get("scheduled_at")
        and datetime.fromisoformat(str(item["scheduled_at"])) <= upcoming_until
    ]

    recent_events = []
    recent_events.extend(
        event for item in attention_items
        if (event := _attention_recent_event(item, recent_since)) is not None
    )
    recent_events.extend(await _heartbeat_recent_events(db, visible_channel_ids=visible_channel_ids, since=recent_since))
    recent_events.extend(await _task_recent_events(db, visible_channel_ids=visible_channel_ids, since=recent_since))
    recent_events.sort(key=_event_time, reverse=True)
    recent_events = recent_events[:100]

    bot_ids: set[str] = {channel.bot_id for channel in channels if channel.bot_id}
    bot_ids.update(str(item.get("assigned_bot_id")) for item in assignments if item.get("assigned_bot_id"))
    bot_ids.update(str(item.get("bot_id")) for item in upcoming if item.get("bot_id"))
    bot_ids.update(str(event.get("bot_id")) for event in recent_events if event.get("bot_id"))
    known_bot_ids = {bot.id for bot in list_bots()}
    bot_ids = {bot_id for bot_id in bot_ids if bot_id and bot_id in known_bot_ids}

    bot_rows: list[dict[str, Any]] = []
    for bot_id in sorted(bot_ids, key=lambda bid: _bot_name(bid).lower()):
        bot_channels = [channel for channel in channels if channel.bot_id == bot_id]
        heartbeat_candidates = [
            heartbeat_by_channel[channel.id]
            for channel in bot_channels
            if channel.id in heartbeat_by_channel
        ]
        next_heartbeat = min(
            (hb for hb in heartbeat_candidates if hb.enabled and hb.next_run_at is not None),
            key=lambda hb: hb.next_run_at,
            default=None,
        )
        bot_assignments = [item for item in assignments if item.get("assigned_bot_id") == bot_id]
        for item in bot_assignments:
            channel_id = item.get("channel_id")
            parsed_channel_id = uuid.UUID(str(channel_id)) if channel_id else None
            hb = heartbeat_by_channel.get(parsed_channel_id) if parsed_channel_id else None
            item["queue_state"] = {
                "blocked": not (hb and hb.enabled and hb.next_run_at),
                "blocked_reason": None if hb and hb.enabled and hb.next_run_at else "No enabled heartbeat is scheduled for this channel.",
                "next_run_at": _iso(hb.next_run_at) if hb else None,
                "heartbeat_channel_id": str(parsed_channel_id) if parsed_channel_id else None,
            }
        bot_rows.append({
            "bot_id": bot_id,
            "bot_name": _bot_name(bot_id),
            "harness_runtime": _bot_runtime(bot_id),
            "channels": [
                {"id": str(channel.id), "name": channel.name}
                for channel in sorted(bot_channels, key=lambda channel: channel.name.lower())
            ],
            "next_heartbeat_at": _iso(next_heartbeat.next_run_at) if next_heartbeat else None,
            "heartbeat_channel_id": str(next_heartbeat.channel_id) if next_heartbeat else None,
            "heartbeat_channel_name": next_heartbeat.channel.name if next_heartbeat and next_heartbeat.channel else None,
            "assignments": bot_assignments,
            "active_assignment": bot_assignments[0] if bot_assignments else None,
            "queue_depth": len(bot_assignments),
            "upcoming": [item for item in upcoming if item.get("bot_id") == bot_id][:6],
            "recent": [event for event in recent_events if event.get("bot_id") == bot_id][:6],
        })

    return {
        "summary": {
            "active_attention": len(active_attention),
            "assigned": len(assignments),
            "blocked": sum(
                1 for item in assignments
                if (item.get("queue_state") or {}).get("blocked")
            ),
            "upcoming": len(upcoming),
            "recent": len(recent_events),
        },
        "window": {
            "recent_hours": recent_hours,
            "upcoming_hours": upcoming_hours,
            "recent_since": _iso(recent_since),
            "upcoming_until": _iso(upcoming_until),
        },
        "bots": bot_rows,
        "attention": active_attention,
        "upcoming": upcoming,
        "recent": recent_events,
    }


async def create_command_center_intake(
    db: AsyncSession,
    *,
    auth_label: str,
    channel_id: uuid.UUID,
    title: str,
    message: str = "",
    severity: str = "warning",
    next_steps: list[str] | None = None,
    assign_bot_id: str | None = None,
    assignment_mode: str | None = None,
    assignment_instructions: str | None = None,
) -> dict[str, Any]:
    channel = await db.get(Channel, channel_id)
    if channel is None:
        raise NotFoundError("Channel not found.")
    item = await create_user_attention_item(
        db,
        actor=auth_label,
        channel_id=channel.id,
        target_kind="channel",
        target_id=str(channel.id),
        title=title,
        message=message,
        severity=severity,
        requires_response=True,
        next_steps=next_steps or [],
    )
    if assign_bot_id or assignment_mode:
        mode = assignment_mode or "next_heartbeat"
        bot_id = assign_bot_id or channel.bot_id
        item = await assign_attention_item(
            db,
            item.id,
            bot_id=bot_id,
            mode=mode,
            instructions=assignment_instructions,
            assigned_by=auth_label,
        )
    return {"item": await serialize_attention_item(db, item)}
