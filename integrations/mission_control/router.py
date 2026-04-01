"""FastAPI router for Mission Control — main router with sub-router includes.

Endpoints: overview, readiness, prefs, modules, workspace proxy, setup guide, membership.
Sub-routers: kanban, plans, timeline, journal, memory.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bot, Channel, ChannelMember, Session, Task, User
from app.dependencies import get_db, require_scopes, verify_auth, verify_auth_or_user
from integrations.mission_control.helpers import (
    get_bot,
    get_mc_prefs,
    get_user,
    has_kanban_data,
    has_plans_data,
    has_timeline_data,
    read_tasks_for_channel,
    require_channel_access,
    tracked_channels,
)
from integrations.mission_control.schemas import (
    BotOverview,
    ChannelOverview,
    FeatureReadiness,
    MCPrefsUpdate,
    ReadinessResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Include sub-routers (all share the same prefix — mounted at /integrations/mission_control/)
from integrations.mission_control.router_kanban import router as kanban_router
from integrations.mission_control.router_plans import router as plans_router
from integrations.mission_control.router_timeline import router as timeline_router
from integrations.mission_control.router_journal import router as journal_router
from integrations.mission_control.router_memory import router as memory_router

router.include_router(kanban_router, dependencies=[Depends(require_scopes("mission_control:read"))])
router.include_router(plans_router, dependencies=[Depends(require_scopes("mission_control:read"))])
router.include_router(timeline_router, dependencies=[Depends(require_scopes("mission_control:read"))])
router.include_router(journal_router, dependencies=[Depends(require_scopes("mission_control:read"))])
router.include_router(memory_router, dependencies=[Depends(require_scopes("mission_control:read"))])


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get("/ping")
async def ping():
    return {"status": "ok", "service": "mission-control"}


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

@router.get("/overview", dependencies=[Depends(require_scopes("mission_control:read"))])
async def overview(
    scope: Literal["fleet", "personal"] = "fleet",
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Fleet stats, channel list with task counts, bot list."""
    user = get_user(auth)
    prefs = await get_mc_prefs(db, user)
    channels = await tracked_channels(db, user, prefs, scope=scope)

    total_channels_all = (await db.execute(select(func.count(Channel.id)))).scalar() or 0

    member_channel_ids: set[uuid.UUID] = set()
    if user:
        rows = (await db.execute(
            select(ChannelMember.channel_id).where(ChannelMember.user_id == user.id)
        )).scalars().all()
        member_channel_ids = set(rows)

    bots_q = select(Bot).order_by(Bot.name)
    bots_result = await db.execute(bots_q)
    bots = list(bots_result.scalars().all())
    bot_map = {b.id: b for b in bots}

    bot_channel_counts: dict[str, int] = {}
    for ch in channels:
        bot_channel_counts[ch.bot_id] = bot_channel_counts.get(ch.bot_id, 0) + 1

    _template_ids = {ch.workspace_schema_template_id for ch in channels if ch.workspace_schema_template_id}
    _template_names: dict[str, str] = {}
    if _template_ids:
        from app.db.models import PromptTemplate
        _tpl_rows = (await db.execute(
            select(PromptTemplate).where(PromptTemplate.id.in_(_template_ids))
        )).scalars().all()
        _template_names = {str(t.id): t.name for t in _tpl_rows}

    task_results = await asyncio.gather(
        *(read_tasks_for_channel(ch) for ch in channels)
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
        "is_admin": user.is_admin if user else True,
    }


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------

@router.get("/readiness", dependencies=[Depends(require_scopes("mission_control:read"))])
async def readiness(
    scope: Literal["fleet", "personal"] = "fleet",
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Check system readiness for each MC feature."""
    from app.agent.bots import list_bots

    user = get_user(auth)
    prefs = await get_mc_prefs(db, user)
    channels = await tracked_channels(db, user, prefs, scope=scope)

    dashboard_issues: list[str] = []
    if not channels:
        dashboard_issues.append("No channels have workspace enabled. Enable it in channel settings.")
    dashboard = FeatureReadiness(
        ready=len(channels) > 0,
        detail=f"{len(channels)} workspace-enabled channel{'s' if len(channels) != 1 else ''}",
        count=len(channels),
        total=len(channels),
        issues=dashboard_issues,
    )

    kanban_results = await asyncio.gather(*(has_kanban_data(ch) for ch in channels)) if channels else []
    kanban_count = sum(1 for r in kanban_results if r)
    kanban_issues: list[str] = []
    if channels and kanban_count == 0:
        kanban_issues.append("No channels have task cards yet. The mission-control carapace (auto-injected) gives bots the tools to create cards, or create them from the Kanban page.")
    elif not channels:
        kanban_issues.append("No workspace-enabled channels. Enable workspace in channel settings first.")
    kanban = FeatureReadiness(
        ready=kanban_count > 0,
        detail=f"{kanban_count} of {len(channels)} channels have task cards",
        count=kanban_count,
        total=len(channels),
        issues=kanban_issues,
    )

    all_bots = list_bots()
    bot_ids_in_channels = {ch.bot_id for ch in channels}
    memory_bots = [b for b in all_bots if b.memory_scheme == "workspace-files" and b.id in bot_ids_in_channels]

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

    journal_count, memory_count = (await asyncio.to_thread(_check_memory_bots)) if memory_bots else (0, 0)

    journal_issues: list[str] = []
    if not memory_bots:
        journal_issues.append("No bots have memory_scheme: workspace-files. Set this in bot YAML.")
    elif journal_count == 0:
        journal_issues.append("No bots have memory/logs/ directory yet. Logs appear after the bot runs.")
    journal_feat = FeatureReadiness(
        ready=journal_count > 0,
        detail=f"{journal_count} bot{'s' if journal_count != 1 else ''} with journal logs",
        count=journal_count,
        total=len(memory_bots),
        issues=journal_issues,
    )

    memory_issues: list[str] = []
    if not memory_bots:
        memory_issues.append("No bots have memory_scheme: workspace-files. Set this in bot YAML.")
    elif memory_count == 0:
        memory_issues.append("No bots have MEMORY.md yet. It's created after the bot's first run.")
    memory_feat = FeatureReadiness(
        ready=memory_count > 0,
        detail=f"{memory_count} bot{'s' if memory_count != 1 else ''} with MEMORY.md",
        count=memory_count,
        total=len(memory_bots),
        issues=memory_issues,
    )

    timeline_results = await asyncio.gather(*(has_timeline_data(ch) for ch in channels)) if channels else []
    timeline_count = sum(1 for r in timeline_results if r)
    timeline_issues: list[str] = []
    if channels and timeline_count == 0:
        timeline_issues.append("No channels have timeline events yet. Events are auto-logged when tasks are created or moved.")
    elif not channels:
        timeline_issues.append("No workspace-enabled channels. Enable workspace in channel settings first.")
    timeline_feat = FeatureReadiness(
        ready=timeline_count > 0,
        detail=f"{timeline_count} of {len(channels)} channels have timeline events",
        count=timeline_count,
        total=len(channels),
        issues=timeline_issues,
    )

    plans_results = await asyncio.gather(*(has_plans_data(ch) for ch in channels)) if channels else []
    plans_count = sum(1 for r in plans_results if r)
    plans_issues: list[str] = []
    if channels and plans_count == 0:
        plans_issues.append("No channels have plans yet. Plans are created when bots draft structured proposals.")
    elif not channels:
        plans_issues.append("No workspace-enabled channels. Enable workspace in channel settings first.")
    plans_feat = FeatureReadiness(
        ready=plans_count > 0,
        detail=f"{plans_count} of {len(channels)} channels have plans",
        count=plans_count,
        total=len(channels),
        issues=plans_issues,
    )

    return ReadinessResponse(
        dashboard=dashboard,
        kanban=kanban,
        journal=journal_feat,
        memory=memory_feat,
        timeline=timeline_feat,
        plans=plans_feat,
    )


# ---------------------------------------------------------------------------
# Prefs
# ---------------------------------------------------------------------------

@router.get("/prefs", dependencies=[Depends(require_scopes("mission_control:read"))])
async def get_prefs(
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Get user's MC preferences."""
    user = get_user(auth)
    prefs = await get_mc_prefs(db, user)
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
    user = get_user(auth)
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


# ---------------------------------------------------------------------------
# Modules
# ---------------------------------------------------------------------------

@router.get("/modules", dependencies=[Depends(require_scopes("mission_control:read"))])
async def list_modules():
    """List dashboard modules registered by integrations."""
    from integrations import discover_dashboard_modules
    return {"modules": discover_dashboard_modules()}


# ---------------------------------------------------------------------------
# Setup guide
# ---------------------------------------------------------------------------

@router.get("/setup-guide", dependencies=[Depends(require_scopes("mission_control:read"))])
async def setup_guide():
    """Return the Mission Control setup guide as markdown."""
    content = """\
# Mission Control Setup Guide

Mission Control is a **DB-backed** project management system. All task cards, timeline events, and plans are stored in a local SQLite database. Workspace files (`tasks.md`, `timeline.md`, `plans.md`) are **read-only renderings** auto-generated from the database — never edit them directly.

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
Task cards are stored in the **MC database** and aggregated across all tracked channels.

**Automatic**: When a channel has workspace enabled, the **mission-control** carapace is auto-injected. This gives the bot the `create_task_card` and `move_task_card` tools, plus the Mission Control skill. No per-bot configuration needed.

You can also create and move cards directly from the **Kanban page** in the UI.

> **Note**: If a bot already has the Mission Control carapace configured manually, the auto-injection is a no-op (deduplication is built in). You can also disable auto-injection per channel by adding `mission-control` to the channel's `carapaces_disabled` list.

### 4. Plans
Plans are created via the `draft_plan` tool and stored in the MC database. After user approval, the **plan executor** automatically creates tasks for each step and manages sequencing. Steps marked with approval gates pause execution until approved in the dashboard.

## Feature Reference

| Feature | Requires | Data Source | What it shows |
|---------|----------|-------------|---------------|
| **Dashboard** | Workspace-enabled channels | MC DB | Channel list, bot list, stats |
| **Kanban** | Workspace-enabled channels (tools auto-injected) | MC DB | Aggregated task board across channels |
| **Timeline** | Workspace-enabled channels | MC DB | Activity events (task moves, plan state changes) |
| **Plans** | Workspace-enabled channels | MC DB | Structured plans with step tracking and approval gates |
| **Journal** | `memory_scheme: workspace-files` | Filesystem | Daily logs from all tracked bots |
| **Memory** | `memory_scheme: workspace-files` | Filesystem | MEMORY.md + reference files per bot |

## Scope Toggle
Admins see a **Fleet / Personal** toggle:
- **Fleet**: All workspace-enabled channels (default)
- **Personal**: Only channels you own

## Integration Modules
Integrations can register custom dashboard modules. These appear as additional pages under Mission Control. Check **Admin → Integrations** for available modules.

## Architecture Notes
- **Database**: MC uses a local SQLite database (WAL mode) independent of the core PostgreSQL database
- **Read-only files**: `tasks.md`, `timeline.md`, and `plans.md` in channel workspaces are auto-generated renderings — all mutations go through tools
- **Tools**: `create_task_card`, `move_task_card`, `draft_plan`, `update_plan_step`, `update_plan_status`, `append_timeline_event`
- **Plan executor**: After plan approval, automatically creates tasks for each step, handles step sequencing, and supports approval gates

## Troubleshooting
- **Empty dashboard?** Check that at least one channel has workspace enabled
- **Empty kanban?** Make sure the channel has workspace enabled — the mission-control carapace (tools + skill) is auto-injected. Ask the bot to create a task, or create cards from the Kanban page UI.
- **Empty timeline?** Timeline events are auto-logged when cards are created/moved or plans change state
- **Empty plans?** Ask the bot to draft a plan, or check if any plans exist in the Plans page
- **Empty journal?** Set `memory_scheme: workspace-files` in bot YAML and wait for the next interaction
- **Empty memory?** Same as journal — MEMORY.md is created on the bot's first run
"""
    return {"content": content}


# ---------------------------------------------------------------------------
# Channel context (debug)
# ---------------------------------------------------------------------------

@router.get("/channels/{channel_id}/context", dependencies=[Depends(require_scopes("mission_control:read"))])
async def channel_context(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Full context debug: schema, files, recent tool calls, recent traces."""
    from app.db.models import PromptTemplate, ToolCall, TraceEvent

    user = get_user(auth)
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    require_channel_access(channel, user)

    from app.services.channel_workspace import list_workspace_files, read_workspace_file

    try:
        bot = get_bot(channel.bot_id)
    except Exception:
        raise HTTPException(404, f"Bot '{channel.bot_id}' not found")

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

    schema_content = None
    template_name = None
    if channel.workspace_schema_content:
        schema_content = channel.workspace_schema_content
    elif channel.workspace_schema_template_id:
        tpl = await db.get(PromptTemplate, channel.workspace_schema_template_id)
        if tpl:
            schema_content = tpl.content
            template_name = tpl.name

    files = []
    if channel.channel_workspace_enabled:
        try:
            files = await asyncio.to_thread(
                list_workspace_files, str(channel.id), bot, include_archive=True, include_data=True,
            )
        except Exception:
            pass

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
        "schema": {"template_name": template_name, "content": schema_content},
        "files": files,
        "tool_calls": tool_calls,
        "trace_events": trace_events,
    }


# ---------------------------------------------------------------------------
# Workspace file proxy
# ---------------------------------------------------------------------------

class FileWriteBody(BaseModel):
    content: str


async def _require_channel(channel_id: uuid.UUID, db: AsyncSession) -> Channel:
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    return channel


@router.get("/channels/{channel_id}/workspace/files")
async def list_workspace_files(
    channel_id: uuid.UUID,
    include_archive: bool = Query(False),
    include_data: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth),
):
    """List files in a channel's workspace."""
    channel = await _require_channel(channel_id, db)
    if not channel.channel_workspace_enabled:
        return {"files": []}
    bot = get_bot(channel.bot_id)
    from app.services.channel_workspace import list_workspace_files as _list
    try:
        files = _list(str(channel_id), bot, include_archive=include_archive, include_data=include_data)
    except Exception:
        logger.exception("Failed to list workspace files for channel %s", channel_id)
        return {"files": []}
    return {"files": files}


@router.get("/channels/{channel_id}/workspace/files/content")
async def read_workspace_file(
    channel_id: uuid.UUID,
    path: str = Query(..., description="File path within workspace"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth),
):
    """Read a file from a channel's workspace."""
    channel = await _require_channel(channel_id, db)
    if not channel.channel_workspace_enabled:
        raise HTTPException(400, "Channel workspace not enabled")
    bot = get_bot(channel.bot_id)
    from app.services.channel_workspace import read_workspace_file as _read
    content = _read(str(channel_id), bot, path)
    if content is None:
        raise HTTPException(404, "File not found")
    return {"path": path, "content": content}


@router.put("/channels/{channel_id}/workspace/files/content")
async def write_workspace_file(
    channel_id: uuid.UUID,
    body: FileWriteBody,
    path: str = Query(..., description="File path within workspace"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth),
):
    """Write a file to a channel's workspace (write-back from dashboard)."""
    channel = await _require_channel(channel_id, db)
    if not channel.channel_workspace_enabled:
        raise HTTPException(400, "Channel workspace not enabled")
    bot = get_bot(channel.bot_id)
    from app.services.channel_workspace import (
        ensure_channel_workspace,
        write_workspace_file as _write,
    )
    ensure_channel_workspace(str(channel_id), bot, display_name=channel.name)
    try:
        result = _write(str(channel_id), bot, path, body.content)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return result


# ---------------------------------------------------------------------------
# Channel membership (join / leave)
# ---------------------------------------------------------------------------

@router.post("/channels/{channel_id}/join", dependencies=[Depends(require_scopes("mission_control:write"))])
async def join_channel(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Add current user as a member of a channel (idempotent)."""
    user = get_user(auth)
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


@router.delete("/channels/{channel_id}/join", dependencies=[Depends(require_scopes("mission_control:write"))])
async def leave_channel(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Remove current user from channel membership."""
    user = get_user(auth)
    if not user:
        raise HTTPException(403, "JWT auth required")

    await db.execute(
        delete(ChannelMember).where(
            ChannelMember.channel_id == channel_id,
            ChannelMember.user_id == user.id,
        )
    )
    await db.commit()
    return {"ok": True}
