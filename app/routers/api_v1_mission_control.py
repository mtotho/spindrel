"""Mission Control API — /api/v1/mission-control/

Aggregated dashboard endpoints: overview, kanban, journal, memory, debug context, prefs.
All queries scoped by user_id from JWT.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bot, Channel, ChannelMember, ToolCall, TraceEvent, User
from app.dependencies import get_db, require_scopes, verify_auth_or_user
from app.services.task_board import (
    default_columns,
    generate_card_id,
    parse_tasks_md,
    serialize_tasks_md,
)
from app.services.plan_board import parse_plans_md, serialize_plans_md

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mission-control", tags=["Mission Control"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COLUMN_VERBS: dict[str, str] = {
    "in progress": "was started",
    "done": "was completed",
    "review": "moved to review",
    "backlog": "moved back to backlog",
}

import re

def _humanize_event(raw: str) -> str:
    """Transform machine-readable timeline text into human-friendly prose."""
    # Card moved: Card mc-xxx moved to **Col** (was: OldCol) — "Title"
    m = re.match(
        r'Card \S+ moved to \*\*(.+?)\*\* \(was: .+?\) — "(.+?)"',
        raw,
    )
    if m:
        col, title = m.group(1), m.group(2)
        verb = _COLUMN_VERBS.get(col.lower(), f"moved to {col}")
        return f"**{title}** {verb}"

    # New card: New card created: mc-xxx "Title" in **Col**
    m = re.match(r'New card created: \S+ "(.+?)" in \*\*(.+?)\*\*', raw)
    if m:
        title, col = m.group(1), m.group(2)
        return f"New task: **{title}** added to {col}"

    # Plan approved: Plan approved: **Title** (plan-xxx)
    m = re.match(r"Plan approved: \*\*(.+?)\*\* \(\S+\)", raw)
    if m:
        return f"Plan **{m.group(1)}** was approved"

    # Plan rejected: Plan rejected: **Title** (plan-xxx)
    m = re.match(r"Plan rejected: \*\*(.+?)\*\* \(\S+\)", raw)
    if m:
        return f"Plan **{m.group(1)}** was rejected"

    return raw


def _get_user(auth) -> User | None:
    """Extract User from auth result. API keys get no user-scoping (admin-level)."""
    if isinstance(auth, User):
        return auth
    return None


def _require_channel_access(channel: Channel, user: User | None):
    """Raise 403 if a user doesn't own the channel."""
    if user and channel.user_id and channel.user_id != user.id:
        raise HTTPException(403, "Not your channel")


def _get_bot(bot_id: str):
    from app.agent.bots import get_bot
    return get_bot(bot_id)


def _plan_step_summary(plan: dict) -> str:
    """Build a concise summary of plan step states for task prompts."""
    steps = plan.get("steps", [])
    if not steps:
        return "No steps defined."
    lines = []
    next_step = None
    for s in steps:
        marker = {"pending": "[ ]", "in_progress": "[~]", "done": "[x]", "skipped": "[-]", "failed": "[!]"}.get(s["status"], "[ ]")
        lines.append(f"  {s['position']}. {marker} {s['content']}")
        if next_step is None and s["status"] in ("pending", "in_progress"):
            next_step = s
    summary = "\n".join(lines)
    if next_step:
        summary += f"\n\nNext step: #{next_step['position']} — {next_step['content']}"
    return summary


async def _tracked_channels(
    db: AsyncSession,
    user: User | None,
    prefs: dict | None = None,
    *,
    scope: str = "fleet",
) -> list[Channel]:
    """Get channels tracked by MC.

    Fleet: all workspace-enabled channels (everyone can see).
    Personal: workspace-enabled channels where user is a member (channel_members).
    tracked_channel_ids pref still applies as additional filter.
    """
    q = select(Channel).where(Channel.channel_workspace_enabled == True)  # noqa: E712

    if user and scope == "personal":
        q = q.where(
            Channel.id.in_(
                select(ChannelMember.channel_id).where(ChannelMember.user_id == user.id)
            )
        )

    result = await db.execute(q.order_by(Channel.name))
    channels = list(result.scalars().all())

    # Filter to tracked_channel_ids if set in prefs
    if prefs and prefs.get("tracked_channel_ids"):
        tracked = set(prefs["tracked_channel_ids"])
        channels = [ch for ch in channels if str(ch.id) in tracked]

    return channels


async def _get_mc_prefs(db: AsyncSession, user: User | None) -> dict:
    """Get MC preferences from user.integration_config."""
    if not user:
        return {}
    # Refresh to get latest
    ic = user.integration_config or {}
    return ic.get("mission_control", {})


async def _read_tasks_for_channel(channel: Channel) -> list[dict]:
    """Read and parse tasks.md for a channel. Returns columns."""
    from app.services.channel_workspace import read_workspace_file
    try:
        bot = _get_bot(channel.bot_id)
        content = await asyncio.to_thread(read_workspace_file, str(channel.id), bot, "tasks.md")
        if content:
            return parse_tasks_md(content)
    except Exception:
        logger.debug("Could not read tasks.md for channel %s", channel.id, exc_info=True)
    return []


def _has_tasks_file(channel: Channel) -> bool:
    """Quick check whether a channel has a tasks.md on disk (no parsing)."""
    from app.services.channel_workspace import get_channel_workspace_root
    try:
        bot = _get_bot(channel.bot_id)
        ws_root = get_channel_workspace_root(str(channel.id), bot)
        return os.path.isfile(os.path.join(ws_root, "tasks.md"))
    except Exception:
        return False


def _has_timeline_file(channel: Channel) -> bool:
    """Quick check whether a channel has a timeline.md on disk."""
    from app.services.channel_workspace import get_channel_workspace_root
    try:
        bot = _get_bot(channel.bot_id)
        ws_root = get_channel_workspace_root(str(channel.id), bot)
        return os.path.isfile(os.path.join(ws_root, "timeline.md"))
    except Exception:
        return False


def _has_plans_file(channel: Channel) -> bool:
    """Quick check whether a channel has a plans.md on disk."""
    from app.services.channel_workspace import get_channel_workspace_root
    try:
        bot = _get_bot(channel.bot_id)
        ws_root = get_channel_workspace_root(str(channel.id), bot)
        return os.path.isfile(os.path.join(ws_root, "plans.md"))
    except Exception:
        return False


async def _read_plans_for_channel(channel: Channel) -> list[dict]:
    """Read and parse plans.md for a channel. Returns plan dicts."""
    from app.services.channel_workspace import read_workspace_file
    try:
        bot = _get_bot(channel.bot_id)
        content = await asyncio.to_thread(
            read_workspace_file, str(channel.id), bot, "plans.md",
        )
        if content:
            return parse_plans_md(content)
    except Exception:
        logger.debug("Could not read plans.md for channel %s", channel.id, exc_info=True)
    return []


async def _read_timeline_for_channel(channel: Channel) -> list[dict]:
    """Read and parse timeline.md for a channel. Returns event dicts."""
    from app.services.channel_workspace import read_workspace_file
    try:
        bot = _get_bot(channel.bot_id)
        content = await asyncio.to_thread(
            read_workspace_file, str(channel.id), bot, "timeline.md",
        )
        if content:
            from integrations.mission_control.tools.mission_control import parse_timeline_md
            return parse_timeline_md(content)
    except Exception:
        logger.debug("Could not read timeline.md for channel %s", channel.id, exc_info=True)
    return []


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class KanbanCard(BaseModel):
    title: str
    meta: dict
    description: str
    channel_id: str
    channel_name: str


class KanbanColumn(BaseModel):
    name: str
    cards: list[KanbanCard]


class KanbanMoveRequest(BaseModel):
    card_id: str
    from_column: str
    to_column: str
    channel_id: uuid.UUID


class KanbanCreateRequest(BaseModel):
    channel_id: uuid.UUID
    title: str
    column: str = "Backlog"
    priority: str = "medium"
    assigned: str = ""
    tags: str = ""
    due: str = ""
    description: str = ""


class KanbanUpdateRequest(BaseModel):
    card_id: str
    channel_id: uuid.UUID
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    assigned: Optional[str] = None
    due: Optional[str] = None
    tags: Optional[str] = None


class MCPrefsUpdate(BaseModel):
    tracked_channel_ids: Optional[list[str]] = None
    tracked_bot_ids: Optional[list[str]] = None
    kanban_filters: Optional[dict] = None
    layout_prefs: Optional[dict] = None


class ChannelOverview(BaseModel):
    id: str
    name: str
    bot_id: str
    bot_name: str | None = None
    model: str | None = None
    workspace_enabled: bool
    task_count: int = 0
    template_name: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    is_member: bool = False


class BotOverview(BaseModel):
    id: str
    name: str
    model: str
    channel_count: int = 0
    memory_scheme: str | None = None


class JournalEntry(BaseModel):
    date: str
    bot_id: str
    bot_name: str
    content: str


class JournalResponse(BaseModel):
    entries: list[JournalEntry]


class MemoryBotSection(BaseModel):
    bot_id: str
    bot_name: str
    memory_content: str | None = None
    reference_files: list[str] = []


class MemoryResponse(BaseModel):
    sections: list[MemoryBotSection]


class TimelineEvent(BaseModel):
    date: str
    time: str
    event: str
    channel_id: str
    channel_name: str


class TimelineResponse(BaseModel):
    events: list[TimelineEvent]


class MCPlanStep(BaseModel):
    position: int
    status: str
    content: str


class MCPlan(BaseModel):
    id: str
    title: str
    status: str
    meta: dict[str, str]
    steps: list[MCPlanStep]
    notes: str
    channel_id: str
    channel_name: str


class MCPlansResponse(BaseModel):
    plans: list[MCPlan]


class FeatureReadiness(BaseModel):
    ready: bool
    detail: str
    count: int = 0
    total: int = 0
    issues: list[str] = []


class ReadinessResponse(BaseModel):
    dashboard: FeatureReadiness
    kanban: FeatureReadiness
    journal: FeatureReadiness
    memory: FeatureReadiness
    timeline: FeatureReadiness
    plans: FeatureReadiness


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/readiness", dependencies=[Depends(require_scopes("mission_control:read"))])
async def readiness(
    scope: Literal["fleet", "personal"] = "fleet",
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Check system readiness for each MC feature."""
    from app.agent.bots import list_bots

    user = _get_user(auth)
    prefs = await _get_mc_prefs(db, user)
    channels = await _tracked_channels(db, user, prefs, scope=scope)

    # Dashboard: channels with workspace enabled
    dashboard_issues: list[str] = []
    if not channels:
        dashboard_issues.append(
            "No channels have workspace enabled. Enable it in channel settings."
        )
    dashboard = FeatureReadiness(
        ready=len(channels) > 0,
        detail=f"{len(channels)} workspace-enabled channel{'s' if len(channels) != 1 else ''}",
        count=len(channels),
        total=len(channels),
        issues=dashboard_issues,
    )

    # Kanban: channels with tasks.md (batch check in single thread call)
    def _count_tasks_files():
        return sum(1 for ch in channels if _has_tasks_file(ch))

    tasks_count = await asyncio.to_thread(_count_tasks_files) if channels else 0
    kanban_issues: list[str] = []
    if channels and tasks_count == 0:
        kanban_issues.append(
            "No channels have tasks.md. The MC skill creates this automatically."
        )
    elif not channels:
        kanban_issues.append(
            "No workspace-enabled channels. Enable workspace in channel settings first."
        )
    kanban = FeatureReadiness(
        ready=tasks_count > 0,
        detail=f"{tasks_count} of {len(channels)} channels have tasks.md",
        count=tasks_count,
        total=len(channels),
        issues=kanban_issues,
    )

    # Journal + Memory: bots with memory_scheme="workspace-files"
    bots = list_bots()
    bot_ids_in_channels = {ch.bot_id for ch in channels}
    memory_bots = [b for b in bots if b.memory_scheme == "workspace-files" and b.id in bot_ids_in_channels]

    journal_count = 0
    memory_count = 0

    def _check_memory_bots():
        j_count = 0
        m_count = 0
        for bot in memory_bots:
            from app.services.memory_scheme import get_memory_root
            try:
                mem_root = get_memory_root(bot)
            except Exception:
                continue
            if os.path.isdir(os.path.join(mem_root, "logs")):
                j_count += 1
            if os.path.isfile(os.path.join(mem_root, "MEMORY.md")):
                m_count += 1
        return j_count, m_count

    if memory_bots:
        journal_count, memory_count = await asyncio.to_thread(_check_memory_bots)

    journal_issues: list[str] = []
    if not memory_bots:
        journal_issues.append(
            "No bots have memory_scheme: workspace-files. Set this in bot YAML."
        )
    elif journal_count == 0:
        journal_issues.append(
            "No bots have memory/logs/ directory yet. Logs appear after the bot runs."
        )
    journal = FeatureReadiness(
        ready=journal_count > 0,
        detail=f"{journal_count} bot{'s' if journal_count != 1 else ''} with journal logs",
        count=journal_count,
        total=len(memory_bots),
        issues=journal_issues,
    )

    memory_issues: list[str] = []
    if not memory_bots:
        memory_issues.append(
            "No bots have memory_scheme: workspace-files. Set this in bot YAML."
        )
    elif memory_count == 0:
        memory_issues.append(
            "No bots have MEMORY.md yet. It's created after the bot's first run."
        )
    memory_feat = FeatureReadiness(
        ready=memory_count > 0,
        detail=f"{memory_count} bot{'s' if memory_count != 1 else ''} with MEMORY.md",
        count=memory_count,
        total=len(memory_bots),
        issues=memory_issues,
    )

    # Timeline: channels with timeline.md (batch check in single thread call)
    def _count_timeline_files():
        return sum(1 for ch in channels if _has_timeline_file(ch))

    timeline_count = await asyncio.to_thread(_count_timeline_files) if channels else 0
    timeline_issues: list[str] = []
    if channels and timeline_count == 0:
        timeline_issues.append(
            "No channels have timeline.md yet. Events are auto-logged when tasks are created or moved."
        )
    elif not channels:
        timeline_issues.append(
            "No workspace-enabled channels. Enable workspace in channel settings first."
        )
    timeline = FeatureReadiness(
        ready=timeline_count > 0,
        detail=f"{timeline_count} of {len(channels)} channels have timeline.md",
        count=timeline_count,
        total=len(channels),
        issues=timeline_issues,
    )

    # Plans: channels with plans.md (batch check in single thread call)
    def _count_plans_files():
        return sum(1 for ch in channels if _has_plans_file(ch))

    plans_count = await asyncio.to_thread(_count_plans_files) if channels else 0
    plans_issues: list[str] = []
    if channels and plans_count == 0:
        plans_issues.append(
            "No channels have plans.md yet. Plans are created when bots draft structured proposals."
        )
    elif not channels:
        plans_issues.append(
            "No workspace-enabled channels. Enable workspace in channel settings first."
        )
    plans_feat = FeatureReadiness(
        ready=plans_count > 0,
        detail=f"{plans_count} of {len(channels)} channels have plans.md",
        count=plans_count,
        total=len(channels),
        issues=plans_issues,
    )

    return ReadinessResponse(
        dashboard=dashboard,
        kanban=kanban,
        journal=journal,
        memory=memory_feat,
        timeline=timeline,
        plans=plans_feat,
    )


@router.get("/overview", dependencies=[Depends(require_scopes("mission_control:read"))])
async def overview(
    scope: Literal["fleet", "personal"] = "fleet",
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Fleet stats, channel list with task counts, bot list."""
    from sqlalchemy import func

    user = _get_user(auth)
    prefs = await _get_mc_prefs(db, user)
    channels = await _tracked_channels(db, user, prefs, scope=scope)

    # Total channel count (regardless of workspace flag) for empty-state UX
    total_channels_all = (await db.execute(select(func.count(Channel.id)))).scalar() or 0

    # Load member channel IDs for the current user (single query)
    member_channel_ids: set[uuid.UUID] = set()
    if user:
        rows = (await db.execute(
            select(ChannelMember.channel_id).where(ChannelMember.user_id == user.id)
        )).scalars().all()
        member_channel_ids = set(rows)

    # Build bot lookup
    bots_q = select(Bot).order_by(Bot.name)
    bots_result = await db.execute(bots_q)
    bots = list(bots_result.scalars().all())
    bot_map = {b.id: b for b in bots}

    # Count channels per bot
    bot_channel_counts: dict[str, int] = {}
    for ch in channels:
        bot_channel_counts[ch.bot_id] = bot_channel_counts.get(ch.bot_id, 0) + 1

    # Batch-load template names to avoid N+1
    _template_ids = {ch.workspace_schema_template_id for ch in channels if ch.workspace_schema_template_id}
    _template_names: dict[str, str] = {}
    if _template_ids:
        from app.db.models import PromptTemplate
        _tpl_rows = (await db.execute(
            select(PromptTemplate).where(PromptTemplate.id.in_(_template_ids))
        )).scalars().all()
        _template_names = {str(t.id): t.name for t in _tpl_rows}

    # Task counts per channel (parallel reads)
    task_results = await asyncio.gather(
        *(_read_tasks_for_channel(ch) for ch in channels)
    )

    total_tasks = 0
    channel_overviews = []
    for ch, columns in zip(channels, task_results):
        task_count = sum(len(col.get("cards", [])) for col in columns)
        total_tasks += task_count
        bot = bot_map.get(ch.bot_id)

        template_name = _template_names.get(str(ch.workspace_schema_template_id)) if ch.workspace_schema_template_id else None

        channel_overviews.append(ChannelOverview(
            id=str(ch.id),
            name=ch.name,
            bot_id=ch.bot_id,
            bot_name=bot.name if bot else None,
            model=bot.model if bot else None,
            workspace_enabled=bool(ch.channel_workspace_enabled),
            task_count=task_count,
            template_name=template_name,
            created_at=ch.created_at.isoformat() if ch.created_at else None,
            updated_at=ch.updated_at.isoformat() if ch.updated_at else None,
            is_member=ch.id in member_channel_ids,
        ))

    bot_overviews = [
        BotOverview(
            id=b.id,
            name=b.name,
            model=b.model,
            channel_count=bot_channel_counts.get(b.id, 0),
            memory_scheme=b.memory_scheme,
        )
        for b in bots
    ]

    return {
        "channels": [co.model_dump() for co in channel_overviews],
        "bots": [bo.model_dump() for bo in bot_overviews],
        "total_channels": len(channels),
        "total_channels_all": total_channels_all,
        "total_bots": len(bots),
        "total_tasks": total_tasks,
        "is_admin": user.is_admin if user else True,  # API keys are admin-level
    }


@router.get("/kanban", dependencies=[Depends(require_scopes("mission_control:read"))])
async def kanban(
    scope: Literal["fleet", "personal"] = "fleet",
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Aggregated kanban: reads tasks.md from all tracked channels, merges columns."""
    user = _get_user(auth)
    prefs = await _get_mc_prefs(db, user)
    channels = await _tracked_channels(db, user, prefs, scope=scope)

    # Merge columns by name across all channels (parallel reads)
    merged: dict[str, list[KanbanCard]] = {}
    column_order: list[str] = []

    all_columns = await asyncio.gather(
        *(_read_tasks_for_channel(ch) for ch in channels)
    )
    for ch, columns in zip(channels, all_columns):
        for col in columns:
            col_name = col["name"]
            if col_name not in merged:
                merged[col_name] = []
                column_order.append(col_name)
            for card in col.get("cards", []):
                merged[col_name].append(KanbanCard(
                    title=card["title"],
                    meta=card.get("meta", {}),
                    description=card.get("description", ""),
                    channel_id=str(ch.id),
                    channel_name=ch.name,
                ))

    result_columns = [
        KanbanColumn(name=name, cards=merged[name])
        for name in column_order
    ]

    return {"columns": [c.model_dump() for c in result_columns]}


@router.post("/kanban/move", dependencies=[Depends(require_scopes("mission_control:write"))])
async def kanban_move(
    body: KanbanMoveRequest,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Move a card between columns. Writes back to the source channel's tasks.md."""
    user = _get_user(auth)
    channel = await db.get(Channel, body.channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    _require_channel_access(channel, user)
    if not channel.channel_workspace_enabled:
        raise HTTPException(400, "Channel workspace not enabled")

    from app.services.channel_workspace import read_workspace_file, write_workspace_file

    try:
        bot = _get_bot(channel.bot_id)
    except Exception:
        raise HTTPException(404, f"Bot '{channel.bot_id}' not found")
    content = await asyncio.to_thread(read_workspace_file, str(channel.id), bot, "tasks.md")
    if not content:
        raise HTTPException(404, "tasks.md not found")

    columns = parse_tasks_md(content)

    # Find and remove card from source column (verify from_column if provided)
    found_card = None
    for col in columns:
        for i, card in enumerate(col["cards"]):
            if card["meta"].get("id") == body.card_id:
                if col["name"].lower() != body.from_column.lower():
                    raise HTTPException(
                        409,
                        f"Card {body.card_id} is in '{col['name']}', not '{body.from_column}'",
                    )
                found_card = col["cards"].pop(i)
                break
        if found_card:
            break

    if not found_card:
        raise HTTPException(404, f"Card {body.card_id} not found")

    # Find or create target column
    target_col = None
    for col in columns:
        if col["name"].lower() == body.to_column.lower():
            target_col = col
            break

    if target_col is None:
        target_col = {"name": body.to_column, "cards": []}
        columns.append(target_col)

    # Add transition metadata
    today = date.today().isoformat()
    if body.to_column.lower() == "in progress":
        found_card["meta"]["started"] = today
    elif body.to_column.lower() == "done":
        found_card["meta"]["completed"] = today

    target_col["cards"].append(found_card)
    await asyncio.to_thread(write_workspace_file, str(channel.id), bot, "tasks.md", serialize_tasks_md(columns))

    # Auto-log to timeline
    try:
        from integrations.mission_control.tools.mission_control import _append_timeline
        await _append_timeline(
            str(channel.id),
            f"Card {body.card_id} moved to **{target_col['name']}** (was: {body.from_column}) — \"{found_card['title']}\"",
        )
    except Exception:
        logger.debug("Failed to log timeline event for kanban_move", exc_info=True)

    return {"ok": True, "card": found_card}


@router.post("/kanban/create", dependencies=[Depends(require_scopes("mission_control:write"))])
async def kanban_create(
    body: KanbanCreateRequest,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Create a new card in a specific channel's tasks.md."""
    user = _get_user(auth)
    channel = await db.get(Channel, body.channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    _require_channel_access(channel, user)
    if not channel.channel_workspace_enabled:
        raise HTTPException(400, "Channel workspace not enabled")

    from app.services.channel_workspace import (
        ensure_channel_workspace,
        read_workspace_file,
        write_workspace_file,
    )

    try:
        bot = _get_bot(channel.bot_id)
    except Exception:
        raise HTTPException(404, f"Bot '{channel.bot_id}' not found")
    await asyncio.to_thread(ensure_channel_workspace, str(channel.id), bot, display_name=channel.name)

    content = await asyncio.to_thread(read_workspace_file, str(channel.id), bot, "tasks.md")
    columns = parse_tasks_md(content) if content else default_columns()

    # Find or create target column
    target_col = None
    for col in columns:
        if col["name"].lower() == body.column.lower():
            target_col = col
            break

    if target_col is None:
        target_col = {"name": body.column, "cards": []}
        done_idx = next((i for i, c in enumerate(columns) if c["name"].lower() == "done"), None)
        if done_idx is not None:
            columns.insert(done_idx, target_col)
        else:
            columns.append(target_col)

    card_id = generate_card_id()
    meta: dict[str, str] = {"id": card_id}
    if body.assigned:
        meta["assigned"] = body.assigned
    meta["priority"] = body.priority
    meta["created"] = date.today().isoformat()
    if body.tags:
        meta["tags"] = body.tags
    if body.due:
        meta["due"] = body.due

    card = {"title": body.title, "meta": meta, "description": body.description}
    target_col["cards"].append(card)

    await asyncio.to_thread(write_workspace_file, str(channel.id), bot, "tasks.md", serialize_tasks_md(columns))

    # Auto-log to timeline
    try:
        from integrations.mission_control.tools.mission_control import _append_timeline
        await _append_timeline(
            str(channel.id),
            f"New card created: {card_id} \"{body.title}\" in **{target_col['name']}**",
        )
    except Exception:
        logger.debug("Failed to log timeline event for kanban_create", exc_info=True)

    return {"ok": True, "card": card, "column": target_col["name"]}


@router.patch("/kanban/update", dependencies=[Depends(require_scopes("mission_control:write"))])
async def kanban_update(
    body: KanbanUpdateRequest,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Update card fields (title, description, priority, assigned, due, tags)."""
    user = _get_user(auth)
    channel = await db.get(Channel, body.channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    _require_channel_access(channel, user)
    if not channel.channel_workspace_enabled:
        raise HTTPException(400, "Channel workspace not enabled")

    from app.services.channel_workspace import read_workspace_file, write_workspace_file

    try:
        bot = _get_bot(channel.bot_id)
    except Exception:
        raise HTTPException(404, f"Bot '{channel.bot_id}' not found")
    content = await asyncio.to_thread(read_workspace_file, str(channel.id), bot, "tasks.md")
    if not content:
        raise HTTPException(404, "tasks.md not found")

    columns = parse_tasks_md(content)

    # Find card by ID
    found_card = None
    for col in columns:
        for card in col["cards"]:
            if card["meta"].get("id") == body.card_id:
                found_card = card
                break
        if found_card:
            break

    if not found_card:
        raise HTTPException(404, f"Card {body.card_id} not found")

    # Apply updates
    changes: list[str] = []
    if body.title is not None and body.title != found_card["title"]:
        found_card["title"] = body.title
        changes.append("title")
    if body.description is not None and body.description != found_card.get("description", ""):
        found_card["description"] = body.description
        changes.append("description")
    if body.priority is not None and body.priority != found_card["meta"].get("priority", ""):
        found_card["meta"]["priority"] = body.priority
        changes.append("priority")
    if body.assigned is not None:
        if body.assigned:
            found_card["meta"]["assigned"] = body.assigned
        else:
            found_card["meta"].pop("assigned", None)
        changes.append("assigned")
    if body.due is not None:
        if body.due:
            found_card["meta"]["due"] = body.due
        else:
            found_card["meta"].pop("due", None)
        changes.append("due")
    if body.tags is not None:
        if body.tags:
            found_card["meta"]["tags"] = body.tags
        else:
            found_card["meta"].pop("tags", None)
        changes.append("tags")

    if not changes:
        return {"ok": True, "card": found_card, "changes": []}

    await asyncio.to_thread(write_workspace_file, str(channel.id), bot, "tasks.md", serialize_tasks_md(columns))

    # Auto-log to timeline
    try:
        from integrations.mission_control.tools.mission_control import _append_timeline
        change_str = ", ".join(changes)
        await _append_timeline(
            str(channel.id),
            f"Card {body.card_id} updated ({change_str}) — \"{found_card['title']}\"",
        )
    except Exception:
        logger.debug("Failed to log timeline event for kanban_update", exc_info=True)

    return {"ok": True, "card": found_card, "changes": changes}


@router.get("/timeline", response_model=TimelineResponse, dependencies=[Depends(require_scopes("mission_control:read"))])
async def timeline(
    days: int = Query(7, ge=1, le=90),
    scope: Literal["fleet", "personal"] = "fleet",
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Aggregated timeline: reads timeline.md from all tracked channels, merges events."""
    user = _get_user(auth)
    prefs = await _get_mc_prefs(db, user)
    channels = await _tracked_channels(db, user, prefs, scope=scope)

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    all_events: list[TimelineEvent] = []

    # Parallel reads across channels
    all_raw = await asyncio.gather(
        *(_read_timeline_for_channel(ch) for ch in channels)
    )
    for ch, raw_events in zip(channels, all_raw):
        for ev in raw_events:
            if ev["date"] < cutoff:
                break  # timeline.md is newest-first, so we can stop early
            all_events.append(TimelineEvent(
                date=ev["date"],
                time=ev["time"],
                event=_humanize_event(ev["event"]),
                channel_id=str(ch.id),
                channel_name=ch.name,
            ))

    # Sort by date desc, then time desc
    all_events.sort(key=lambda e: (e.date, e.time), reverse=True)
    return {"events": all_events}


@router.get("/journal", response_model=JournalResponse, dependencies=[Depends(require_scopes("mission_control:read"))])
async def journal(
    days: int = Query(7, ge=1, le=90),
    scope: Literal["fleet", "personal"] = "fleet",
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Aggregated daily logs from tracked bots."""
    user = _get_user(auth)
    prefs = await _get_mc_prefs(db, user)
    channels = await _tracked_channels(db, user, prefs, scope=scope)

    # Collect unique bot_ids from tracked channels
    bot_ids = list({ch.bot_id for ch in channels})

    # Filter to tracked_bot_ids if set
    if prefs.get("tracked_bot_ids"):
        tracked = set(prefs["tracked_bot_ids"])
        bot_ids = [bid for bid in bot_ids if bid in tracked]

    entries: list[dict] = []
    today = date.today()

    for bot_id in bot_ids:
        try:
            bot = _get_bot(bot_id)
        except Exception:
            continue

        if bot.memory_scheme != "workspace-files":
            continue

        from app.services.memory_scheme import get_memory_root
        try:
            mem_root = get_memory_root(bot)
        except Exception:
            continue

        logs_dir = os.path.join(mem_root, "logs")
        if not os.path.isdir(logs_dir):
            continue

        def _read_logs(logs_dir=logs_dir, bot=bot):
            results = []
            for day_offset in range(days):
                d = today - timedelta(days=day_offset)
                log_path = os.path.join(logs_dir, f"{d.isoformat()}.md")
                if os.path.isfile(log_path):
                    try:
                        with open(log_path) as f:
                            content = f.read()
                        if content.strip():
                            results.append({
                                "date": d.isoformat(),
                                "bot_id": bot.id,
                                "bot_name": bot.name,
                                "content": content,
                            })
                    except Exception:
                        pass
            return results

        entries.extend(await asyncio.to_thread(_read_logs))

    # Sort by date descending
    entries.sort(key=lambda e: e["date"], reverse=True)
    return {"entries": entries}


@router.get("/memory", response_model=MemoryResponse, dependencies=[Depends(require_scopes("mission_control:read"))])
async def memory(
    scope: Literal["fleet", "personal"] = "fleet",
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """MEMORY.md + reference files from tracked bots."""
    user = _get_user(auth)
    prefs = await _get_mc_prefs(db, user)
    channels = await _tracked_channels(db, user, prefs, scope=scope)

    bot_ids = list({ch.bot_id for ch in channels})
    if prefs.get("tracked_bot_ids"):
        tracked = set(prefs["tracked_bot_ids"])
        bot_ids = [bid for bid in bot_ids if bid in tracked]

    sections: list[dict] = []

    for bot_id in bot_ids:
        try:
            bot = _get_bot(bot_id)
        except Exception:
            continue

        if bot.memory_scheme != "workspace-files":
            continue

        from app.services.memory_scheme import get_memory_root
        try:
            mem_root = get_memory_root(bot)
        except Exception:
            continue

        def _read_memory(mem_root=mem_root, bot=bot):
            # Read MEMORY.md
            memory_content = None
            mem_md = os.path.join(mem_root, "MEMORY.md")
            if os.path.isfile(mem_md):
                try:
                    with open(mem_md) as f:
                        memory_content = f.read()
                except Exception:
                    pass

            # List reference files
            ref_dir = os.path.join(mem_root, "reference")
            ref_files: list[str] = []
            if os.path.isdir(ref_dir):
                ref_files = sorted(
                    e.name for e in os.scandir(ref_dir) if e.is_file()
                )

            return {
                "bot_id": bot.id,
                "bot_name": bot.name,
                "memory_content": memory_content,
                "reference_files": ref_files,
            }

        sections.append(await asyncio.to_thread(_read_memory))

    return {"sections": sections}


@router.get(
    "/channels/{channel_id}/context",
    dependencies=[Depends(require_scopes("mission_control:read"))],
)
async def channel_context(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Full context debug: schema, files, recent tool calls, recent traces."""
    user = _get_user(auth)
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    _require_channel_access(channel, user)

    from app.services.channel_workspace import list_workspace_files, read_workspace_file

    try:
        bot = _get_bot(channel.bot_id)
    except Exception:
        raise HTTPException(404, f"Bot '{channel.bot_id}' not found")

    # 1. Configuration
    config = {
        "channel_id": str(channel.id),
        "channel_name": channel.name,
        "bot_id": channel.bot_id,
        "bot_name": bot.name,
        "model": channel.model_override or bot.model,
        "workspace_enabled": bool(channel.channel_workspace_enabled),
        "workspace_rag": bool(channel.workspace_rag),
        "context_compaction": bool(channel.context_compaction),
        "memory_scheme": bot.memory_scheme,
        "history_mode": channel.history_mode or bot.history_mode,
        "tools": bot.local_tools,
        "mcp_servers": bot.mcp_servers,
        "skills": bot.skills,
        "pinned_tools": bot.pinned_tools,
    }

    # 2. Workspace schema
    schema_content = None
    template_name = None
    if channel.workspace_schema_content:
        schema_content = channel.workspace_schema_content
    elif channel.workspace_schema_template_id:
        from app.db.models import PromptTemplate
        tpl = await db.get(PromptTemplate, channel.workspace_schema_template_id)
        if tpl:
            schema_content = tpl.content
            template_name = tpl.name

    # 3. Workspace files
    files = []
    if channel.channel_workspace_enabled:
        try:
            files = await asyncio.to_thread(
                list_workspace_files, str(channel.id), bot, include_archive=True, include_data=True,
            )
        except Exception:
            pass

    # 4. Recent tool calls (last 50) — guard against null session_id
    tool_calls = []
    trace_events = []
    if channel.active_session_id:
        tc_result = await db.execute(
            select(ToolCall)
            .where(ToolCall.session_id == channel.active_session_id)
            .order_by(ToolCall.created_at.desc())
            .limit(50)
        )
        tool_calls = [
            {
                "id": str(tc.id),
                "tool_name": tc.tool_name,
                "tool_type": tc.tool_type,
                "arguments": tc.arguments,
                "result": (tc.result or "")[:500],
                "error": tc.error,
                "duration_ms": tc.duration_ms,
                "created_at": tc.created_at.isoformat() if tc.created_at else None,
            }
            for tc in tc_result.scalars().all()
        ]

        # 5. Recent trace events (last 30)
        te_result = await db.execute(
            select(TraceEvent)
            .where(TraceEvent.session_id == channel.active_session_id)
            .order_by(TraceEvent.created_at.desc())
            .limit(30)
        )
        trace_events = [
            {
                "id": str(te.id),
                "event_type": te.event_type,
                "event_name": te.event_name,
                "data": te.data,
                "duration_ms": te.duration_ms,
                "created_at": te.created_at.isoformat() if te.created_at else None,
            }
            for te in te_result.scalars().all()
        ]

    return {
        "config": config,
        "schema": {
            "template_name": template_name,
            "content": schema_content,
        },
        "files": files,
        "tool_calls": tool_calls,
        "trace_events": trace_events,
    }


@router.get("/prefs", dependencies=[Depends(require_scopes("mission_control:read"))])
async def get_prefs(
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Get user's MC preferences."""
    user = _get_user(auth)
    prefs = await _get_mc_prefs(db, user)
    return prefs or {
        "tracked_channel_ids": None,
        "tracked_bot_ids": None,
        "kanban_filters": {},
        "layout_prefs": {},
    }


@router.put("/prefs", dependencies=[Depends(require_scopes("mission_control:write"))])
async def update_prefs(
    body: MCPrefsUpdate,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Update user's MC preferences."""
    user = _get_user(auth)
    if not user:
        raise HTTPException(400, "Preferences require JWT auth (not API key)")

    ic = dict(user.integration_config or {})
    mc_prefs = dict(ic.get("mission_control", {}))

    update = body.model_dump(exclude_unset=True)
    mc_prefs.update(update)
    ic["mission_control"] = mc_prefs
    user.integration_config = ic

    db.add(user)
    await db.commit()

    return mc_prefs


@router.get(
    "/memory/{bot_id}/reference/{filename}",
    dependencies=[Depends(require_scopes("mission_control:read"))],
)
async def read_reference_file(
    bot_id: str,
    filename: str,
    auth=Depends(verify_auth_or_user),
):
    """Read a specific reference file from a bot's memory/reference/ directory."""
    # Validate filename — no path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")

    try:
        bot = _get_bot(bot_id)
    except Exception:
        raise HTTPException(404, f"Bot '{bot_id}' not found")

    if bot.memory_scheme != "workspace-files":
        raise HTTPException(400, f"Bot '{bot_id}' does not use workspace-files memory scheme")

    from app.services.memory_scheme import get_memory_root

    try:
        mem_root = get_memory_root(bot)
    except Exception:
        raise HTTPException(500, "Could not resolve memory root")

    ref_path = os.path.join(mem_root, "reference", filename)

    # Security: verify resolved path is within the reference directory
    real_ref_dir = os.path.realpath(os.path.join(mem_root, "reference"))
    real_path = os.path.realpath(ref_path)
    if not real_path.startswith(real_ref_dir + os.sep) and real_path != real_ref_dir:
        raise HTTPException(400, "Invalid filename")

    if not os.path.isfile(ref_path):
        raise HTTPException(404, "Reference file not found")

    def _read():
        with open(ref_path) as f:
            return f.read()

    try:
        content = await asyncio.to_thread(_read)
    except UnicodeDecodeError:
        raise HTTPException(400, "File is not a text file")
    return {"content": content}


@router.get(
    "/setup-guide",
    dependencies=[Depends(require_scopes("mission_control:read"))],
)
async def setup_guide():
    """Return the Mission Control setup guide as markdown."""
    content = """\
# Mission Control Setup Guide

Mission Control aggregates workspace data from your channels and bots into a unified fleet dashboard.

## Prerequisites

### 1. Enable Channel Workspaces
Each channel you want to track needs **workspace enabled**:
- Go to **Admin → Channels → [channel] → Settings**
- Toggle **Channel Workspace** on
- Optionally select a **workspace schema template** (e.g. Software Dev, Research)

### 2. Configure Bot Memory
For Journal and Memory pages, bots need the workspace-files memory scheme:
```yaml
# In your bot YAML (bots/my-bot.yaml)
memory_scheme: workspace-files
```
This creates a `memory/` directory with:
- `MEMORY.md` — curated facts and preferences
- `memory/logs/` — daily activity logs (auto-generated)
- `memory/reference/` — reference documents

### 3. Task Board (Kanban)
The Kanban page reads `tasks.md` from each channel's workspace.

**Automatic**: When a channel has workspace enabled, the **mission-control** carapace is auto-injected. This gives the bot the `create_task_card` and `move_task_card` tools, plus the Mission Control skill documenting the `tasks.md` format, `status.md`, and card metadata conventions. No per-bot configuration needed.

You can also create and move cards directly from the Kanban page in the UI.

> **Note**: If a bot already has the Mission Control skill or tools configured manually, the auto-injection is a no-op (deduplication is built in). You can also disable the auto-injection per channel by adding `mission-control` to the channel's `carapaces_disabled` list.

## Feature Reference

| Feature | Requires | What it shows |
|---------|----------|---------------|
| **Dashboard** | Workspace-enabled channels | Channel list, bot list, stats |
| **Kanban** | Workspace-enabled channels (tools auto-injected) | Aggregated task board across channels |
| **Journal** | `memory_scheme: workspace-files` | Daily logs from all tracked bots |
| **Memory** | `memory_scheme: workspace-files` | MEMORY.md + reference files per bot |

## Scope Toggle
Admins see a **Fleet / Personal** toggle:
- **Fleet**: All workspace-enabled channels (default)
- **Personal**: Only channels you own

## Integration Modules
Integrations can register custom dashboard modules. These appear as additional pages under Mission Control. Check **Admin → Integrations** for available modules.

## Troubleshooting
- **Empty dashboard?** Check that at least one channel has workspace enabled
- **Empty kanban?** Make sure the channel has workspace enabled — the mission-control carapace (skill + tools) is auto-injected. Ask the bot to create a task, or create cards from the Kanban page UI.
- **Empty journal?** Set `memory_scheme: workspace-files` in bot YAML and wait for the next interaction
- **Empty memory?** Same as journal — MEMORY.md is created on the bot's first run
"""
    return {"content": content}


@router.get("/modules", dependencies=[Depends(require_scopes("mission_control:read"))])
async def list_modules():
    """List dashboard modules registered by integrations."""
    from integrations import discover_dashboard_modules

    return {"modules": discover_dashboard_modules()}


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

@router.get("/plans", response_model=MCPlansResponse, dependencies=[Depends(require_scopes("mission_control:read"))])
async def plans(
    scope: Literal["fleet", "personal"] = "fleet",
    status: str | None = Query(None, description="Comma-separated statuses to filter (e.g. draft,executing)"),
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Aggregated plans: reads plans.md from all tracked channels."""
    user = _get_user(auth)
    prefs = await _get_mc_prefs(db, user)
    channels = await _tracked_channels(db, user, prefs, scope=scope)

    status_filter = {s.strip() for s in status.split(",")} if status else None

    all_raw = await asyncio.gather(
        *(_read_plans_for_channel(ch) for ch in channels)
    )

    all_plans: list[MCPlan] = []
    for ch, raw_plans in zip(channels, all_raw):
        for p in raw_plans:
            if status_filter and p["status"] not in status_filter:
                continue
            all_plans.append(MCPlan(
                id=p["meta"].get("id", ""),
                title=p["title"],
                status=p["status"],
                meta=p.get("meta", {}),
                steps=[MCPlanStep(**s) for s in p.get("steps", [])],
                notes=p.get("notes", ""),
                channel_id=str(ch.id),
                channel_name=ch.name,
            ))

    return {"plans": all_plans}


@router.post(
    "/channels/{channel_id}/plans/{plan_id}/approve",
    dependencies=[Depends(require_scopes("mission_control:write"))],
)
async def approve_plan(
    channel_id: uuid.UUID,
    plan_id: str,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Approve a draft plan — transitions to approved and triggers bot execution."""
    user = _get_user(auth)
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    _require_channel_access(channel, user)
    if not channel.channel_workspace_enabled:
        raise HTTPException(400, "Channel workspace not enabled")

    from app.services.channel_workspace import read_workspace_file, write_workspace_file

    try:
        bot = _get_bot(channel.bot_id)
    except Exception:
        raise HTTPException(404, f"Bot '{channel.bot_id}' not found")

    content = await asyncio.to_thread(
        read_workspace_file, str(channel.id), bot, "plans.md",
    )
    if not content:
        raise HTTPException(404, "plans.md not found")

    plans_list = parse_plans_md(content)

    plan = None
    for p in plans_list:
        if p["meta"].get("id") == plan_id:
            plan = p
            break

    if not plan:
        raise HTTPException(404, f"Plan '{plan_id}' not found")
    if plan["status"] != "draft":
        raise HTTPException(409, f"Plan is [{plan['status']}], expected [draft]")

    plan["status"] = "approved"
    plan["meta"]["approved"] = date.today().isoformat()

    await asyncio.to_thread(
        write_workspace_file, str(channel.id), bot, "plans.md",
        serialize_plans_md(plans_list),
    )

    # Log to timeline
    try:
        from integrations.mission_control.tools.mission_control import _append_timeline
        await _append_timeline(str(channel.id), f"Plan approved: **{plan['title']}** ({plan_id})")
    except Exception:
        logger.debug("Failed to log timeline for plan approval", exc_info=True)

    # Create execution task with plan-aware context for self-continuation
    task_created = False
    try:
        from app.db.models import Task as TaskModel
        from app.services.channels import ensure_active_session
        from app.services.sessions import store_passive_message

        session_id = await ensure_active_session(db, channel)
        await db.commit()

        step_summary = _plan_step_summary(plan)
        prompt = (
            f"Plan '{plan['title']}' ({plan_id}) has been approved. "
            f"Execute the next pending step.\n\n"
            f"Current step status:\n{step_summary}"
        )
        await store_passive_message(db, session_id, prompt, {"source": "mission_control"})
        await db.commit()

        task = TaskModel(
            bot_id=channel.bot_id,
            client_id=channel.client_id,
            session_id=session_id,
            channel_id=channel.id,
            prompt=prompt,
            status="pending",
            task_type="api",
            dispatch_type=channel.integration or "none",
            dispatch_config=channel.dispatch_config or {},
            execution_config={
                "system_preamble": (
                    f"You are executing approved plan '{plan['title']}' ({plan_id}). "
                    "Work through ONE step at a time. For each step: "
                    "1) call update_plan_step to mark it in_progress, "
                    "2) do the work, "
                    "3) call update_plan_step to mark it done (or failed if it cannot be completed). "
                    "Write intermediate results to workspace files. "
                    "After completing a step, if more steps remain, call schedule_task() "
                    "to continue with the next step — use this exact prompt pattern: "
                    f"\"Continue executing plan '{plan['title']}' ({plan_id}). "
                    f"Pick up from the next pending step.\""
                ),
            },
            callback_config={
                "trigger_rag_loop": True,
            },
            created_at=datetime.now(timezone.utc),
        )
        db.add(task)
        await db.commit()
        task_created = True
    except Exception:
        logger.warning("Failed to send approval message to channel %s", channel.id, exc_info=True)

    return {
        "ok": True,
        "plan_id": plan_id,
        "status": "approved",
        "task_created": task_created,
    }


@router.post(
    "/channels/{channel_id}/plans/{plan_id}/reject",
    dependencies=[Depends(require_scopes("mission_control:write"))],
)
async def reject_plan(
    channel_id: uuid.UUID,
    plan_id: str,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Reject a draft plan — transitions to abandoned."""
    user = _get_user(auth)
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    _require_channel_access(channel, user)
    if not channel.channel_workspace_enabled:
        raise HTTPException(400, "Channel workspace not enabled")

    from app.services.channel_workspace import read_workspace_file, write_workspace_file

    try:
        bot = _get_bot(channel.bot_id)
    except Exception:
        raise HTTPException(404, f"Bot '{channel.bot_id}' not found")

    content = await asyncio.to_thread(
        read_workspace_file, str(channel.id), bot, "plans.md",
    )
    if not content:
        raise HTTPException(404, "plans.md not found")

    plans_list = parse_plans_md(content)

    plan = None
    for p in plans_list:
        if p["meta"].get("id") == plan_id:
            plan = p
            break

    if not plan:
        raise HTTPException(404, f"Plan '{plan_id}' not found")
    if plan["status"] not in ("draft", "approved"):
        raise HTTPException(409, f"Plan is [{plan['status']}], expected [draft] or [approved]")

    plan["status"] = "abandoned"

    await asyncio.to_thread(
        write_workspace_file, str(channel.id), bot, "plans.md",
        serialize_plans_md(plans_list),
    )

    try:
        from integrations.mission_control.tools.mission_control import _append_timeline
        await _append_timeline(str(channel.id), f"Plan rejected: **{plan['title']}** ({plan_id})")
    except Exception:
        logger.debug("Failed to log timeline for plan rejection", exc_info=True)

    return {"ok": True, "plan_id": plan_id, "status": "abandoned"}


@router.post(
    "/channels/{channel_id}/plans/{plan_id}/resume",
    dependencies=[Depends(require_scopes("mission_control:write"))],
)
async def resume_plan(
    channel_id: uuid.UUID,
    plan_id: str,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Resume a stalled executing plan — sends a continue message to the channel."""
    user = _get_user(auth)
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    _require_channel_access(channel, user)
    if not channel.channel_workspace_enabled:
        raise HTTPException(400, "Channel workspace not enabled")

    from app.services.channel_workspace import read_workspace_file

    try:
        bot = _get_bot(channel.bot_id)
    except Exception:
        raise HTTPException(404, f"Bot '{channel.bot_id}' not found")

    content = await asyncio.to_thread(
        read_workspace_file, str(channel.id), bot, "plans.md",
    )
    if not content:
        raise HTTPException(404, "plans.md not found")

    plans_list = parse_plans_md(content)

    plan = None
    for p in plans_list:
        if p["meta"].get("id") == plan_id:
            plan = p
            break

    if not plan:
        raise HTTPException(404, f"Plan '{plan_id}' not found")
    if plan["status"] != "executing":
        raise HTTPException(409, f"Plan is [{plan['status']}], expected [executing]")

    try:
        from integrations.mission_control.tools.mission_control import _append_timeline
        await _append_timeline(str(channel.id), f"Plan resumed: **{plan['title']}** ({plan_id})")
    except Exception:
        logger.debug("Failed to log timeline for plan resume", exc_info=True)

    task_created = False
    try:
        from app.db.models import Task as TaskModel
        from app.services.channels import ensure_active_session
        from app.services.sessions import store_passive_message

        session_id = await ensure_active_session(db, channel)
        await db.commit()

        step_summary = _plan_step_summary(plan)
        prompt = (
            f"Continue executing plan '{plan['title']}' ({plan_id}). "
            f"Pick up from the next pending step.\n\n"
            f"Current step status:\n{step_summary}"
        )
        await store_passive_message(db, session_id, prompt, {"source": "mission_control"})
        await db.commit()

        task = TaskModel(
            bot_id=channel.bot_id,
            client_id=channel.client_id,
            session_id=session_id,
            channel_id=channel.id,
            prompt=prompt,
            status="pending",
            task_type="api",
            dispatch_type=channel.integration or "none",
            dispatch_config=channel.dispatch_config or {},
            execution_config={
                "system_preamble": (
                    f"You are resuming execution of plan '{plan['title']}' ({plan_id}). "
                    "Work through ONE step at a time. For each step: "
                    "1) call update_plan_step to mark it in_progress, "
                    "2) do the work, "
                    "3) call update_plan_step to mark it done (or failed if it cannot be completed). "
                    "Write intermediate results to workspace files. "
                    "After completing a step, if more steps remain, call schedule_task() "
                    "to continue with the next step."
                ),
            },
            callback_config={
                "trigger_rag_loop": True,
            },
            created_at=datetime.now(timezone.utc),
        )
        db.add(task)
        await db.commit()
        task_created = True
    except Exception:
        logger.warning("Failed to send resume message to channel %s", channel.id, exc_info=True)

    return {
        "ok": True,
        "plan_id": plan_id,
        "status": "executing",
        "task_created": task_created,
    }


# ---------------------------------------------------------------------------
# Channel membership (join / leave)
# ---------------------------------------------------------------------------

@router.post(
    "/channels/{channel_id}/join",
    dependencies=[Depends(require_scopes("mission_control:write"))],
)
async def join_channel(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Add current user as a member of a channel (idempotent)."""
    user = _get_user(auth)
    if not user:
        raise HTTPException(403, "JWT auth required")

    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")

    from sqlalchemy.dialects.postgresql import insert as pg_insert
    stmt = pg_insert(ChannelMember).values(
        channel_id=channel_id, user_id=user.id,
    ).on_conflict_do_nothing()
    await db.execute(stmt)
    await db.commit()
    return {"ok": True}


@router.delete(
    "/channels/{channel_id}/join",
    dependencies=[Depends(require_scopes("mission_control:write"))],
)
async def leave_channel(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Remove current user from channel membership."""
    user = _get_user(auth)
    if not user:
        raise HTTPException(403, "JWT auth required")

    from sqlalchemy import delete
    await db.execute(
        delete(ChannelMember).where(
            ChannelMember.channel_id == channel_id,
            ChannelMember.user_id == user.id,
        )
    )
    await db.commit()
    return {"ok": True}
