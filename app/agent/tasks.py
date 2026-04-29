"""Task worker: runs scheduled/deferred agent tasks and dispatches results."""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.agent.bots import get_bot
from app.config import settings
from app.db.engine import async_session
from app.db.models import Channel, ChannelHeartbeat, HeartbeatRun, Task, TraceEvent
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
    raw_cb = getattr(task, "callback_config", None)
    cb = raw_cb if isinstance(raw_cb, dict) else {}
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
    raw_cb = getattr(task, "callback_config", None)
    cb = raw_cb if isinstance(raw_cb, dict) else {}
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

    if cb.get("attention_assignment"):
        try:
            from app.services.workspace_attention import on_attention_assignment_task_complete
            await on_attention_assignment_task_complete(task.id, status)
        except Exception:
            logger.exception("Attention assignment completion failed for task %s", task.id)

    if cb.get("attention_triage"):
        try:
            from app.services.workspace_attention import on_attention_triage_task_complete
            await on_attention_triage_task_complete(task.id, status)
        except Exception:
            logger.exception("Attention triage completion failed for task %s", task.id)

    if cb.get("mission_id"):
        try:
            from app.services.workspace_missions import on_mission_task_complete
            await on_mission_task_complete(task.id, status)
        except Exception:
            logger.exception("Mission task completion failed for task %s", task.id)

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


def _task_trigger_deps():
    from app.agent.task_trigger_host import TaskTriggerHostDeps

    return TaskTriggerHostDeps(
        async_session=async_session,
        spawn_from_schedule=_spawn_from_schedule,
        fire_subscription=_fire_subscription,
        matches_event_filter=_matches_event_filter,
        spawn_from_event_trigger=_spawn_from_event_trigger,
    )


def _parse_recurrence(value: str) -> timedelta | None:
    """Parse a relative offset like +1h, +30m, +1d, +1w into a timedelta."""
    from app.agent.task_trigger_host import parse_recurrence

    return parse_recurrence(value)


def validate_recurrence(value: str | None) -> str | None:
    """Validate a recurrence string. Returns the value if valid, raises ValueError if not."""
    from app.agent.task_trigger_host import validate_recurrence as validate_recurrence_host

    return validate_recurrence_host(value)


async def _spawn_from_schedule(schedule_id: uuid.UUID) -> None:
    """Spawn a concrete one-off task from an active schedule template."""
    from app.agent.task_trigger_host import spawn_from_schedule

    await spawn_from_schedule(schedule_id, deps=_task_trigger_deps())


async def spawn_due_schedules() -> None:
    """Find active schedule templates that are due and spawn concrete tasks."""
    from app.agent.task_trigger_host import spawn_due_schedules as spawn_due_schedules_host

    await spawn_due_schedules_host(deps=_task_trigger_deps())


async def _fire_subscription(subscription_id: uuid.UUID) -> None:
    """Fire a single subscription: spawn a child run, advance next_fire_at."""
    from app.agent.task_trigger_host import fire_subscription

    await fire_subscription(subscription_id, deps=_task_trigger_deps())


async def spawn_due_subscriptions() -> None:
    """Find enabled subscriptions whose cron schedule is due and spawn runs."""
    from app.agent.task_trigger_host import spawn_due_subscriptions as spawn_due_subscriptions_host

    await spawn_due_subscriptions_host(deps=_task_trigger_deps())


def _matches_event_filter(filter_config: dict, event_data: dict) -> bool:
    """Check if event_data matches all key-value pairs in filter_config."""
    from app.agent.task_trigger_host import matches_event_filter

    return matches_event_filter(filter_config, event_data)


async def _spawn_from_event_trigger(template_id: uuid.UUID, event_data: dict) -> None:
    """Spawn a concrete task from an event-triggered template."""
    from app.agent.task_trigger_host import spawn_from_event_trigger

    await spawn_from_event_trigger(template_id, event_data, deps=_task_trigger_deps())


async def fire_event_triggers(event_source: str, event_type: str, event_data: dict) -> int:
    """Find active event-triggered tasks matching this event and spawn instances."""
    from app.agent.task_trigger_host import fire_event_triggers as fire_event_triggers_host

    return await fire_event_triggers_host(
        event_source,
        event_type,
        event_data,
        deps=_task_trigger_deps(),
    )


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
        await _publish_turn_ended(
            target_task,
            turn_id=turn_id,
            result=result,
            error=error,
            kind_hint="heartbeat" if target_task.task_type == "heartbeat" else None,
        )
    except Exception:
        logger.warning("Failed to publish %s for task %s", log_label, target_task.id)


def _heartbeat_execution_meta(task: Task) -> dict:
    return dict((getattr(task, "execution_config", None) or {}).get("heartbeat") or {})


def _heartbeat_run_uuid(task: Task) -> uuid.UUID | None:
    run_id = _heartbeat_execution_meta(task).get("heartbeat_run_id")
    if not run_id:
        return None
    try:
        return uuid.UUID(str(run_id))
    except (TypeError, ValueError):
        return None


async def _mark_heartbeat_task_started(task: Task, correlation_id: uuid.UUID | None) -> None:
    run_id = _heartbeat_run_uuid(task)
    if run_id is None:
        return
    async with async_session() as db:
        run_rec = await db.get(HeartbeatRun, run_id)
        if run_rec:
            run_rec.status = "running"
            run_rec.task_id = task.id
            run_rec.correlation_id = correlation_id
            await db.commit()


async def _finalize_heartbeat_task_run(
    task: Task,
    *,
    status: str,
    result_text: str | None,
    error_text: str | None,
    correlation_id: uuid.UUID | None,
) -> None:
    meta = _heartbeat_execution_meta(task)
    run_id = _heartbeat_run_uuid(task)
    heartbeat_id = meta.get("heartbeat_id")
    try:
        hb_uuid = uuid.UUID(str(heartbeat_id)) if heartbeat_id else None
    except (TypeError, ValueError):
        hb_uuid = None
    if run_id is None and hb_uuid is None:
        return
    async with async_session() as db:
        if run_id is not None:
            run_rec = await db.get(HeartbeatRun, run_id)
            if run_rec:
                run_rec.completed_at = datetime.now(timezone.utc)
                run_rec.result = result_text
                run_rec.error = error_text
                run_rec.correlation_id = correlation_id
                run_rec.task_id = task.id
                run_rec.status = status
                run_rec.repetition_detected = bool(meta.get("repetition_detected", False))
        if hb_uuid is not None:
            heartbeat = await db.get(ChannelHeartbeat, hb_uuid)
            if heartbeat:
                heartbeat.last_result = result_text
                heartbeat.last_error = error_text
                if status in ("complete", "failed"):
                    heartbeat.run_count = (heartbeat.run_count or 0) + 1
                heartbeat.updated_at = datetime.now(timezone.utc)
        await db.commit()


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
    """Execute a single task through the task-run host."""
    from app.agent.task_run_host import TaskRunHostDeps, run_task as run_task_host
    from app.services.session_targets import resolve_task_session_target

    await run_task_host(
        task,
        deps=TaskRunHostDeps(
            async_session=async_session,
            settings=settings,
            session_locks=session_locks,
            get_bot=get_bot,
            resolve_task_session_target=resolve_task_session_target,
            is_pipeline_child=_is_pipeline_child,
            resolve_sub_session_bus_channel=_resolve_sub_session_bus_channel,
            dispatch_to_specialized_runner=_dispatch_to_specialized_runner,
            publish_turn_ended=_publish_turn_ended,
            fire_task_complete=_fire_task_complete,
            record_timeout_event=_record_timeout_event,
            resolve_task_timeout=resolve_task_timeout,
            mark_task_failed_in_db=_mark_task_failed_in_db,
            publish_turn_ended_safe=_publish_turn_ended_safe,
            mark_heartbeat_task_started=_mark_heartbeat_task_started,
            finalize_heartbeat_task_run=_finalize_heartbeat_task_run,
            heartbeat_execution_meta=_heartbeat_execution_meta,
        ),
    )


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
    last_daily_summary_check_at = datetime.now(timezone.utc) - timedelta(minutes=10)

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

            # Daily system-health summary lane (cheap once-per-day gate inside)
            if (now - last_daily_summary_check_at).total_seconds() >= 300:
                last_daily_summary_check_at = now
                try:
                    from app.services.system_health_summary import maybe_run_daily_summary
                    await maybe_run_daily_summary()
                except Exception:
                    logger.exception("maybe_run_daily_summary failed")

        except Exception:
            logger.exception("task_worker poll error")
        await asyncio.sleep(5)
