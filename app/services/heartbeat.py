"""Heartbeat worker: fires periodic prompts for channels on a schedule."""
import asyncio
import logging
import uuid
from datetime import datetime, time, timedelta, timezone

import zoneinfo

from sqlalchemy import select

from app.config import settings
from app.db.engine import async_session
from app.db.models import Channel, ChannelHeartbeat, Task

logger = logging.getLogger(__name__)


def parse_quiet_hours(spec: str) -> tuple[time, time] | None:
    """Parse a quiet-hours spec like '23:00-07:00' into (start, end) times.

    Returns None if the spec is empty or invalid.
    """
    spec = spec.strip()
    if not spec:
        return None
    try:
        start_s, end_s = spec.split("-", 1)
        sh, sm = start_s.strip().split(":")
        eh, em = end_s.strip().split(":")
        return (time(int(sh), int(sm)), time(int(eh), int(em)))
    except (ValueError, TypeError):
        logger.warning("Invalid HEARTBEAT_QUIET_HOURS format: %r (expected HH:MM-HH:MM)", spec)
        return None


def is_quiet_hours(now_local: datetime, quiet_range: tuple[time, time]) -> bool:
    """Check whether *now_local* falls inside the quiet window.

    Handles ranges that wrap past midnight (e.g. 23:00-07:00).
    """
    start, end = quiet_range
    current = now_local.time()
    if start <= end:
        # Same-day range, e.g. 01:00-05:00
        return start <= current < end
    else:
        # Wraps midnight, e.g. 23:00-07:00
        return current >= start or current < end


def get_effective_interval(hb_interval: int) -> int:
    """Return the effective interval in minutes, respecting quiet hours."""
    quiet = parse_quiet_hours(settings.HEARTBEAT_QUIET_HOURS)
    if quiet is None:
        return hb_interval

    try:
        tz = zoneinfo.ZoneInfo(settings.TIMEZONE)
    except (KeyError, Exception):
        tz = zoneinfo.ZoneInfo("UTC")

    now_local = datetime.now(tz)
    if is_quiet_hours(now_local, quiet):
        quiet_interval = settings.HEARTBEAT_QUIET_INTERVAL_MINUTES
        if quiet_interval == 0:
            return 0  # signals "skip"
        return max(hb_interval, quiet_interval)
    return hb_interval


async def fetch_due_heartbeats() -> list[ChannelHeartbeat]:
    """Return heartbeats that are enabled and due (next_run_at <= now).

    Returns an empty list during quiet hours when the quiet interval is 0
    (heartbeats disabled).
    """
    quiet = parse_quiet_hours(settings.HEARTBEAT_QUIET_HOURS)
    if quiet is not None:
        try:
            tz = zoneinfo.ZoneInfo(settings.TIMEZONE)
        except (KeyError, Exception):
            tz = zoneinfo.ZoneInfo("UTC")
        if is_quiet_hours(datetime.now(tz), quiet) and settings.HEARTBEAT_QUIET_INTERVAL_MINUTES == 0:
            return []

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
            dispatch_type = channel.integration or "none"
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

        # Advance schedule — use effective interval (may be extended during quiet hours)
        heartbeat = await db.get(ChannelHeartbeat, hb.id)
        if heartbeat:
            effective = get_effective_interval(heartbeat.interval_minutes)
            heartbeat.last_run_at = now
            heartbeat.next_run_at = now + timedelta(minutes=effective if effective > 0 else heartbeat.interval_minutes)
            heartbeat.updated_at = now

        await db.commit()
        logger.info(
            "Heartbeat %s fired: task created for channel %s (bot=%s, next=%s)",
            hb.id, channel.id, channel.bot_id,
            heartbeat.next_run_at.strftime("%H:%M:%S") if heartbeat and heartbeat.next_run_at else "?",
        )


async def _run_elevation_analysis() -> None:
    """Run elevation log analysis and write results to file."""
    from app.services.elevation_analysis import analyze_elevation_log

    try:
        analysis = analyze_elevation_log()
        if analysis.get("total_turns", 0) == 0:
            logger.info("Elevation analysis: no data yet, skipping")
            return

        logger.info("Elevation analysis complete: %d turns, %d elevated",
                     analysis["total_turns"], analysis["elevated_turns"])
    except Exception:
        logger.exception("Elevation analysis failed")


async def heartbeat_worker() -> None:
    """Background worker loop: polls for due heartbeats every 30 seconds."""
    logger.info("Heartbeat worker started")
    _last_elevation_analysis: datetime | None = None
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

        # Run elevation analysis once per day
        now = datetime.now(timezone.utc)
        if settings.MODEL_ELEVATION_ENABLED and (
            _last_elevation_analysis is None
            or (now - _last_elevation_analysis) >= timedelta(hours=24)
        ):
            _last_elevation_analysis = now
            asyncio.create_task(_run_elevation_analysis())

        await asyncio.sleep(30)
