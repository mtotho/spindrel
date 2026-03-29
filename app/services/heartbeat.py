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


def next_aligned_time(now: datetime, interval_minutes: int) -> datetime:
    """Compute the next clock-aligned run time.

    Snaps to even multiples of *interval_minutes* from midnight UTC so that
    heartbeats always fire on predictable clock boundaries (e.g. :00/:30 for
    30-min intervals) regardless of when the server started or last fired.
    """
    if not interval_minutes or interval_minutes <= 0:
        return now + timedelta(minutes=30)  # safety fallback
    minutes_since_midnight = now.hour * 60 + now.minute
    current_slot = minutes_since_midnight // interval_minutes
    next_slot_minutes = (current_slot + 1) * interval_minutes
    base = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return base + timedelta(minutes=next_slot_minutes)


def _truncate_at_sentence(text: str, max_chars: int) -> str:
    """Truncate *text* to at most *max_chars*, breaking at the last sentence
    boundary (. ! ? followed by whitespace or end-of-string) so we never cut
    mid-sentence.  Falls back to the full slice if no boundary is found.
    """
    if len(text) <= max_chars:
        return text
    window = text[:max_chars]
    # Walk backwards to find last sentence-ending punctuation
    for i in range(len(window) - 1, -1, -1):
        if window[i] in ".!?" and (i + 1 >= len(window) or window[i + 1] in " \n\t\r"):
            return window[: i + 1]
    # No sentence boundary found — fall back to hard cut
    return window.rstrip() + "…"


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


def resolve_heartbeat_timeout(hb: ChannelHeartbeat) -> int:
    """Resolve effective timeout: hb.max_run_seconds > global default."""
    if hb.max_run_seconds is not None:
        return hb.max_run_seconds
    return settings.TASK_MAX_RUN_SECONDS


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
        injected_tools: list[dict] | None = None
        _dispatch_mode = getattr(hb, "dispatch_mode", "always") or "always"
        if hb.dispatch_results and channel.dispatch_config:
            dispatch_type = channel.integration or "none"
            dispatch_config = dict(channel.dispatch_config)
            dispatch_config.pop("thread_ts", None)
            dispatch_config["reply_in_thread"] = False
            if _dispatch_mode == "optional":
                # LLM gets a tool to post if it wants; result NOT auto-dispatched
                from app.tools.local.heartbeat_tools import POST_HEARTBEAT_TO_CHANNEL_SCHEMA
                injected_tools = [POST_HEARTBEAT_TO_CHANNEL_SCHEMA]

        # Resolve prompt: workspace file > template > inline
        from app.services.prompt_resolution import resolve_prompt
        prompt = await resolve_prompt(
            workspace_id=str(hb.workspace_id) if hb.workspace_id else None,
            workspace_file_path=hb.workspace_file_path,
            template_id=str(hb.prompt_template_id) if hb.prompt_template_id else None,
            inline_prompt=hb.prompt or settings.HEARTBEAT_DEFAULT_PROMPT,
            db=db,
        )

        # --- Build heartbeat metadata header ---
        # NOTE: This is injected as a system_preamble right before the user message.
        # It MUST be forceful enough to override conversational mode — small models
        # will otherwise just acknowledge the heartbeat prompt instead of executing it.
        metadata_lines = [
            "=== SCHEDULED HEARTBEAT TASK ===",
            "IMPORTANT: This is NOT a conversation. This is an automated task you must EXECUTE NOW.",
            "The next message is your TASK PROMPT — follow its instructions and produce output.",
            "Do NOT acknowledge, confirm, or discuss the prompt. Just do the task.",
            "",
            f"Current time: {now.strftime('%Y-%m-%d %H:%M UTC')}",
            f"Channel: {channel.name}",
            f"Heartbeat interval: every {hb.interval_minutes} minutes",
            f"Run number: {(hb.run_count or 0) + 1}",
        ]

        # Last heartbeat info
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
        if last_run and last_run.completed_at:
            elapsed = now - last_run.completed_at
            elapsed_str = f"{int(elapsed.total_seconds() // 60)} minutes ago"
            metadata_lines.append(f"Last heartbeat: {last_run.completed_at.strftime('%Y-%m-%d %H:%M UTC')} ({elapsed_str})")
        else:
            metadata_lines.append("Last heartbeat: none (this is the first run)")

        # Activity since last heartbeat — count user and assistant messages
        _since = last_run.completed_at if (last_run and last_run.completed_at) else (now - timedelta(minutes=hb.interval_minutes))
        if channel.active_session_id:
            from app.db.models import Message as _Msg
            from sqlalchemy import func as _func
            _activity_stmt = (
                select(_Msg.role, _func.count(_Msg.id))
                .where(
                    _Msg.session_id == channel.active_session_id,
                    _Msg.created_at > _since,
                    _Msg.role.in_(["user", "assistant"]),
                )
                .group_by(_Msg.role)
            )
            _activity_rows = (await db.execute(_activity_stmt)).all()
            _counts = {role: count for role, count in _activity_rows}
            user_msgs = _counts.get("user", 0)
            assistant_msgs = _counts.get("assistant", 0)

            # Subtract heartbeat messages from counts
            _hb_msg_stmt = (
                select(_func.count(_Msg.id))
                .where(
                    _Msg.session_id == channel.active_session_id,
                    _Msg.created_at > _since,
                    _Msg.role == "user",
                    _Msg.metadata_["is_heartbeat"].astext == "true",
                )
            )
            _hb_count = (await db.execute(_hb_msg_stmt)).scalar() or 0
            user_msgs -= _hb_count

            if user_msgs > 0 or assistant_msgs > 0:
                metadata_lines.append(f"Activity since last heartbeat: {user_msgs} user message(s), {assistant_msgs} assistant response(s)")
            else:
                metadata_lines.append("Activity since last heartbeat: none (channel has been idle)")

            # Last user message timestamp
            if user_msgs > 0:
                _last_user_stmt = (
                    select(_Msg.created_at)
                    .where(
                        _Msg.session_id == channel.active_session_id,
                        _Msg.role == "user",
                        _Msg.metadata_["is_heartbeat"].astext != "true",
                    )
                    .order_by(_Msg.created_at.desc())
                    .limit(1)
                )
                _last_user_ts = (await db.execute(_last_user_stmt)).scalar()
                if _last_user_ts:
                    _user_elapsed = now - _last_user_ts
                    _mins = int(_user_elapsed.total_seconds() // 60)
                    if _mins > 60:
                        _user_ago = f"{_mins // 60}h {_mins % 60}m ago"
                    else:
                        _user_ago = f"{_mins}m ago"
                    metadata_lines.append(f"Last user message: {_user_ago}")

        # Previous result — truncated at sentence boundary to avoid mid-sentence cuts
        if last_run and last_run.result:
            _prev_max = hb.previous_result_max_chars if hb.previous_result_max_chars is not None else settings.HEARTBEAT_PREVIOUS_CONCLUSION_CHARS
            if _prev_max == 0:
                # 0 = no truncation, include full result
                metadata_lines.append(f"Previous heartbeat conclusion: {last_run.result}")
            else:
                conclusion = _truncate_at_sentence(last_run.result, _prev_max)
                metadata_lines.append(f"Previous heartbeat conclusion: {conclusion}")
                if len(last_run.result) > _prev_max:
                    metadata_lines.append("(Use get_last_heartbeat tool for full previous output if needed)")

        # Dispatch mode guidance
        if _dispatch_mode == "optional":
            metadata_lines.append(
                "OUTPUT MODE: Your text response will NOT be posted anywhere — it is internal only. "
                "To post to the channel, you MUST call the post_heartbeat_to_channel tool. "
                "Only call it if you have something worth sharing. If nothing noteworthy, "
                "just respond with your internal notes and nothing will be posted."
            )
        elif hb.dispatch_results:
            metadata_lines.append("Dispatch: Your response will be posted to the channel.")

        metadata_header = "\n".join(metadata_lines)
        # The metadata is injected as a system_preamble (not part of the user message).
        # This keeps RAG retrieval clean — skills, tools, and memory are retrieved based
        # on the actual heartbeat prompt, not the metadata noise.
        heartbeat_preamble = metadata_header

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
            heartbeat.next_run_at = next_aligned_time(now, effective if effective > 0 else heartbeat.interval_minutes)
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
        _hb_fallback_models = hb.fallback_models or None
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
        _hb_timeout = resolve_heartbeat_timeout(hb)
        run_result = await asyncio.wait_for(
            run(
                messages, bot, prompt,
                session_id=eff_session_id,
                client_id=client_id or "heartbeat",
                correlation_id=correlation_id,
                dispatch_type=dispatch_type,
                dispatch_config=dispatch_config,
                channel_id=channel_id,
                model_override=model_override,
                provider_id_override=provider_id_override,
                fallback_models=_hb_fallback_models,
                injected_tools=injected_tools,
                system_preamble=heartbeat_preamble,
            ),
            timeout=_hb_timeout,
        )
        result_text = run_result.response

        # Persist turn
        from app.services.sessions import persist_turn
        async with async_session() as db:
            await persist_turn(
                db, eff_session_id, bot, messages, messages_start,
                correlation_id=correlation_id, channel_id=channel_id,
                is_heartbeat=True,
                msg_metadata={"trigger": "heartbeat"},
            )

        # Dispatch result (skip for "optional" mode — the LLM used the tool if it wanted to post)
        if _dispatch_mode != "optional":
            from app.agent import dispatchers
            dispatcher = dispatchers.get(dispatch_type)
            task_proxy = Task(
                id=uuid.uuid4(),
                bot_id=bot_id,
                session_id=eff_session_id,
                client_id=client_id,
                dispatch_type=dispatch_type,
                dispatch_config=dispatch_config,
            )
            _dispatch_text = f"💓 _Heartbeat_\n{result_text}"
            await dispatcher.deliver(task_proxy, _dispatch_text, client_actions=run_result.client_actions)

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

    except asyncio.TimeoutError:
        logger.error("Heartbeat %s timed out after %ds", hb.id, _hb_timeout)
        error_text = f"Timed out after {_hb_timeout}s"

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


_heartbeat_semaphore = asyncio.Semaphore(3)


async def _expire_stale_approvals() -> None:
    """Mark pending tool approvals as expired if they've exceeded their timeout."""
    try:
        from app.db.models import ToolApproval
        now = datetime.now(timezone.utc)
        async with async_session() as db:
            stmt = (
                select(ToolApproval)
                .where(
                    ToolApproval.status == "pending",
                )
                .limit(100)
            )
            rows = (await db.execute(stmt)).scalars().all()
            expired_count = 0
            for row in rows:
                elapsed = (now - row.created_at).total_seconds()
                if elapsed > row.timeout_seconds:
                    row.status = "expired"
                    expired_count += 1
                    # Also resolve the in-memory Future if still waiting
                    from app.agent.approval_pending import cancel_approval
                    cancel_approval(str(row.id))
            if expired_count:
                await db.commit()
                logger.info("Expired %d stale tool approvals", expired_count)
    except Exception:
        logger.exception("Failed to expire stale approvals")


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
            # Sweep for stale tool approvals
            await _expire_stale_approvals()
        except Exception:
            logger.exception("heartbeat_worker poll error")
        await asyncio.sleep(30)


async def _safe_fire_heartbeat(hb: ChannelHeartbeat) -> None:
    """Wrapper to catch exceptions from fire_heartbeat in asyncio.create_task."""
    async with _heartbeat_semaphore:
        try:
            await fire_heartbeat(hb)
        except Exception:
            logger.exception("Failed to fire heartbeat %s", hb.id)


async def trigger_channel_heartbeat(
    channel_id: uuid.UUID,
    bot=None,
    *,
    correlation_id: uuid.UUID | None = None,
) -> None:
    """Fire all heartbeats for a channel immediately (used by compaction pre-trigger).

    If the channel has no heartbeats configured, this is a no-op.
    """
    async with async_session() as db:
        hbs = (await db.execute(
            select(ChannelHeartbeat)
            .where(ChannelHeartbeat.channel_id == channel_id, ChannelHeartbeat.enabled == True)
        )).scalars().all()
    if not hbs:
        logger.debug("trigger_channel_heartbeat: no active heartbeats for channel %s", channel_id)
        return
    for hb in hbs:
        try:
            await fire_heartbeat(hb)
        except Exception:
            logger.warning("trigger_channel_heartbeat: failed to fire heartbeat %s", hb.id, exc_info=True)
