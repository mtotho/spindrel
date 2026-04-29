"""Upcoming activity aggregation.

Owns the policy for merging scheduled heartbeats, tasks, and optional maintenance
runs. Routers choose the visibility/auth shape; this service owns the
query mechanics and response item shape.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Channel, ChannelHeartbeat, Task
from app.services.channels import apply_channel_visibility
from app.services.heartbeat import _is_heartbeat_in_quiet_hours

UpcomingType = Literal["heartbeat", "task", "memory_hygiene", "skill_review", "maintenance"]


def _bot_name(bot_id: str) -> str:
    try:
        from app.agent.bots import get_bot

        return get_bot(bot_id).name
    except Exception:
        return bot_id


async def _visible_channel_ids(db: AsyncSession, auth: Any) -> set[Any]:
    stmt = apply_channel_visibility(select(Channel.id), auth)
    rows = (await db.execute(stmt)).scalars().all()
    return set(rows)


async def list_upcoming_activity(
    db: AsyncSession,
    *,
    limit: int = 50,
    type_filter: str | None = None,
    auth: Any = None,
    include_memory_hygiene: bool = True,
    include_channelless_tasks: bool = True,
) -> list[dict]:
    """Return merged upcoming activity rows sorted by scheduled time.

    ``auth`` is passed through the existing channel-visibility helper. API keys
    and admins see all channels; non-admin users see public plus owned private
    channels. Maintenance jobs are admin/system data, so callers must opt into it.
    """
    now = datetime.now(timezone.utc)
    items: list[dict] = []
    visible_channel_ids = await _visible_channel_ids(db, auth)

    if type_filter is None or type_filter == "heartbeat":
        hb_stmt = (
            select(ChannelHeartbeat)
            .options(selectinload(ChannelHeartbeat.channel))
            .where(
                ChannelHeartbeat.enabled.is_(True),
                ChannelHeartbeat.next_run_at.isnot(None),
                ChannelHeartbeat.channel_id.in_(visible_channel_ids),
            )
            .order_by(ChannelHeartbeat.next_run_at.asc())
        )
        heartbeats = (await db.execute(hb_stmt)).scalars().all()

        for hb in heartbeats:
            channel: Channel | None = hb.channel
            if not channel:
                continue

            items.append({
                "type": "heartbeat",
                "scheduled_at": hb.next_run_at.isoformat() if hb.next_run_at else None,
                "bot_id": channel.bot_id,
                "bot_name": _bot_name(channel.bot_id),
                "channel_id": str(channel.id),
                "channel_name": channel.name,
                "title": "Heartbeat",
                "interval_minutes": hb.interval_minutes,
                "in_quiet_hours": _is_heartbeat_in_quiet_hours(hb),
            })

    if type_filter is None or type_filter == "task":
        task_stmt = (
            select(Task)
            .where(
                Task.scheduled_at > now,
                Task.status.in_(["pending", "active"]),
            )
            .order_by(Task.scheduled_at.asc())
        )
        if include_channelless_tasks:
            task_stmt = task_stmt.where(
                (Task.channel_id.is_(None)) | (Task.channel_id.in_(visible_channel_ids))
            )
        else:
            task_stmt = task_stmt.where(Task.channel_id.in_(visible_channel_ids))
        tasks = (await db.execute(task_stmt)).scalars().all()

        channel_ids = {t.channel_id for t in tasks if t.channel_id}
        channel_map: dict = {}
        if channel_ids:
            ch_rows = (
                await db.execute(select(Channel).where(Channel.id.in_(channel_ids)))
            ).scalars().all()
            channel_map = {ch.id: ch for ch in ch_rows}

        for task in tasks:
            ch = channel_map.get(task.channel_id) if task.channel_id else None
            prompt = task.prompt or ""
            items.append({
                "type": "task",
                "scheduled_at": task.scheduled_at.isoformat() if task.scheduled_at else None,
                "bot_id": task.bot_id,
                "bot_name": _bot_name(task.bot_id),
                "channel_id": str(task.channel_id) if task.channel_id else None,
                "channel_name": ch.name if ch else None,
                "title": task.title or (prompt[:60] + "..." if len(prompt) > 60 else prompt),
                "task_id": str(task.id),
                "task_type": task.task_type,
                "recurrence": task.recurrence,
            })

    if include_memory_hygiene and (
        type_filter is None
        or type_filter in {"memory_hygiene", "skill_review", "maintenance"}
    ):
        from app.services.maintenance_automations import list_upcoming_maintenance_items

        for maint_item in await list_upcoming_maintenance_items(db):
            job_type = maint_item.get("job_type")
            if type_filter in {"memory_hygiene", "skill_review"} and job_type != type_filter:
                continue
            item = dict(maint_item)
            if type_filter != "maintenance":
                item["type"] = item.pop("legacy_type", job_type)
            if job_type == "memory_hygiene" and item["type"] == "memory_hygiene":
                item["title"] = "Dreaming"
            items.append(item)

    items.sort(key=lambda x: x.get("scheduled_at") or "9999")
    return items[:limit]
