"""Heartbeat worker: fires periodic prompts for channels on a schedule."""
import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.engine import async_session
from app.db.models import Channel, ChannelHeartbeat, Task

logger = logging.getLogger(__name__)


async def fetch_due_heartbeats() -> list[ChannelHeartbeat]:
    """Return heartbeats that are enabled and due (next_run_at <= now)."""
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        stmt = (
            select(ChannelHeartbeat)
            .where(
                ChannelHeartbeat.enabled.is_(True),
                ChannelHeartbeat.next_run_at.isnot(None),
                ChannelHeartbeat.next_run_at <= now,
            )
            .limit(20)
        )
        return list((await db.execute(stmt)).scalars().all())


async def fire_heartbeat(hb: ChannelHeartbeat) -> None:
    """Create a Task for a due heartbeat and advance the schedule."""
    now = datetime.now(timezone.utc)

    async with async_session() as db:
        channel = await db.get(Channel, hb.channel_id)
        if not channel:
            logger.warning("Heartbeat %s: channel %s not found, skipping", hb.id, hb.channel_id)
            return

        dispatch_type = "none"
        dispatch_config = None
        if hb.dispatch_results and channel.dispatch_config:
            # Derive dispatch type from channel integration
            if channel.integration == "slack":
                dispatch_type = "slack"
            elif channel.integration:
                dispatch_type = channel.integration
            else:
                dispatch_type = "none"
            dispatch_config = dict(channel.dispatch_config)
            # Heartbeats should post as top-level channel messages, not thread replies
            dispatch_config.pop("thread_ts", None)
            dispatch_config["reply_in_thread"] = False

        callback_config = {
            "source": "heartbeat",
            "heartbeat_id": str(hb.id),
            "trigger_rag_loop": hb.trigger_response,
        }
        if hb.model:
            callback_config["model_override"] = hb.model
        if hb.model_provider_id:
            callback_config["model_provider_id_override"] = hb.model_provider_id

        # Auto-inject last heartbeat result as lightweight context
        prompt = hb.prompt
        last_task_stmt = (
            select(Task)
            .where(
                Task.channel_id == hb.channel_id,
                Task.status == "complete",
                Task.callback_config["source"].astext == "heartbeat",
            )
            .order_by(Task.completed_at.desc())
            .limit(1)
        )
        last_task = (await db.execute(last_task_stmt)).scalars().first()
        if last_task and last_task.result:
            ts = last_task.completed_at.strftime("%Y-%m-%d %H:%M UTC") if last_task.completed_at else "unknown"
            result_preview = last_task.result[:600]
            if len(last_task.result) > 600:
                result_preview += "\n… (use get_last_heartbeat tool for full result)"
            prompt = (
                f"[Previous heartbeat result ({ts})]\n{result_preview}\n\n---\n\n{prompt}"
            )

        task = Task(
            bot_id=channel.bot_id,
            client_id=channel.client_id,
            session_id=channel.active_session_id,
            channel_id=channel.id,
            prompt=prompt,
            status="pending",
            dispatch_type=dispatch_type,
            dispatch_config=dispatch_config,
            callback_config=callback_config,
            created_at=now,
        )
        db.add(task)

        # Advance schedule
        heartbeat = await db.get(ChannelHeartbeat, hb.id)
        if heartbeat:
            heartbeat.last_run_at = now
            heartbeat.next_run_at = now + timedelta(minutes=heartbeat.interval_minutes)
            heartbeat.updated_at = now

        await db.commit()
        logger.info(
            "Heartbeat %s fired: task created for channel %s (bot=%s, next=%s)",
            hb.id, channel.id, channel.bot_id,
            (now + timedelta(minutes=hb.interval_minutes)).strftime("%H:%M:%S"),
        )


async def heartbeat_worker() -> None:
    """Background worker loop: polls for due heartbeats every 30 seconds."""
    logger.info("Heartbeat worker started")
    while True:
        try:
            due = await fetch_due_heartbeats()
            for hb in due:
                try:
                    await fire_heartbeat(hb)
                except Exception:
                    logger.exception("Failed to fire heartbeat %s", hb.id)
        except Exception:
            logger.exception("heartbeat_worker poll error")
        await asyncio.sleep(30)
