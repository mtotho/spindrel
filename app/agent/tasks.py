"""Task worker: runs scheduled/deferred agent tasks and dispatches results."""
import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

import openai
from sqlalchemy import select

from app.agent.bots import get_bot
from app.config import settings
from app.db.engine import async_session
from app.db.models import Channel, Session, Task, TraceEvent
from app.services import session_locks

logger = logging.getLogger(__name__)


def _is_pipeline_child(task: Task) -> bool:
    """True when this task is the child execution of a pipeline agent step.

    Pipeline children funnel their output back into the parent pipeline via
    the step_executor callback — the channel's UI envelope renders the
    result from ``step_states``, not from a standalone assistant message.
    Every channel-visible emission (NEW_MESSAGE, TURN_STARTED, TURN_ENDED,
    outbox enqueue) is suppressed when this is True for inline pipelines.

    Sub-session pipelines are different: their child-turn events DO publish,
    but on the parent channel's bus, tagged with ``session_id=run_session_id``
    so the parent-channel UI can filter them out and the run-view modal can
    filter them in. See ``_resolve_sub_session_bus_channel``.
    """
    cb = task.callback_config or {}
    return bool(cb.get("pipeline_task_id"))


async def _resolve_sub_session_bus_channel(task: Task) -> uuid.UUID | None:
    """For a sub-session pipeline child task, return the parent channel's id.

    Used to route turn-lifecycle events onto the parent channel's bus so the
    run-view modal (subscribed via the parent channel's SSE stream) receives
    them. Returns None when the task's session doesn't resolve to a parent
    channel (standalone eval, cross-channel variants, etc.).
    """
    sid = getattr(task, "session_id", None)
    if sid is None:
        return None
    try:
        from app.services.sub_session_bus import resolve_bus_channel_id
        async with async_session() as db:
            return await resolve_bus_channel_id(db, sid)
    except Exception:
        logger.debug("sub-session bus resolve failed for task %s", task.id, exc_info=True)
        return None


async def _publish_turn_ended(
    task: Task,
    *,
    turn_id: uuid.UUID,
    result: str | None,
    error: str | None = None,
    client_actions: list | None = None,
    extra_metadata: dict | None = None,
    kind_hint: str | None = None,
) -> None:
    """Publish a TURN_ENDED event for a task.

    Tasks without a channel_id cannot reach a renderer; they are logged
    and dropped. Every production code path attaches a channel_id when
    creating a task — a missing one is a programming error.

    Pipeline agent-step children suppress this publish entirely — their
    output flows into the pipeline envelope via step_states, not as a
    distinct turn on the channel.
    """
    channel_id = getattr(task, "channel_id", None)
    is_pipeline_child = _is_pipeline_child(task)
    is_session_scoped = bool((getattr(task, "execution_config", None) or {}).get("session_scoped"))

    # Sub-session pipeline children: publish on the parent channel's bus so
    # the run-view modal receives the event. Tag the payload with the
    # child's session_id so parent-channel UI subscribers can filter the
    # event out — without this tag the child bot shows up as a phantom
    # streaming indicator in the parent channel's chat store.
    sub_session_id: uuid.UUID | None = None
    if is_pipeline_child and channel_id is None:
        channel_id = await _resolve_sub_session_bus_channel(task)
        sub_session_id = getattr(task, "session_id", None)
    elif is_session_scoped:
        sub_session_id = getattr(task, "session_id", None)
    # Inline pipeline children keep the old suppression (parent envelope
    # renders step status from step_states, not from a standalone turn).
    elif is_pipeline_child:
        return

    if channel_id is None:
        logger.warning("task %s has no channel_id, dropping TURN_ENDED publish", task.id)
        return

    from app.domain.channel_events import ChannelEvent, ChannelEventKind
    from app.domain.payloads import TurnEndedPayload
    from app.services.channel_events import publish_typed

    publish_typed(
        channel_id,
        ChannelEvent(
            channel_id=channel_id,
            kind=ChannelEventKind.TURN_ENDED,
            payload=TurnEndedPayload(
                bot_id=task.bot_id,
                turn_id=turn_id,
                result=result,
                error=error,
                client_actions=list(client_actions or []),
                extra_metadata=dict(extra_metadata or {}),
                task_id=str(task.id),
                kind_hint=kind_hint,
                session_id=sub_session_id,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Generic task completion hook
# ---------------------------------------------------------------------------

async def _fire_task_complete(task: Task, status: str) -> None:
    """Fire the generic after_task_complete hook. Any integration can listen.

    For workflow tasks, the workflow advancement callback is called DIRECTLY
    (not through the generic fire_hook broadcast) because fire_hook swallows
    exceptions — which would silently stall workflows.
    """
    logger.info("Firing after_task_complete hook for task %s (type=%s, status=%s)", task.id, task.task_type, status)

    # Direct workflow advancement — bypass fire_hook error swallowing
    cb = task.callback_config or {}
    if cb.get("workflow_run_id") and cb.get("workflow_step_index") is not None:
        try:
            from app.services.workflow_executor import on_step_task_completed
            await on_step_task_completed(
                cb["workflow_run_id"], cb["workflow_step_index"], status, task,
            )
        except Exception:
            logger.exception(
                "Workflow step completion failed for task %s (run=%s step=%s)",
                task.id, cb["workflow_run_id"], cb["workflow_step_index"],
            )

    # Pipeline step completion — resume the parent pipeline
    if cb.get("pipeline_task_id") and cb.get("pipeline_step_index") is not None:
        try:
            from app.services.step_executor import on_pipeline_step_completed
            await on_pipeline_step_completed(
                cb["pipeline_task_id"], cb["pipeline_step_index"], status, task,
            )
        except Exception:
            logger.exception(
                "Pipeline step completion failed for task %s (pipeline=%s step=%s)",
                task.id, cb["pipeline_task_id"], cb["pipeline_step_index"],
            )

    # Fire generic hook broadcast for non-workflow listeners (integrations, etc.)
    try:
        from app.agent.hooks import HookContext, fire_hook
        ctx = HookContext(
            bot_id=task.bot_id,
            channel_id=task.channel_id,
            extra={"task_id": str(task.id), "task_type": task.task_type, "status": status},
        )
        await fire_hook("after_task_complete", ctx, task=task, status=status)
    except Exception:
        logger.error("after_task_complete hook error", exc_info=True)


# ---------------------------------------------------------------------------
# Timeout trace event
# ---------------------------------------------------------------------------

async def _record_timeout_event(
    task: Task,
    correlation_id: uuid.UUID | None,
    error_msg: str,
) -> None:
    """Create a TraceEvent for a timed-out task so it appears in the logs UI."""
    if correlation_id is None:
        return
    try:
        async with async_session() as db:
            db.add(TraceEvent(
                correlation_id=correlation_id,
                session_id=task.session_id,
                bot_id=task.bot_id,
                client_id=task.client_id,
                event_type="task_timeout",
                event_name=f"Task timed out ({task.task_type})",
                data={"task_id": str(task.id), "error": error_msg, "task_type": task.task_type},
            ))
            await db.commit()
    except Exception:
        logger.debug("Failed to record timeout trace event for task %s", task.id, exc_info=True)


# ---------------------------------------------------------------------------
# Timeout resolution
# ---------------------------------------------------------------------------

def resolve_task_timeout(task: Task, channel: Channel | None = None) -> int:
    """Resolve effective timeout: task.max_run_seconds > channel.task_max_run_seconds > global default."""
    if task.max_run_seconds is not None:
        return task.max_run_seconds
    if channel is not None and channel.task_max_run_seconds is not None:
        return channel.task_max_run_seconds
    return settings.TASK_MAX_RUN_SECONDS


# ---------------------------------------------------------------------------
# Recurrence helpers
# ---------------------------------------------------------------------------

_RELATIVE_RE = re.compile(r"^\+(\d+)([smhdw])$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def _parse_recurrence(value: str) -> timedelta | None:
    """Parse a relative offset like +1h, +30m, +1d, +1w into a timedelta."""
    m = _RELATIVE_RE.match(value.strip())
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    return timedelta(seconds=n * _UNIT_SECONDS[unit])


def validate_recurrence(value: str | None) -> str | None:
    """Validate a recurrence string. Returns the value if valid, raises ValueError if not."""
    if not value:
        return value
    if _parse_recurrence(value) is None:
        raise ValueError(
            f"Invalid recurrence {value!r}. Use format +N[s|m|h|d|w] (e.g. +30m, +1h, +1d, +1w)."
        )
    return value


async def _spawn_from_schedule(schedule_id: uuid.UUID) -> None:
    """Spawn a concrete one-off task from an active schedule template.

    Atomically: create the concrete task, advance schedule.scheduled_at, bump run_count.
    """
    async with async_session() as db:
        schedule = await db.get(Task, schedule_id)
        if schedule is None or schedule.status != "active" or not schedule.recurrence:
            return

        interval = _parse_recurrence(schedule.recurrence)
        if not interval:
            logger.warning("Schedule %s has invalid recurrence %r — skipping", schedule.id, schedule.recurrence)
            return

        # Resolve latest content from linked template or workspace file (if any)
        from app.services.prompt_resolution import resolve_prompt
        prompt = await resolve_prompt(
            workspace_id=str(schedule.workspace_id) if schedule.workspace_id else None,
            workspace_file_path=schedule.workspace_file_path,
            template_id=str(schedule.prompt_template_id) if schedule.prompt_template_id else None,
            inline_prompt=schedule.prompt,
            db=db,
        )

        # Create concrete execution task
        concrete = Task(
            bot_id=schedule.bot_id,
            client_id=schedule.client_id,
            session_id=schedule.session_id,
            channel_id=schedule.channel_id,
            prompt=prompt,
            title=schedule.title,
            prompt_template_id=schedule.prompt_template_id,
            workspace_file_path=schedule.workspace_file_path,
            workspace_id=schedule.workspace_id,
            scheduled_at=schedule.scheduled_at,
            status="pending",
            task_type=schedule.task_type,
            dispatch_type=schedule.dispatch_type,
            dispatch_config=dict(schedule.dispatch_config) if schedule.dispatch_config else None,
            callback_config=dict(schedule.callback_config) if schedule.callback_config else None,
            execution_config=dict(schedule.execution_config) if schedule.execution_config else None,
            recurrence=None,  # concrete task, not a schedule
            parent_task_id=schedule.id,
            max_run_seconds=schedule.max_run_seconds,
            workflow_id=schedule.workflow_id,
            workflow_session_mode=schedule.workflow_session_mode,
            created_at=datetime.now(timezone.utc),
        )
        db.add(concrete)

        # Advance schedule to next occurrence
        base = schedule.scheduled_at or datetime.now(timezone.utc)
        schedule.scheduled_at = base + interval
        schedule.run_count = (schedule.run_count or 0) + 1

        await db.commit()
        logger.info(
            "Schedule %s spawned concrete task %s (run #%d), next at %s",
            schedule.id, concrete.id, schedule.run_count,
            schedule.scheduled_at.strftime("%Y-%m-%d %H:%M UTC"),
        )


async def spawn_due_schedules() -> None:
    """Find active schedule templates that are due and spawn concrete tasks."""
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        stmt = (
            select(Task.id)
            .where(Task.status == "active")
            .where(Task.recurrence.isnot(None))
            .where(Task.scheduled_at <= now)
            .limit(50)
        )
        schedule_ids = list((await db.execute(stmt)).scalars().all())

    for sid in schedule_ids:
        try:
            await _spawn_from_schedule(sid)
        except Exception:
            logger.exception("Failed to spawn from schedule %s", sid)


# ---------------------------------------------------------------------------
# Subscription-based schedules (per-channel cron on a shared pipeline)
# ---------------------------------------------------------------------------

async def _fire_subscription(subscription_id: uuid.UUID) -> None:
    """Fire a single subscription: spawn a child run, advance next_fire_at."""
    from app.db.models import ChannelPipelineSubscription
    from app.services.cron_utils import next_fire_at as _cron_next
    from app.services.task_ops import spawn_child_run

    async with async_session() as db:
        sub = await db.get(ChannelPipelineSubscription, subscription_id)
        if sub is None or not sub.enabled or not sub.schedule:
            return
        now = datetime.now(timezone.utc)
        # Advance + persist first so failures don't cause re-fire storms.
        try:
            sub.next_fire_at = _cron_next(sub.schedule, now)
        except Exception:
            logger.exception(
                "Invalid cron on subscription %s (%r) — disabling next_fire_at",
                sub.id, sub.schedule,
            )
            sub.next_fire_at = None
        sub.last_fired_at = now
        sub.updated_at = now
        task_id = sub.task_id
        channel_id = sub.channel_id
        params = (sub.schedule_config or {}).get("params") or {}
        await db.commit()

        try:
            await spawn_child_run(
                task_id, db,
                params=params,
                channel_id=channel_id,
            )
            await db.commit()
        except Exception:
            logger.exception(
                "Failed to spawn run for subscription %s (task=%s, channel=%s)",
                subscription_id, task_id, channel_id,
            )


async def spawn_due_subscriptions() -> None:
    """Find enabled subscriptions whose cron schedule is due and spawn runs."""
    from app.db.models import ChannelPipelineSubscription

    now = datetime.now(timezone.utc)
    async with async_session() as db:
        stmt = (
            select(ChannelPipelineSubscription.id)
            .where(ChannelPipelineSubscription.enabled.is_(True))
            .where(ChannelPipelineSubscription.schedule.isnot(None))
            .where(ChannelPipelineSubscription.next_fire_at.isnot(None))
            .where(ChannelPipelineSubscription.next_fire_at <= now)
            .limit(50)
        )
        sub_ids = list((await db.execute(stmt)).scalars().all())

    for sid in sub_ids:
        try:
            await _fire_subscription(sid)
        except Exception:
            logger.exception("Failed to fire subscription %s", sid)


# ---------------------------------------------------------------------------
# Event triggers
# ---------------------------------------------------------------------------

def _matches_event_filter(filter_config: dict, event_data: dict) -> bool:
    """Check if event_data matches all key-value pairs in filter_config."""
    for key, expected in filter_config.items():
        actual = event_data.get(key)
        if actual is None or str(actual) != str(expected):
            return False
    return True


async def _spawn_from_event_trigger(template_id: uuid.UUID, event_data: dict) -> None:
    """Spawn a concrete task from an event-triggered template."""
    async with async_session() as db:
        template = await db.get(Task, template_id)
        if template is None or template.status != "active":
            return

        from app.services.prompt_resolution import resolve_prompt
        prompt = await resolve_prompt(
            workspace_id=str(template.workspace_id) if template.workspace_id else None,
            workspace_file_path=template.workspace_file_path,
            template_id=str(template.prompt_template_id) if template.prompt_template_id else None,
            inline_prompt=template.prompt,
            db=db,
        )

        # Inject event data into execution_config so the agent can reference it
        ec = dict(template.execution_config) if template.execution_config else {}
        ec["event_data"] = event_data

        concrete = Task(
            bot_id=template.bot_id,
            client_id=template.client_id,
            session_id=template.session_id,
            channel_id=template.channel_id,
            prompt=prompt,
            title=template.title,
            prompt_template_id=template.prompt_template_id,
            workspace_file_path=template.workspace_file_path,
            workspace_id=template.workspace_id,
            scheduled_at=datetime.now(timezone.utc),
            status="pending",
            task_type=template.task_type,
            dispatch_type=template.dispatch_type,
            dispatch_config=dict(template.dispatch_config) if template.dispatch_config else None,
            callback_config=dict(template.callback_config) if template.callback_config else None,
            execution_config=ec,
            recurrence=None,
            parent_task_id=template.id,
            max_run_seconds=template.max_run_seconds,
            workflow_id=template.workflow_id,
            workflow_session_mode=template.workflow_session_mode,
            created_at=datetime.now(timezone.utc),
        )
        db.add(concrete)
        template.run_count = (template.run_count or 0) + 1
        await db.commit()
        logger.info("Event trigger %s spawned concrete task %s", template.id, concrete.id)


async def fire_event_triggers(event_source: str, event_type: str, event_data: dict) -> int:
    """Find active event-triggered tasks matching this event and spawn instances."""
    async with async_session() as db:
        stmt = (
            select(Task)
            .where(Task.status == "active")
            .where(Task.trigger_config["type"].as_string() == "event")
            .where(Task.trigger_config["event_source"].as_string() == event_source)
            .where(Task.trigger_config["event_type"].as_string() == event_type)
            .limit(50)
        )
        tasks = (await db.execute(stmt)).scalars().all()

    spawned = 0
    for task in tasks:
        tc = task.trigger_config or {}
        event_filter = tc.get("event_filter") or {}
        if not _matches_event_filter(event_filter, event_data):
            continue
        try:
            await _spawn_from_event_trigger(task.id, event_data)
            spawned += 1
        except Exception:
            logger.exception("Failed to spawn from event trigger %s", task.id)
    return spawned


# ---------------------------------------------------------------------------
# Runner helpers
# ---------------------------------------------------------------------------

def _parse_uuid_opt(cfg: dict, key: str) -> uuid.UUID | None:
    """Parse an optional UUID from a config dict."""
    raw = cfg.get(key)
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None

async def run_exec_task(task: Task) -> None:
    """Execute a raw exec task: run command in sandbox, store result, dispatch."""
    logger.info("Running exec task %s", task.id)
    now = datetime.now(timezone.utc)
    _turn_id = uuid.uuid4()

    async with async_session() as db:
        t = await db.get(Task, task.id)
        if t is None:
            return
        t.status = "running"
        t.run_at = now
        await db.commit()

    # Read execution params from execution_config (new) with fallback to callback_config (legacy)
    ecfg = task.execution_config or task.callback_config or {}
    cfg = task.callback_config or {}
    command = ecfg.get("command", "")
    args = ecfg.get("args", [])
    working_directory = ecfg.get("working_directory")
    stream_to = ecfg.get("stream_to")
    output_dispatch_type = ecfg.get("output_dispatch_type", task.dispatch_type or "none")
    output_dispatch_config = ecfg.get("output_dispatch_config") or dict(task.dispatch_config or {})
    source_correlation_id = _parse_uuid_opt(ecfg, "source_correlation_id")
    sandbox_instance_id = _parse_uuid_opt(ecfg, "sandbox_instance_id")

    try:
        from app.agent.bots import get_bot
        from app.agent.recording import schedule_exec_completion_record
        from app.services.sandbox import sandbox_service
        from app.tools.local.exec_tool import build_exec_script

        bot = get_bot(task.bot_id)
        script = build_exec_script(command, args, working_directory, stream_to)

        # Resolve timeout (initialized before try so except handlers can reference it)
        _exec_timeout = resolve_task_timeout(task)  # type: int

        async def _do_exec():
            if sandbox_instance_id is not None:
                from app.config import settings as _settings
                if not _settings.DOCKER_SANDBOX_ENABLED:
                    raise RuntimeError("DOCKER_SANDBOX_ENABLED is false")
                allowed = bot.docker_sandbox_profiles or None
                instance = await sandbox_service.get_instance_for_bot(
                    sandbox_instance_id, bot.id, allowed_profiles=allowed
                )
                if instance is None:
                    raise RuntimeError("Sandbox instance not found or not allowed")
                return await sandbox_service.exec(instance, script)
            elif bot.workspace.enabled or bot.shared_workspace_id:
                from app.services.workspace import workspace_service
                ws_result = await workspace_service.exec(bot.id, script, bot.workspace, working_directory or "", bot=bot)
                from dataclasses import dataclass as _dc
                @_dc
                class _R:
                    stdout: str; stderr: str; exit_code: int; truncated: bool; duration_ms: int
                return _R(stdout=ws_result.stdout, stderr=ws_result.stderr,
                            exit_code=ws_result.exit_code, truncated=ws_result.truncated,
                            duration_ms=ws_result.duration_ms)
            elif bot.bot_sandbox.enabled:
                return await sandbox_service.exec_bot_local(bot.id, script, bot.bot_sandbox)
            else:
                raise RuntimeError("No sandbox available for exec task")

        result = await asyncio.wait_for(_do_exec(), timeout=_exec_timeout)

        parts = []
        if result.stdout:
            parts.append(result.stdout)
        if result.stderr:
            parts.append(f"[stderr]\n{result.stderr}")
        if result.truncated:
            parts.append("[output truncated]")
        parts.append(f"[exit {result.exit_code}, {result.duration_ms}ms]")
        result_text = "\n".join(parts)

        async with async_session() as db:
            t = await db.get(Task, task.id)
            if t:
                t.status = "complete"
                t.result = result_text
                t.completed_at = datetime.now(timezone.utc)
                await db.commit()

        await _fire_task_complete(task, "complete")

        _err: str | None = None
        if result.exit_code != 0:
            _err = ((result.stderr or "").strip()[:500] or f"non-zero exit {result.exit_code}")
        schedule_exec_completion_record(
            command=command,
            task_id=task.id,
            session_id=task.session_id,
            client_id=task.client_id,
            bot_id=task.bot_id,
            correlation_id=source_correlation_id,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
            truncated=result.truncated,
            result_text=result_text,
            error=_err,
        )
        await asyncio.sleep(0)

        output_task = Task(
            id=task.id,
            bot_id=task.bot_id,
            channel_id=task.channel_id,
            dispatch_type=output_dispatch_type,
            dispatch_config=output_dispatch_config,
        )
        await _publish_turn_ended(output_task, turn_id=_turn_id, result=result_text)

        if cfg.get("notify_parent") and result_text:
            _parent_bot_id = cfg.get("parent_bot_id")
            _parent_session_str = cfg.get("parent_session_id")
            _parent_client_id = cfg.get("parent_client_id")
            if _parent_bot_id and _parent_session_str:
                try:
                    _parent_session_id = uuid.UUID(_parent_session_str)
                    _cb_task = Task(
                        bot_id=_parent_bot_id,
                        client_id=_parent_client_id,
                        session_id=_parent_session_id,
                        channel_id=task.channel_id,
                        prompt=f"[Exec task completed: {command}]\n\n{result_text}",
                        status="pending",
                        task_type="callback",
                        dispatch_type=output_dispatch_type,
                        dispatch_config=dict(output_dispatch_config),
                        parent_task_id=task.id,
                        created_at=datetime.now(timezone.utc),
                    )
                    async with async_session() as db:
                        db.add(_cb_task)
                        await db.commit()
                        await db.refresh(_cb_task)
                    logger.info(
                        "Exec task %s: created parent callback task %s (bot=%s, session=%s)",
                        task.id, _cb_task.id, _parent_bot_id, _parent_session_id,
                    )
                except Exception:
                    logger.exception("Failed to create parent callback task for exec task %s", task.id)

    except asyncio.TimeoutError:
        logger.error("Exec task %s timed out after %ds", task.id, _exec_timeout)
        _timeout_msg = f"Timed out after {_exec_timeout}s"
        await _mark_task_failed_in_db(task.id, error=_timeout_msg)
        await _fire_task_complete(task, "failed")
        output_task = Task(
            id=task.id, bot_id=task.bot_id, channel_id=task.channel_id,
            dispatch_type=output_dispatch_type, dispatch_config=output_dispatch_config,
        )
        await _publish_turn_ended_safe(
            output_task,
            turn_id=_turn_id,
            error=_timeout_msg,
            log_label="timeout error for exec task",
        )

    except Exception as exc:
        logger.exception("Exec task %s failed", task.id)
        await _mark_task_failed_in_db(task.id, error=str(exc)[:4000])
        await _fire_task_complete(task, "failed")
        try:
            from app.agent.recording import schedule_exec_completion_record

            schedule_exec_completion_record(
                command=command or "unknown",
                task_id=task.id,
                session_id=task.session_id,
                client_id=task.client_id,
                bot_id=task.bot_id,
                correlation_id=source_correlation_id,
                exit_code=-1,
                duration_ms=0,
                truncated=False,
                result_text="",
                error=str(exc)[:4000],
            )
            await asyncio.sleep(0)
        except Exception:
            logger.exception("Failed to schedule exec failure record for task %s", task.id)


async def _run_workflow_trigger_task(task: Task) -> None:
    """Trigger a workflow run from a scheduled task. Mirrors heartbeat's _fire_heartbeat_workflow."""
    from app.db.models import WorkflowRun
    from app.services.workflow_executor import trigger_workflow

    # Dedup: skip if there's already an active run for this workflow
    async with async_session() as db:
        active_run = (await db.execute(
            select(WorkflowRun.id)
            .where(WorkflowRun.workflow_id == task.workflow_id)
            .where(WorkflowRun.status.in_(["running", "awaiting_approval"]))
            .limit(1)
        )).scalar_one_or_none()
        if active_run:
            logger.info(
                "Task %s: skipping workflow %s — active run %s already exists",
                task.id, task.workflow_id, active_run,
            )
            async with async_session() as db2:
                t = await db2.get(Task, task.id)
                if t:
                    t.status = "complete"
                    t.result = f"Skipped: active workflow run {active_run} already exists"
                    t.completed_at = datetime.now(timezone.utc)
                    await db2.commit()
            await _fire_task_complete(task, "complete")
            return

    now = datetime.now(timezone.utc)
    async with async_session() as db:
        t = await db.get(Task, task.id)
        if t is None:
            return
        t.status = "running"
        t.run_at = now
        await db.commit()

    try:
        run = await trigger_workflow(
            task.workflow_id,
            {},
            bot_id=task.bot_id,
            channel_id=task.channel_id,
            triggered_by="task",
            dispatch_type=task.dispatch_type if task.dispatch_type != "none" else None,
            dispatch_config=dict(task.dispatch_config) if task.dispatch_config else None,
            session_mode=task.workflow_session_mode,
        )
        async with async_session() as db:
            t = await db.get(Task, task.id)
            if t:
                t.status = "complete"
                t.result = f"Triggered workflow run {run.id}"
                t.completed_at = datetime.now(timezone.utc)
                await db.commit()
        await _fire_task_complete(task, "complete")
    except Exception as exc:
        logger.exception("Workflow trigger task %s failed", task.id)
        await _mark_task_failed_in_db(task.id, error=str(exc)[:4000])
        await _fire_task_complete(task, "failed")


# ===== Cluster 9 task-failure + dispatch helpers =====


async def _mark_task_failed_in_db(
    task_id: uuid.UUID,
    *,
    error: str,
    completed_at: datetime | None = None,
) -> None:
    """Persist `status='failed'` + truncated error + completed_at on the Task row.

    Single source of truth for the 6-of-8 mark-failed sites that share the same
    fetch → set → commit pattern. The two non-conforming sites (`run_task`'s
    rate-limit retry branch which mutates the row in-place, and
    `recover_stuck_tasks` which guards on `status == 'running'`) keep their
    inline writes.
    """
    async with async_session() as db:
        t = await db.get(Task, task_id)
        if t:
            t.status = "failed"
            t.error = error
            t.completed_at = completed_at or datetime.now(timezone.utc)
            await db.commit()


async def _publish_turn_ended_safe(
    target_task: Task,
    *,
    turn_id: uuid.UUID,
    error: str,
    result: dict | None = None,
    log_label: str = "task",
) -> None:
    """Best-effort `_publish_turn_ended` — swallows exceptions and logs a warning.

    Wraps the try/except boilerplate that wraps every TURN_ENDED publish in the
    failure paths. The `log_label` (e.g. "task", "exec task", "rate limit error")
    flows into the warning so log lines stay distinguishable.
    """
    try:
        await _publish_turn_ended(target_task, turn_id=turn_id, result=result, error=error)
    except Exception:
        logger.warning("Failed to publish %s for task %s", log_label, target_task.id)


async def _dispatch_to_specialized_runner(task: Task) -> bool:
    """Route task_type-specific tasks to their dedicated runners.

    Returns True if the task was dispatched (caller should return).
    Returns False to indicate the caller should run the general agent path.
    Handles: `exec`, `pipeline` (with scheduling-session lock-defer), workflow
    trigger, and `claude_code` (including the missing-integration failure path).
    """
    if task.task_type == "exec" or (task.task_type == "agent" and task.dispatch_type == "exec"):
        await run_exec_task(task)
        return True
    if task.task_type == "pipeline":
        # Respect the scheduling session's lock so the pipeline (and its
        # anchor envelope) fires AFTER the bot's "pipeline is running"
        # reply is persisted — otherwise the envelope sorts into the
        # chat before the bot's text, which reads backwards.
        # Pipeline agent-step *children* skip this check (they're spawned
        # mid-pipeline and need the same session) — see _skip_lock below.
        _lock_held_elsewhere = (
            task.session_id is not None
            and session_locks.is_active(task.session_id)
        )
        if _lock_held_elsewhere:
            async with async_session() as db:
                t = await db.get(Task, task.id)
                if t:
                    t.status = "pending"
                    t.run_at = None
                    t.scheduled_at = datetime.now(timezone.utc) + timedelta(seconds=3)
                    await db.commit()
            logger.info("Pipeline %s deferred 3s: scheduling session %s busy", task.id, task.session_id)
            return True
        from app.services.step_executor import run_task_pipeline
        await run_task_pipeline(task)
        return True
    if task.workflow_id:
        await _run_workflow_trigger_task(task)
        return True
    if task.task_type == "claude_code":
        try:
            from integrations.claude_code.executor import run_claude_code_task
        except ImportError:
            logger.error("claude_code integration not installed; failing task %s", task.id)
            await _mark_task_failed_in_db(task.id, error="claude_code integration not installed")
            return True
        await run_claude_code_task(task)
        return True
    return False


async def run_task(task: Task) -> None:
    """Execute a single task: run the agent, store result, dispatch."""
    if await _dispatch_to_specialized_runner(task):
        return

    # Resolve the channel's current active session so tasks always run in the
    # live session, not a stale session_id captured at task-creation time.
    # (Heartbeats already do this in fire_heartbeat; tasks created by bots via
    # create_task or _schedule_next_occurrence can hold an outdated session_id
    # after a channel session reset.)
    # Skip for workflow tasks — they use dedicated per-step sessions to avoid
    # polluting chat and to prevent session lock contention.
    # Skip for delegation tasks — they preserve their original parent session_id
    # so cross-bot detection can correctly identify the parent and create a
    # proper child session with the right linkage.
    _task_channel: Channel | None = None
    if task.channel_id and task.task_type not in ("workflow", "delegation", "eval"):
        async with async_session() as db:
            channel = await db.get(Channel, task.channel_id)
            if channel:
                _task_channel = channel
                if channel.active_session_id and task.session_id != channel.active_session_id:
                    logger.info(
                        "Task %s: resolving stale session %s → channel active session %s",
                        task.id, task.session_id, channel.active_session_id,
                    )
                    task.session_id = channel.active_session_id

    # Respect the per-session active lock.  If a streaming HTTP request is still
    # running for this session, defer this task by 10 seconds rather than running
    # a parallel agent loop.
    # Skip lock for delegation tasks: they create their own child session (cross-bot)
    # or explicitly need to run alongside the parent who is waiting for their result.
    _skip_lock = task.task_type == "delegation"
    _lock_acquired = False
    if task.session_id and not _skip_lock:
        if session_locks.acquire(task.session_id):
            _lock_acquired = True
        else:
            async with async_session() as db:
                t = await db.get(Task, task.id)
                if t:
                    t.status = "pending"
                    t.run_at = None
                    t.scheduled_at = datetime.now(timezone.utc) + timedelta(seconds=10)
                    await db.commit()
            logger.info("Task %s deferred 10s: session %s is busy", task.id, task.session_id)
            return

    logger.info("Running task %s (bot=%s)", task.id, task.bot_id)

    # Task is already marked running by fetch_due_tasks (atomic fetch-and-mark).
    # Verify it still exists before proceeding.
    async with async_session() as db:
        t = await db.get(Task, task.id)
        if t is None:
            if _lock_acquired:
                session_locks.release(task.session_id)
            return

    # Per-task turn correlation. Threaded through TURN_STARTED and every
    # TURN_ENDED publish (success, timeout, rate-limit, exception) so
    # subscribers can demultiplex parallel turns by turn_id.
    _turn_id = uuid.uuid4()

    # Tell the bus a queued task is starting; renderers (Slack/Discord)
    # post a "thinking…" placeholder when this fires. Suppressed for
    # pipeline agent-step children — the parent pipeline's envelope
    # shows the step's progress instead.
    _suppress_channel = _is_pipeline_child(task)
    _session_scoped_task = bool((task.execution_config or {}).get("session_scoped"))
    # For sub-session pipeline children, route TURN_STARTED to the parent
    # channel's bus so the run-view modal sees the event. Inline pipeline
    # children stay suppressed (the parent envelope renders step status
    # from step_states).
    _publish_channel_id: uuid.UUID | None = task.channel_id
    # When a sub-session pipeline child publishes on the parent channel's
    # bus, tag the payload with the child's session_id so parent-channel
    # UI subscribers can filter the event out (otherwise the child's bot
    # would show up as a phantom streaming indicator in the parent channel).
    _publish_session_id: uuid.UUID | None = None
    if _session_scoped_task:
        _publish_session_id = getattr(task, "session_id", None)
    if _suppress_channel and task.channel_id is None:
        _publish_channel_id = await _resolve_sub_session_bus_channel(task)
        _suppress_channel = _publish_channel_id is None
        if not _suppress_channel:
            _publish_session_id = getattr(task, "session_id", None)
    if _publish_channel_id is not None and not _suppress_channel:
        try:
            from app.domain.channel_events import ChannelEvent, ChannelEventKind
            from app.domain.payloads import TurnStartedPayload
            from app.services.channel_events import publish_typed

            publish_typed(
                _publish_channel_id,
                ChannelEvent(
                    channel_id=_publish_channel_id,
                    kind=ChannelEventKind.TURN_STARTED,
                    payload=TurnStartedPayload(
                        bot_id=task.bot_id,
                        turn_id=_turn_id,
                        task_id=str(task.id),
                        reason="queued_task_starting",
                        session_id=_publish_session_id,
                    ),
                ),
            )
        except Exception:
            logger.debug("publish TURN_STARTED failed for task %s", task.id, exc_info=True)

    _task_timeout = settings.TASK_MAX_RUN_SECONDS  # default; overridden below after channel loads

    # Bot-invoke evaluator injects a per-case system_prompt_override via
    # execution_config. Set the ContextVar before load_or_create so the fresh
    # session's system message is built from the variant text, not the bot's
    # configured prompt. Task-scoped: asyncio.create_task copies this context
    # at spawn, so parallel eval tasks don't bleed into each other.
    _ecfg_override = (task.execution_config or {}).get("system_prompt_override")
    if _ecfg_override is not None:
        from app.agent.context import current_system_prompt_override
        current_system_prompt_override.set(_ecfg_override)

    try:
        from app.agent.loop import run
        from app.agent.persona import get_persona
        from app.services.sessions import _effective_system_prompt, load_or_create
        bot = get_bot(task.bot_id)
        _ecfg_pre = task.execution_config or task.callback_config or {}
        _model_override = _ecfg_pre.get("model_override") or None
        _provider_id_override = _ecfg_pre.get("model_provider_id_override") or None

        async with async_session() as db:
            # Detect cross-bot delegation: task.session_id belongs to a different bot
            # In that case, create a proper child delegation session instead of reusing the parent
            parent_for_delegation = None
            delegation_depth = 1
            delegation_root_id = None

            if task.session_id is not None:
                orig_session = await db.get(Session, task.session_id)
                if orig_session is not None and orig_session.bot_id != task.bot_id:
                    parent_for_delegation = task.session_id
                    delegation_depth = (orig_session.depth or 0) + 1
                    delegation_root_id = orig_session.root_session_id or orig_session.id

            if parent_for_delegation is not None:
                # Cross-bot task → create a new child session with delegation linkage
                child_session_id = uuid.uuid4()
                child_session = Session(
                    id=child_session_id,
                    client_id=task.client_id or "task",
                    bot_id=task.bot_id,
                    channel_id=task.channel_id,
                    parent_session_id=parent_for_delegation,
                    root_session_id=delegation_root_id,
                    depth=delegation_depth,
                    source_task_id=task.id,
                )
                db.add(child_session)
                await db.commit()
                _task_channel = await db.get(Channel, task.channel_id) if task.channel_id else None
                messages = [{
                    "role": "system",
                    "content": _effective_system_prompt(
                        bot,
                        channel=_task_channel,
                        model_override=_model_override,
                        provider_id_override=_provider_id_override,
                    ),
                }]
                if bot.persona:
                    persona_layer = await get_persona(bot.id, workspace_id=bot.shared_workspace_id)
                    if persona_layer:
                        messages.append({"role": "system", "content": f"[PERSONA]\n{persona_layer}"})
                session_id = child_session_id
                logger.info(
                    "Task %s: cross-bot delegation → child session %s (depth=%d, root=%s)",
                    task.id, child_session_id, delegation_depth, delegation_root_id,
                )
            else:
                _initial_profile = "task_none" if (task.execution_config or {}).get("history_mode") == "none" else "task_recent"
                if task.task_type in ("memory_hygiene", "skill_review", "delegation"):
                    _initial_profile = "task_none"
                session_id, messages = await load_or_create(
                    db,
                    task.session_id,
                    task.client_id or "task",
                    task.bot_id,
                    channel_id=task.channel_id,
                    context_profile_name=_initial_profile,
                    model_override=_model_override,
                    provider_id_override=_provider_id_override,
                )

        # Trim conversation history. Respects `execution_config.history_mode`
        # set via the Task editor's "Chat context" picker, falling back to the
        # heartbeat default for legacy tasks:
        #   "none"   → 0 turns (system/preamble only — hermetic)
        #   "recent" → `history_recent_count` turns (default 10)
        #   "full"   → no trimming (-1)
        from app.services.heartbeat import _trim_history_for_task
        _ecfg_hist = task.execution_config or {}
        _hist_mode = _ecfg_hist.get("history_mode")
        if _hist_mode == "none":
            _hist_turns = 0
        elif _hist_mode == "recent":
            try:
                _hist_turns = int(_ecfg_hist.get("history_recent_count") or 10)
            except (TypeError, ValueError):
                _hist_turns = 10
        elif _hist_mode == "full":
            _hist_turns = -1
        else:
            _hist_turns = settings.HEARTBEAT_MAX_HISTORY_TURNS
        messages = _trim_history_for_task(messages, _hist_turns)
        _context_profile_name = "task_none" if _hist_turns == 0 else "task_recent"
        if task.task_type in ("memory_hygiene", "skill_review", "delegation"):
            _context_profile_name = "task_none"

        correlation_id = uuid.uuid4()
        task.correlation_id = correlation_id  # reflect back to in-memory object for hooks
        # Persist correlation_id on task row for cost attribution in forecast.
        # Also store in execution_config for workflow step tracking if applicable.
        async with async_session() as _corr_db:
            _t = await _corr_db.get(Task, task.id)
            if _t:
                _t.correlation_id = correlation_id
                await _corr_db.commit()
        messages_start = len(messages)  # capture before run() appends new turn

        # Resolve latest content from linked template or workspace file (if any)
        from app.services.prompt_resolution import resolve_prompt
        async with async_session() as resolve_db:
            task_prompt = await resolve_prompt(
                workspace_id=str(task.workspace_id) if task.workspace_id else None,
                workspace_file_path=task.workspace_file_path,
                template_id=str(task.prompt_template_id) if task.prompt_template_id else None,
                inline_prompt=task.prompt,
                db=resolve_db,
            )

        # For scheduled tasks, prepend a preamble so the bot knows this is an
        # automated execution, not a live user message.
        _is_scheduled = False
        _recurrence: str | None = None
        if task.parent_task_id:
            async with async_session() as _preamble_db:
                _parent = await _preamble_db.get(Task, task.parent_task_id)
                if _parent and _parent.recurrence:
                    _is_scheduled = True
                    _recurrence = _parent.recurrence
        if _is_scheduled:
            _preamble_lines = [f"[SCHEDULED TASK — recurring {_recurrence}]"]
            if task.title:
                _preamble_lines.append(f"Title: {task.title}")
            _preamble_lines.append(
                "You are executing a scheduled task, not responding to a live user. "
                "Execute the instructions below directly."
            )
            _preamble_lines.append("---")
            task_prompt = "\n".join(_preamble_lines) + "\n" + task_prompt

        # Model override from execution_config (preferred) or callback_config (legacy)
        _fallback_models = _ecfg_pre.get("fallback_models") or None
        _skip_tool_policy = bool(_ecfg_pre.get("skip_tool_approval", False))

        # Scoped secrets from workflow steps
        _allowed_secrets = _ecfg_pre.get("allowed_secrets")
        if _allowed_secrets is not None:
            from app.agent.context import current_allowed_secrets
            current_allowed_secrets.set(_allowed_secrets)

        # Webhook prompt injection: system_preamble, ephemeral skills, injected tools
        _system_preamble = _ecfg_pre.get("system_preamble") or None
        _ecfg_skills = _ecfg_pre.get("skills") or None
        _ecfg_tool_names = _ecfg_pre.get("tools") or None

        if _ecfg_skills:
            from app.agent.context import set_ephemeral_skills
            set_ephemeral_skills(_ecfg_skills)

        _ecfg_injected_tools: list[dict] | None = None
        if _ecfg_tool_names:
            from app.tools.registry import get_local_tool_schemas
            _ecfg_injected_tools = get_local_tool_schemas(_ecfg_tool_names) or None

        # Exclude specific tools (e.g. block delegate_to_agent in callback tasks)
        _exclude_tools = _ecfg_pre.get("exclude_tools") or None
        if _exclude_tools:
            import dataclasses as _dc
            _exclude_set = set(_exclude_tools)
            bot = _dc.replace(bot, local_tools=[t for t in bot.local_tools if t not in _exclude_set])
            logger.info("Task %s: excluded tools %s", task.id, _exclude_tools)

        _task_timeout = resolve_task_timeout(task, _task_channel)

        # Suppress skill auto-inject for hygiene tasks — the review prompt
        # text would match enrolled skills semantically, polluting inject metrics.
        _skip_skill_inject = task.task_type in ("memory_hygiene", "skill_review")

        # Mark autonomous runs so policy rules can target them. Hygiene
        # jobs get their own origin so rules can distinguish them from
        # user-scheduled tasks.
        from app.agent.context import current_run_origin
        if task.task_type in ("memory_hygiene", "skill_review"):
            current_run_origin.set("hygiene")
        elif task.task_type == "delegation":
            current_run_origin.set("subagent")
        else:
            current_run_origin.set("task")

        run_result = await asyncio.wait_for(
            run(
                messages, bot, task_prompt,
                session_id=session_id,
                client_id=task.client_id or "task",
                correlation_id=correlation_id,
                dispatch_type=task.dispatch_type,
                dispatch_config=task.dispatch_config,
                channel_id=task.channel_id,
                model_override=_model_override,
                provider_id_override=_provider_id_override,
                fallback_models=_fallback_models,
                system_preamble=_system_preamble,
                injected_tools=_ecfg_injected_tools,
                skip_tool_policy=_skip_tool_policy,
                task_mode=True,
                skip_skill_inject=_skip_skill_inject,
                context_profile_name=_context_profile_name,
            ),
            timeout=_task_timeout,
        )
        result_text = run_result.response

        # Persist turn to session history so future agent turns see it as context
        _task_meta: dict | None = None
        if _is_scheduled:
            _task_meta = {"trigger": "scheduled_task", "task_id": str(task.id)}
            if task.title:
                _task_meta["task_title"] = task.title
            if _recurrence:
                _task_meta["recurrence"] = _recurrence
            if task.parent_task_id:
                _task_meta["schedule_id"] = str(task.parent_task_id)
        elif task.task_type == "callback":
            # Callback tasks should identify themselves
            # so the UI can display them properly instead of showing "You".
            _task_meta = {"trigger": "callback", "task_id": str(task.id), "sender_type": "bot", "sender_display_name": bot.name}
            # Check if the parent was a delegation task for richer metadata
            if task.parent_task_id:
                async with async_session() as _cb_db:
                    _cb_parent = await _cb_db.get(Task, task.parent_task_id)
                    if _cb_parent and _cb_parent.task_type == "delegation":
                        _task_meta["trigger"] = "delegation_callback"
                        _task_meta["delegation_child_bot_id"] = _cb_parent.bot_id
                        try:
                            _child_bot = get_bot(_cb_parent.bot_id)
                            _task_meta["delegation_child_display"] = _child_bot.display_name or _child_bot.name
                        except Exception:
                            pass
        elif (task.callback_config or {}).get("pipeline_task_id"):
            # Pipeline agent-step child: the "user" message is the rendered
            # step prompt emitted by the pipeline, not a human. Label it
            # with the parent pipeline's title so the sub-session modal
            # doesn't render "You" for an automated step.
            _pipeline_task_id = (task.callback_config or {}).get("pipeline_task_id")
            _pipeline_title = "Pipeline step"
            try:
                async with async_session() as _pp_db:
                    _pp_parent = await _pp_db.get(Task, uuid.UUID(_pipeline_task_id))
                    if _pp_parent and _pp_parent.title:
                        _pipeline_title = _pp_parent.title
            except Exception:
                pass
            _task_meta = {
                "trigger": "pipeline_step",
                "sender_type": "pipeline",
                "sender_display_name": _pipeline_title,
                "pipeline_task_id": _pipeline_task_id,
                "pipeline_step_index": (task.callback_config or {}).get("pipeline_step_index"),
            }
        # If the inbound path pre-persisted the user message via
        # ``store_passive_message`` (the inject_message → Task flow used by
        # BlueBubbles, GitHub, /api/v1/sessions/{id}/messages, and
        # /api/v1/channels/{id}/messages), the message id rides on
        # ``execution_config["pre_user_msg_id"]``. Forward it to persist_turn
        # so the user message is not double-persisted (otherwise the channel
        # ends up showing two ``[Me]: ...`` rows for one inbound message —
        # the bug that surfaced via the BlueBubbles webhook in production).
        _pre_user_msg_id_str = (task.execution_config or {}).get("pre_user_msg_id")
        _pre_user_msg_id = None
        if _pre_user_msg_id_str:
            try:
                _pre_user_msg_id = uuid.UUID(_pre_user_msg_id_str)
            except (ValueError, TypeError):
                logger.warning(
                    "task %s: invalid pre_user_msg_id %r in execution_config",
                    task.id, _pre_user_msg_id_str,
                )
        from app.services.sessions import persist_turn
        # Pipeline agent-step children still persist to the session (so
        # context carries over for subsequent steps), but we pass
        # channel_id=None to skip outbox enqueue AND the bus publish —
        # the pipeline envelope owns the channel-side rendering.
        _persist_channel_id = None if _suppress_channel else task.channel_id
        async with async_session() as db:
            await persist_turn(
                db, session_id, bot, messages, messages_start,
                correlation_id=correlation_id,
                channel_id=_persist_channel_id,
                msg_metadata=_task_meta,
                pre_user_msg_id=_pre_user_msg_id,
                hide_messages=_suppress_channel,
                suppress_outbox=_session_scoped_task,
            )

        # Dispatch result (including any generated images)
        # Prepend a visual indicator for Slack / other text-based dispatchers
        _dispatch_text = result_text
        if _is_scheduled:
            _label = f"🔁 _{task.title or 'Scheduled task'}_\n"
            _dispatch_text = _label + result_text

        # Build delegation metadata for dispatch echo attribution
        _delegation_meta = None
        if task.task_type == "delegation":
            _parent_bot_id = (task.callback_config or {}).get("parent_bot_id")
            _parent_display = _parent_bot_id
            if _parent_bot_id:
                try:
                    _pb = get_bot(_parent_bot_id)
                    _parent_display = _pb.display_name or _pb.name
                except Exception:
                    pass
            _delegation_meta = {
                "delegated_by": _parent_bot_id,
                "delegated_by_display": _parent_display,
                "delegation_task_id": str(task.id),
            }

        # Callback tasks should NOT re-dispatch client_actions (images/files)
        # that were already dispatched by the child delegation task.
        _dispatch_actions = None if task.task_type == "callback" else run_result.client_actions

        await _publish_turn_ended(
            task,
            turn_id=_turn_id,
            result=_dispatch_text,
            client_actions=_dispatch_actions,
            extra_metadata=_delegation_meta,
        )

        _cb = task.callback_config or {}

        # Prepare follow-up tasks to create atomically with completion.
        # Creating them in the same transaction as the status=complete update
        # prevents a race where pending_tasks briefly drops to 0 between
        # the delegation completing and the callback being created.
        _followup_tasks: list[Task] = []

        # trigger_rag_loop: create an immediate follow-up agent turn so the bot can
        # react to what it just posted. Posts response to the same channel.
        if _cb.get("trigger_rag_loop") and result_text:
            _followup_tasks.append(Task(
                bot_id=task.bot_id,
                client_id=task.client_id,
                session_id=session_id,
                channel_id=task.channel_id,
                prompt=f"[Your scheduled task just ran and posted to the channel. The output was:]\n\n{result_text}",
                status="pending",
                task_type="callback",
                dispatch_type=task.dispatch_type,
                dispatch_config=dict(task.dispatch_config or {}),
                callback_config={"trigger_rag_loop": False},  # prevent loop
                parent_task_id=task.id,
                created_at=datetime.now(timezone.utc),
            ))

        # Notify parent: create a callback task for the parent bot if requested.
        # Fire when there's text OR client_actions (e.g. image-bot may generate
        # images via tools but return empty text).
        _has_result = bool(result_text) or bool(run_result.client_actions)
        if _cb.get("notify_parent") and _has_result:
            _parent_bot_id = _cb.get("parent_bot_id")
            _parent_session_str = _cb.get("parent_session_id")
            _parent_client_id = _cb.get("parent_client_id")
            if _parent_bot_id and _parent_session_str:
                try:
                    _parent_session_id = uuid.UUID(_parent_session_str)
                    # Resolve child bot display name for the callback prompt
                    _child_display = task.bot_id
                    try:
                        _child_bot = get_bot(task.bot_id)
                        _child_display = _child_bot.display_name or _child_bot.name
                    except Exception:
                        pass
                    _cb_result_desc = result_text or "[The sub-agent completed its work via tool calls with no text response.]"
                    _cb_prompt = (
                        f"[DELEGATION RESULT — from {_child_display}]\n"
                        f"The sub-agent has already posted its response to the channel. "
                        f"Here is what it returned:\n\n"
                        f"{_cb_result_desc}\n\n"
                        f"Provide a brief follow-up or summary if appropriate. "
                        f"Do NOT re-post any files or images the sub-agent already provided. "
                        f"Do NOT delegate again — the work is complete."
                    )
                    _followup_tasks.append(Task(
                        bot_id=_parent_bot_id,
                        client_id=_parent_client_id,
                        session_id=_parent_session_id,
                        channel_id=task.channel_id,
                        prompt=_cb_prompt,
                        status="pending",
                        task_type="callback",
                        dispatch_type=task.dispatch_type,
                        dispatch_config=dict(task.dispatch_config or {}),
                        # Block delegation tools in callback to prevent re-delegation loops
                        execution_config={"exclude_tools": ["delegate_to_agent"]},
                        parent_task_id=task.id,
                        created_at=datetime.now(timezone.utc),
                    ))
                except Exception:
                    logger.exception("Failed to build parent callback task for task %s", task.id)

        # Mark complete and create follow-up tasks atomically
        async with async_session() as db:
            t = await db.get(Task, task.id)
            if t:
                t.status = "complete"
                t.result = result_text
                t.completed_at = datetime.now(timezone.utc)
            for _ft in _followup_tasks:
                db.add(_ft)
            await db.commit()
            for _ft in _followup_tasks:
                await db.refresh(_ft)

        await _fire_task_complete(task, "complete")

        for _ft in _followup_tasks:
            logger.info(
                "Task %s: created follow-up task %s (type=%s, bot=%s)",
                task.id, _ft.id, _ft.task_type, _ft.bot_id,
            )

    except asyncio.TimeoutError:
        logger.error("Task %s timed out after %ds", task.id, _task_timeout)
        _timeout_err = f"Timed out after {_task_timeout}s"
        await _mark_task_failed_in_db(task.id, error=_timeout_err)
        await _record_timeout_event(task, correlation_id, _timeout_err)
        await _fire_task_complete(task, "failed")
        await _publish_turn_ended_safe(
            task, turn_id=_turn_id, error=_timeout_err, log_label="timeout error",
        )

    except openai.RateLimitError as exc:
        async with async_session() as db:
            t = await db.get(Task, task.id)
            if t is None:
                return
            if t.retry_count < settings.TASK_RATE_LIMIT_RETRIES:
                t.retry_count += 1
                # Exponential backoff: 65s, 130s, 260s — slightly longer than a 60s TPM window
                delay = settings.LLM_RATE_LIMIT_INITIAL_WAIT * (2 ** (t.retry_count - 1))
                t.status = "pending"
                t.scheduled_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
                t.error = f"rate_limited (attempt {t.retry_count}/{settings.TASK_RATE_LIMIT_RETRIES}): {str(exc)[:200]}"
                await db.commit()
                logger.warning(
                    "Task %s rate limited, rescheduled in %ds (attempt %d/%d)",
                    task.id, delay, t.retry_count, settings.TASK_RATE_LIMIT_RETRIES,
                )
            else:
                t.status = "failed"
                t.error = f"rate_limited (max retries exhausted): {str(exc)[:3800]}"
                t.completed_at = datetime.now(timezone.utc)
                await db.commit()
                logger.error("Task %s failed after %d rate limit retries", task.id, t.retry_count)
                await _fire_task_complete(task, "failed")
                await _publish_turn_ended_safe(
                    task, turn_id=_turn_id, error="rate_limited",
                    log_label="rate limit error",
                )

    except Exception as exc:
        logger.exception("Task %s failed", task.id)
        await _mark_task_failed_in_db(task.id, error=str(exc)[:4000])
        await _fire_task_complete(task, "failed")
        await _publish_turn_ended_safe(
            task, turn_id=_turn_id, error=str(exc)[:500], log_label="error",
        )
    finally:
        if _lock_acquired:
            session_locks.release(task.session_id)


async def fetch_due_tasks() -> list[Task]:
    """Atomically fetch pending tasks and mark them running.

    Uses FOR UPDATE SKIP LOCKED to prevent duplicate pickup across
    concurrent poll cycles.
    """
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        stmt = (
            select(Task)
            .where(Task.status == "pending")
            .where(
                (Task.scheduled_at.is_(None)) | (Task.scheduled_at <= now)
            )
            .limit(20)
            .with_for_update(skip_locked=True)
        )
        tasks = list((await db.execute(stmt)).scalars().all())
        for t in tasks:
            t.status = "running"
            t.run_at = now
        await db.commit()
        # Expunge so they're usable outside the session
        for t in tasks:
            db.expunge(t)
        return tasks


async def recover_stuck_tasks() -> None:
    """Mark running tasks that have exceeded their timeout as failed.

    Called periodically by task_worker to clean up tasks stuck from crashes/timeouts.
    Fires the task completion hook so workflow runs advance properly.
    """
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        stmt = select(Task).where(Task.status == "running", Task.run_at.isnot(None))
        running = list((await db.execute(stmt)).scalars().all())

    if not running:
        return

    # Build a channel cache for timeout resolution
    channel_ids = {t.channel_id for t in running if t.channel_id}
    channels_by_id: dict[uuid.UUID, Channel] = {}
    if channel_ids:
        async with async_session() as db:
            ch_rows = (await db.execute(
                select(Channel).where(Channel.id.in_(channel_ids))
            )).scalars().all()
            channels_by_id = {ch.id: ch for ch in ch_rows}

    recovered = 0
    for task in running:
        ch = channels_by_id.get(task.channel_id) if task.channel_id else None
        timeout = resolve_task_timeout(task, ch)
        elapsed = (now - task.run_at).total_seconds()
        if elapsed > timeout:
            async with async_session() as db:
                t = await db.get(Task, task.id)
                if t and t.status == "running":
                    t.status = "failed"
                    t.error = f"Recovered: stuck running for {int(elapsed)}s (timeout={timeout}s)"
                    t.completed_at = now
                    await db.commit()
                    recovered += 1
                    logger.warning("Recovered stuck task %s (running %ds, timeout %ds)", task.id, int(elapsed), timeout)
                    # Record a trace event so the logs UI can display the timeout
                    await _record_timeout_event(task, t.correlation_id, t.error)
                    # For workflow tasks, skip the hook to prevent auto-resume
                    # on server restart. The stalled-run sweep will handle them.
                    is_workflow_task = bool((task.callback_config or {}).get("workflow_run_id"))
                    if is_workflow_task:
                        logger.warning(
                            "Recovered stuck workflow task %s — skipping hook (stalled-run sweep will handle)",
                            task.id,
                        )
                    else:
                        await _fire_task_complete(t, "failed")
    if recovered:
        logger.info("Recovered %d stuck tasks", recovered)


async def recover_stalled_workflow_runs() -> None:
    """Detect and recover workflow runs that are stuck in 'running' state.

    Catches four scenarios:
    1. Step has a task_id but the Task is terminal (hook never fired)
    2. Step is "running" with no task_id (crash between state commit and task creation)
    3. All steps still "pending" after 5 min (advance_workflow failed before starting)
    4. All steps terminal but run still "running" (advance_workflow failed after last step)
    """
    from app.db.models import WorkflowRun

    now = datetime.now(timezone.utc)

    async with async_session() as db:
        stmt = (
            select(WorkflowRun)
            .where(WorkflowRun.status.in_(["running", "awaiting_approval"]))
        )
        stalled = list((await db.execute(stmt)).scalars().all())

    if not stalled:
        return

    recovered = 0
    for run in stalled:
        step_states = list(run.step_states or [])
        # Find the running step
        running_step_idx = None
        for i, st in enumerate(step_states):
            if st.get("status") == "running":
                running_step_idx = i
                break

        if running_step_idx is None:
            # Scenario 3: run is "running" but ALL steps are still "pending".
            # This happens when advance_workflow fails before setting step 0 to
            # "running" (e.g. exception in _create_step_task that wasn't caught,
            # or the hook chain failed silently).
            if (
                run.status == "running"
                and step_states
                and all(s.get("status") == "pending" for s in step_states)
            ):
                created_at = run.created_at
                if created_at and created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                if created_at and (now - created_at).total_seconds() > 300:
                    logger.warning(
                        "Recovering stalled workflow run %s — all %d steps still pending after %ds",
                        run.id, len(step_states), int((now - created_at).total_seconds()),
                    )
                    try:
                        from app.services.workflow_executor import advance_workflow
                        await advance_workflow(run.id)
                        recovered += 1
                    except Exception:
                        logger.exception("Recovery advance_workflow failed for run %s", run.id)

            # Scenario 4: run is "running" but ALL steps are terminal (done/skipped/failed).
            # This happens when advance_workflow fails after on_step_task_completed commits
            # the step state but before marking the run complete.
            elif (
                run.status == "running"
                and step_states
                and all(s.get("status") in ("done", "skipped", "failed") for s in step_states)
            ):
                logger.warning(
                    "Recovering stalled workflow run %s — all %d steps terminal but run still 'running'",
                    run.id, len(step_states),
                )
                try:
                    from app.services.workflow_executor import advance_workflow
                    await advance_workflow(run.id)
                    recovered += 1
                except Exception:
                    logger.exception("Recovery advance_workflow failed for run %s", run.id)

            continue

        state = step_states[running_step_idx]
        started_at_str = state.get("started_at")
        if started_at_str:
            try:
                started_at = datetime.fromisoformat(started_at_str)
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
                elapsed_s = (now - started_at).total_seconds()
                if elapsed_s < 300:  # Not stale until 5 minutes
                    continue
            except (ValueError, TypeError):
                pass

        task_id_str = state.get("task_id")
        if task_id_str:
            # Scenario 1: step has a task_id — check if the task is terminal
            try:
                task_uuid = uuid.UUID(task_id_str)
            except (ValueError, TypeError):
                continue
            async with async_session() as db:
                task = await db.get(Task, task_uuid)
            if task and task.status in ("complete", "failed", "cancelled"):
                # Re-fire the step completion callback
                logger.warning(
                    "Recovering stalled workflow run %s step %d — task %s is %s but hook never fired",
                    run.id, running_step_idx, task.id, task.status,
                )
                from app.services.workflow_executor import on_step_task_completed
                await on_step_task_completed(
                    str(run.id), running_step_idx, task.status, task,
                )
                recovered += 1
        else:
            # Scenario 2: step is running but no task was ever created (crash)
            logger.warning(
                "Recovering stalled workflow run %s step %d — no task_id, marking failed",
                run.id, running_step_idx,
            )
            async with async_session() as db:
                fresh_run = await db.get(WorkflowRun, run.id)
                if fresh_run and fresh_run.status in ("running", "awaiting_approval"):
                    import copy as _copy
                    from app.services.workflow_executor import _set_step_states
                    ss = _copy.deepcopy(fresh_run.step_states or [])
                    ss[running_step_idx]["status"] = "failed"
                    ss[running_step_idx]["error"] = "Recovered: task was never created (server crash)"
                    ss[running_step_idx]["completed_at"] = now.isoformat()
                    _set_step_states(fresh_run, ss)
                    await db.commit()
            from app.services.workflow_executor import advance_workflow
            await advance_workflow(run.id)
            recovered += 1

    if recovered:
        logger.info("Recovered %d stalled workflow runs", recovered)


async def task_worker() -> None:
    """Background worker loop: polls for due tasks every 5 seconds."""
    logger.info("Task worker started")
    try:
        await recover_stuck_tasks()
    except Exception:
        logger.exception("recover_stuck_tasks failed at startup")

    last_recovery_at = datetime.now(timezone.utc)
    last_workflow_sweep_at = datetime.now(timezone.utc)
    last_hygiene_check_at = datetime.now(timezone.utc)

    while True:
        try:
            if settings.SYSTEM_PAUSED:
                await asyncio.sleep(5)
                continue
            # Spawn concrete tasks from active schedule templates first
            await spawn_due_schedules()
            # Then fire any per-channel subscriptions whose cron is due
            await spawn_due_subscriptions()
            # Then fire any widget @on_cron handlers whose schedule is due
            from app.services.widget_cron import spawn_due_widget_crons
            await spawn_due_widget_crons()
            # Native-widget cron path (Standing Orders, etc.) — parallel to
            # the HTML @on_cron lane; queries WidgetInstance rows directly.
            from app.services.standing_orders import spawn_due_native_widget_ticks
            await spawn_due_native_widget_ticks()
            # Then fetch and run all due concrete tasks
            due = await fetch_due_tasks()
            for task in due:
                asyncio.create_task(run_task(task))

            now = datetime.now(timezone.utc)

            # Periodic stuck-task recovery (every 60s)
            if (now - last_recovery_at).total_seconds() >= 60:
                last_recovery_at = now
                try:
                    await recover_stuck_tasks()
                except Exception:
                    logger.exception("periodic recover_stuck_tasks failed")

            # Periodic stalled workflow run sweep (every 2 min)
            if (now - last_workflow_sweep_at).total_seconds() >= 120:
                last_workflow_sweep_at = now
                try:
                    await recover_stalled_workflow_runs()
                except Exception:
                    logger.exception("recover_stalled_workflow_runs failed")

            # Periodic memory hygiene check (every 60s)
            if (now - last_hygiene_check_at).total_seconds() >= 60:
                last_hygiene_check_at = now
                try:
                    from app.services.memory_hygiene import check_memory_hygiene
                    await check_memory_hygiene()
                except Exception:
                    logger.exception("check_memory_hygiene failed")

        except Exception:
            logger.exception("task_worker poll error")
        await asyncio.sleep(5)
