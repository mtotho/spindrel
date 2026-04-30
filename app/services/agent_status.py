"""Read-only agent status snapshot.

This composes existing task and heartbeat evidence into one compact runtime
view.  It is intentionally not a new liveness protocol or event store.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Channel, ChannelHeartbeat, HeartbeatRun, Session, Task, ToolCall


AgentState = Literal["idle", "scheduled", "working", "blocked", "error", "unknown"]
AgentStatusRecommendation = Literal[
    "continue",
    "wait_for_run",
    "review_failure",
    "review_stale_run",
    "enable_heartbeat",
    "unknown",
]

RUNNING_STATUSES = {"running"}
FAILED_STATUSES = {"failed", "error"}
SCHEDULED_TASK_STATUSES = {"pending", "active"}


def _uuid_or_none(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None or isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _clip(value: object, *, limit: int = 500) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _error_payload(
    *,
    message: str | None = None,
    error_code: str | None = None,
    error_kind: str | None = None,
    retryable: bool | None = None,
) -> dict[str, Any]:
    return {
        "message": _clip(message, limit=500),
        "error_code": error_code,
        "error_kind": error_kind,
        "retryable": retryable,
    }


def _trace(correlation_id: uuid.UUID | None) -> dict[str, Any]:
    return {"correlation_id": str(correlation_id) if correlation_id else None}


def _elapsed_seconds(started_at: datetime | None, now: datetime) -> int | None:
    started = _aware(started_at)
    if not started:
        return None
    return max(0, int((now - started).total_seconds()))


def _duration_ms(started_at: datetime | None, completed_at: datetime | None) -> int | None:
    started = _aware(started_at)
    completed = _aware(completed_at)
    if not started or not completed:
        return None
    return max(0, int((completed - started).total_seconds() * 1000))


def _max_run_seconds(*values: int | None) -> int:
    for value in values:
        if value:
            return int(value)
    return int(settings.TASK_MAX_RUN_SECONDS)


async def _resolve_context(
    db: AsyncSession,
    *,
    bot_id: str | None,
    channel_id: str | uuid.UUID | None,
    session_id: str | uuid.UUID | None,
) -> tuple[str | None, Channel | None, Session | None]:
    resolved_session_id = _uuid_or_none(session_id)
    resolved_channel_id = _uuid_or_none(channel_id)
    session = await db.get(Session, resolved_session_id) if resolved_session_id else None
    if session:
        bot_id = bot_id or session.bot_id
        resolved_channel_id = resolved_channel_id or session.channel_id
    channel = await db.get(Channel, resolved_channel_id) if resolved_channel_id else None
    if channel:
        bot_id = bot_id or channel.bot_id
    return bot_id, channel, session


def _task_scope(
    stmt: Select[Any],
    *,
    bot_id: str | None,
    channel_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
) -> Select[Any]:
    if bot_id:
        stmt = stmt.where(Task.bot_id == bot_id)
    if channel_id:
        stmt = stmt.where(Task.channel_id == channel_id)
    if session_id:
        stmt = stmt.where(or_(Task.session_id == session_id, Task.run_session_id == session_id))
    return stmt


def _heartbeat_scope(
    stmt: Select[Any],
    *,
    bot_id: str | None,
    channel_id: uuid.UUID | None,
) -> Select[Any]:
    if channel_id:
        stmt = stmt.where(ChannelHeartbeat.channel_id == channel_id)
    if bot_id:
        stmt = stmt.where(Channel.bot_id == bot_id)
    return stmt


def _task_started_at(task: Task) -> datetime | None:
    return task.run_at or task.created_at


def _task_title(task: Task) -> str:
    return _clip(task.title, limit=240) or _clip(task.prompt, limit=240) or f"{task.task_type} task"


def _task_current(task: Task, *, now: datetime) -> dict[str, Any]:
    max_run = _max_run_seconds(task.max_run_seconds)
    started_at = _task_started_at(task)
    elapsed = _elapsed_seconds(started_at, now)
    return {
        "type": "task",
        "id": str(task.id),
        "task_id": str(task.id),
        "task_type": task.task_type,
        "channel_id": str(task.channel_id) if task.channel_id else None,
        "session_id": str(task.session_id) if task.session_id else None,
        "status": task.status,
        "started_at": _iso(started_at),
        "elapsed_seconds": elapsed,
        "max_run_seconds": max_run,
        "stale": elapsed is not None and elapsed > max_run,
        "summary": _task_title(task),
        "trace": _trace(task.correlation_id),
    }


def _heartbeat_current(run: HeartbeatRun, heartbeat: ChannelHeartbeat, *, now: datetime) -> dict[str, Any]:
    max_run = _max_run_seconds(heartbeat.max_run_seconds)
    elapsed = _elapsed_seconds(run.run_at, now)
    return {
        "type": "heartbeat",
        "id": str(run.id),
        "heartbeat_id": str(heartbeat.id),
        "task_id": str(run.task_id) if run.task_id else None,
        "channel_id": str(heartbeat.channel_id),
        "status": run.status,
        "started_at": _iso(run.run_at),
        "elapsed_seconds": elapsed,
        "max_run_seconds": max_run,
        "stale": elapsed is not None and elapsed > max_run,
        "summary": "Heartbeat run is in progress",
        "trace": _trace(run.correlation_id),
    }


def _task_run_item(task: Task, error: dict[str, Any] | None = None) -> dict[str, Any]:
    started_at = _task_started_at(task)
    return {
        "type": "task",
        "id": str(task.id),
        "task_id": str(task.id),
        "task_type": task.task_type,
        "channel_id": str(task.channel_id) if task.channel_id else None,
        "session_id": str(task.session_id) if task.session_id else None,
        "status": task.status,
        "started_at": _iso(started_at),
        "completed_at": _iso(task.completed_at),
        "duration_ms": _duration_ms(started_at, task.completed_at),
        "summary": _clip(task.result, limit=500) or _task_title(task),
        "trace": _trace(task.correlation_id),
        "error": error or _error_payload(message=task.error),
    }


def _heartbeat_run_item(
    run: HeartbeatRun,
    heartbeat: ChannelHeartbeat,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": "heartbeat",
        "id": str(run.id),
        "heartbeat_id": str(heartbeat.id),
        "task_id": str(run.task_id) if run.task_id else None,
        "channel_id": str(heartbeat.channel_id),
        "status": run.status,
        "started_at": _iso(run.run_at),
        "completed_at": _iso(run.completed_at),
        "duration_ms": _duration_ms(run.run_at, run.completed_at),
        "summary": _clip(run.result, limit=500) or "Heartbeat run",
        "trace": _trace(run.correlation_id),
        "error": error or _error_payload(message=run.error),
        "repetition_detected": run.repetition_detected,
    }


async def _tool_errors_for_correlations(
    db: AsyncSession,
    correlation_ids: list[uuid.UUID],
) -> dict[uuid.UUID, dict[str, Any]]:
    if not correlation_ids:
        return {}
    rows = list((await db.execute(
        select(ToolCall)
        .where(ToolCall.correlation_id.in_(correlation_ids))
        .where(or_(
            ToolCall.error_code.is_not(None),
            ToolCall.error_kind.is_not(None),
            ToolCall.retryable.is_not(None),
            ToolCall.error.is_not(None),
        ))
        .order_by(ToolCall.created_at.desc())
    )).scalars().all())
    errors: dict[uuid.UUID, dict[str, Any]] = {}
    for row in rows:
        if not row.correlation_id or row.correlation_id in errors:
            continue
        errors[row.correlation_id] = _error_payload(
            message=row.error,
            error_code=row.error_code,
            error_kind=row.error_kind,
            retryable=row.retryable,
        )
    return errors


async def _current_task(
    db: AsyncSession,
    *,
    bot_id: str | None,
    channel_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
) -> Task | None:
    stmt = (
        select(Task)
        .where(Task.status.in_(RUNNING_STATUSES))
        .order_by(func.coalesce(Task.run_at, Task.created_at).desc())
        .limit(1)
    )
    stmt = _task_scope(stmt, bot_id=bot_id, channel_id=channel_id, session_id=session_id)
    return (await db.execute(stmt)).scalars().first()


async def _current_heartbeat(
    db: AsyncSession,
    *,
    bot_id: str | None,
    channel_id: uuid.UUID | None,
) -> tuple[HeartbeatRun, ChannelHeartbeat] | None:
    stmt = (
        select(HeartbeatRun, ChannelHeartbeat)
        .join(ChannelHeartbeat, HeartbeatRun.heartbeat_id == ChannelHeartbeat.id)
        .join(Channel, ChannelHeartbeat.channel_id == Channel.id)
        .where(HeartbeatRun.status.in_(RUNNING_STATUSES))
        .order_by(HeartbeatRun.run_at.desc())
        .limit(1)
    )
    stmt = _heartbeat_scope(stmt, bot_id=bot_id, channel_id=channel_id)
    return (await db.execute(stmt)).first()


async def _heartbeat_snapshot(
    db: AsyncSession,
    *,
    bot_id: str | None,
    channel_id: uuid.UUID | None,
) -> dict[str, Any]:
    stmt = (
        select(ChannelHeartbeat)
        .join(Channel, ChannelHeartbeat.channel_id == Channel.id)
        .order_by(ChannelHeartbeat.enabled.desc(), ChannelHeartbeat.next_run_at.asc().nullslast())
        .limit(20)
    )
    stmt = _heartbeat_scope(stmt, bot_id=bot_id, channel_id=channel_id)
    heartbeats = list((await db.execute(stmt)).scalars().all())
    if not heartbeats:
        return {
            "configured": False,
            "configured_count": 0,
            "enabled": False,
            "channel_id": str(channel_id) if channel_id else None,
            "next_run_at": None,
            "last_run_at": None,
            "last_status": None,
            "last_error": None,
            "repetition_detected": None,
        }

    heartbeat = heartbeats[0]
    latest = (await db.execute(
        select(HeartbeatRun)
        .where(HeartbeatRun.heartbeat_id == heartbeat.id)
        .order_by(HeartbeatRun.run_at.desc())
        .limit(1)
    )).scalars().first()
    return {
        "configured": True,
        "configured_count": len(heartbeats),
        "enabled": heartbeat.enabled,
        "heartbeat_id": str(heartbeat.id),
        "channel_id": str(heartbeat.channel_id),
        "interval_minutes": heartbeat.interval_minutes,
        "next_run_at": _iso(heartbeat.next_run_at),
        "last_run_at": _iso(heartbeat.last_run_at or (latest.run_at if latest else None)),
        "last_status": latest.status if latest else None,
        "last_error": _clip(heartbeat.last_error or (latest.error if latest else None), limit=500),
        "repetition_detected": latest.repetition_detected if latest else None,
        "run_count": heartbeat.run_count,
        "max_run_seconds": _max_run_seconds(heartbeat.max_run_seconds),
    }


async def _recent_runs(
    db: AsyncSession,
    *,
    bot_id: str | None,
    channel_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    limit: int,
) -> list[dict[str, Any]]:
    task_stmt = (
        select(Task)
        .where(Task.status.not_in(["pending", "active"]))
        .order_by(func.coalesce(Task.run_at, Task.created_at).desc())
        .limit(limit)
    )
    task_stmt = _task_scope(task_stmt, bot_id=bot_id, channel_id=channel_id, session_id=session_id)
    tasks = list((await db.execute(task_stmt)).scalars().all())

    heartbeat_stmt = (
        select(HeartbeatRun, ChannelHeartbeat)
        .join(ChannelHeartbeat, HeartbeatRun.heartbeat_id == ChannelHeartbeat.id)
        .join(Channel, ChannelHeartbeat.channel_id == Channel.id)
        .order_by(HeartbeatRun.run_at.desc())
        .limit(limit)
    )
    heartbeat_stmt = _heartbeat_scope(heartbeat_stmt, bot_id=bot_id, channel_id=channel_id)
    heartbeat_rows = list((await db.execute(heartbeat_stmt)).all())

    correlation_ids = [
        value
        for value in [
            *(task.correlation_id for task in tasks),
            *(run.correlation_id for run, _heartbeat in heartbeat_rows),
        ]
        if value
    ]
    errors = await _tool_errors_for_correlations(db, correlation_ids)

    items: list[dict[str, Any]] = []
    seen_correlations: set[uuid.UUID] = set()
    for run, heartbeat in heartbeat_rows:
        if run.correlation_id:
            seen_correlations.add(run.correlation_id)
        items.append(_heartbeat_run_item(run, heartbeat, errors.get(run.correlation_id)))
    for task in tasks:
        if task.correlation_id and task.correlation_id in seen_correlations:
            continue
        items.append(_task_run_item(task, errors.get(task.correlation_id)))

    items.sort(key=lambda item: item.get("started_at") or "", reverse=True)
    return items[:limit]


async def _scheduled_task(
    db: AsyncSession,
    *,
    bot_id: str | None,
    channel_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
) -> Task | None:
    stmt = (
        select(Task)
        .where(Task.status.in_(SCHEDULED_TASK_STATUSES))
        .order_by(Task.run_at.asc().nullslast(), Task.created_at.desc())
        .limit(1)
    )
    stmt = _task_scope(stmt, bot_id=bot_id, channel_id=channel_id, session_id=session_id)
    return (await db.execute(stmt)).scalars().first()


def _derive_state(
    *,
    current: dict[str, Any] | None,
    heartbeat: dict[str, Any],
    recent_runs: list[dict[str, Any]],
    scheduled_task: Task | None,
) -> tuple[AgentState, AgentStatusRecommendation]:
    if current:
        if current.get("stale"):
            return "blocked", "review_stale_run"
        return "working", "wait_for_run"

    latest = recent_runs[0] if recent_runs else None
    if latest and latest.get("status") in FAILED_STATUSES:
        return "error", "review_failure"
    if latest and latest.get("repetition_detected"):
        return "blocked", "review_failure"

    if heartbeat.get("enabled") and heartbeat.get("next_run_at"):
        return "scheduled", "wait_for_run"
    if scheduled_task is not None:
        return "scheduled", "wait_for_run"
    if not heartbeat.get("configured"):
        return "idle", "enable_heartbeat"
    return "idle", "continue"


async def build_agent_status_snapshot(
    db: AsyncSession,
    *,
    bot_id: str | None = None,
    channel_id: str | uuid.UUID | None = None,
    session_id: str | uuid.UUID | None = None,
    limit: int = 10,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(now) or datetime.now(timezone.utc)
    resolved_bot_id, channel, session = await _resolve_context(
        db,
        bot_id=bot_id,
        channel_id=channel_id,
        session_id=session_id,
    )
    resolved_channel_id = channel.id if channel else _uuid_or_none(channel_id)
    resolved_session_id = session.id if session else _uuid_or_none(session_id)

    context = {
        "bot_id": resolved_bot_id,
        "channel_id": str(resolved_channel_id) if resolved_channel_id else None,
        "session_id": str(resolved_session_id) if resolved_session_id else None,
    }
    if not any(context.values()):
        return {
            "schema_version": "agent-status.v1",
            "available": False,
            "context": context,
            "state": "unknown",
            "recommendation": "unknown",
            "reason": "No bot, channel, or session context was resolved.",
            "current": None,
            "heartbeat": {"configured": False, "enabled": False},
            "recent_runs": [],
        }

    heartbeat = await _heartbeat_snapshot(
        db,
        bot_id=resolved_bot_id,
        channel_id=resolved_channel_id,
    )
    current_task = await _current_task(
        db,
        bot_id=resolved_bot_id,
        channel_id=resolved_channel_id,
        session_id=resolved_session_id,
    )
    current_heartbeat = await _current_heartbeat(
        db,
        bot_id=resolved_bot_id,
        channel_id=resolved_channel_id,
    )

    current_items: list[dict[str, Any]] = []
    if current_task is not None:
        current_items.append(_task_current(current_task, now=now))
    if current_heartbeat is not None:
        run, heartbeat_row = current_heartbeat
        current_items.append(_heartbeat_current(run, heartbeat_row, now=now))
    current_items.sort(key=lambda item: item.get("started_at") or "", reverse=True)
    current = current_items[0] if current_items else None

    recent_runs = await _recent_runs(
        db,
        bot_id=resolved_bot_id,
        channel_id=resolved_channel_id,
        session_id=resolved_session_id,
        limit=max(1, min(int(limit or 10), 50)),
    )
    scheduled_task = await _scheduled_task(
        db,
        bot_id=resolved_bot_id,
        channel_id=resolved_channel_id,
        session_id=resolved_session_id,
    )
    state, recommendation = _derive_state(
        current=current,
        heartbeat=heartbeat,
        recent_runs=recent_runs,
        scheduled_task=scheduled_task,
    )

    return {
        "schema_version": "agent-status.v1",
        "available": True,
        "context": context,
        "state": state,
        "recommendation": recommendation,
        "current": current,
        "heartbeat": heartbeat,
        "recent_runs": recent_runs,
    }
