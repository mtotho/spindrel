"""Heartbeat worker: fires periodic prompts for channels on a schedule."""
import asyncio
import logging
import uuid
from datetime import datetime, time, timedelta, timezone

import zoneinfo

from sqlalchemy import select

from app.config import settings
from app.agent.context_profiles import trim_messages_to_recent_turns
from app.db.engine import async_session
from app.db.models import Channel, ChannelHeartbeat, HeartbeatRun, Task, ToolCall

logger = logging.getLogger(__name__)


SPATIAL_HEARTBEAT_PROMPT = """Spatial canvas turn:
- Use the [spatial canvas] context to understand your position, nearby channels/widgets/bots, radius, nearest-neighbor fallback, and any movement/tug/widget-management budgets.
- If inspect is available, inspect only nearby objects that could help organize the space or make the heartbeat useful.
- If spatial widget management is available, create or arrange widgets that would make this channel's workspace easier to understand at a glance.
- If movement or tugging is available, make small intentional moves only when they improve organization or visibility.
- If memory/file tools are available, keep current spatial memory in your bot workspace at memory/reference/spatial.md: useful landmarks, why widgets are placed where they are, active layout intent, and follow-ups for the next spatial turn. Keep it current-state focused.
- When spatial memory becomes historical or stale, archive it into your bot workspace's dated memory logs alongside your other memory notes instead of leaving old map state in memory/reference/spatial.md.
- Do not post a routine status update unless you changed something or found something worth sharing."""


def _trim_history_for_task(messages: list[dict], max_turns: int) -> list[dict]:
    """Trim conversation history to last *max_turns* non-heartbeat turn-pairs.

    Preserves all leading system messages (system prompt, persona, compaction
    summary).  From the remaining user/assistant/tool messages, keeps only the
    last *max_turns* user-message-initiated groups.  A "group" starts at each
    ``role: "user"`` message and includes everything until the next user message.

    When *max_turns* is 0, all non-system messages are stripped (no history).
    When *max_turns* is negative, no trimming is applied.
    """
    return trim_messages_to_recent_turns(messages, max_turns)


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


async def reset_stale_running_runs(db) -> int:
    """Recover HeartbeatRun rows stuck at ``status='running'`` from a crashed process.

    Mirrors :func:`app.services.outbox.reset_stale_in_flight`. The heartbeat
    worker marks a row ``status='running'`` before invoking the channel's
    turn pipeline and flips it to ``'done'`` / ``'error'`` in a follow-up
    transaction. If the process crashes between those two writes, the row
    is stranded forever — the scheduler's next fire will still write a
    fresh run, but the old row wedges the ``/admin/channels/*/heartbeat-runs``
    history view and muddies repetition-detection heuristics that look at
    recent runs.

    Called once at startup BEFORE the heartbeat worker launches; flips every
    stranded row to ``status='cancelled'`` with ``completed_at=now()`` so the
    row becomes a terminal history entry rather than a live-looking orphan.
    Returns the number of rows recovered.
    """
    from sqlalchemy import update

    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(HeartbeatRun)
        .where(HeartbeatRun.status == "running")
        .values(status="cancelled", completed_at=now, error="process crashed before completion")
    )
    await db.commit()
    return result.rowcount or 0


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


def _detect_repetition(
    recent_runs: list[HeartbeatRun],
    tool_calls_by_corr: dict[uuid.UUID, list[str]],
    threshold: float = 0.8,
) -> bool:
    """True if 3+ consecutive runs have highly similar output OR identical tool call patterns."""
    from difflib import SequenceMatcher

    results = [r.result for r in recent_runs if r.result]
    # Text repetition: most recent 3 results highly similar
    if len(results) >= 3:
        a, b, c = results[0][:500], results[1][:500], results[2][:500]
        # Scale threshold down for short responses — minor rephrasing of
        # short text yields lower ratios than for long text.
        avg_len = (len(a) + len(b) + len(c)) / 3
        if avg_len < 150:
            effective_threshold = threshold * 0.55
        elif avg_len < 300:
            effective_threshold = threshold * 0.7
        else:
            effective_threshold = threshold
        if (
            SequenceMatcher(None, a, b).ratio() > effective_threshold
            and SequenceMatcher(None, b, c).ratio() > effective_threshold
        ):
            return True

    # Action repetition: 3+ runs with identical tool call sequences
    corr_ids = [r.correlation_id for r in recent_runs if r.correlation_id]
    if len(corr_ids) >= 3:
        sequences = [tuple(tool_calls_by_corr.get(cid, [])) for cid in corr_ids[:3]]
        if all(s == sequences[0] for s in sequences[1:]) and sequences[0]:
            return True

    return False


def _build_repetition_preamble(recent_runs: list[HeartbeatRun]) -> str:
    """Build a forceful preamble showing full recent results so the LLM avoids repeating them."""
    lines = [
        "",
        "!!! REPETITION ALERT — CRITICAL !!!",
        "Your last several heartbeat outputs are nearly IDENTICAL.",
        "You MUST NOT produce similar text again. Read the previous results below",
        "and produce something SUBSTANTIALLY different, or say 'No updates.' if there",
        "is genuinely nothing new to report.",
        "",
    ]
    results_with_text = [r for r in recent_runs if r.result]
    for i, r in enumerate(results_with_text[:3]):
        lines.append(f"--- Previous result #{i + 1} ---")
        lines.append(r.result)
        lines.append("")
    lines.append("--- END PREVIOUS RESULTS ---")
    lines.append("Do NOT rephrase or echo the above. Provide NEW information or say 'No updates.'")
    return "\n".join(lines)


async def _fire_heartbeat_workflow(hb: ChannelHeartbeat, now: datetime) -> None:
    """Trigger a workflow run for a heartbeat and record the outcome."""
    from app.services.workflow_executor import trigger_workflow
    from app.db.models import WorkflowRun

    # Dedup: skip if there's already an active run for this workflow
    async with async_session() as db:
        active_run = (await db.execute(
            select(WorkflowRun.id)
            .where(WorkflowRun.workflow_id == hb.workflow_id)
            .where(WorkflowRun.status.in_(["running", "awaiting_approval"]))
            .limit(1)
        )).scalar_one_or_none()
        if active_run:
            logger.info(
                "Heartbeat %s: skipping workflow %s — active run %s already exists",
                hb.id, hb.workflow_id, active_run,
            )
            return

    async with async_session() as db:
        channel = await db.get(Channel, hb.channel_id)
        if not channel:
            logger.warning("Heartbeat %s: channel %s not found, skipping", hb.id, hb.channel_id)
            return

        # Record the heartbeat run
        run_record = HeartbeatRun(
            heartbeat_id=hb.id,
            run_at=now,
            status="running",
        )
        db.add(run_record)

        # Advance schedule
        heartbeat = await db.get(ChannelHeartbeat, hb.id)
        if heartbeat:
            effective = get_effective_interval(heartbeat.interval_minutes, heartbeat)
            heartbeat.last_run_at = now
            heartbeat.next_run_at = next_aligned_time(now, effective if effective > 0 else heartbeat.interval_minutes)
            heartbeat.updated_at = now

        await db.commit()
        await db.refresh(run_record)
        run_id = run_record.id
        bot_id = channel.bot_id
        channel_id = channel.id

        # Resolve dispatch for workflow
        dispatch_type = "none"
        dispatch_config = None
        if hb.dispatch_results and channel.dispatch_config:
            dispatch_type = channel.integration or "none"
            dispatch_config = dict(channel.dispatch_config)
            dispatch_config.pop("thread_ts", None)
            dispatch_config["reply_in_thread"] = False

    error_text = None
    workflow_run_id = None
    try:
        wf_run = await trigger_workflow(
            hb.workflow_id,
            {},
            bot_id=bot_id,
            channel_id=channel_id,
            triggered_by="heartbeat",
            dispatch_type=dispatch_type,
            dispatch_config=dispatch_config,
            session_mode=hb.workflow_session_mode,
        )
        workflow_run_id = str(wf_run.id)
        logger.info(
            "Heartbeat %s triggered workflow %s → run %s",
            hb.id, hb.workflow_id, workflow_run_id,
        )
    except Exception as exc:
        logger.exception("Heartbeat %s: workflow trigger failed", hb.id)
        error_text = str(exc)[:4000]

    # Update heartbeat run record — workflow runs complete asynchronously,
    # so we mark the heartbeat run as "complete" (trigger succeeded) or "failed".
    async with async_session() as db:
        run_rec = await db.get(HeartbeatRun, run_id)
        if run_rec:
            run_rec.completed_at = datetime.now(timezone.utc)
            run_rec.status = "complete" if error_text is None else "failed"
            run_rec.error = error_text
            run_rec.result = f"Triggered workflow run {workflow_run_id}" if workflow_run_id else None

        heartbeat = await db.get(ChannelHeartbeat, hb.id)
        if heartbeat:
            heartbeat.last_result = run_rec.result if run_rec else None
            heartbeat.last_error = error_text
            heartbeat.run_count = (heartbeat.run_count or 0) + 1
            heartbeat.updated_at = datetime.now(timezone.utc)

        await db.commit()


async def fire_heartbeat(hb: ChannelHeartbeat) -> None:
    """Execute a heartbeat directly (no Task row) and record history.

    If ``workflow_id`` is set, triggers the workflow instead of running the
    agent prompt.  The heartbeat run record still tracks the outcome.
    """
    now = datetime.now(timezone.utc)

    # --- Workflow mode: trigger workflow instead of agent prompt ---
    if hb.workflow_id:
        await _fire_heartbeat_workflow(hb, now)
        return

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
        if getattr(hb, "append_spatial_prompt", False):
            prompt = "\n\n".join(part for part in [prompt.strip(), SPATIAL_HEARTBEAT_PROMPT] if part)

        try:
            from app.services.games.heartbeat import build_active_games_block

            games_block = await build_active_games_block(
                db,
                channel_id=channel.id,
                bot_id=channel.bot_id,
            )
        except Exception:
            logger.exception("Heartbeat %s: failed to build active games block", hb.id)
            games_block = None
        if games_block:
            prompt = "\n\n".join(part for part in [prompt.strip(), games_block] if part)
            try:
                from app.tools.local.dashboard_tools import _INVOKE_WIDGET_ACTION_SCHEMA
                if injected_tools is None:
                    injected_tools = []
                if not any(
                    (t.get("function") or {}).get("name") == "invoke_widget_action"
                    for t in injected_tools
                ):
                    injected_tools.append(_INVOKE_WIDGET_ACTION_SCHEMA)
            except Exception:
                logger.exception("Heartbeat %s: failed to inject invoke_widget_action tool", hb.id)

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

        # Fetch last 5 completed runs (newest first)
        recent_runs_stmt = (
            select(HeartbeatRun)
            .where(
                HeartbeatRun.heartbeat_id == hb.id,
                HeartbeatRun.status == "complete",
            )
            .order_by(HeartbeatRun.completed_at.desc())
            .limit(5)
        )
        recent_runs = list((await db.execute(recent_runs_stmt)).scalars().all())
        last_run = recent_runs[0] if recent_runs else None
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

        # Recent run digest + repetition detection
        _rep_enabled = hb.repetition_detection if hb.repetition_detection is not None else settings.HEARTBEAT_REPETITION_DETECTION
        _repetition_detected = False
        tool_calls_by_corr: dict[uuid.UUID, list[str]] = {}
        if len(recent_runs) >= 2:
            # Fetch tool calls for recent runs (for digest display + repetition detection)
            if _rep_enabled:
                corr_ids = [r.correlation_id for r in recent_runs if r.correlation_id]
                if corr_ids:
                    tc_rows = (await db.execute(
                        select(ToolCall.correlation_id, ToolCall.tool_name)
                        .where(ToolCall.correlation_id.in_(corr_ids))
                        .order_by(ToolCall.created_at)
                    )).all()
                    for cid, name in tc_rows:
                        tool_calls_by_corr.setdefault(cid, []).append(name)

            digest_lines = ["", "Recent heartbeat outputs (newest first):"]
            for i, r in enumerate(recent_runs[:5]):
                if r.result:
                    first_line = r.result.strip().split("\n")[0][:120]
                    ago = int((now - r.completed_at).total_seconds() // 60) if r.completed_at else 0
                    tools = tool_calls_by_corr.get(r.correlation_id, [])
                    tool_str = f" [tools: {', '.join(tools)}]" if tools else ""
                    digest_lines.append(f"  #{i + 1} ({ago}m ago): {first_line}{tool_str}")
                elif r.error:
                    digest_lines.append(f"  #{i + 1}: [error]")
            metadata_lines.extend(digest_lines)

            if _rep_enabled and _detect_repetition(
                recent_runs, tool_calls_by_corr, settings.HEARTBEAT_REPETITION_THRESHOLD
            ):
                _repetition_detected = True
                logger.warning("Heartbeat %s: repetition detected across recent runs", hb.id)
                metadata_lines.append(_build_repetition_preamble(recent_runs))

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
        if model_override and not provider_id_override:
            try:
                from app.services.providers import resolve_provider_for_model

                provider_id_override = resolve_provider_for_model(model_override)
            except Exception:
                logger.debug("Heartbeat %s: failed to infer provider for model %s", hb.id, model_override, exc_info=True)
        _hb_fallback_models = hb.fallback_models or None
        from app.services.heartbeat_policy import normalize_heartbeat_execution_policy
        _hb_execution_policy = normalize_heartbeat_execution_policy(getattr(hb, "execution_policy", None))
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
                db,
                session_id,
                client_id or "heartbeat",
                bot_id,
                context_profile_name="heartbeat",
            )

        # Trim conversation history for small task models — full history
        # gives small models a conversational pattern to continue instead
        # of executing the task prompt.
        messages = _trim_history_for_task(messages, settings.HEARTBEAT_MAX_HISTORY_TURNS)

        messages_start = len(messages)
        _hb_timeout = resolve_heartbeat_timeout(hb)
        # Mark this run as a heartbeat so policy rules can target autonomous
        # contexts (e.g. require approval for file(overwrite) on heartbeats
        # even when interactive chat allows it).
        from app.agent.context import current_run_origin
        current_run_origin.set("heartbeat")
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
                skip_tool_policy=hb.skip_tool_approval,
                task_mode=True,
                context_profile_name="heartbeat",
                run_control_policy=_hb_execution_policy,
            ),
            timeout=_hb_timeout,
        )
        result_text = run_result.response

        # Persist turn
        from app.services.sessions import persist_turn
        _dispatched = hb.dispatch_results and _dispatch_mode != "optional"
        async with async_session() as db:
            await persist_turn(
                db, eff_session_id, bot, messages, messages_start,
                correlation_id=correlation_id, channel_id=channel_id,
                is_heartbeat=True,
                msg_metadata={"trigger": "heartbeat", "dispatched": _dispatched},
            )

        # Publish heartbeat result to the bus. Renderers consume TURN_ENDED
        # with kind_hint="heartbeat" and prepend the 💓 prefix themselves.
        if _dispatch_mode != "optional" and channel_id is not None:
            _proxy_task_id = uuid.uuid4()
            from app.domain.channel_events import ChannelEvent, ChannelEventKind
            from app.domain.payloads import TurnEndedPayload
            from app.services.channel_events import publish_typed

            publish_typed(
                channel_id,
                ChannelEvent(
                    channel_id=channel_id,
                    kind=ChannelEventKind.TURN_ENDED,
                    payload=TurnEndedPayload(
                        bot_id=bot_id,
                        turn_id=correlation_id,
                        result=result_text,
                        client_actions=list(run_result.client_actions or []),
                        task_id=str(_proxy_task_id),
                        kind_hint="heartbeat",
                    ),
                ),
            )

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
            run_rec.repetition_detected = _repetition_detected

        heartbeat = await db.get(ChannelHeartbeat, hb.id)
        if heartbeat:
            heartbeat.last_result = result_text
            heartbeat.last_error = error_text
            heartbeat.run_count = (heartbeat.run_count or 0) + 1
            heartbeat.updated_at = datetime.now(timezone.utc)

        await db.commit()


_heartbeat_semaphore = asyncio.Semaphore(3)
_inflight_heartbeats: set[uuid.UUID] = set()  # dedup: prevent re-queuing while running


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


async def _seconds_until_next_heartbeat() -> float:
    """Query the soonest next_run_at across all enabled heartbeats.

    Returns seconds to wait (capped at 30s).  Falls back to 30s if no
    heartbeats are scheduled or on any DB error.
    """
    try:
        from sqlalchemy import func as sa_func
        async with async_session() as db:
            soonest = (await db.execute(
                select(sa_func.min(ChannelHeartbeat.next_run_at))
                .where(
                    ChannelHeartbeat.enabled.is_(True),
                    ChannelHeartbeat.next_run_at.isnot(None),
                )
            )).scalar()
        if soonest is None:
            return 30.0
        delta = (soonest - datetime.now(timezone.utc)).total_seconds()
        # At least 1s to avoid busy-looping, at most 30s as safety cap
        return max(1.0, min(delta, 30.0))
    except Exception:
        return 30.0


async def heartbeat_worker() -> None:
    """Background worker loop: polls for due heartbeats, sleeps until the next one."""
    logger.info("Heartbeat worker started")
    while True:
        try:
            if settings.SYSTEM_PAUSED:
                await asyncio.sleep(30)
                continue
            due = await fetch_due_heartbeats()
            for hb in due:
                if hb.id in _inflight_heartbeats:
                    logger.debug("Heartbeat %s already in-flight, skipping", hb.id)
                    continue
                _inflight_heartbeats.add(hb.id)
                asyncio.create_task(_safe_fire_heartbeat(hb))
            # Sweep for stale tool approvals
            await _expire_stale_approvals()
        except Exception:
            logger.exception("heartbeat_worker poll error")
        sleep_for = await _seconds_until_next_heartbeat()
        await asyncio.sleep(sleep_for)


async def _safe_fire_heartbeat(hb: ChannelHeartbeat) -> None:
    """Wrapper to catch exceptions from fire_heartbeat in asyncio.create_task."""
    try:
        async with _heartbeat_semaphore:
            await fire_heartbeat(hb)
    except Exception:
        logger.exception("Failed to fire heartbeat %s", hb.id)
    finally:
        _inflight_heartbeats.discard(hb.id)


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
