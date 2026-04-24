"""Memory & Knowledge aggregate endpoints: /learning/*.

The route stays `/learning` for compatibility, but the admin UI now frames this
as durable context: memory, knowledge bases, history, dreaming, and skills.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import cast, func, select, Date
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Bot as BotRow,
    BotSkillEnrollment,
    Channel,
    ConversationSection,
    FilesystemChunk,
    Skill as SkillRow,
    Task as TaskRow,
    ToolCall,
    TraceEvent,
)
from app.dependencies import get_db, require_scopes

from ._helpers import build_tool_call_previews

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/learning", tags=["Memory & Knowledge"])


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

class SourceFileTarget(BaseModel):
    kind: Literal["workspace_file"] = "workspace_file"
    workspace_id: str
    path: str
    display_path: str
    owner_type: Literal["bot", "channel"]
    owner_id: str
    owner_name: str

class MemoryFileActivity(BaseModel):
    bot_id: str
    bot_name: str
    file_path: str
    operation: str  # write, append, edit
    created_at: datetime
    is_hygiene: bool = False
    correlation_id: Optional[str] = None
    job_type: Optional[str] = None  # memory_hygiene or skill_review when is_hygiene
    source_file: Optional[SourceFileTarget] = None

class LearningSearchRequest(BaseModel):
    query: str
    sources: list[Literal["memory", "bot_knowledge", "channel_knowledge", "history"]] = Field(
        default_factory=lambda: ["memory", "bot_knowledge", "channel_knowledge", "history"]
    )
    bot_ids: Optional[list[str]] = None
    channel_ids: Optional[list[str]] = None
    days: int = 30
    top_k_per_source: int = 6

class LearningSearchResult(BaseModel):
    id: str
    source: str
    title: str
    snippet: str
    score: Optional[float] = None
    bot_id: Optional[str] = None
    bot_name: Optional[str] = None
    channel_id: Optional[str] = None
    channel_name: Optional[str] = None
    file_path: Optional[str] = None
    section: Optional[int] = None
    created_at: Optional[datetime] = None
    correlation_id: Optional[str] = None
    open_url: Optional[str] = None
    source_file: Optional[SourceFileTarget] = None
    metadata: dict = Field(default_factory=dict)

class LearningSearchResponse(BaseModel):
    query: str
    results: list[LearningSearchResult] = []

class KnowledgeLibraryItem(BaseModel):
    source: Literal["bot_knowledge", "channel_knowledge"]
    owner_id: str
    owner_name: str
    path_prefix: str
    file_count: int = 0
    chunk_count: int = 0
    last_indexed_at: Optional[datetime] = None
    open_url: Optional[str] = None

class KnowledgeLibraryResponse(BaseModel):
    items: list[KnowledgeLibraryItem] = []

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
# Helpers
# ---------------------------------------------------------------------------

def _trim_snippet(text: str | None, limit: int = 420) -> str:
    snippet = (text or "").strip()
    if snippet.startswith("# "):
        first_nl = snippet.find("\n")
        if first_nl > 0:
            snippet = snippet[first_nl + 1:].strip()
    if len(snippet) <= limit:
        return snippet
    return snippet[: limit - 1].rstrip() + "..."


def _selected_ids(values: list[str] | None) -> set[str] | None:
    cleaned = {str(v).strip() for v in values or [] if str(v or "").strip()}
    return cleaned or None


def _workspace_source_file(
    *,
    workspace_id: str | None,
    path: str | None,
    display_path: str | None = None,
    owner_type: Literal["bot", "channel"],
    owner_id: str,
    owner_name: str,
) -> SourceFileTarget | None:
    if not workspace_id or not path:
        return None
    return SourceFileTarget(
        workspace_id=str(workspace_id),
        path=path,
        display_path=display_path or path,
        owner_type=owner_type,
        owner_id=owner_id,
        owner_name=owner_name,
    )


def _bot_workspace_relative_path(bot, path: str | None) -> str | None:
    if not path:
        return None
    cleaned = path.lstrip("/")
    if getattr(bot, "shared_workspace_id", None) and not cleaned.startswith("bots/"):
        return f"bots/{bot.id}/{cleaned}"
    return cleaned


async def _bot_configs(selected: set[str] | None = None):
    from app.agent.bots import list_bots

    bots = [bot for bot in list_bots() if not selected or bot.id in selected]
    return bots


async def _search_memory_source(
    query: str,
    selected_bots: set[str] | None,
    top_k: int,
) -> list[LearningSearchResult]:
    from pathlib import Path

    from app.services.bot_indexing import resolve_for
    from app.services.memory_scheme import get_memory_index_prefix
    from app.services.memory_search import hybrid_memory_search

    results: list[LearningSearchResult] = []
    for bot in await _bot_configs(selected_bots):
        if getattr(bot, "memory_scheme", None) != "workspace-files":
            continue
        try:
            plan = resolve_for(bot, scope="workspace")
            if plan is None:
                continue
            hits = await hybrid_memory_search(
                query,
                bot.id,
                roots=[str(Path(root).resolve()) for root in plan.roots],
                memory_prefix=get_memory_index_prefix(bot),
                embedding_model=plan.embedding_model,
                top_k=top_k,
            )
        except Exception:
            logger.debug("Admin memory search failed for bot %s", bot.id, exc_info=True)
            continue
        for hit_index, hit in enumerate(hits):
            results.append(LearningSearchResult(
                id=f"memory:{bot.id}:{hit.file_path}:{hit_index}",
                source="memory",
                title=hit.file_path,
                snippet=_trim_snippet(hit.content),
                score=hit.score,
                bot_id=bot.id,
                bot_name=bot.name,
                file_path=hit.file_path,
                open_url=f"/admin/bots/{bot.id}#learning",
                source_file=_workspace_source_file(
                    workspace_id=getattr(bot, "shared_workspace_id", None),
                    path=_bot_workspace_relative_path(bot, hit.file_path),
                    display_path=hit.file_path,
                    owner_type="bot",
                    owner_id=bot.id,
                    owner_name=bot.name,
                ),
            ))
    results.sort(key=lambda item: item.score or 0, reverse=True)
    return results[:top_k]


async def _search_bot_knowledge_source(
    query: str,
    selected_bots: set[str] | None,
    top_k: int,
) -> list[LearningSearchResult]:
    from app.services.bot_indexing import resolve_for
    from app.services.memory_search import hybrid_memory_search
    from app.services.workspace import workspace_service

    results: list[LearningSearchResult] = []
    for bot in await _bot_configs(selected_bots):
        try:
            if not bot.workspace.enabled or not bot.workspace.indexing.enabled:
                continue
            plan = resolve_for(bot, scope="workspace")
            if plan is None:
                continue
            hits = await hybrid_memory_search(
                query=query,
                bot_id=bot.id,
                roots=list(plan.roots),
                memory_prefix=workspace_service.get_bot_knowledge_base_index_prefix(bot),
                embedding_model=plan.embedding_model,
                top_k=top_k,
            )
        except Exception:
            logger.debug("Admin bot knowledge search failed for bot %s", bot.id, exc_info=True)
            continue
        for hit_index, hit in enumerate(hits):
            results.append(LearningSearchResult(
                id=f"bot_knowledge:{bot.id}:{hit.file_path}:{hit_index}",
                source="bot_knowledge",
                title=hit.file_path,
                snippet=_trim_snippet(hit.content),
                score=hit.score,
                bot_id=bot.id,
                bot_name=bot.name,
                file_path=hit.file_path,
                open_url=f"/admin/bots/{bot.id}#learning",
                source_file=_workspace_source_file(
                    workspace_id=getattr(bot, "shared_workspace_id", None),
                    path=_bot_workspace_relative_path(bot, hit.file_path),
                    display_path=hit.file_path,
                    owner_type="bot",
                    owner_id=bot.id,
                    owner_name=bot.name,
                ),
            ))
    results.sort(key=lambda item: item.score or 0, reverse=True)
    return results[:top_k]


async def _channels_for_search(
    db: AsyncSession,
    selected_channels: set[str] | None,
    limit: int = 24,
) -> list[Channel]:
    stmt = select(Channel).order_by(Channel.name).limit(limit)
    if selected_channels:
        ids: list[uuid.UUID] = []
        for raw in selected_channels:
            try:
                ids.append(uuid.UUID(raw))
            except ValueError:
                continue
        if not ids:
            return []
        stmt = select(Channel).where(Channel.id.in_(ids)).order_by(Channel.name).limit(limit)
    return list((await db.execute(stmt)).scalars().all())


async def _search_channel_knowledge_source(
    db: AsyncSession,
    query: str,
    selected_channels: set[str] | None,
    top_k: int,
) -> list[LearningSearchResult]:
    from pathlib import Path

    from app.agent.bots import get_bot
    from app.services.bot_indexing import resolve_for
    from app.services.channel_workspace import _get_ws_root, get_channel_knowledge_base_index_prefix
    from app.services.channel_workspace_indexing import _get_channel_index_bot_id
    from app.services.memory_search import hybrid_memory_search

    results: list[LearningSearchResult] = []
    for channel in await _channels_for_search(db, selected_channels):
        try:
            bot = get_bot(channel.bot_id)
            plan = resolve_for(bot, scope="workspace")
            if plan is None:
                continue
            ch_id = str(channel.id)
            hits = await hybrid_memory_search(
                query=query,
                bot_id=_get_channel_index_bot_id(ch_id),
                roots=[str(Path(_get_ws_root(bot)).resolve())],
                memory_prefix=get_channel_knowledge_base_index_prefix(ch_id),
                embedding_model=plan.embedding_model,
                top_k=top_k,
            )
        except Exception:
            logger.debug("Admin channel knowledge search failed for channel %s", channel.id, exc_info=True)
            continue
        for hit_index, hit in enumerate(hits):
            ch_id = str(channel.id)
            results.append(LearningSearchResult(
                id=f"channel_knowledge:{ch_id}:{hit.file_path}:{hit_index}",
                source="channel_knowledge",
                title=hit.file_path,
                snippet=_trim_snippet(hit.content),
                score=hit.score,
                channel_id=ch_id,
                channel_name=channel.name,
                bot_id=channel.bot_id,
                file_path=hit.file_path,
                open_url=f"/channels/{ch_id}/settings#Knowledge",
                source_file=_workspace_source_file(
                    workspace_id=getattr(bot, "shared_workspace_id", None),
                    path=hit.file_path,
                    owner_type="channel",
                    owner_id=ch_id,
                    owner_name=channel.name,
                ),
            ))
    results.sort(key=lambda item: item.score or 0, reverse=True)
    return results[:top_k]


async def _search_history_source(
    db: AsyncSession,
    query: str,
    selected_channels: set[str] | None,
    top_k: int,
) -> list[LearningSearchResult]:
    from app.tools.local.conversation_history import search_sections

    results: list[LearningSearchResult] = []
    for channel in await _channels_for_search(db, selected_channels, limit=18):
        if not channel.active_session_id:
            continue
        try:
            matches = await search_sections(channel.active_session_id, query)
        except Exception:
            logger.debug("Admin history search failed for channel %s", channel.id, exc_info=True)
            continue
        for match in matches:
            section: ConversationSection = match["section"]
            ch_id = str(channel.id)
            results.append(LearningSearchResult(
                id=f"history:{section.id}",
                source="history",
                title=section.title or f"Section #{section.sequence}",
                snippet=_trim_snippet(match.get("snippet") or section.summary),
                channel_id=ch_id,
                channel_name=channel.name,
                bot_id=channel.bot_id,
                section=section.sequence,
                created_at=section.created_at,
                open_url=f"/channels/{ch_id}/settings#Memory",
                metadata={
                    "match_source": match.get("source"),
                    "message_count": section.message_count,
                    "tags": section.tags or [],
                    "period_start": section.period_start.isoformat() if section.period_start else None,
                },
            ))
    results.sort(key=lambda item: item.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return results[:top_k]


async def _memory_activity(
    db: AsyncSession,
    *,
    days: int = 30,
    bot_ids: set[str] | None = None,
    operations: set[str] | None = None,
    job_types: set[str] | None = None,
    limit: int = 100,
) -> list[MemoryFileActivity]:
    from app.agent.bots import list_bots

    bot_rows = (await db.execute(select(BotRow.id, BotRow.name))).all()
    bot_name_map = {row.id: row.name for row in bot_rows}
    bot_config_map = {bot.id: bot for bot in list_bots()}
    cutoff = datetime.now(timezone.utc) - timedelta(days=days) if days > 0 else None
    allowed_ops = operations or {"write", "append", "edit"}

    task_rows = (await db.execute(
        select(TaskRow.correlation_id, TaskRow.task_type)
        .where(TaskRow.task_type.in_(("memory_hygiene", "skill_review")))
    )).all()
    corr_to_job = {str(row.correlation_id): row.task_type for row in task_rows if row.correlation_id}

    stmt = (
        select(ToolCall)
        .where(
            ToolCall.tool_name == "file",
            ToolCall.arguments["operation"].astext.in_(list(allowed_ops)),
        )
        .order_by(ToolCall.created_at.desc())
        .limit(limit)
    )
    if cutoff:
        stmt = stmt.where(ToolCall.created_at >= cutoff)
    if bot_ids:
        stmt = stmt.where(ToolCall.bot_id.in_(bot_ids))

    rows = (await db.execute(stmt)).scalars().all()
    activity: list[MemoryFileActivity] = []
    for tc in rows:
        path = tc.arguments.get("path", "") if tc.arguments else ""
        if "memory/" not in path:
            continue
        corr_str = str(tc.correlation_id) if tc.correlation_id else None
        job_type = corr_to_job.get(corr_str or "")
        if job_types and (job_type or "turn") not in job_types:
            continue
        idx = path.find("memory/")
        short = path[idx:] if idx >= 0 else path
        bot_id = tc.bot_id or ""
        bot_name = bot_name_map.get(bot_id, bot_id)
        bot_config = bot_config_map.get(bot_id)
        activity.append(MemoryFileActivity(
            bot_id=bot_id,
            bot_name=bot_name,
            file_path=short,
            operation=tc.arguments.get("operation", "write") if tc.arguments else "write",
            created_at=tc.created_at,
            is_hygiene=job_type in {"memory_hygiene", "skill_review"},
            correlation_id=corr_str,
            job_type=job_type,
            source_file=_workspace_source_file(
                workspace_id=getattr(bot_config, "shared_workspace_id", None),
                path=_bot_workspace_relative_path(bot_config, short) if bot_config else short,
                display_path=short,
                owner_type="bot",
                owner_id=bot_id,
                owner_name=bot_name,
            ),
        ))
    return activity


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/search", response_model=LearningSearchResponse)
async def learning_search(
    body: LearningSearchRequest,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    """Unified admin search over the durable context sources agents use."""
    query = body.query.strip()
    if not query:
        return LearningSearchResponse(query=body.query, results=[])

    top_k = max(1, min(body.top_k_per_source, 12))
    selected_bots = _selected_ids(body.bot_ids)
    selected_channels = _selected_ids(body.channel_ids)
    sources = set(body.sources or ["memory", "bot_knowledge", "channel_knowledge", "history"])
    results: list[LearningSearchResult] = []

    if "memory" in sources:
        results.extend(await _search_memory_source(query, selected_bots, top_k))
    if "bot_knowledge" in sources:
        results.extend(await _search_bot_knowledge_source(query, selected_bots, top_k))
    if "channel_knowledge" in sources:
        results.extend(await _search_channel_knowledge_source(db, query, selected_channels, top_k))
    if "history" in sources:
        results.extend(await _search_history_source(db, query, selected_channels, top_k))

    source_order = {"memory": 0, "bot_knowledge": 1, "channel_knowledge": 2, "history": 3}
    results.sort(key=lambda item: (source_order.get(item.source, 9), -(item.score or 0)))
    return LearningSearchResponse(query=query, results=results[: top_k * max(1, len(sources))])


@router.get("/memory-activity", response_model=list[MemoryFileActivity])
async def learning_memory_activity(
    days: int = Query(default=30, ge=0, le=365),
    bot_id: list[str] | None = Query(default=None),
    operation: list[str] | None = Query(default=None),
    job_type: list[str] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    """Filtered memory-file change activity from existing tool-call events."""
    return await _memory_activity(
        db,
        days=days,
        bot_ids=_selected_ids(bot_id),
        operations=_selected_ids(operation),
        job_types=_selected_ids(job_type),
        limit=limit,
    )


@router.get("/knowledge-library", response_model=KnowledgeLibraryResponse)
async def learning_knowledge_library(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    """Inventory convention-based bot and channel knowledge-base indexes."""
    from app.agent.bots import get_bot, list_bots
    from app.services.channel_workspace import get_channel_knowledge_base_index_prefix
    from app.services.channel_workspace_indexing import _get_channel_index_bot_id
    from app.services.workspace import workspace_service

    items: list[KnowledgeLibraryItem] = []

    for bot in list_bots():
        prefix = workspace_service.get_bot_knowledge_base_index_prefix(bot)
        row = (await db.execute(
            select(
                func.count(func.distinct(FilesystemChunk.file_path)),
                func.count(FilesystemChunk.id),
                func.max(FilesystemChunk.indexed_at),
            )
            .where(
                FilesystemChunk.bot_id == bot.id,
                FilesystemChunk.file_path.like(f"{prefix.rstrip('/')}/%"),
            )
        )).first()
        items.append(KnowledgeLibraryItem(
            source="bot_knowledge",
            owner_id=bot.id,
            owner_name=bot.name,
            path_prefix=prefix,
            file_count=int(row[0] or 0) if row else 0,
            chunk_count=int(row[1] or 0) if row else 0,
            last_indexed_at=row[2] if row else None,
            open_url=f"/admin/bots/{bot.id}#learning",
        ))

    channels = (await db.execute(select(Channel).order_by(Channel.name))).scalars().all()
    for channel in channels:
        prefix = get_channel_knowledge_base_index_prefix(str(channel.id))
        row = (await db.execute(
            select(
                func.count(func.distinct(FilesystemChunk.file_path)),
                func.count(FilesystemChunk.id),
                func.max(FilesystemChunk.indexed_at),
            )
            .where(
                FilesystemChunk.bot_id == _get_channel_index_bot_id(str(channel.id)),
                FilesystemChunk.file_path.like(f"{prefix.rstrip('/')}/%"),
            )
        )).first()
        bot_name = channel.bot_id
        try:
            bot_name = get_bot(channel.bot_id).name
        except Exception:
            pass
        items.append(KnowledgeLibraryItem(
            source="channel_knowledge",
            owner_id=str(channel.id),
            owner_name=channel.name,
            path_prefix=prefix,
            file_count=int(row[0] or 0) if row else 0,
            chunk_count=int(row[1] or 0) if row else 0,
            last_indexed_at=row[2] if row else None,
            open_url=f"/channels/{channel.id}/settings#Knowledge",
            # Keep bot_name discoverable without adding another schema field.
            # The UI primarily needs owner_name and source.
        ))

    items.sort(key=lambda item: (item.source, item.owner_name.lower()))
    return KnowledgeLibraryResponse(items=items)

@router.get("/overview", response_model=LearningOverviewOut)
async def learning_overview(
    days: int = Query(default=0, ge=0, le=90, description="Time window in days (0 = all-time)"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("bots:read")),
):
    """Aggregate learning/dreaming dashboard data across all bots."""
    from app.agent.bots import list_bots
    from app.services.memory_hygiene import resolve_config

    # 1. All bots with workspace-files memory
    all_bots = (await db.execute(
        select(BotRow).where(BotRow.memory_scheme == "workspace-files")
    )).scalars().all()

    bot_statuses: list[BotDreamingStatus] = []
    enabled_count = 0
    bot_name_map: dict[str, str] = {}
    bot_config_map = {bot.id: bot for bot in list_bots()}
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
        bot_id = tc.bot_id or ""
        bot_name = bot_name_map.get(bot_id, bot_id)
        bot_config = bot_config_map.get(bot_id)
        memory_activity.append(MemoryFileActivity(
            bot_id=bot_id,
            bot_name=bot_name,
            file_path=short,
            operation=tc.arguments.get("operation", "write") if tc.arguments else "write",
            created_at=tc.created_at,
            is_hygiene=is_hygiene,
            correlation_id=corr_str,
            job_type=corr_to_job_type.get(corr_str) if is_hygiene and corr_str else None,
            source_file=_workspace_source_file(
                workspace_id=getattr(bot_config, "shared_workspace_id", None),
                path=_bot_workspace_relative_path(bot_config, short) if bot_config else short,
                display_path=short,
                owner_type="bot",
                owner_id=bot_id,
                owner_name=bot_name,
            ),
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
    """Daily skill activity time-series for Memory & Knowledge charts."""
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
