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
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bot, Channel, ToolCall, TraceEvent, User
from app.dependencies import get_db, require_scopes, verify_auth_or_user
from app.services.task_board import (
    default_columns,
    generate_card_id,
    parse_tasks_md,
    serialize_tasks_md,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mission-control", tags=["Mission Control"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


async def _tracked_channels(
    db: AsyncSession,
    user: User | None,
    prefs: dict | None = None,
) -> list[Channel]:
    """Get channels tracked by MC for this user."""
    q = select(Channel).where(Channel.channel_workspace_enabled == True)  # noqa: E712

    if user:
        q = q.where(Channel.user_id == user.id)

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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/overview", dependencies=[Depends(require_scopes("mission_control:read"))])
async def overview(
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Fleet stats, channel list with task counts, bot list."""
    user = _get_user(auth)
    prefs = await _get_mc_prefs(db, user)
    channels = await _tracked_channels(db, user, prefs)

    # Build bot lookup
    bots_q = select(Bot).order_by(Bot.name)
    if user:
        bots_q = bots_q.where((Bot.user_id == user.id) | (Bot.user_id == None))  # noqa: E711
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

    # Task counts per channel
    total_tasks = 0
    channel_overviews = []
    for ch in channels:
        columns = await _read_tasks_for_channel(ch)
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
        "total_bots": len(bots),
        "total_tasks": total_tasks,
    }


@router.get("/kanban", dependencies=[Depends(require_scopes("mission_control:read"))])
async def kanban(
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Aggregated kanban: reads tasks.md from all tracked channels, merges columns."""
    user = _get_user(auth)
    prefs = await _get_mc_prefs(db, user)
    channels = await _tracked_channels(db, user, prefs)

    # Merge columns by name across all channels
    merged: dict[str, list[KanbanCard]] = {}
    column_order: list[str] = []

    for ch in channels:
        columns = await _read_tasks_for_channel(ch)
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

    return {"ok": True, "card": card, "column": target_col["name"]}


@router.get("/journal", response_model=JournalResponse, dependencies=[Depends(require_scopes("mission_control:read"))])
async def journal(
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Aggregated daily logs from tracked bots."""
    user = _get_user(auth)
    prefs = await _get_mc_prefs(db, user)
    channels = await _tracked_channels(db, user, prefs)

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
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """MEMORY.md + reference files from tracked bots."""
    user = _get_user(auth)
    prefs = await _get_mc_prefs(db, user)
    channels = await _tracked_channels(db, user, prefs)

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
