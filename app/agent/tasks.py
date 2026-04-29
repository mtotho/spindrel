"""Task worker: runs scheduled/deferred agent tasks and dispatches results."""
import asyncio
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


def _task_exec_deps():
    from app.agent.recording import schedule_exec_completion_record
    from app.agent.task_exec_host import TaskExecHostDeps
    from app.services.sandbox import sandbox_service
    from app.services.workspace import workspace_service
    from app.tools.local.exec_tool import build_exec_script

    return TaskExecHostDeps(
        async_session=async_session,
        settings=settings,
        get_bot=get_bot,
        build_exec_script=build_exec_script,
        sandbox_service=sandbox_service,
        workspace_service=workspace_service,
        resolve_task_timeout=resolve_task_timeout,
        fire_task_complete=_fire_task_complete,
        mark_task_failed_in_db=_mark_task_failed_in_db,
        publish_turn_ended=_publish_turn_ended,
        publish_turn_ended_safe=_publish_turn_ended_safe,
        schedule_exec_completion_record=schedule_exec_completion_record,
        sleep=asyncio.sleep,
    )


# ---------------------------------------------------------------------------
# Runner helpers
# ---------------------------------------------------------------------------

async def run_exec_task(task: Task) -> None:
    """Execute a raw exec task: run command in sandbox, store result, dispatch."""
    from app.agent.task_exec_host import run_exec_task as run_exec_task_host

    await run_exec_task_host(task, deps=_task_exec_deps())


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


def _task_worker_deps():
    from app.agent.task_worker_host import TaskWorkerHostDeps

    async def _spawn_due_widget_crons() -> None:
        from app.services.widget_cron import spawn_due_widget_crons

        await spawn_due_widget_crons()

    async def _spawn_due_native_widget_ticks() -> None:
        from app.services.standing_orders import spawn_due_native_widget_ticks

        await spawn_due_native_widget_ticks()

    async def _check_memory_hygiene() -> None:
        from app.services.memory_hygiene import check_memory_hygiene

        await check_memory_hygiene()

    async def _maybe_run_daily_summary():
        from app.services.system_health_summary import maybe_run_daily_summary

        return await maybe_run_daily_summary()

    return TaskWorkerHostDeps(
        async_session=async_session,
        settings=settings,
        resolve_task_timeout=resolve_task_timeout,
        record_timeout_event=_record_timeout_event,
        fire_task_complete=_fire_task_complete,
        fetch_due_tasks=fetch_due_tasks,
        run_task=run_task,
        recover_stuck_tasks=recover_stuck_tasks,
        recover_stalled_workflow_runs=recover_stalled_workflow_runs,
        spawn_due_schedules=spawn_due_schedules,
        spawn_due_subscriptions=spawn_due_subscriptions,
        spawn_due_widget_crons=_spawn_due_widget_crons,
        spawn_due_native_widget_ticks=_spawn_due_native_widget_ticks,
        check_memory_hygiene=_check_memory_hygiene,
        maybe_run_daily_summary=_maybe_run_daily_summary,
        create_task=asyncio.create_task,
        sleep=asyncio.sleep,
    )


async def fetch_due_tasks() -> list[Task]:
    """Atomically fetch pending tasks and mark them running.

    Uses FOR UPDATE SKIP LOCKED to prevent duplicate pickup across
    concurrent poll cycles.
    """
    from app.agent.task_worker_host import fetch_due_tasks as fetch_due_tasks_host

    return await fetch_due_tasks_host(deps=_task_worker_deps())


async def recover_stuck_tasks() -> None:
    """Mark running tasks that have exceeded their timeout as failed.

    Called periodically by task_worker to clean up tasks stuck from crashes/timeouts.
    Fires the task completion hook so workflow runs advance properly.
    """
    from app.agent.task_worker_host import recover_stuck_tasks as recover_stuck_tasks_host

    await recover_stuck_tasks_host(deps=_task_worker_deps())


async def recover_stalled_workflow_runs() -> None:
    """Detect and recover workflow runs that are stuck in 'running' state.

    Catches four scenarios:
    1. Step has a task_id but the Task is terminal (hook never fired)
    2. Step is "running" with no task_id (crash between state commit and task creation)
    3. All steps still "pending" after 5 min (advance_workflow failed before starting)
    4. All steps terminal but run still "running" (advance_workflow failed after last step)
    """
    from app.agent.task_worker_host import (
        recover_stalled_workflow_runs as recover_stalled_workflow_runs_host,
    )

    await recover_stalled_workflow_runs_host(deps=_task_worker_deps())


async def task_worker() -> None:
    """Background worker loop: polls for due tasks every 5 seconds."""
    from app.agent.task_worker_host import task_worker as task_worker_host

    await task_worker_host(deps=_task_worker_deps())
