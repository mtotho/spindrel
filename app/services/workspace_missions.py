"""Workspace missions.

Missions are the human-facing wrapper around existing task/chat execution.
They own durable intent and progress history; the actual LLM work is still
ordinary ``Task`` execution so traces, tool calls, sessions, model overrides,
and harness support stay on the established path.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import get_bot, list_bots
from app.agent.tasks import validate_recurrence
from app.db.models import (
    Channel,
    Task,
    WorkspaceMission,
    WorkspaceMissionAssignment,
    WorkspaceMissionUpdate,
)
from app.domain.errors import NotFoundError, ValidationError
from app.services.channels import apply_channel_visibility


DEFAULT_MISSION_RECURRENCE = "+4h"
MISSION_TASK_TYPES = {"mission_kickoff", "mission_tick"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _bot_name(bot_id: str) -> str:
    try:
        bot = get_bot(bot_id)
        return getattr(bot, "name", None) or getattr(bot, "display_name", None) or bot_id
    except Exception:
        return bot_id


def _bot_runtime(bot_id: str) -> str | None:
    try:
        return getattr(get_bot(bot_id), "harness_runtime", None)
    except Exception:
        return None


def _validate_bot(bot_id: str) -> None:
    try:
        get_bot(bot_id)
    except Exception as exc:  # noqa: BLE001 - normalize registry failures
        raise ValidationError(f"Unknown bot: {bot_id}") from exc


async def _visible_channel_ids(db: AsyncSession, auth: Any) -> set[uuid.UUID]:
    rows = list((await db.execute(apply_channel_visibility(select(Channel.id), auth))).scalars().all())
    return set(rows)


async def _get_visible_channel(db: AsyncSession, auth: Any, channel_id: uuid.UUID | None) -> Channel | None:
    if channel_id is None:
        return None
    stmt = apply_channel_visibility(select(Channel).where(Channel.id == channel_id), auth)
    channel = (await db.execute(stmt)).scalar_one_or_none()
    if channel is None:
        raise NotFoundError("Channel not found.")
    return channel


def normalize_mission_recurrence(recurrence: str | None, interval_kind: str | None) -> tuple[str, str | None]:
    kind = interval_kind or ("manual" if not recurrence else "preset")
    if kind not in {"manual", "preset", "custom"}:
        raise ValidationError("interval_kind must be manual, preset, or custom.")
    if kind == "manual":
        return "manual", None
    value = recurrence or DEFAULT_MISSION_RECURRENCE
    try:
        validate_recurrence(value)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    return kind, value


def _mission_execution_config(
    mission: WorkspaceMission,
    *,
    run_kind: str,
) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "tools": ["report_mission_progress"],
        "system_preamble": (
            "You are working on a Spindrel Workspace Mission. Make concrete progress, "
            "then call report_mission_progress with a concise update and next actions. "
            "Do not post routine progress to channel chat unless the mission explicitly asks."
        ),
        "mission_id": str(mission.id),
        "mission_run_kind": run_kind,
    }
    if mission.model_override:
        cfg["model_override"] = mission.model_override
    if mission.model_provider_id_override:
        cfg["model_provider_id_override"] = mission.model_provider_id_override
    if mission.fallback_models:
        cfg["fallback_models"] = mission.fallback_models
    if mission.harness_effort:
        cfg["harness_effort"] = mission.harness_effort
    if mission.history_mode:
        cfg["history_mode"] = mission.history_mode
    if mission.history_recent_count is not None:
        cfg["history_recent_count"] = mission.history_recent_count
    return cfg


async def _recent_update_lines(db: AsyncSession, mission_id: uuid.UUID, limit: int = 6) -> list[str]:
    rows = list((await db.execute(
        select(WorkspaceMissionUpdate)
        .where(WorkspaceMissionUpdate.mission_id == mission_id)
        .order_by(desc(WorkspaceMissionUpdate.created_at))
        .limit(limit)
    )).scalars().all())
    lines = []
    for row in reversed(rows):
        label = row.kind
        bot = f" by {row.bot_id}" if row.bot_id else ""
        lines.append(f"- [{label}{bot}] {row.summary[:800]}")
    return lines


async def build_mission_prompt(
    db: AsyncSession,
    mission: WorkspaceMission,
    *,
    run_kind: str,
) -> str:
    updates = await _recent_update_lines(db, mission.id)
    update_block = "\n".join(updates) if updates else "- none yet"
    return (
        f"[MISSION {run_kind.upper()}]\n"
        f"Mission id: {mission.id}\n"
        f"Title: {mission.title}\n"
        f"Scope: {mission.scope}\n"
        f"Channel id: {mission.channel_id or 'workspace'}\n"
        f"Play: {mission.play_key or 'general'}\n\n"
        f"Directive:\n{mission.directive}\n\n"
        f"Recent mission updates:\n{update_block}\n\n"
        "Do useful work toward the mission. End by calling report_mission_progress "
        "with a short update and 1-3 next actions. Your final text response should "
        "match the same concise update."
    )


async def _append_update(
    db: AsyncSession,
    mission: WorkspaceMission,
    *,
    bot_id: str | None,
    kind: str,
    summary: str,
    next_actions: list[str] | None = None,
    task_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    correlation_id: uuid.UUID | None = None,
) -> WorkspaceMissionUpdate:
    now = _now()
    update = WorkspaceMissionUpdate(
        mission_id=mission.id,
        bot_id=bot_id,
        kind=kind,
        summary=summary.strip()[:8000],
        next_actions=[str(a).strip() for a in (next_actions or []) if str(a).strip()][:6],
        task_id=task_id,
        session_id=session_id,
        correlation_id=correlation_id,
        created_at=now,
    )
    db.add(update)
    mission.last_update_at = now
    mission.last_task_id = task_id or mission.last_task_id
    mission.last_correlation_id = correlation_id or mission.last_correlation_id
    mission.updated_at = now
    if bot_id:
        assignment = (await db.execute(
            select(WorkspaceMissionAssignment).where(
                WorkspaceMissionAssignment.mission_id == mission.id,
                WorkspaceMissionAssignment.bot_id == bot_id,
            )
        )).scalar_one_or_none()
        if assignment:
            assignment.last_update_at = now
            assignment.updated_at = now
    await db.flush()
    return update


async def _create_mission_task(
    db: AsyncSession,
    mission: WorkspaceMission,
    *,
    bot_id: str,
    run_kind: str,
    scheduled_at: datetime | None = None,
    recurrence: str | None = None,
    status: str = "pending",
) -> Task:
    prompt = await build_mission_prompt(db, mission, run_kind=run_kind)
    task = Task(
        bot_id=bot_id,
        channel_id=mission.channel_id,
        prompt=prompt,
        title=f"Mission: {mission.title}",
        status=status,
        scheduled_at=scheduled_at or _now(),
        recurrence=recurrence,
        task_type=f"mission_{run_kind}",
        dispatch_type="none",
        dispatch_config={},
        callback_config={"mission_id": str(mission.id), "mission_run_kind": run_kind},
        execution_config=_mission_execution_config(mission, run_kind=run_kind),
        created_at=_now(),
    )
    db.add(task)
    await db.flush()
    return task


async def serialize_mission(
    db: AsyncSession,
    mission: WorkspaceMission,
    *,
    include_updates: int = 5,
) -> dict[str, Any]:
    assignments = list((await db.execute(
        select(WorkspaceMissionAssignment)
        .where(WorkspaceMissionAssignment.mission_id == mission.id)
        .order_by(WorkspaceMissionAssignment.created_at.asc())
    )).scalars().all())
    updates = list((await db.execute(
        select(WorkspaceMissionUpdate)
        .where(WorkspaceMissionUpdate.mission_id == mission.id)
        .order_by(desc(WorkspaceMissionUpdate.created_at))
        .limit(include_updates)
    )).scalars().all())
    channel_name = None
    if mission.channel_id:
        channel = await db.get(Channel, mission.channel_id)
        channel_name = channel.name if channel else None
    schedule = await db.get(Task, mission.schedule_task_id) if mission.schedule_task_id else None
    return {
        "id": str(mission.id),
        "title": mission.title,
        "directive": mission.directive,
        "status": mission.status,
        "scope": mission.scope,
        "channel_id": str(mission.channel_id) if mission.channel_id else None,
        "channel_name": channel_name,
        "play_key": mission.play_key,
        "interval_kind": mission.interval_kind,
        "recurrence": mission.recurrence,
        "model_override": mission.model_override,
        "model_provider_id_override": mission.model_provider_id_override,
        "fallback_models": mission.fallback_models or [],
        "harness_effort": mission.harness_effort,
        "history_mode": mission.history_mode,
        "history_recent_count": mission.history_recent_count,
        "kickoff_task_id": str(mission.kickoff_task_id) if mission.kickoff_task_id else None,
        "schedule_task_id": str(mission.schedule_task_id) if mission.schedule_task_id else None,
        "last_task_id": str(mission.last_task_id) if mission.last_task_id else None,
        "last_correlation_id": str(mission.last_correlation_id) if mission.last_correlation_id else None,
        "last_update_at": _iso(mission.last_update_at),
        "next_run_at": _iso(schedule.scheduled_at if schedule and schedule.status == "active" else mission.next_run_at),
        "created_by": mission.created_by,
        "created_at": _iso(mission.created_at),
        "updated_at": _iso(mission.updated_at),
        "assignments": [
            {
                "id": str(row.id),
                "mission_id": str(row.mission_id),
                "bot_id": row.bot_id,
                "bot_name": _bot_name(row.bot_id),
                "harness_runtime": _bot_runtime(row.bot_id),
                "role": row.role,
                "status": row.status,
                "target_channel_id": str(row.target_channel_id) if row.target_channel_id else None,
                "last_update_at": _iso(row.last_update_at),
                "created_at": _iso(row.created_at),
            }
            for row in assignments
        ],
        "updates": [
            {
                "id": str(row.id),
                "mission_id": str(row.mission_id),
                "bot_id": row.bot_id,
                "bot_name": _bot_name(row.bot_id) if row.bot_id else None,
                "kind": row.kind,
                "summary": row.summary,
                "next_actions": row.next_actions or [],
                "task_id": str(row.task_id) if row.task_id else None,
                "session_id": str(row.session_id) if row.session_id else None,
                "correlation_id": str(row.correlation_id) if row.correlation_id else None,
                "created_at": _iso(row.created_at),
            }
            for row in updates
        ],
    }


async def list_missions(
    db: AsyncSession,
    *,
    auth: Any,
    include_completed: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    visible = await _visible_channel_ids(db, auth)
    stmt = select(WorkspaceMission).where(
        or_(WorkspaceMission.channel_id.is_(None), WorkspaceMission.channel_id.in_(visible))
    )
    if not include_completed:
        stmt = stmt.where(WorkspaceMission.status.in_(["active", "paused"]))
    stmt = stmt.order_by(desc(WorkspaceMission.updated_at)).limit(max(1, min(limit, 250)))
    rows = list((await db.execute(stmt)).scalars().all())
    return [await serialize_mission(db, row) for row in rows]


async def create_mission(
    db: AsyncSession,
    *,
    auth: Any,
    actor: str,
    title: str,
    directive: str,
    scope: str = "workspace",
    channel_id: uuid.UUID | None = None,
    bot_id: str | None = None,
    play_key: str | None = None,
    interval_kind: str | None = "preset",
    recurrence: str | None = DEFAULT_MISSION_RECURRENCE,
    model_override: str | None = None,
    model_provider_id_override: str | None = None,
    fallback_models: list[dict] | None = None,
    harness_effort: str | None = None,
    history_mode: str | None = "recent",
    history_recent_count: int | None = 8,
) -> WorkspaceMission:
    title = title.strip()
    directive = directive.strip()
    if not title:
        raise ValidationError("Mission title is required.")
    if not directive:
        raise ValidationError("Mission directive is required.")
    if scope not in {"workspace", "channel"}:
        raise ValidationError("scope must be workspace or channel.")
    channel = await _get_visible_channel(db, auth, channel_id)
    if scope == "channel" and channel is None:
        raise ValidationError("Channel missions require channel_id.")
    effective_bot_id = bot_id or (channel.bot_id if channel else None)
    if not effective_bot_id:
        bots = sorted(list_bots(), key=lambda bot: bot.name.lower())
        effective_bot_id = bots[0].id if bots else None
    if not effective_bot_id:
        raise ValidationError("Mission requires an assigned bot.")
    _validate_bot(effective_bot_id)
    kind, normalized_recurrence = normalize_mission_recurrence(recurrence, interval_kind)
    if history_mode is not None and history_mode not in {"none", "recent", "full"}:
        raise ValidationError("history_mode must be none, recent, or full.")

    mission = WorkspaceMission(
        title=title,
        directive=directive,
        status="active",
        scope=scope,
        channel_id=channel.id if channel else None,
        play_key=(play_key or "").strip() or None,
        interval_kind=kind,
        recurrence=normalized_recurrence,
        model_override=(model_override or "").strip() or None,
        model_provider_id_override=(model_provider_id_override or "").strip() or None,
        fallback_models=fallback_models or [],
        harness_effort=(harness_effort or "").strip() or None,
        history_mode=history_mode,
        history_recent_count=history_recent_count,
        created_by=actor,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(mission)
    await db.flush()
    db.add(WorkspaceMissionAssignment(
        mission_id=mission.id,
        bot_id=effective_bot_id,
        role="owner",
        status="active",
        target_channel_id=mission.channel_id,
    ))
    await _append_update(
        db,
        mission,
        bot_id=None,
        kind="created",
        summary=f"Mission created: {directive[:500]}",
        next_actions=["Kickoff run queued"],
    )
    kickoff = await _create_mission_task(db, mission, bot_id=effective_bot_id, run_kind="kickoff")
    mission.kickoff_task_id = kickoff.id
    mission.last_task_id = kickoff.id
    if normalized_recurrence:
        schedule = await _create_mission_task(
            db,
            mission,
            bot_id=effective_bot_id,
            run_kind="tick",
            scheduled_at=_now(),
            recurrence=normalized_recurrence,
            status="active",
        )
        mission.schedule_task_id = schedule.id
        mission.next_run_at = schedule.scheduled_at
    await db.commit()
    await db.refresh(mission)
    return mission


async def get_mission(db: AsyncSession, mission_id: uuid.UUID, *, auth: Any | None = None) -> WorkspaceMission:
    mission = await db.get(WorkspaceMission, mission_id)
    if mission is None:
        raise NotFoundError("Mission not found.")
    if auth is not None and mission.channel_id:
        visible = await _visible_channel_ids(db, auth)
        if mission.channel_id not in visible:
            raise NotFoundError("Mission not found.")
    return mission


async def set_mission_status(
    db: AsyncSession,
    mission_id: uuid.UUID,
    *,
    auth: Any,
    status: str,
) -> WorkspaceMission:
    if status not in {"active", "paused", "completed", "cancelled"}:
        raise ValidationError("Invalid mission status.")
    mission = await get_mission(db, mission_id, auth=auth)
    mission.status = status
    mission.updated_at = _now()
    if mission.schedule_task_id:
        task = await db.get(Task, mission.schedule_task_id)
        if task:
            task.status = "active" if status == "active" else "cancelled"
    await db.commit()
    await db.refresh(mission)
    return mission


async def run_mission_now(
    db: AsyncSession,
    mission_id: uuid.UUID,
    *,
    auth: Any,
) -> WorkspaceMission:
    mission = await get_mission(db, mission_id, auth=auth)
    if mission.status not in {"active", "paused"}:
        raise ValidationError("Only active or paused missions can run.")
    assignment = (await db.execute(
        select(WorkspaceMissionAssignment)
        .where(
            WorkspaceMissionAssignment.mission_id == mission.id,
            WorkspaceMissionAssignment.status == "active",
        )
        .order_by(WorkspaceMissionAssignment.created_at.asc())
        .limit(1)
    )).scalar_one_or_none()
    if assignment is None:
        raise ValidationError("Mission has no active bot assignment.")
    task = await _create_mission_task(db, mission, bot_id=assignment.bot_id, run_kind="tick")
    mission.last_task_id = task.id
    mission.updated_at = _now()
    await db.commit()
    await db.refresh(mission)
    return mission


async def assign_mission_bot(
    db: AsyncSession,
    mission_id: uuid.UUID,
    *,
    auth: Any,
    bot_id: str,
    target_channel_id: uuid.UUID | None = None,
) -> WorkspaceMission:
    mission = await get_mission(db, mission_id, auth=auth)
    _validate_bot(bot_id)
    if target_channel_id:
        await _get_visible_channel(db, auth, target_channel_id)
    assignment = (await db.execute(
        select(WorkspaceMissionAssignment).where(
            WorkspaceMissionAssignment.mission_id == mission.id,
            WorkspaceMissionAssignment.bot_id == bot_id,
        )
    )).scalar_one_or_none()
    if assignment is None:
        assignment = WorkspaceMissionAssignment(
            mission_id=mission.id,
            bot_id=bot_id,
            role="support" if mission.schedule_task_id else "owner",
            status="active",
            target_channel_id=target_channel_id or mission.channel_id,
        )
        db.add(assignment)
    else:
        assignment.status = "active"
        assignment.target_channel_id = target_channel_id or assignment.target_channel_id or mission.channel_id
        assignment.updated_at = _now()
    if mission.schedule_task_id:
        task = await db.get(Task, mission.schedule_task_id)
        if task:
            task.bot_id = bot_id
            task.channel_id = target_channel_id or mission.channel_id
    mission.updated_at = _now()
    await db.commit()
    await db.refresh(mission)
    return mission


async def report_mission_progress(
    db: AsyncSession,
    mission_id: uuid.UUID,
    *,
    bot_id: str,
    summary: str,
    next_actions: list[str] | None = None,
    task_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    correlation_id: uuid.UUID | None = None,
) -> WorkspaceMissionUpdate:
    mission = await get_mission(db, mission_id)
    assignment = (await db.execute(
        select(WorkspaceMissionAssignment).where(
            WorkspaceMissionAssignment.mission_id == mission.id,
            WorkspaceMissionAssignment.bot_id == bot_id,
            WorkspaceMissionAssignment.status == "active",
        )
    )).scalar_one_or_none()
    if assignment is None:
        raise ValidationError("This bot is not actively assigned to the mission.")
    update = await _append_update(
        db,
        mission,
        bot_id=bot_id,
        kind="progress",
        summary=summary,
        next_actions=next_actions,
        task_id=task_id,
        session_id=session_id,
        correlation_id=correlation_id,
    )
    await db.commit()
    await db.refresh(update)
    return update


async def on_mission_task_complete(task_id: uuid.UUID, status: str) -> None:
    from app.db.engine import async_session

    async with async_session() as db:
        task = await db.get(Task, task_id)
        if task is None:
            return
        cb = task.callback_config or {}
        mission_id_raw = cb.get("mission_id")
        if not mission_id_raw:
            return
        try:
            mission_id = uuid.UUID(str(mission_id_raw))
        except ValueError:
            return
        mission = await db.get(WorkspaceMission, mission_id)
        if mission is None:
            return
        mission.last_task_id = task.id
        mission.last_correlation_id = task.correlation_id
        if task.parent_task_id == mission.schedule_task_id and mission.schedule_task_id:
            schedule = await db.get(Task, mission.schedule_task_id)
            mission.next_run_at = schedule.scheduled_at if schedule else mission.next_run_at
        existing_for_task = (await db.execute(
            select(func.count(WorkspaceMissionUpdate.id)).where(
                WorkspaceMissionUpdate.mission_id == mission.id,
                WorkspaceMissionUpdate.task_id == task.id,
            )
        )).scalar_one()
        if existing_for_task:
            mission.updated_at = _now()
            await db.commit()
            return
        if status == "complete":
            summary = (task.result or "Mission run completed.").strip()
            kind = "kickoff" if cb.get("mission_run_kind") == "kickoff" else "result"
        else:
            summary = (task.error or f"Mission run ended with status {status}.").strip()
            kind = "error"
        await _append_update(
            db,
            mission,
            bot_id=task.bot_id,
            kind=kind,
            summary=summary[:8000],
            next_actions=[],
            task_id=task.id,
            session_id=task.session_id,
            correlation_id=task.correlation_id,
        )
        await db.commit()
