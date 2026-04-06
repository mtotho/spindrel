"""Upcoming activity endpoint: /upcoming-activity."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent.bots import get_bot
from app.db.models import Bot as BotRow, Channel, ChannelHeartbeat, Task
from app.dependencies import get_db, verify_auth_or_user
from app.services.heartbeat import _is_heartbeat_in_quiet_hours

router = APIRouter()


@router.get("/upcoming-activity")
async def upcoming_activity(
    limit: int = Query(50, ge=1, le=200),
    type: str | None = Query(None, description="Filter by type: heartbeat, task, memory_hygiene"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Return a merged, chronologically sorted list of upcoming heartbeats, tasks, and memory hygiene runs."""
    now = datetime.now(timezone.utc)
    items: list[dict] = []

    # --- Heartbeats ---
    if type is None or type == "heartbeat":
        hb_stmt = (
            select(ChannelHeartbeat)
            .options(selectinload(ChannelHeartbeat.channel))
            .where(
                ChannelHeartbeat.enabled.is_(True),
                ChannelHeartbeat.next_run_at.isnot(None),
            )
            .order_by(ChannelHeartbeat.next_run_at.asc())
        )
        heartbeats = (await db.execute(hb_stmt)).scalars().all()

        for hb in heartbeats:
            channel: Channel | None = hb.channel
            if not channel:
                continue
            bot_name = channel.bot_id
            try:
                bot = get_bot(channel.bot_id)
                bot_name = bot.name
            except Exception:
                pass

            items.append({
                "type": "heartbeat",
                "scheduled_at": hb.next_run_at.isoformat() if hb.next_run_at else None,
                "bot_id": channel.bot_id,
                "bot_name": bot_name,
                "channel_id": str(channel.id),
                "channel_name": channel.name,
                "title": "Heartbeat",
                "interval_minutes": hb.interval_minutes,
                "in_quiet_hours": _is_heartbeat_in_quiet_hours(hb),
            })

    # --- Scheduled tasks ---
    if type is None or type == "task":
        task_stmt = (
            select(Task)
            .where(
                Task.scheduled_at > now,
                Task.status.in_(["pending", "active"]),
            )
            .order_by(Task.scheduled_at.asc())
        )
        tasks = (await db.execute(task_stmt)).scalars().all()

        # Batch-load channels for all tasks with channel_id
        channel_ids = {t.channel_id for t in tasks if t.channel_id}
        channel_map: dict = {}
        if channel_ids:
            ch_rows = (await db.execute(
                select(Channel).where(Channel.id.in_(channel_ids))
            )).scalars().all()
            channel_map = {ch.id: ch for ch in ch_rows}

        for t in tasks:
            bot_name = t.bot_id
            try:
                bot = get_bot(t.bot_id)
                bot_name = bot.name
            except Exception:
                pass

            ch = channel_map.get(t.channel_id) if t.channel_id else None

            items.append({
                "type": "task",
                "scheduled_at": t.scheduled_at.isoformat() if t.scheduled_at else None,
                "bot_id": t.bot_id,
                "bot_name": bot_name,
                "channel_id": str(t.channel_id) if t.channel_id else None,
                "channel_name": ch.name if ch else None,
                "title": t.title or (t.prompt[:60] + "..." if len(t.prompt) > 60 else t.prompt),
                "task_id": str(t.id),
                "task_type": t.task_type,
                "recurrence": t.recurrence,
            })

    # --- Memory hygiene ---
    if type is None or type == "memory_hygiene":
        from app.services.memory_hygiene import resolve_enabled, resolve_interval

        hygiene_bots = (await db.execute(
            select(BotRow).where(
                BotRow.memory_scheme == "workspace-files",
                BotRow.next_hygiene_run_at.isnot(None),
            )
        )).scalars().all()

        for bot_row in hygiene_bots:
            if not resolve_enabled(bot_row):
                continue
            interval = resolve_interval(bot_row)
            bot_name = bot_row.id
            try:
                bot = get_bot(bot_row.id)
                bot_name = bot.name
            except Exception:
                pass

            items.append({
                "type": "memory_hygiene",
                "scheduled_at": bot_row.next_hygiene_run_at.isoformat() if bot_row.next_hygiene_run_at else None,
                "bot_id": bot_row.id,
                "bot_name": bot_name,
                "channel_id": None,
                "channel_name": None,
                "title": "Memory Hygiene",
                "interval_hours": interval,
            })

    # Sort merged list by scheduled_at
    items.sort(key=lambda x: x.get("scheduled_at") or "9999")

    # Apply limit
    items = items[:limit]

    return {"items": items}
