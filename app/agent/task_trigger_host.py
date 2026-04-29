"""Host orchestration for task trigger spawning."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.db.models import Task

logger = logging.getLogger(__name__)

_RELATIVE_RE = re.compile(r"^\+(\d+)([smhdw])$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


@dataclass(frozen=True)
class TaskTriggerHostDeps:
    """Patchable dependencies supplied by app.agent.tasks at run time."""

    async_session: Callable[[], Any]
    spawn_from_schedule: Callable[[uuid.UUID], Awaitable[None]]
    fire_subscription: Callable[[uuid.UUID], Awaitable[None]]
    matches_event_filter: Callable[[dict, dict], bool]
    spawn_from_event_trigger: Callable[[uuid.UUID, dict], Awaitable[None]]


def parse_recurrence(value: str) -> timedelta | None:
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
    if parse_recurrence(value) is None:
        raise ValueError(
            f"Invalid recurrence {value!r}. Use format +N[s|m|h|d|w] (e.g. +30m, +1h, +1d, +1w)."
        )
    return value


async def spawn_from_schedule(schedule_id: uuid.UUID, *, deps: TaskTriggerHostDeps) -> None:
    """Spawn a concrete one-off task from an active schedule template."""
    async with deps.async_session() as db:
        schedule = await db.get(Task, schedule_id)
        if schedule is None or schedule.status != "active" or not schedule.recurrence:
            return

        interval = parse_recurrence(schedule.recurrence)
        if not interval:
            logger.warning("Schedule %s has invalid recurrence %r — skipping", schedule.id, schedule.recurrence)
            return

        from app.services.prompt_resolution import resolve_prompt
        prompt = await resolve_prompt(
            workspace_id=str(schedule.workspace_id) if schedule.workspace_id else None,
            workspace_file_path=schedule.workspace_file_path,
            template_id=str(schedule.prompt_template_id) if schedule.prompt_template_id else None,
            inline_prompt=schedule.prompt,
            db=db,
        )

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
            recurrence=None,
            parent_task_id=schedule.id,
            max_run_seconds=schedule.max_run_seconds,
            workflow_id=schedule.workflow_id,
            workflow_session_mode=schedule.workflow_session_mode,
            steps=list(schedule.steps) if schedule.steps else None,
            layout=dict(schedule.layout) if schedule.layout else {},
            run_isolation=schedule.run_isolation or "inline",
            created_at=datetime.now(timezone.utc),
        )
        db.add(concrete)

        base = schedule.scheduled_at or datetime.now(timezone.utc)
        schedule.scheduled_at = base + interval
        schedule.run_count = (schedule.run_count or 0) + 1

        await db.commit()
        logger.info(
            "Schedule %s spawned concrete task %s (run #%d), next at %s",
            schedule.id, concrete.id, schedule.run_count,
            schedule.scheduled_at.strftime("%Y-%m-%d %H:%M UTC"),
        )


async def spawn_due_schedules(*, deps: TaskTriggerHostDeps) -> None:
    """Find active schedule templates that are due and spawn concrete tasks."""
    now = datetime.now(timezone.utc)
    async with deps.async_session() as db:
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
            await deps.spawn_from_schedule(sid)
        except Exception:
            logger.exception("Failed to spawn from schedule %s", sid)


async def fire_subscription(subscription_id: uuid.UUID, *, deps: TaskTriggerHostDeps) -> None:
    """Fire a single subscription: spawn a child run, advance next_fire_at."""
    from app.db.models import ChannelPipelineSubscription
    from app.services.cron_utils import next_fire_at as _cron_next
    from app.services.task_ops import spawn_child_run

    async with deps.async_session() as db:
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


async def spawn_due_subscriptions(*, deps: TaskTriggerHostDeps) -> None:
    """Find enabled subscriptions whose cron schedule is due and spawn runs."""
    from app.db.models import ChannelPipelineSubscription

    now = datetime.now(timezone.utc)
    async with deps.async_session() as db:
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
            await deps.fire_subscription(sid)
        except Exception:
            logger.exception("Failed to fire subscription %s", sid)


def matches_event_filter(filter_config: dict, event_data: dict) -> bool:
    """Check if event_data matches all key-value pairs in filter_config."""
    for key, expected in filter_config.items():
        actual = event_data.get(key)
        if actual is None or str(actual) != str(expected):
            return False
    return True


async def spawn_from_event_trigger(
    template_id: uuid.UUID,
    event_data: dict,
    *,
    deps: TaskTriggerHostDeps,
) -> None:
    """Spawn a concrete task from an event-triggered template."""
    async with deps.async_session() as db:
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
            steps=list(template.steps) if template.steps else None,
            layout=dict(template.layout) if template.layout else {},
            run_isolation=template.run_isolation or "inline",
            created_at=datetime.now(timezone.utc),
        )
        db.add(concrete)
        template.run_count = (template.run_count or 0) + 1
        await db.commit()
        logger.info("Event trigger %s spawned concrete task %s", template.id, concrete.id)


async def fire_event_triggers(
    event_source: str,
    event_type: str,
    event_data: dict,
    *,
    deps: TaskTriggerHostDeps,
) -> int:
    """Find active event-triggered tasks matching this event and spawn instances."""
    async with deps.async_session() as db:
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
        if not deps.matches_event_filter(event_filter, event_data):
            continue
        try:
            await deps.spawn_from_event_trigger(task.id, event_data)
            spawned += 1
        except Exception:
            logger.exception("Failed to spawn from event trigger %s", task.id)
    return spawned
