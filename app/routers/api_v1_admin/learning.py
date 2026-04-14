"""Learning Center aggregate endpoint: /learning/overview."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bot as BotRow, BotSkillEnrollment, Skill as SkillRow, Task as TaskRow, ToolCall, TraceEvent
from app.dependencies import get_db, require_scopes

from ._helpers import build_tool_call_previews

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/learning", tags=["Learning Center"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class BotDreamingStatus(BaseModel):
    bot_id: str
    bot_name: str
    enabled: bool
    last_run_at: Optional[str] = None
    last_task_status: Optional[str] = None
    next_run_at: Optional[str] = None
    interval_hours: int = 24
    model: Optional[str] = None

class RecentHygieneRun(BaseModel):
    id: str
    bot_id: str
    bot_name: str
    status: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    result: Optional[str] = None
    error: Optional[str] = None
    correlation_id: Optional[str] = None
    tool_calls: list[dict] = []
    total_tokens: int = 0
    iterations: int = 0
    duration_ms: Optional[int] = None
    files_affected: list[str] = []  # memory file paths written during this run
    skill_overrides: list[dict] = []  # [{skill_id, source, reason, age_days, archived}]

class MemoryFileActivity(BaseModel):
    bot_id: str
    bot_name: str
    file_path: str
    operation: str  # write, append, edit
    created_at: datetime
    is_hygiene: bool = False
    correlation_id: Optional[str] = None

class LearningOverviewOut(BaseModel):
    total_bots: int = 0
    dreaming_enabled_count: int = 0
    total_hygiene_runs_7d: int = 0
    total_bot_skills: int = 0
    total_surfacings: int = 0
    total_auto_injects: int = 0
    bots: list[BotDreamingStatus] = []
    recent_runs: list[RecentHygieneRun] = []
    memory_activity: list[MemoryFileActivity] = []


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("/overview", response_model=LearningOverviewOut)
async def learning_overview(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("bots:read")),
):
    """Aggregate learning/dreaming dashboard data across all bots."""
    from app.services.memory_hygiene import (
        resolve_enabled, resolve_interval, resolve_model,
    )

    # 1. All bots with workspace-files memory
    all_bots = (await db.execute(
        select(BotRow).where(BotRow.memory_scheme == "workspace-files")
    )).scalars().all()

    bot_statuses: list[BotDreamingStatus] = []
    enabled_count = 0
    bot_name_map: dict[str, str] = {}
    bot_ids = [bot.id for bot in all_bots]

    for bot in all_bots:
        bot_name_map[bot.id] = bot.name

    # Batch: get last hygiene task status per bot in one query
    last_task_map: dict[str, str] = {}
    if bot_ids:
        # Window function to get latest task per bot in one query
        latest_subq = (
            select(
                TaskRow.bot_id,
                TaskRow.status,
                func.row_number().over(
                    partition_by=TaskRow.bot_id,
                    order_by=TaskRow.created_at.desc(),
                ).label("rn"),
            )
            .where(TaskRow.bot_id.in_(bot_ids), TaskRow.task_type == "memory_hygiene")
            .subquery()
        )
        latest_rows = (await db.execute(
            select(latest_subq.c.bot_id, latest_subq.c.status)
            .where(latest_subq.c.rn == 1)
        )).all()
        for row in latest_rows:
            last_task_map[row.bot_id] = row.status

    for bot in all_bots:
        enabled = resolve_enabled(bot)
        interval = resolve_interval(bot)
        model = resolve_model(bot)
        if enabled:
            enabled_count += 1

        bot_statuses.append(BotDreamingStatus(
            bot_id=bot.id,
            bot_name=bot.name,
            enabled=enabled,
            last_run_at=bot.last_hygiene_run_at.isoformat() if bot.last_hygiene_run_at else None,
            last_task_status=last_task_map.get(bot.id),
            next_run_at=bot.next_hygiene_run_at.isoformat() if bot.next_hygiene_run_at else None,
            interval_hours=interval,
            model=model,
        ))

    bot_statuses.sort(key=lambda b: b.bot_name.lower())

    # 2. Recent hygiene runs across all bots (last 20)
    recent_tasks = (await db.execute(
        select(TaskRow)
        .where(TaskRow.task_type == "memory_hygiene")
        .order_by(TaskRow.created_at.desc())
        .limit(20)
    )).scalars().all()

    runs_out: list[RecentHygieneRun] = []
    for t in recent_tasks:
        runs_out.append(RecentHygieneRun(
            id=str(t.id),
            bot_id=t.bot_id,
            bot_name=bot_name_map.get(t.bot_id, t.bot_id),
            status=t.status,
            created_at=t.created_at,
            completed_at=t.completed_at,
            result=(t.result[:500] if t.result and len(t.result) > 500 else t.result),
            error=t.error,
            correlation_id=str(t.correlation_id) if t.correlation_id else None,
        ))

    # Enrich runs with tool calls and token stats
    correlation_ids = [t.correlation_id for t in recent_tasks if t.correlation_id]
    if correlation_ids:
        tc_rows = (await db.execute(
            select(ToolCall)
            .where(ToolCall.correlation_id.in_(correlation_ids))
            .order_by(ToolCall.created_at)
        )).scalars().all()
        tc_by_corr: dict = {}
        for tc in tc_rows:
            tc_by_corr.setdefault(tc.correlation_id, []).append(tc)

        te_rows = (await db.execute(
            select(TraceEvent)
            .where(
                TraceEvent.correlation_id.in_(correlation_ids),
                TraceEvent.event_type == "token_usage",
            )
        )).scalars().all()
        stats_by_corr: dict = {}
        for te in te_rows:
            s = stats_by_corr.setdefault(te.correlation_id, {"tokens": 0, "iterations": 0})
            if te.data:
                s["tokens"] += te.data.get("total_tokens", 0)
                s["iterations"] = max(s["iterations"], te.data.get("iteration", 0))

        for run, task in zip(runs_out, recent_tasks):
            if not task.correlation_id:
                continue
            tcs = tc_by_corr.get(task.correlation_id, [])
            if tcs:
                run.tool_calls = build_tool_call_previews(tcs)
            stats = stats_by_corr.get(task.correlation_id)
            if stats:
                run.total_tokens = stats["tokens"]
                run.iterations = stats["iterations"]
            if task.completed_at and task.created_at:
                run.duration_ms = int((task.completed_at - task.created_at).total_seconds() * 1000)

    # 2b. Extract files affected per hygiene run from tool calls
    if correlation_ids:
        file_write_rows = (await db.execute(
            select(ToolCall.correlation_id, ToolCall.arguments)
            .where(
                ToolCall.correlation_id.in_(correlation_ids),
                ToolCall.tool_name == "file",
                ToolCall.arguments["operation"].astext.in_(["write", "append", "edit"]),
            )
        )).all()
        files_by_corr: dict[str, list[str]] = {}
        for row in file_write_rows:
            path = row.arguments.get("path", "") if row.arguments else ""
            if "memory/" in path:
                # Normalize: strip workspace prefix, keep from memory/ onward
                idx = path.find("memory/")
                short = path[idx:] if idx >= 0 else path
                files_by_corr.setdefault(str(row.correlation_id), []).append(short)
        for run in runs_out:
            if run.correlation_id and run.correlation_id in files_by_corr:
                run.files_affected = sorted(set(files_by_corr[run.correlation_id]))

    # 2c. Skill prune overrides per hygiene run
    if correlation_ids:
        override_rows = (await db.execute(
            select(TraceEvent)
            .where(
                TraceEvent.correlation_id.in_(correlation_ids),
                TraceEvent.event_type == "skill_prune_override",
            )
        )).scalars().all()
        overrides_by_corr: dict[str, list[dict]] = {}
        for ov in override_rows:
            if ov.data and ov.correlation_id:
                overrides_by_corr.setdefault(str(ov.correlation_id), []).append(ov.data)
        for run in runs_out:
            if run.correlation_id and run.correlation_id in overrides_by_corr:
                run.skill_overrides = overrides_by_corr[run.correlation_id]

    # 2d. Collect hygiene correlation_ids for tagging memory activity
    hygiene_corr_ids: set[str] = set()
    for task in recent_tasks:
        if task.correlation_id:
            hygiene_corr_ids.add(str(task.correlation_id))

    # 3. Hygiene runs count (last 7 days)
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    runs_7d = (await db.execute(
        select(func.count())
        .select_from(TaskRow)
        .where(TaskRow.task_type == "memory_hygiene", TaskRow.created_at >= seven_days_ago)
    )).scalar() or 0

    # 4. Bot-authored skills stats
    skill_stats = (await db.execute(
        select(
            func.count().label("total"),
            func.coalesce(func.sum(SkillRow.surface_count), 0).label("surfacings"),
        )
        .select_from(SkillRow)
        .where(SkillRow.source_type == "tool")
    )).first()

    # 4b. Total auto-injects across all enrollments
    total_ai = (await db.execute(
        select(func.coalesce(func.sum(BotSkillEnrollment.auto_inject_count), 0))
    )).scalar() or 0

    # 5. Recent memory file activity (last 7 days, across all bots)
    memory_writes = (await db.execute(
        select(ToolCall)
        .where(
            ToolCall.tool_name == "file",
            ToolCall.arguments["operation"].astext.in_(["write", "append", "edit"]),
            ToolCall.created_at >= seven_days_ago,
            ToolCall.bot_id.in_(bot_ids) if bot_ids else ToolCall.bot_id.is_(None),
        )
        .order_by(ToolCall.created_at.desc())
        .limit(50)
    )).scalars().all()

    memory_activity: list[MemoryFileActivity] = []
    for tc in memory_writes:
        path = tc.arguments.get("path", "") if tc.arguments else ""
        if "memory/" not in path:
            continue
        idx = path.find("memory/")
        short = path[idx:] if idx >= 0 else path
        corr_str = str(tc.correlation_id) if tc.correlation_id else None
        memory_activity.append(MemoryFileActivity(
            bot_id=tc.bot_id or "",
            bot_name=bot_name_map.get(tc.bot_id or "", tc.bot_id or ""),
            file_path=short,
            operation=tc.arguments.get("operation", "write") if tc.arguments else "write",
            created_at=tc.created_at,
            is_hygiene=corr_str in hygiene_corr_ids if corr_str else False,
            correlation_id=corr_str,
        ))

    return LearningOverviewOut(
        total_bots=len(all_bots),
        dreaming_enabled_count=enabled_count,
        total_hygiene_runs_7d=runs_7d,
        total_bot_skills=skill_stats.total if skill_stats else 0,
        total_surfacings=int(skill_stats.surfacings) if skill_stats else 0,
        total_auto_injects=int(total_ai),
        bots=bot_statuses,
        recent_runs=runs_out,
        memory_activity=memory_activity,
    )
