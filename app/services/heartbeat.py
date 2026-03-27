"""Heartbeat worker: fires periodic prompts for channels on a schedule."""
import asyncio
import logging
import uuid
from datetime import datetime, time, timedelta, timezone

import zoneinfo

from sqlalchemy import select

from app.config import settings
from app.db.engine import async_session
from app.db.models import Channel, ChannelHeartbeat, HeartbeatRun, Task

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


def _resolve_quiet_range(hb: "ChannelHeartbeat | None" = None) -> tuple[time, time] | None:
    """Return the quiet-hours range for a heartbeat, falling back to global config."""
    if hb is not None and hb.quiet_start is not None and hb.quiet_end is not None:
        return (hb.quiet_start, hb.quiet_end)
    return parse_quiet_hours(settings.HEARTBEAT_QUIET_HOURS)


def _resolve_tz(hb: "ChannelHeartbeat | None" = None) -> zoneinfo.ZoneInfo:
    """Return the timezone for a heartbeat, falling back to global config."""
    tz_name = (hb.timezone if hb is not None and hb.timezone else None) or settings.TIMEZONE
    try:
        return zoneinfo.ZoneInfo(tz_name)
    except (KeyError, Exception):
        return zoneinfo.ZoneInfo("UTC")


def get_effective_interval(hb_interval: int, hb: "ChannelHeartbeat | None" = None) -> int:
    """Return the effective interval in minutes, respecting quiet hours.

    If *hb* is provided, uses its per-heartbeat quiet hours / timezone.
    Falls back to global HEARTBEAT_QUIET_HOURS / TIMEZONE settings.
    """
    quiet = _resolve_quiet_range(hb)
    if quiet is None:
        return hb_interval

    tz = _resolve_tz(hb)
    now_local = datetime.now(tz)
    if is_quiet_hours(now_local, quiet):
        quiet_interval = settings.HEARTBEAT_QUIET_INTERVAL_MINUTES
        if quiet_interval == 0:
            return 0  # signals "skip"
        return max(hb_interval, quiet_interval)
    return hb_interval


def _is_heartbeat_in_quiet_hours(hb: ChannelHeartbeat) -> bool:
    """Check if a specific heartbeat is currently in its quiet window."""
    quiet = _resolve_quiet_range(hb)
    if quiet is None:
        return False
    tz = _resolve_tz(hb)
    return is_quiet_hours(datetime.now(tz), quiet)


async def fetch_due_heartbeats() -> list[ChannelHeartbeat]:
    """Return heartbeats that are enabled and due (next_run_at <= now).

    Filters out heartbeats that are currently in their quiet window
    (per-heartbeat or global) when HEARTBEAT_QUIET_INTERVAL_MINUTES == 0.
    """
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
        candidates = list((await db.execute(stmt)).scalars().all())

    # Filter out heartbeats in their quiet window
    result = []
    for hb in candidates:
        if _is_heartbeat_in_quiet_hours(hb) and settings.HEARTBEAT_QUIET_INTERVAL_MINUTES == 0:
            logger.debug("Heartbeat %s skipped (quiet hours)", hb.id)
            continue
        result.append(hb)
    return result


async def fire_heartbeat(hb: ChannelHeartbeat) -> None:
    """Execute a heartbeat directly (no Task row) and record history."""
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

        # Resolve prompt from linked template (falls back to inline prompt)
        from app.services.prompt_resolution import resolve_prompt_template
        prompt = await resolve_prompt_template(
            str(hb.prompt_template_id) if hb.prompt_template_id else None,
            hb.prompt,
            db,
        )

        # Inject previous heartbeat result from heartbeat_runs history
        last_run_stmt = (
            select(HeartbeatRun)
            .where(
                HeartbeatRun.heartbeat_id == hb.id,
                HeartbeatRun.status == "complete",
            )
            .order_by(HeartbeatRun.completed_at.desc())
            .limit(1)
        )
        last_run = (await db.execute(last_run_stmt)).scalars().first()
        if last_run and last_run.result:
            ts = last_run.completed_at.strftime("%Y-%m-%d %H:%M UTC") if last_run.completed_at else "unknown"
            result_preview = last_run.result[:600]
            if len(last_run.result) > 600:
                result_preview += "\n… (use get_last_heartbeat tool for full result)"
            prompt = (
                f"[Previous heartbeat result ({ts})]\n{result_preview}\n\n---\n\n{prompt}"
            )

        # Create a heartbeat_run record
        run_record = HeartbeatRun(
            heartbeat_id=hb.id,
            run_at=now,
            status="running",
        )
        db.add(run_record)

        # Advance schedule — use effective interval (may be extended during quiet hours)
        heartbeat = await db.get(ChannelHeartbeat, hb.id)
        if heartbeat:
            effective = get_effective_interval(heartbeat.interval_minutes, heartbeat)
            heartbeat.last_run_at = now
            heartbeat.next_run_at = now + timedelta(minutes=effective if effective > 0 else heartbeat.interval_minutes)
            heartbeat.updated_at = now

        await db.commit()
        await db.refresh(run_record)

        # Capture what we need before leaving the DB session
        run_id = run_record.id
        bot_id = channel.bot_id
        client_id = channel.client_id
        session_id = channel.active_session_id
        channel_id = channel.id
        model_override = hb.model or None
        provider_id_override = hb.model_provider_id or None
        trigger_rag_loop = hb.trigger_response

    logger.info(
        "Heartbeat %s fired directly for channel %s (bot=%s, next=%s)",
        hb.id, channel_id, bot_id,
        heartbeat.next_run_at.strftime("%H:%M:%S") if heartbeat and heartbeat.next_run_at else "?",
    )

    # Run the agent directly (same path run_task uses)
    correlation_id = uuid.uuid4()
    result_text = None
    error_text = None
    try:
        from app.agent.loop import run
        from app.agent.bots import get_bot
        from app.agent.persona import get_persona
        from app.services.sessions import _effective_system_prompt, load_or_create

        bot = get_bot(bot_id)
        async with async_session() as db:
            eff_session_id, messages = await load_or_create(
                db, session_id, client_id or "heartbeat", bot_id
            )

        messages_start = len(messages)
        run_result = await run(
            messages, bot, prompt,
            session_id=eff_session_id,
            client_id=client_id or "heartbeat",
            correlation_id=correlation_id,
            dispatch_type=dispatch_type,
            dispatch_config=dispatch_config,
            channel_id=channel_id,
            model_override=model_override,
            provider_id_override=provider_id_override,
        )
        result_text = run_result.response

        # Persist turn
        from app.services.sessions import persist_turn
        async with async_session() as db:
            await persist_turn(db, eff_session_id, bot, messages, messages_start, correlation_id=correlation_id, channel_id=channel_id)

        # Dispatch result
        from app.agent import dispatchers
        dispatcher = dispatchers.get(dispatch_type)
        task_proxy = Task(
            id=uuid.uuid4(),
            bot_id=bot_id,
            dispatch_type=dispatch_type,
            dispatch_config=dispatch_config,
        )
        await dispatcher.deliver(task_proxy, result_text, client_actions=run_result.client_actions)

        # trigger_rag_loop: create a follow-up Task so the bot can react
        if trigger_rag_loop and result_text:
            _trl_task = Task(
                bot_id=bot_id,
                client_id=client_id,
                session_id=eff_session_id,
                prompt=f"[Your scheduled heartbeat just ran and posted to the channel. The output was:]\n\n{result_text}",
                status="pending",
                task_type="callback",
                dispatch_type=dispatch_type,
                dispatch_config=dict(dispatch_config or {}),
                callback_config={"trigger_rag_loop": False},
                created_at=datetime.now(timezone.utc),
            )
            async with async_session() as db:
                db.add(_trl_task)
                await db.commit()
            logger.info("Heartbeat %s: created trigger_rag_loop follow-up task", hb.id)

    except Exception as exc:
        logger.exception("Heartbeat %s execution failed", hb.id)
        error_text = str(exc)[:4000]

    # Update heartbeat_run record and heartbeat tracking columns
    async with async_session() as db:
        run_rec = await db.get(HeartbeatRun, run_id)
        if run_rec:
            run_rec.completed_at = datetime.now(timezone.utc)
            run_rec.result = result_text
            run_rec.error = error_text
            run_rec.correlation_id = correlation_id
            run_rec.status = "complete" if error_text is None else "failed"

        heartbeat = await db.get(ChannelHeartbeat, hb.id)
        if heartbeat:
            heartbeat.last_result = result_text
            heartbeat.last_error = error_text
            heartbeat.run_count = (heartbeat.run_count or 0) + 1
            heartbeat.updated_at = datetime.now(timezone.utc)

        await db.commit()


async def heartbeat_worker() -> None:
    """Background worker loop: polls for due heartbeats every 30 seconds."""
    logger.info("Heartbeat worker started")
    while True:
        try:
            if settings.SYSTEM_PAUSED:
                await asyncio.sleep(30)
                continue
            due = await fetch_due_heartbeats()
            for hb in due:
                asyncio.create_task(_safe_fire_heartbeat(hb))
        except Exception:
            logger.exception("heartbeat_worker poll error")
        await asyncio.sleep(30)


async def _safe_fire_heartbeat(hb: ChannelHeartbeat) -> None:
    """Wrapper to catch exceptions from fire_heartbeat in asyncio.create_task."""
    try:
        await fire_heartbeat(hb)
    except Exception:
        logger.exception("Failed to fire heartbeat %s", hb.id)
