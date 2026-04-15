"""Learning Center aggregate endpoints: /learning/overview, /learning/activity."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import cast, func, select, Date
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
    # Skill review fields
    skill_review_enabled: bool = False
    skill_review_last_run_at: Optional[str] = None
    skill_review_last_task_status: Optional[str] = None
    skill_review_next_run_at: Optional[str] = None
    skill_review_interval_hours: int = 72
    skill_review_model: Optional[str] = None

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
    job_type: str = "memory_hygiene"

class MemoryFileActivity(BaseModel):
    bot_id: str
    bot_name: str
    file_path: str
    operation: str  # write, append, edit
    created_at: datetime
    is_hygiene: bool = False
    correlation_id: Optional[str] = None
    job_type: Optional[str] = None  # memory_hygiene or skill_review when is_hygiene

class LearningOverviewOut(BaseModel):
    total_bots: int = 0
    dreaming_enabled_count: int = 0
    hygiene_runs: int = 0       # count in selected window (or all-time)
    total_bot_skills: int = 0   # current catalog count (not time-windowed)
    surfacings: int = 0         # get_skill calls in window (or all-time counter)
    auto_injects: int = 0       # auto-inject events in window (or all-time counter)
    days: int = 0               # echo back the requested window (0 = all)
    bots: list[BotDreamingStatus] = []
    recent_runs: list[RecentHygieneRun] = []
    memory_activity: list[MemoryFileActivity] = []


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("/overview", response_model=LearningOverviewOut)
async def learning_overview(
    days: int = Query(default=0, ge=0, le=90, description="Time window in days (0 = all-time)"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("bots:read")),
):
    """Aggregate learning/dreaming dashboard data across all bots."""
    from app.services.memory_hygiene import resolve_config

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

    # Batch: get last task status per bot per job type in one query
    _hygiene_types = ("memory_hygiene", "skill_review")
    last_task_map: dict[str, dict[str, str]] = {}  # {bot_id: {job_type: status}}
    if bot_ids:
        latest_subq = (
            select(
                TaskRow.bot_id,
                TaskRow.task_type,
                TaskRow.status,
                func.row_number().over(
                    partition_by=[TaskRow.bot_id, TaskRow.task_type],
                    order_by=TaskRow.created_at.desc(),
                ).label("rn"),
            )
            .where(TaskRow.bot_id.in_(bot_ids), TaskRow.task_type.in_(_hygiene_types))
            .subquery()
        )
        latest_rows = (await db.execute(
            select(latest_subq.c.bot_id, latest_subq.c.task_type, latest_subq.c.status)
            .where(latest_subq.c.rn == 1)
        )).all()
        for row in latest_rows:
            last_task_map.setdefault(row.bot_id, {})[row.task_type] = row.status

    for bot in all_bots:
        mh_cfg = resolve_config(bot, "memory_hygiene")
        sr_cfg = resolve_config(bot, "skill_review")
        if mh_cfg.enabled:
            enabled_count += 1

        bot_tasks = last_task_map.get(bot.id, {})

        bot_statuses.append(BotDreamingStatus(
            bot_id=bot.id,
            bot_name=bot.name,
            enabled=mh_cfg.enabled,
            last_run_at=bot.last_hygiene_run_at.isoformat() if bot.last_hygiene_run_at else None,
            last_task_status=bot_tasks.get("memory_hygiene"),
            next_run_at=bot.next_hygiene_run_at.isoformat() if bot.next_hygiene_run_at else None,
            interval_hours=mh_cfg.interval_hours,
            model=mh_cfg.model,
            skill_review_enabled=sr_cfg.enabled,
            skill_review_last_run_at=bot.last_skill_review_run_at.isoformat() if bot.last_skill_review_run_at else None,
            skill_review_last_task_status=bot_tasks.get("skill_review"),
            skill_review_next_run_at=bot.next_skill_review_run_at.isoformat() if bot.next_skill_review_run_at else None,
            skill_review_interval_hours=sr_cfg.interval_hours,
            skill_review_model=sr_cfg.model,
        ))

    bot_statuses.sort(key=lambda b: b.bot_name.lower())

    # 2. Recent hygiene/skill-review runs across all bots (last 20)
    recent_tasks = (await db.execute(
        select(TaskRow)
        .where(TaskRow.task_type.in_(_hygiene_types))
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
            job_type=t.task_type,
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

    # 2d. Collect hygiene correlation_ids + job types for tagging memory activity
    hygiene_corr_ids: set[str] = set()
    corr_to_job_type: dict[str, str] = {}
    for task in recent_tasks:
        if task.correlation_id:
            cid = str(task.correlation_id)
            hygiene_corr_ids.add(cid)
            corr_to_job_type[cid] = task.task_type

    # 3. Time-windowed stats (or all-time when days=0)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days) if days > 0 else None

    # 3a. Hygiene + skill review runs count
    _runs_q = select(func.count()).select_from(TaskRow).where(TaskRow.task_type.in_(_hygiene_types))
    if cutoff:
        _runs_q = _runs_q.where(TaskRow.created_at >= cutoff)
    hygiene_runs = (await db.execute(_runs_q)).scalar() or 0

    # 3b. Bot-authored skills catalog count (always current, not windowed)
    skill_count = (await db.execute(
        select(func.count()).select_from(SkillRow).where(SkillRow.source_type == "tool")
    )).scalar() or 0

    # 3c. Surfacings
    if cutoff:
        surfacings = (await db.execute(
            select(func.count()).select_from(ToolCall)
            .where(ToolCall.tool_name == "get_skill", ToolCall.created_at >= cutoff)
        )).scalar() or 0
    else:
        surfacings = (await db.execute(
            select(func.coalesce(func.sum(SkillRow.surface_count), 0))
            .where(SkillRow.source_type == "tool")
        )).scalar() or 0

    # 3d. Auto-injects
    if cutoff:
        auto_injects = (await db.execute(
            select(func.count()).select_from(TraceEvent)
            .where(
                TraceEvent.event_type == "skill_index",
                TraceEvent.created_at >= cutoff,
                func.jsonb_array_length(TraceEvent.data["auto_injected"]) > 0,
            )
        )).scalar() or 0
    else:
        auto_injects = (await db.execute(
            select(func.coalesce(func.sum(BotSkillEnrollment.auto_inject_count), 0))
        )).scalar() or 0

    # 4. Recent memory file activity (windowed, across all bots)
    _mem_q = (
        select(ToolCall)
        .where(
            ToolCall.tool_name == "file",
            ToolCall.arguments["operation"].astext.in_(["write", "append", "edit"]),
            ToolCall.bot_id.in_(bot_ids) if bot_ids else ToolCall.bot_id.is_(None),
        )
        .order_by(ToolCall.created_at.desc())
        .limit(100)
    )
    if cutoff:
        _mem_q = _mem_q.where(ToolCall.created_at >= cutoff)
    memory_writes = (await db.execute(_mem_q)).scalars().all()

    memory_activity: list[MemoryFileActivity] = []
    for tc in memory_writes:
        path = tc.arguments.get("path", "") if tc.arguments else ""
        if "memory/" not in path:
            continue
        idx = path.find("memory/")
        short = path[idx:] if idx >= 0 else path
        corr_str = str(tc.correlation_id) if tc.correlation_id else None
        is_hygiene = corr_str in hygiene_corr_ids if corr_str else False
        memory_activity.append(MemoryFileActivity(
            bot_id=tc.bot_id or "",
            bot_name=bot_name_map.get(tc.bot_id or "", tc.bot_id or ""),
            file_path=short,
            operation=tc.arguments.get("operation", "write") if tc.arguments else "write",
            created_at=tc.created_at,
            is_hygiene=is_hygiene,
            correlation_id=corr_str,
            job_type=corr_to_job_type.get(corr_str) if is_hygiene and corr_str else None,
        ))

    return LearningOverviewOut(
        total_bots=len(all_bots),
        dreaming_enabled_count=enabled_count,
        hygiene_runs=int(hygiene_runs),
        total_bot_skills=int(skill_count),
        surfacings=int(surfacings),
        auto_injects=int(auto_injects),
        days=days,
        bots=bot_statuses,
        recent_runs=runs_out,
        memory_activity=memory_activity,
    )


# ---------------------------------------------------------------------------
# /learning/activity — daily time-series for charts
# ---------------------------------------------------------------------------

class DailyActivityPoint(BaseModel):
    date: str  # YYYY-MM-DD
    surfacings: int = 0
    auto_injects: int = 0
    memory_writes: int = 0


@router.get("/activity", response_model=list[DailyActivityPoint])
async def learning_activity(
    days: int = Query(default=14, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    _scopes=Depends(require_scopes("admin")),
):
    """Daily skill activity time-series for the Learning Center charts."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    day_col = cast(TraceEvent.created_at, Date)
    tc_day_col = cast(ToolCall.created_at, Date)

    # Surfacings: get_skill tool calls per day
    surf_rows = (await db.execute(
        select(tc_day_col.label("day"), func.count().label("n"))
        .where(ToolCall.tool_name == "get_skill", ToolCall.created_at >= cutoff)
        .group_by(tc_day_col)
    )).all()
    surf_map = {str(r.day): r.n for r in surf_rows}

    # Auto-injects: trace events with non-empty auto_injected array per day
    ai_rows = (await db.execute(
        select(day_col.label("day"), func.count().label("n"))
        .where(
            TraceEvent.event_type == "skill_index",
            TraceEvent.created_at >= cutoff,
            func.jsonb_array_length(TraceEvent.data["auto_injected"]) > 0,
        )
        .group_by(day_col)
    )).all()
    ai_map = {str(r.day): r.n for r in ai_rows}

    # Memory writes per day
    mem_rows = (await db.execute(
        select(tc_day_col.label("day"), func.count().label("n"))
        .where(
            ToolCall.tool_name == "file",
            ToolCall.arguments["operation"].astext.in_(["write", "append", "edit"]),
            ToolCall.created_at >= cutoff,
        )
        .group_by(tc_day_col)
    )).all()
    mem_map = {str(r.day): r.n for r in mem_rows}

    # Build complete series (fill gaps with 0)
    result = []
    for i in range(days):
        d = (datetime.now(timezone.utc) - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        result.append(DailyActivityPoint(
            date=d,
            surfacings=surf_map.get(d, 0),
            auto_injects=ai_map.get(d, 0),
            memory_writes=mem_map.get(d, 0),
        ))
    return result
