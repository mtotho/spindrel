"""Learning Center aggregate endpoint: /learning/overview."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bot as BotRow, Skill as SkillRow, Task as TaskRow, ToolCall, TraceEvent
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

class LearningOverviewOut(BaseModel):
    total_bots: int = 0
    dreaming_enabled_count: int = 0
    total_hygiene_runs_7d: int = 0
    total_bot_skills: int = 0
    total_surfacings: int = 0
    bots: list[BotDreamingStatus] = []
    recent_runs: list[RecentHygieneRun] = []


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

    for bot in all_bots:
        enabled = resolve_enabled(bot)
        interval = resolve_interval(bot)
        model = resolve_model(bot)
        if enabled:
            enabled_count += 1
        bot_name_map[bot.id] = bot.name

        # Get last task status per bot
        last_task = (await db.execute(
            select(TaskRow.status, TaskRow.completed_at)
            .where(TaskRow.bot_id == bot.id, TaskRow.task_type == "memory_hygiene")
            .order_by(TaskRow.created_at.desc())
            .limit(1)
        )).first()

        bot_statuses.append(BotDreamingStatus(
            bot_id=bot.id,
            bot_name=bot.name,
            enabled=enabled,
            last_run_at=bot.last_hygiene_run_at.isoformat() if bot.last_hygiene_run_at else None,
            last_task_status=last_task.status if last_task else None,
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

    return LearningOverviewOut(
        total_bots=len(all_bots),
        dreaming_enabled_count=enabled_count,
        total_hygiene_runs_7d=runs_7d,
        total_bot_skills=skill_stats.total if skill_stats else 0,
        total_surfacings=int(skill_stats.surfacings) if skill_stats else 0,
        bots=bot_statuses,
        recent_runs=runs_out,
    )
