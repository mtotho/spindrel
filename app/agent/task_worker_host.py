"""Host orchestration for the task worker loop and recovery sweeps."""

from __future__ import annotations

import logging
import uuid
from inspect import isawaitable
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.db.models import Channel, Task, WorkflowRun

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TaskWorkerHostDeps:
    """Patchable dependencies supplied by app.agent.tasks at run time."""

    async_session: Callable[[], Any]
    settings: Any
    resolve_task_timeout: Callable[[Task, Channel | None], int]
    record_timeout_event: Callable[[Task, uuid.UUID | None, str], Awaitable[None]]
    fire_task_complete: Callable[[Task, str], Awaitable[None]]
    fetch_due_tasks: Callable[[], Awaitable[list[Task]]]
    run_task: Callable[[Task], Awaitable[None]]
    recover_stuck_tasks: Callable[[], Awaitable[None]]
    recover_stalled_workflow_runs: Callable[[], Awaitable[None]]
    spawn_due_schedules: Callable[[], Awaitable[None]]
    spawn_due_subscriptions: Callable[[], Awaitable[None]]
    spawn_due_widget_crons: Callable[[], Awaitable[None]]
    spawn_due_native_widget_ticks: Callable[[], Awaitable[None]]
    check_memory_hygiene: Callable[[], Awaitable[None]]
    maybe_run_daily_summary: Callable[[], Awaitable[Any]]
    create_task: Callable[[Awaitable[Any]], Any]
    sleep: Callable[[float], Awaitable[None]]


async def fetch_due_tasks(*, deps: TaskWorkerHostDeps) -> list[Task]:
    """Atomically fetch pending tasks and mark them running."""
    now = datetime.now(timezone.utc)
    async with deps.async_session() as db:
        stmt = (
            select(Task)
            .where(Task.status == "pending")
            .where((Task.scheduled_at.is_(None)) | (Task.scheduled_at <= now))
            .limit(20)
            .with_for_update(skip_locked=True)
        )
        tasks = list((await db.execute(stmt)).scalars().all())
        for task in tasks:
            task.status = "running"
            task.run_at = now
        await db.commit()
        for task in tasks:
            maybe_awaitable = db.expunge(task)
            if isawaitable(maybe_awaitable):
                await maybe_awaitable
        return tasks


async def recover_stuck_tasks(*, deps: TaskWorkerHostDeps) -> None:
    """Mark running tasks that have exceeded their timeout as failed."""
    now = datetime.now(timezone.utc)
    async with deps.async_session() as db:
        stmt = select(Task).where(Task.status == "running", Task.run_at.isnot(None))
        running = list((await db.execute(stmt)).scalars().all())

    if not running:
        return

    channel_ids = {task.channel_id for task in running if task.channel_id}
    channels_by_id: dict[uuid.UUID, Channel] = {}
    if channel_ids:
        async with deps.async_session() as db:
            ch_rows = (
                await db.execute(select(Channel).where(Channel.id.in_(channel_ids)))
            ).scalars().all()
            channels_by_id = {channel.id: channel for channel in ch_rows}

    recovered = 0
    for task in running:
        channel = channels_by_id.get(task.channel_id) if task.channel_id else None
        timeout = deps.resolve_task_timeout(task, channel)
        elapsed = (now - task.run_at).total_seconds()
        if elapsed <= timeout:
            continue

        async with deps.async_session() as db:
            fresh_task = await db.get(Task, task.id)
            if not fresh_task or fresh_task.status != "running":
                continue

            fresh_task.status = "failed"
            fresh_task.error = (
                f"Recovered: stuck running for {int(elapsed)}s (timeout={timeout}s)"
            )
            fresh_task.completed_at = now
            await db.commit()
            recovered += 1
            logger.warning(
                "Recovered stuck task %s (running %ds, timeout %ds)",
                task.id,
                int(elapsed),
                timeout,
            )
            await deps.record_timeout_event(task, fresh_task.correlation_id, fresh_task.error)
            is_workflow_task = bool((task.callback_config or {}).get("workflow_run_id"))
            if is_workflow_task:
                logger.warning(
                    "Recovered stuck workflow task %s - skipping hook (stalled-run sweep will handle)",
                    task.id,
                )
            else:
                await deps.fire_task_complete(fresh_task, "failed")

    if recovered:
        logger.info("Recovered %d stuck tasks", recovered)


async def recover_stalled_workflow_runs(*, deps: TaskWorkerHostDeps) -> None:
    """Detect and recover workflow runs stuck in a running state."""
    now = datetime.now(timezone.utc)

    async with deps.async_session() as db:
        stmt = select(WorkflowRun).where(WorkflowRun.status.in_(["running", "awaiting_approval"]))
        stalled = list((await db.execute(stmt)).scalars().all())

    if not stalled:
        return

    recovered = 0
    for run in stalled:
        step_states = list(run.step_states or [])
        running_step_idx = None
        for idx, state in enumerate(step_states):
            if state.get("status") == "running":
                running_step_idx = idx
                break

        if running_step_idx is None:
            recovered += await _recover_stalled_run_without_running_step(run, step_states, now)
            continue

        state = step_states[running_step_idx]
        started_at_str = state.get("started_at")
        if started_at_str:
            try:
                started_at = datetime.fromisoformat(started_at_str)
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
                if (now - started_at).total_seconds() < 300:
                    continue
            except (ValueError, TypeError):
                pass

        task_id_str = state.get("task_id")
        if task_id_str:
            recovered += await _recover_terminal_task_step(
                run,
                running_step_idx,
                task_id_str,
                deps=deps,
            )
        else:
            recovered += await _recover_missing_task_step(
                run,
                running_step_idx,
                now,
                deps=deps,
            )

    if recovered:
        logger.info("Recovered %d stalled workflow runs", recovered)


async def _recover_stalled_run_without_running_step(
    run: WorkflowRun,
    step_states: list[dict],
    now: datetime,
) -> int:
    if (
        run.status == "running"
        and step_states
        and all(state.get("status") == "pending" for state in step_states)
    ):
        created_at = run.created_at
        if created_at and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if created_at and (now - created_at).total_seconds() > 300:
            logger.warning(
                "Recovering stalled workflow run %s - all %d steps still pending after %ds",
                run.id,
                len(step_states),
                int((now - created_at).total_seconds()),
            )
            try:
                from app.services.workflow_executor import advance_workflow

                await advance_workflow(run.id)
                return 1
            except Exception:
                logger.exception("Recovery advance_workflow failed for run %s", run.id)

    elif (
        run.status == "running"
        and step_states
        and all(state.get("status") in ("done", "skipped", "failed") for state in step_states)
    ):
        logger.warning(
            "Recovering stalled workflow run %s - all %d steps terminal but run still 'running'",
            run.id,
            len(step_states),
        )
        try:
            from app.services.workflow_executor import advance_workflow

            await advance_workflow(run.id)
            return 1
        except Exception:
            logger.exception("Recovery advance_workflow failed for run %s", run.id)

    return 0


async def _recover_terminal_task_step(
    run: WorkflowRun,
    running_step_idx: int,
    task_id_str: str,
    *,
    deps: TaskWorkerHostDeps,
) -> int:
    try:
        task_id = uuid.UUID(task_id_str)
    except (ValueError, TypeError):
        return 0

    async with deps.async_session() as db:
        task = await db.get(Task, task_id)

    if task and task.status in ("complete", "failed", "cancelled"):
        logger.warning(
            "Recovering stalled workflow run %s step %d - task %s is %s but hook never fired",
            run.id,
            running_step_idx,
            task.id,
            task.status,
        )
        from app.services.workflow_executor import on_step_task_completed

        await on_step_task_completed(str(run.id), running_step_idx, task.status, task)
        return 1
    return 0


async def _recover_missing_task_step(
    run: WorkflowRun,
    running_step_idx: int,
    now: datetime,
    *,
    deps: TaskWorkerHostDeps,
) -> int:
    logger.warning(
        "Recovering stalled workflow run %s step %d - no task_id, marking failed",
        run.id,
        running_step_idx,
    )
    async with deps.async_session() as db:
        fresh_run = await db.get(WorkflowRun, run.id)
        if fresh_run and fresh_run.status in ("running", "awaiting_approval"):
            import copy as _copy
            from app.services.workflow_executor import _set_step_states

            step_states = _copy.deepcopy(fresh_run.step_states or [])
            step_states[running_step_idx]["status"] = "failed"
            step_states[running_step_idx]["error"] = "Recovered: task was never created (server crash)"
            step_states[running_step_idx]["completed_at"] = now.isoformat()
            _set_step_states(fresh_run, step_states)
            await db.commit()

    from app.services.workflow_executor import advance_workflow

    await advance_workflow(run.id)
    return 1


async def task_worker(*, deps: TaskWorkerHostDeps) -> None:
    """Background worker loop: polls for due tasks every 5 seconds."""
    logger.info("Task worker started")
    try:
        await deps.recover_stuck_tasks()
    except Exception:
        logger.exception("recover_stuck_tasks failed at startup")

    last_recovery_at = datetime.now(timezone.utc)
    last_workflow_sweep_at = datetime.now(timezone.utc)
    last_hygiene_check_at = datetime.now(timezone.utc)
    last_daily_summary_check_at = datetime.now(timezone.utc) - timedelta(minutes=10)

    while True:
        try:
            if deps.settings.SYSTEM_PAUSED:
                await deps.sleep(5)
                continue

            await deps.spawn_due_schedules()
            await deps.spawn_due_subscriptions()
            await deps.spawn_due_widget_crons()
            await deps.spawn_due_native_widget_ticks()

            for task in await deps.fetch_due_tasks():
                deps.create_task(deps.run_task(task))

            now = datetime.now(timezone.utc)

            if (now - last_recovery_at).total_seconds() >= 60:
                last_recovery_at = now
                try:
                    await deps.recover_stuck_tasks()
                except Exception:
                    logger.exception("periodic recover_stuck_tasks failed")

            if (now - last_workflow_sweep_at).total_seconds() >= 120:
                last_workflow_sweep_at = now
                try:
                    await deps.recover_stalled_workflow_runs()
                except Exception:
                    logger.exception("recover_stalled_workflow_runs failed")

            if (now - last_hygiene_check_at).total_seconds() >= 60:
                last_hygiene_check_at = now
                try:
                    await deps.check_memory_hygiene()
                except Exception:
                    logger.exception("check_memory_hygiene failed")

            if (now - last_daily_summary_check_at).total_seconds() >= 300:
                last_daily_summary_check_at = now
                try:
                    await deps.maybe_run_daily_summary()
                except Exception:
                    logger.exception("maybe_run_daily_summary failed")

        except Exception:
            logger.exception("task_worker poll error")
        await deps.sleep(5)
