"""Agent-facing snapshot of assigned Mission Control work."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Channel,
    WorkspaceAttentionItem,
    WorkspaceMission,
    WorkspaceMissionAssignment,
    WorkspaceMissionUpdate,
)


SEVERITY_RANK = {
    "critical": 4,
    "error": 3,
    "warning": 2,
    "info": 1,
}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _coerce_limit(max_items: int | None) -> int:
    try:
        value = int(max_items or 10)
    except (TypeError, ValueError):
        value = 10
    return max(1, min(value, 50))


async def _channel_name(db: AsyncSession, channel_id: uuid.UUID | None) -> str | None:
    if channel_id is None:
        return None
    channel = await db.get(Channel, channel_id)
    return channel.name if channel else None


async def _latest_update(
    db: AsyncSession,
    mission_id: uuid.UUID,
) -> WorkspaceMissionUpdate | None:
    return (await db.execute(
        select(WorkspaceMissionUpdate)
        .where(WorkspaceMissionUpdate.mission_id == mission_id)
        .order_by(desc(WorkspaceMissionUpdate.created_at))
        .limit(1)
    )).scalar_one_or_none()


def _update_payload(row: WorkspaceMissionUpdate | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "kind": row.kind,
        "summary": row.summary,
        "next_actions": list(row.next_actions or []),
        "created_at": _iso(row.created_at),
    }


def _mission_sort_key(row: dict[str, Any]) -> tuple[int, datetime, int, float]:
    next_run = row.get("_next_run_at_sort")
    last_update = row.get("_last_update_at_sort")
    return (
        1 if next_run is None else 0,
        next_run or datetime.max.replace(tzinfo=timezone.utc),
        1 if last_update is None else 0,
        -(last_update.timestamp()) if last_update else 0.0,
    )


async def _assigned_missions(
    db: AsyncSession,
    *,
    bot_id: str,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    rows = list((await db.execute(
        select(WorkspaceMission, WorkspaceMissionAssignment)
        .join(
            WorkspaceMissionAssignment,
            WorkspaceMissionAssignment.mission_id == WorkspaceMission.id,
        )
        .where(
            WorkspaceMissionAssignment.bot_id == bot_id,
            WorkspaceMissionAssignment.status == "active",
            WorkspaceMission.status.in_(("active", "paused")),
        )
    )).all())

    payloads: list[dict[str, Any]] = []
    for mission, assignment in rows:
        latest = await _latest_update(db, mission.id)
        payloads.append({
            "id": str(mission.id),
            "title": mission.title,
            "status": mission.status,
            "scope": mission.scope,
            "channel_id": str(mission.channel_id) if mission.channel_id else None,
            "channel_name": await _channel_name(db, mission.channel_id),
            "assignment_id": str(assignment.id),
            "role": assignment.role,
            "target_channel_id": str(assignment.target_channel_id) if assignment.target_channel_id else None,
            "target_channel_name": await _channel_name(db, assignment.target_channel_id),
            "next_run_at": _iso(mission.next_run_at),
            "last_update_at": _iso(mission.last_update_at),
            "last_task_id": str(mission.last_task_id) if mission.last_task_id else None,
            "last_correlation_id": str(mission.last_correlation_id) if mission.last_correlation_id else None,
            "latest_update": _update_payload(latest),
            "_next_run_at_sort": mission.next_run_at,
            "_last_update_at_sort": mission.last_update_at,
        })

    payloads.sort(key=_mission_sort_key)
    trimmed = payloads[:limit]
    for row in trimmed:
        row.pop("_next_run_at_sort", None)
        row.pop("_last_update_at_sort", None)
    return trimmed, len(payloads)


def _attention_sort_key(row: WorkspaceAttentionItem) -> tuple[int, datetime]:
    assigned_at = row.assigned_at or datetime.max.replace(tzinfo=timezone.utc)
    return (-SEVERITY_RANK.get(row.severity, 0), assigned_at)


async def _assigned_attention(
    db: AsyncSession,
    *,
    bot_id: str,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    rows = list((await db.execute(
        select(WorkspaceAttentionItem)
        .where(
            WorkspaceAttentionItem.assigned_bot_id == bot_id,
            WorkspaceAttentionItem.assignment_status.in_(("assigned", "running")),
            WorkspaceAttentionItem.status.in_(("open", "responded")),
        )
    )).scalars().all())
    rows.sort(key=_attention_sort_key)

    payload = [
        {
            "id": str(item.id),
            "title": item.title,
            "severity": item.severity,
            "status": item.status,
            "assignment_status": item.assignment_status,
            "assignment_mode": item.assignment_mode,
            "channel_id": str(item.channel_id) if item.channel_id else None,
            "channel_name": await _channel_name(db, item.channel_id),
            "target_kind": item.target_kind,
            "target_id": item.target_id,
            "assignment_instructions": item.assignment_instructions,
            "next_steps": list(item.next_steps or []),
            "latest_correlation_id": str(item.latest_correlation_id) if item.latest_correlation_id else None,
            "assigned_at": _iso(item.assigned_at),
            "assignment_task_id": str(item.assignment_task_id) if item.assignment_task_id else None,
            "last_seen_at": _iso(item.last_seen_at),
        }
        for item in rows[:limit]
    ]
    return payload, len(rows)


def _recommended_next_action(mission_count: int, attention_count: int) -> str:
    if attention_count:
        return "review_attention"
    if mission_count:
        return "advance_mission"
    return "idle"


async def build_agent_work_snapshot(
    db: AsyncSession,
    *,
    bot_id: str | None,
    channel_id: str | uuid.UUID | None = None,
    session_id: str | uuid.UUID | None = None,
    max_items: int | None = 10,
) -> dict[str, Any]:
    """Return assigned work state for a runtime agent."""
    if not bot_id:
        return {
            "available": False,
            "bot_id": None,
            "channel_id": str(channel_id) if channel_id else None,
            "session_id": str(session_id) if session_id else None,
            "reason": "No bot context available.",
            "summary": {
                "assigned_mission_count": 0,
                "assigned_attention_count": 0,
                "has_current_work": False,
                "recommended_next_action": "idle",
            },
            "missions": [],
            "attention": [],
        }

    limit = _coerce_limit(max_items)
    missions, mission_count = await _assigned_missions(db, bot_id=bot_id, limit=limit)
    attention, attention_count = await _assigned_attention(db, bot_id=bot_id, limit=limit)
    recommended = _recommended_next_action(mission_count, attention_count)
    return {
        "available": True,
        "bot_id": bot_id,
        "channel_id": str(channel_id) if channel_id else None,
        "session_id": str(session_id) if session_id else None,
        "summary": {
            "assigned_mission_count": mission_count,
            "assigned_attention_count": attention_count,
            "has_current_work": bool(mission_count or attention_count),
            "recommended_next_action": recommended,
        },
        "missions": missions,
        "attention": attention,
    }
