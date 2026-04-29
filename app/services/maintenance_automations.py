"""Read model for bot-scoped maintenance automations.

The backing storage still lives on Bot columns and concrete executions still
use Task rows. This service gives admin/dashboard/schedule surfaces one shared
view of the two maintenance job definitions without migrating schema.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DEFAULT_MEMORY_HYGIENE_PROMPT, DEFAULT_SKILL_REVIEW_PROMPT
from app.db.models import Bot as BotRow, Task

MaintenanceJobType = Literal["memory_hygiene", "skill_review"]
MAINTENANCE_JOB_TYPES: tuple[MaintenanceJobType, ...] = ("memory_hygiene", "skill_review")

_DEFAULT_PROMPTS: dict[MaintenanceJobType, str] = {
    "memory_hygiene": DEFAULT_MEMORY_HYGIENE_PROMPT,
    "skill_review": DEFAULT_SKILL_REVIEW_PROMPT,
}
_JOB_TITLES: dict[MaintenanceJobType, str] = {
    "memory_hygiene": "Memory maintenance",
    "skill_review": "Skill review",
}
_LEGACY_UPCOMING_TYPES: dict[MaintenanceJobType, str] = {
    "memory_hygiene": "memory_hygiene",
    "skill_review": "skill_review",
}


@dataclass(frozen=True)
class MaintenanceJob:
    bot_id: str
    bot_name: str
    job_type: MaintenanceJobType
    title: str
    enabled: bool
    interval_hours: int
    only_if_active: bool
    resolved_prompt: str
    has_custom_prompt: bool
    extra_instructions: str | None
    last_run_at: datetime | None
    next_run_at: datetime | None
    last_task_status: str | None
    last_task_id: str | None
    model: str | None
    model_provider_id: str | None
    target_hour: int


def is_maintenance_job_type(task_type: str | None) -> bool:
    return task_type in MAINTENANCE_JOB_TYPES


def maintenance_job_title(job_type: MaintenanceJobType) -> str:
    return _JOB_TITLES[job_type]


def _job_meta(job_type: MaintenanceJobType) -> dict:
    from app.services.memory_hygiene import _JOB_META

    return _JOB_META[job_type]


def build_maintenance_job(
    bot_row: BotRow,
    job_type: MaintenanceJobType,
    *,
    last_task: Task | None = None,
) -> MaintenanceJob:
    from app.services.memory_hygiene import resolve_config

    meta = _job_meta(job_type)
    cfg = resolve_config(bot_row, job_type)
    default_prompt = _DEFAULT_PROMPTS[job_type]
    return MaintenanceJob(
        bot_id=bot_row.id,
        bot_name=bot_row.name,
        job_type=job_type,
        title=_JOB_TITLES[job_type],
        enabled=cfg.enabled,
        interval_hours=cfg.interval_hours,
        only_if_active=cfg.only_if_active,
        resolved_prompt=cfg.prompt,
        has_custom_prompt=bool(cfg.prompt and cfg.prompt != default_prompt),
        extra_instructions=cfg.extra_instructions,
        last_run_at=getattr(bot_row, meta["col_last_run"], None),
        next_run_at=getattr(bot_row, meta["col_next_run"], None),
        last_task_status=last_task.status if last_task else None,
        last_task_id=str(last_task.id) if last_task else None,
        model=cfg.model,
        model_provider_id=cfg.model_provider_id,
        target_hour=cfg.target_hour,
    )


async def _latest_tasks_by_bot_and_type(
    db: AsyncSession,
    bot_ids: list[str],
) -> dict[tuple[str, MaintenanceJobType], Task]:
    if not bot_ids:
        return {}
    tasks = (await db.execute(
        select(Task)
        .where(Task.bot_id.in_(bot_ids), Task.task_type.in_(MAINTENANCE_JOB_TYPES))
        .order_by(Task.created_at.desc())
    )).scalars().all()
    latest: dict[tuple[str, MaintenanceJobType], Task] = {}
    for task in tasks:
        key = (task.bot_id, task.task_type)
        if key not in latest and is_maintenance_job_type(task.task_type):
            latest[key] = task
    return latest


async def list_maintenance_jobs(
    db: AsyncSession,
    *,
    bot_ids: list[str] | None = None,
    enabled_only: bool = False,
) -> list[MaintenanceJob]:
    """Return resolved bot-scoped maintenance definitions."""
    stmt = select(BotRow).where(BotRow.memory_scheme == "workspace-files")
    if bot_ids is not None:
        stmt = stmt.where(BotRow.id.in_(bot_ids))
    bots = (await db.execute(stmt)).scalars().all()

    latest = await _latest_tasks_by_bot_and_type(db, [bot.id for bot in bots])
    jobs: list[MaintenanceJob] = []
    for bot in bots:
        for job_type in MAINTENANCE_JOB_TYPES:
            job = build_maintenance_job(bot, job_type, last_task=latest.get((bot.id, job_type)))
            if enabled_only and not job.enabled:
                continue
            jobs.append(job)
    return jobs


async def get_bot_maintenance_jobs(db: AsyncSession, bot_id: str) -> dict[MaintenanceJobType, MaintenanceJob]:
    jobs = await list_maintenance_jobs(db, bot_ids=[bot_id])
    return {job.job_type: job for job in jobs}


async def list_upcoming_maintenance_items(db: AsyncSession) -> list[dict]:
    """Return upcoming maintenance rows in the upcoming-activity item shape."""
    jobs = await list_maintenance_jobs(db, enabled_only=True)
    items: list[dict] = []
    for job in jobs:
        if job.next_run_at is None:
            continue
        items.append({
            "type": "maintenance",
            "legacy_type": _LEGACY_UPCOMING_TYPES[job.job_type],
            "scheduled_at": job.next_run_at.isoformat(),
            "bot_id": job.bot_id,
            "bot_name": job.bot_name,
            "channel_id": None,
            "channel_name": None,
            "title": job.title,
            "task_type": job.job_type,
            "job_type": job.job_type,
            "interval_hours": job.interval_hours,
        })
    items.sort(key=lambda item: item.get("scheduled_at") or "9999")
    return items
