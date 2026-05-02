"""Session target policy for automated task and heartbeat runs.

This is intentionally separate from ``Task.run_isolation``.  Run isolation is
the pipeline transcript/sub-session mechanism; session target answers which
channel session a scheduled/manual run should use as its chat context.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, ChannelIntegration, Session, Task

SESSION_TARGET_KEY = "session_target"
SESSION_TARGET_PRIMARY = "primary"
SESSION_TARGET_EXISTING = "existing"
SESSION_TARGET_NEW_EACH_RUN = "new_each_run"
SESSION_TARGET_MODES = {
    SESSION_TARGET_PRIMARY,
    SESSION_TARGET_EXISTING,
    SESSION_TARGET_NEW_EACH_RUN,
}


def normalize_session_target(value: Any) -> dict[str, Any]:
    """Return a canonical JSON-serializable session target policy."""
    if value is None:
        return {"mode": SESSION_TARGET_PRIMARY}
    if not isinstance(value, dict):
        raise ValueError("session_target must be an object")

    mode = str(value.get("mode") or SESSION_TARGET_PRIMARY).strip()
    if mode not in SESSION_TARGET_MODES:
        raise ValueError(
            "session_target.mode must be one of: "
            f"{', '.join(sorted(SESSION_TARGET_MODES))}"
        )
    if mode != SESSION_TARGET_EXISTING:
        return {"mode": mode}

    raw_session_id = value.get("session_id")
    if not raw_session_id:
        raise ValueError("session_target.session_id is required for existing mode")
    try:
        session_id = str(uuid.UUID(str(raw_session_id)))
    except (TypeError, ValueError) as exc:
        raise ValueError("session_target.session_id must be a valid UUID") from exc
    return {"mode": SESSION_TARGET_EXISTING, "session_id": session_id}


def _default_session_target_for_task(task: Task) -> dict[str, Any]:
    """Return the implicit session target when a task did not configure one.

    Channel automation defaults to the current primary session so scheduled and
    manual channel tasks follow the live conversation. API message tasks are
    different: the caller already posted a user message into a concrete session,
    so the agent response must stay in that same session.
    """
    if task.task_type == "api" and task.session_id is not None:
        return {"mode": SESSION_TARGET_EXISTING, "session_id": str(task.session_id)}
    return {"mode": SESSION_TARGET_PRIMARY}


def set_session_target_in_config(
    config: dict[str, Any] | None,
    value: Any,
) -> dict[str, Any]:
    """Return a copy of ``config`` with normalized ``session_target`` set."""
    next_config = dict(config or {})
    next_config[SESSION_TARGET_KEY] = normalize_session_target(value)
    return next_config


async def validate_session_target_for_channel(
    db: AsyncSession,
    channel_id: uuid.UUID | None,
    value: Any,
) -> dict[str, Any]:
    """Normalize and validate a target policy for a channel-owned run."""
    target = normalize_session_target(value)
    if target["mode"] == SESSION_TARGET_PRIMARY:
        return target

    if channel_id is None:
        raise ValueError("A channel is required for this session target")

    if target["mode"] == SESSION_TARGET_NEW_EACH_RUN:
        channel = await db.get(Channel, channel_id)
        if channel is None:
            raise ValueError("Channel not found")
        return target

    session = await db.get(Session, uuid.UUID(target["session_id"]))
    if session is None:
        raise ValueError("Selected session not found")
    if session.channel_id != channel_id or session.session_type != "channel":
        raise ValueError("Selected session does not belong to this channel")
    return target


async def _create_detached_channel_session_for_task(
    db: AsyncSession,
    channel: Channel,
    task: Task,
) -> uuid.UUID:
    has_integration = channel.integration is not None
    if not has_integration:
        result = await db.execute(
            select(ChannelIntegration.id)
            .where(ChannelIntegration.channel_id == channel.id)
            .limit(1)
        )
        has_integration = result.scalar_one_or_none() is not None

    session_id = uuid.uuid4()
    session = Session(
        id=session_id,
        client_id=channel.client_id or f"channel:{channel.id}",
        bot_id=task.bot_id,
        channel_id=channel.id,
        locked=has_integration,
        metadata_={
            "created_by": "task_session_target",
            "source_task_id": str(task.id),
        },
    )
    db.add(session)
    channel.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return session_id


async def resolve_task_session_target(
    db: AsyncSession,
    task: Task,
) -> tuple[uuid.UUID | None, Channel | None]:
    """Resolve and persist the concrete session for a task run.

    Returns the resolved session id and channel row.  Tasks without channels,
    delegated tasks, eval tasks, and already session-scoped pipeline children
    keep their current ``session_id`` unchanged.
    """
    if task.channel_id is None:
        return task.session_id, None
    if task.task_type in ("delegation", "eval"):
        return task.session_id, None
    if bool((task.execution_config or {}).get("session_scoped")):
        return task.session_id, None

    channel = await db.get(Channel, task.channel_id)
    if channel is None:
        return task.session_id, None

    execution_config = task.execution_config or {}
    if SESSION_TARGET_KEY in execution_config:
        target = normalize_session_target(execution_config.get(SESSION_TARGET_KEY))
    else:
        target = _default_session_target_for_task(task)
    if target["mode"] == SESSION_TARGET_PRIMARY:
        from app.services.channels import ensure_active_session

        resolved_session_id = await ensure_active_session(db, channel)
    elif target["mode"] == SESSION_TARGET_EXISTING:
        session = await db.get(Session, uuid.UUID(target["session_id"]))
        if (
            session is None
            or session.channel_id != channel.id
            or session.session_type != "channel"
        ):
            raise ValueError("Selected session does not belong to this channel")
        resolved_session_id = session.id
    else:
        resolved_session_id = await _create_detached_channel_session_for_task(db, channel, task)

    if task.session_id != resolved_session_id:
        task.session_id = resolved_session_id
        db_task = await db.get(Task, task.id)
        if db_task is not None:
            db_task.session_id = resolved_session_id
            db_task.client_id = channel.client_id
            db_task.channel_id = channel.id
            db_task.execution_config = dict(task.execution_config or {})
        task.client_id = channel.client_id
        await db.flush()
    return resolved_session_id, channel
