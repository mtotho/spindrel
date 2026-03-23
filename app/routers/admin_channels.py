"""Admin Channels page — list, detail, channel settings, knowledge CRUD,
session reset, and /api/slack/config backward-compat endpoint.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.engine import async_session
from app.db.models import (
    Bot as BotRow,
    BotKnowledge,
    Channel,
    ChannelHeartbeat,
    KnowledgeAccess,
    Memory,
    Message,
    Plan,
    PlanItem,
    Session,
    Skill as SkillRow,
    Task,
    ToolCall,
    ToolEmbedding,
    TraceEvent,
)
from app.routers.admin_template_filters import install_admin_template_filters
from app.services.channels import reset_channel_session, switch_channel_session

logger = logging.getLogger(__name__)

router = APIRouter()
api_router = APIRouter()  # Registered at root level for /api/slack/config

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
install_admin_template_filters(templates.env)


async def _build_completions_json(db) -> str:
    """Build the @-tag completions list (skills, tools, tool-packs) as JSON."""
    from app.tools.packs import get_tool_packs

    all_skills = (await db.execute(select(SkillRow).order_by(SkillRow.name))).scalars().all()
    tool_names = (await db.execute(
        select(ToolEmbedding.tool_name).distinct().order_by(ToolEmbedding.tool_name)
    )).scalars().all()
    packs = get_tool_packs()
    completions = (
        [{"value": f"skill:{s.id}", "label": f"skill:{s.id} — {s.name}"} for s in all_skills]
        + [{"value": f"tool:{t}", "label": f"tool:{t}"} for t in tool_names]
        + [{"value": f"tool-pack:{k}", "label": f"tool-pack:{k} — {len(v)} tools"} for k, v in sorted(packs.items())]
    )
    return json.dumps(completions)


async def _fetch_slack_channel_names(channel_ids: list[str]) -> dict[str, str]:
    """Call Slack conversations.info for each channel. Returns {channel_id: name}."""
    token = settings.SLACK_BOT_TOKEN
    if not token or not channel_ids:
        return {}
    names: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        for cid in channel_ids:
            try:
                r = await client.get(
                    "https://slack.com/api/conversations.info",
                    params={"channel": cid},
                    headers={"Authorization": f"Bearer {token}"},
                )
                data = r.json()
                if data.get("ok"):
                    ch = data.get("channel") or {}
                    name = ch.get("name_normalized") or ch.get("name")
                    if name:
                        names[cid] = name
            except Exception as exc:
                logger.warning("Failed to fetch Slack channel name for %s: %s", cid, exc)
    return names


# ---------------------------------------------------------------------------
# Channel list page
# ---------------------------------------------------------------------------

@router.get("/channels", response_class=HTMLResponse)
async def admin_channels(request: Request):
    async with async_session() as db:
        channels = (await db.execute(
            select(Channel).order_by(Channel.integration.desc().nullsfirst(), Channel.name)
        )).scalars().all()
        all_bots = (await db.execute(select(BotRow).order_by(BotRow.name))).scalars().all()

    # Resolve Slack channel names for display
    slack_ids = []
    for ch in channels:
        if ch.integration == "slack" and ch.client_id:
            slack_id = ch.client_id.removeprefix("slack:")
            slack_ids.append(slack_id)
    slack_names = await _fetch_slack_channel_names(slack_ids)

    return templates.TemplateResponse("admin/channels.html", {
        "request": request,
        "channels": channels,
        "all_bots": all_bots,
        "slack_names": slack_names,
        "has_token": bool(settings.SLACK_BOT_TOKEN),
    })


@router.post("/channels/{channel_id}", response_class=HTMLResponse)
async def admin_channel_save(
    request: Request,
    channel_id: uuid.UUID,
    bot_id: str = Form(...),
    name: str = Form(""),
    require_mention: str | None = Form(None),
    passive_memory: str | None = Form(None),
):
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        channel = await db.get(Channel, channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")

        channel.bot_id = bot_id.strip()
        if name.strip():
            channel.name = name.strip()
        channel.require_mention = require_mention == "true"
        channel.passive_memory = passive_memory == "true"
        channel.updated_at = now
        await db.commit()
        await db.refresh(channel)
        all_bots = (await db.execute(select(BotRow).order_by(BotRow.name))).scalars().all()

    # Resolve Slack name if integration
    slack_names: dict[str, str] = {}
    if channel.integration == "slack" and channel.client_id:
        slack_id = channel.client_id.removeprefix("slack:")
        slack_names = await _fetch_slack_channel_names([slack_id])

    tmpl = templates.env.get_template("admin/channel_row.html")
    row_html = tmpl.render(
        request=request,
        channel=channel,
        slack_names=slack_names,
        all_bots=all_bots,
    )
    oob_row = row_html.replace(
        f'id="channel-row-{channel_id}"',
        f'id="channel-row-{channel_id}" hx-swap-oob="outerHTML:#channel-row-{channel_id}"',
        1,
    )
    return HTMLResponse(oob_row)


@router.post("/channels/{channel_id}/reset", response_class=HTMLResponse)
async def admin_channel_reset(request: Request, channel_id: uuid.UUID):
    async with async_session() as db:
        channel = await db.get(Channel, channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")
        new_session_id = await reset_channel_session(db, channel)

    return HTMLResponse(
        f'<span class="text-xs text-green-400">Reset! New session: {str(new_session_id)[:8]}...</span>'
    )


@router.post("/channels/{channel_id}/switch-session/{session_id}", response_class=HTMLResponse)
async def admin_channel_switch_session(request: Request, channel_id: uuid.UUID, session_id: uuid.UUID):
    async with async_session() as db:
        channel = await db.get(Channel, channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")
        try:
            await switch_channel_session(db, channel, session_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Re-render the sessions section
        sessions = (await db.execute(
            select(Session)
            .where(Session.channel_id == channel_id)
            .order_by(Session.last_active.desc())
            .limit(20)
        )).scalars().all()
        msg_counts: dict[uuid.UUID, int] = {}
        if sessions:
            sids = [s.id for s in sessions]
            rows = (await db.execute(
                select(Message.session_id, func.count())
                .where(Message.session_id.in_(sids))
                .group_by(Message.session_id)
            )).all()
            msg_counts = {r[0]: r[1] for r in rows}

    return templates.TemplateResponse("admin/channel_sessions_section.html", {
        "request": request,
        "channel": channel,
        "sessions": sessions,
        "msg_counts": msg_counts,
    })


# ---------------------------------------------------------------------------
# Channel detail page
# ---------------------------------------------------------------------------

@router.get("/channels/{channel_id}/detail", response_class=HTMLResponse)
async def admin_channel_detail(request: Request, channel_id: uuid.UUID):
    async with async_session() as db:
        channel = await db.get(Channel, channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")

        all_bots = (await db.execute(select(BotRow).order_by(BotRow.name))).scalars().all()

        # Active session with message count + last user message
        active_session = None
        active_msg_count = 0
        last_user_msg = None
        if channel.active_session_id:
            active_session = await db.get(Session, channel.active_session_id)
            if active_session:
                active_msg_count = (await db.execute(
                    select(func.count()).select_from(Message)
                    .where(Message.session_id == active_session.id)
                )).scalar() or 0
                last_user_msg = (await db.execute(
                    select(Message)
                    .where(Message.session_id == active_session.id, Message.role == "user")
                    .order_by(Message.created_at.desc())
                    .limit(1)
                )).scalar_one_or_none()

        completions_json = await _build_completions_json(db)

    # Resolve Slack channel name
    slack_name = None
    if channel.integration == "slack" and channel.client_id:
        slack_id = channel.client_id.removeprefix("slack:")
        names = await _fetch_slack_channel_names([slack_id])
        slack_name = names.get(slack_id)

    return templates.TemplateResponse("admin/channel_detail.html", {
        "request": request,
        "channel": channel,
        "all_bots": all_bots,
        "slack_name": slack_name,
        "active_session": active_session,
        "active_msg_count": active_msg_count,
        "last_user_msg": last_user_msg,
        "completions_json": completions_json,
        "settings_compaction_interval": settings.COMPACTION_INTERVAL,
        "settings_compaction_keep_turns": settings.COMPACTION_KEEP_TURNS,
    })


@router.post("/channels/{channel_id}/settings", response_class=HTMLResponse)
async def admin_channel_settings_save(
    request: Request,
    channel_id: uuid.UUID,
    bot_id: str = Form(...),
    name: str = Form(""),
    require_mention: str | None = Form(None),
    passive_memory: str | None = Form(None),
    workspace_rag: str | None = Form(None),
    context_compaction: str = Form("true"),
    compaction_interval: str = Form(""),
    compaction_keep_turns: str = Form(""),
    memory_knowledge_compaction_prompt: str = Form(""),
    elevation_enabled: str = Form(""),
    elevation_threshold: str = Form(""),
    elevated_model: str = Form(""),
):
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        channel = await db.get(Channel, channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")
        channel.bot_id = bot_id.strip()
        if name.strip():
            channel.name = name.strip()
        channel.require_mention = require_mention == "true"
        channel.passive_memory = passive_memory == "true"
        channel.workspace_rag = workspace_rag == "true"
        channel.context_compaction = context_compaction == "true"
        channel.compaction_interval = int(compaction_interval) if compaction_interval.strip() else None
        channel.compaction_keep_turns = int(compaction_keep_turns) if compaction_keep_turns.strip() else None
        channel.memory_knowledge_compaction_prompt = memory_knowledge_compaction_prompt.strip() or None
        channel.elevation_enabled = {"true": True, "false": False}.get(elevation_enabled.strip().lower())
        try:
            channel.elevation_threshold = float(elevation_threshold.strip()) if elevation_threshold.strip() else None
        except ValueError:
            channel.elevation_threshold = None
        channel.elevated_model = elevated_model.strip() or None
        channel.updated_at = now
        await db.commit()
        await db.refresh(channel)
        all_bots = (await db.execute(select(BotRow).order_by(BotRow.name))).scalars().all()
        completions_json = await _build_completions_json(db)

    return templates.TemplateResponse("admin/channel_settings_section.html", {
        "request": request,
        "channel": channel,
        "all_bots": all_bots,
        "saved": True,
        "completions_json": completions_json,
        "settings_compaction_interval": settings.COMPACTION_INTERVAL,
        "settings_compaction_keep_turns": settings.COMPACTION_KEEP_TURNS,
    })


# ---------------------------------------------------------------------------
# HTMX lazy sections
# ---------------------------------------------------------------------------

@router.get("/channels/{channel_id}/sessions-section", response_class=HTMLResponse)
async def admin_channel_sessions_section(request: Request, channel_id: uuid.UUID):
    async with async_session() as db:
        channel = await db.get(Channel, channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")
        sessions = (await db.execute(
            select(Session)
            .where(Session.channel_id == channel_id)
            .order_by(Session.last_active.desc())
            .limit(20)
        )).scalars().all()
        # Get message counts for each session
        msg_counts: dict[uuid.UUID, int] = {}
        if sessions:
            sids = [s.id for s in sessions]
            rows = (await db.execute(
                select(Message.session_id, func.count())
                .where(Message.session_id.in_(sids))
                .group_by(Message.session_id)
            )).all()
            msg_counts = {r[0]: r[1] for r in rows}

    return templates.TemplateResponse("admin/channel_sessions_section.html", {
        "request": request,
        "channel": channel,
        "sessions": sessions,
        "msg_counts": msg_counts,
    })


@router.get("/channels/{channel_id}/knowledge-section", response_class=HTMLResponse)
async def admin_channel_knowledge_section(request: Request, channel_id: uuid.UUID):
    async with async_session() as db:
        channel = await db.get(Channel, channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")

        # Current knowledge access entries for this channel
        entries = (await db.execute(
            select(KnowledgeAccess)
            .options(selectinload(KnowledgeAccess.knowledge))
            .where(
                KnowledgeAccess.scope_type == "channel",
                KnowledgeAccess.scope_key == str(channel_id),
            )
            .order_by(KnowledgeAccess.created_at)
        )).scalars().all()

        # All knowledge docs for the add dropdown (excluding already-added)
        existing_kid_set = {e.knowledge_id for e in entries}
        all_knowledge = (await db.execute(
            select(BotKnowledge).order_by(BotKnowledge.name)
        )).scalars().all()
        available = [k for k in all_knowledge if k.id not in existing_kid_set]

    return templates.TemplateResponse("admin/channel_knowledge_section.html", {
        "request": request,
        "channel": channel,
        "entries": entries,
        "available": available,
    })


@router.post("/channels/{channel_id}/knowledge/add", response_class=HTMLResponse)
async def admin_channel_knowledge_add(
    request: Request,
    channel_id: uuid.UUID,
    knowledge_id: str = Form(...),
    mode: str = Form("rag"),
):
    async with async_session() as db:
        channel = await db.get(Channel, channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")
        kid = uuid.UUID(knowledge_id)
        # Check not duplicate
        existing = (await db.execute(
            select(KnowledgeAccess).where(
                KnowledgeAccess.knowledge_id == kid,
                KnowledgeAccess.scope_type == "channel",
                KnowledgeAccess.scope_key == str(channel_id),
            )
        )).scalar_one_or_none()
        if not existing:
            db.add(KnowledgeAccess(
                knowledge_id=kid,
                scope_type="channel",
                scope_key=str(channel_id),
                mode=mode,
            ))
            await db.commit()

    # Re-render the whole section
    return await admin_channel_knowledge_section(request, channel_id)


@router.put("/channels/{channel_id}/knowledge/{ka_id}/mode", response_class=HTMLResponse)
async def admin_channel_knowledge_mode(
    request: Request,
    channel_id: uuid.UUID,
    ka_id: uuid.UUID,
    mode: str = Form(...),
):
    async with async_session() as db:
        entry = await db.get(KnowledgeAccess, ka_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Not found")
        entry.mode = mode
        await db.commit()

    return await admin_channel_knowledge_section(request, channel_id)


@router.put("/channels/{channel_id}/knowledge/{ka_id}/threshold", response_class=HTMLResponse)
async def admin_channel_knowledge_threshold(
    request: Request,
    channel_id: uuid.UUID,
    ka_id: uuid.UUID,
    similarity_threshold: str = Form(""),
):
    async with async_session() as db:
        entry = await db.get(KnowledgeAccess, ka_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Not found")
        knowledge = await db.get(BotKnowledge, entry.knowledge_id)
        if not knowledge:
            raise HTTPException(status_code=404, detail="Knowledge not found")
        val = similarity_threshold.strip()
        knowledge.similarity_threshold = float(val) if val else None
        await db.commit()

    return await admin_channel_knowledge_section(request, channel_id)


@router.delete("/channels/{channel_id}/knowledge/{ka_id}", response_class=HTMLResponse)
async def admin_channel_knowledge_remove(
    request: Request,
    channel_id: uuid.UUID,
    ka_id: uuid.UUID,
):
    async with async_session() as db:
        entry = await db.get(KnowledgeAccess, ka_id)
        if entry:
            await db.delete(entry)
            await db.commit()

    return await admin_channel_knowledge_section(request, channel_id)


@router.get("/channels/{channel_id}/attachments-section", response_class=HTMLResponse)
async def admin_channel_attachments_section(request: Request, channel_id: uuid.UUID):
    from app.db.models import Attachment

    async with async_session() as db:
        channel = await db.get(Channel, channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")

        row = (await db.execute(
            select(
                func.count().label("total_count"),
                func.count().filter(Attachment.file_data.is_not(None)).label("with_file_data_count"),
                func.coalesce(func.sum(Attachment.size_bytes).filter(Attachment.file_data.is_not(None)), 0).label("total_size_bytes"),
                func.min(Attachment.created_at).label("oldest_created_at"),
            ).where(Attachment.channel_id == channel_id)
        )).one()

    stats = {
        "total_count": row.total_count,
        "with_file_data_count": row.with_file_data_count,
        "total_size_bytes": row.total_size_bytes,
        "oldest_created_at": row.oldest_created_at,
    }

    return templates.TemplateResponse("admin/channel_attachments_section.html", {
        "request": request,
        "channel": channel,
        "stats": stats,
        "settings_retention_days": settings.ATTACHMENT_RETENTION_DAYS,
        "settings_max_size_bytes": settings.ATTACHMENT_MAX_SIZE_BYTES,
    })


@router.post("/channels/{channel_id}/attachment-settings", response_class=HTMLResponse)
async def admin_channel_attachment_settings_save(
    request: Request,
    channel_id: uuid.UUID,
    attachment_retention_days: str = Form(""),
    attachment_max_size_mb: str = Form(""),
    attachment_types: list[str] = Form([]),
):
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        channel = await db.get(Channel, channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")

        # Retention days: empty or missing = None (keep forever)
        val = attachment_retention_days.strip()
        channel.attachment_retention_days = int(val) if val else None

        # Max size: convert MB → bytes, empty = None (no limit)
        val = attachment_max_size_mb.strip()
        channel.attachment_max_size_bytes = int(float(val) * 1048576) if val else None

        # Types: all 5 checked = None (no filtering), otherwise store the list
        all_types = {"image", "file", "text", "audio", "video"}
        if set(attachment_types) >= all_types:
            channel.attachment_types_allowed = None
        else:
            channel.attachment_types_allowed = attachment_types if attachment_types else None

        channel.updated_at = now
        await db.commit()
        await db.refresh(channel)

    # Re-render with saved flag
    return await _render_attachments_section(request, channel_id, saved=True)


async def _render_attachments_section(request: Request, channel_id: uuid.UUID, saved: bool = False):
    from app.db.models import Attachment

    async with async_session() as db:
        channel = await db.get(Channel, channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")

        row = (await db.execute(
            select(
                func.count().label("total_count"),
                func.count().filter(Attachment.file_data.is_not(None)).label("with_file_data_count"),
                func.coalesce(func.sum(Attachment.size_bytes).filter(Attachment.file_data.is_not(None)), 0).label("total_size_bytes"),
                func.min(Attachment.created_at).label("oldest_created_at"),
            ).where(Attachment.channel_id == channel_id)
        )).one()

    stats = {
        "total_count": row.total_count,
        "with_file_data_count": row.with_file_data_count,
        "total_size_bytes": row.total_size_bytes,
        "oldest_created_at": row.oldest_created_at,
    }

    return templates.TemplateResponse("admin/channel_attachments_section.html", {
        "request": request,
        "channel": channel,
        "stats": stats,
        "saved": saved,
        "settings_retention_days": settings.ATTACHMENT_RETENTION_DAYS,
        "settings_max_size_bytes": settings.ATTACHMENT_MAX_SIZE_BYTES,
    })


@router.get("/channels/{channel_id}/tasks-section", response_class=HTMLResponse)
async def admin_channel_tasks_section(request: Request, channel_id: uuid.UUID):
    async with async_session() as db:
        tasks = (await db.execute(
            select(Task)
            .where(Task.channel_id == channel_id)
            .order_by(Task.created_at.desc())
            .limit(10)
        )).scalars().all()

    return templates.TemplateResponse("admin/channel_tasks_section.html", {
        "request": request,
        "tasks": tasks,
    })


@router.get("/channels/{channel_id}/plans-section", response_class=HTMLResponse)
async def admin_channel_plans_section(request: Request, channel_id: uuid.UUID):
    async with async_session() as db:
        channel = await db.get(Channel, channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")
        plans = (await db.execute(
            select(Plan)
            .options(selectinload(Plan.items))
            .where(Plan.channel_id == channel_id)
            .order_by(Plan.updated_at.desc())
        )).scalars().all()

    return templates.TemplateResponse("admin/channel_plans_section.html", {
        "request": request,
        "channel": channel,
        "plans": plans,
    })


@router.put("/channels/{channel_id}/plans/{plan_id}/status", response_class=HTMLResponse)
async def admin_channel_plan_status(
    request: Request,
    channel_id: uuid.UUID,
    plan_id: uuid.UUID,
    status: str = Form(...),
):
    if status not in ("active", "complete", "abandoned"):
        raise HTTPException(status_code=400, detail="Invalid status")
    async with async_session() as db:
        plan = await db.get(Plan, plan_id)
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        plan.status = status
        plan.updated_at = datetime.now(timezone.utc)
        await db.commit()

    return await admin_channel_plans_section(request, channel_id)


@router.delete("/channels/{channel_id}/plans/{plan_id}", response_class=HTMLResponse)
async def admin_channel_plan_delete(
    request: Request,
    channel_id: uuid.UUID,
    plan_id: uuid.UUID,
):
    async with async_session() as db:
        plan = await db.get(Plan, plan_id)
        if plan:
            await db.delete(plan)
            await db.commit()

    return await admin_channel_plans_section(request, channel_id)


@router.get("/channels/{channel_id}/memories-section", response_class=HTMLResponse)
async def admin_channel_memories_section(request: Request, channel_id: uuid.UUID):
    async with async_session() as db:
        channel = await db.get(Channel, channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")
        memories = (await db.execute(
            select(Memory)
            .where(Memory.channel_id == channel_id)
            .order_by(Memory.created_at.desc())
            .limit(15)
        )).scalars().all()

    return templates.TemplateResponse("admin/channel_memories_section.html", {
        "request": request,
        "channel": channel,
        "memories": memories,
    })


@router.delete("/channels/{channel_id}/memories/{memory_id}", response_class=HTMLResponse)
async def admin_channel_memory_delete(
    request: Request,
    channel_id: uuid.UUID,
    memory_id: uuid.UUID,
):
    async with async_session() as db:
        mem = await db.get(Memory, memory_id)
        if mem:
            await db.delete(mem)
            await db.commit()

    return await admin_channel_memories_section(request, channel_id)


# ---------------------------------------------------------------------------
# Heartbeat section + routes
# ---------------------------------------------------------------------------


async def _heartbeat_correlation_ids(db, tasks: list[Task]) -> dict[uuid.UUID, uuid.UUID]:
    """Look up correlation_id for each heartbeat task.

    Tries Messages first (user message created after task.run_at), then falls
    back to TraceEvents for tasks that failed before messages were persisted.
    Returns {task_id: correlation_id}.
    """
    if not tasks:
        return {}
    candidates = [t for t in tasks if t.session_id and t.run_at]
    if not candidates:
        return {}

    session_ids = list({t.session_id for t in candidates})
    earliest_run = min(t.run_at for t in candidates)

    # Primary: user messages with correlation_id
    msg_rows = (await db.execute(
        select(Message.session_id, Message.correlation_id, Message.created_at)
        .where(
            Message.session_id.in_(session_ids),
            Message.role == "user",
            Message.correlation_id.is_not(None),
            Message.created_at >= earliest_run,
        )
        .order_by(Message.created_at)
    )).all()

    result: dict[uuid.UUID, uuid.UUID] = {}
    unmatched = []
    for t in candidates:
        found = False
        for row in msg_rows:
            if row.session_id == t.session_id and row.created_at >= t.run_at:
                result[t.id] = row.correlation_id
                found = True
                break
        if not found:
            unmatched.append(t)

    # Fallback: trace events for tasks with no message match (e.g. early failures)
    if unmatched:
        te_rows = (await db.execute(
            select(TraceEvent.session_id, TraceEvent.correlation_id, TraceEvent.created_at)
            .where(
                TraceEvent.session_id.in_([t.session_id for t in unmatched]),
                TraceEvent.correlation_id.is_not(None),
                TraceEvent.created_at >= earliest_run,
            )
            .order_by(TraceEvent.created_at)
        )).all()
        for t in unmatched:
            for row in te_rows:
                if row.session_id == t.session_id and row.created_at >= t.run_at:
                    result[t.id] = row.correlation_id
                    break

    return result


@router.get("/channels/{channel_id}/heartbeat-section", response_class=HTMLResponse)
async def admin_channel_heartbeat_section(request: Request, channel_id: uuid.UUID):
    from app.services.providers import get_available_models_grouped

    async with async_session() as db:
        channel = await db.get(Channel, channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")

        heartbeat = (await db.execute(
            select(ChannelHeartbeat).where(ChannelHeartbeat.channel_id == channel_id)
        )).scalar_one_or_none()

        # Recent heartbeat task history
        history_stmt = (
            select(Task)
            .where(Task.channel_id == channel_id)
            .where(Task.callback_config["source"].astext == "heartbeat")
            .order_by(Task.created_at.desc())
            .limit(10)
        )
        history = list((await db.execute(history_stmt)).scalars().all())
        corr_map = await _heartbeat_correlation_ids(db, history)

        total_history = (await db.execute(
            select(func.count()).select_from(
                select(Task.id)
                .where(Task.channel_id == channel_id)
                .where(Task.callback_config["source"].astext == "heartbeat")
                .subquery()
            )
        )).scalar_one()

        completions_json = await _build_completions_json(db)

    model_groups = await get_available_models_grouped()

    return templates.TemplateResponse("admin/channel_heartbeat_section.html", {
        "request": request,
        "channel": channel,
        "heartbeat": heartbeat,
        "model_groups": model_groups,
        "completions_json": completions_json,
        "history": history,
        "corr_map": corr_map,
        "total_history": total_history,
    })


@router.post("/channels/{channel_id}/heartbeat", response_class=HTMLResponse)
async def admin_channel_heartbeat_save(
    request: Request,
    channel_id: uuid.UUID,
    interval_minutes: int = Form(60),
    model: str = Form(""),
    model_provider_id: str = Form(""),
    prompt: str = Form(""),
    dispatch_results: str = Form(""),
    trigger_response: str = Form(""),
):
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        channel = await db.get(Channel, channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")

        heartbeat = (await db.execute(
            select(ChannelHeartbeat).where(ChannelHeartbeat.channel_id == channel_id)
        )).scalar_one_or_none()

        if heartbeat is None:
            heartbeat = ChannelHeartbeat(
                channel_id=channel_id,
                enabled=False,
            )
            db.add(heartbeat)

        heartbeat.interval_minutes = max(1, interval_minutes)
        heartbeat.model = model.strip()
        heartbeat.model_provider_id = model_provider_id.strip() or None
        heartbeat.prompt = prompt.strip()
        heartbeat.dispatch_results = dispatch_results == "on"
        heartbeat.trigger_response = trigger_response == "on"
        heartbeat.updated_at = now

        # If enabled and next_run_at not set, schedule first run
        if heartbeat.enabled and heartbeat.next_run_at is None:
            from datetime import timedelta
            heartbeat.next_run_at = now + timedelta(minutes=heartbeat.interval_minutes)

        await db.commit()

    return await admin_channel_heartbeat_section(request, channel_id)


@router.post("/channels/{channel_id}/heartbeat/toggle", response_class=HTMLResponse)
async def admin_channel_heartbeat_toggle(request: Request, channel_id: uuid.UUID):
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        channel = await db.get(Channel, channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")

        heartbeat = (await db.execute(
            select(ChannelHeartbeat).where(ChannelHeartbeat.channel_id == channel_id)
        )).scalar_one_or_none()

        if heartbeat is None:
            heartbeat = ChannelHeartbeat(
                channel_id=channel_id,
                enabled=True,
            )
            db.add(heartbeat)
        else:
            heartbeat.enabled = not heartbeat.enabled

        heartbeat.updated_at = now

        if heartbeat.enabled and heartbeat.next_run_at is None:
            from datetime import timedelta
            heartbeat.next_run_at = now + timedelta(minutes=heartbeat.interval_minutes)
        elif not heartbeat.enabled:
            heartbeat.next_run_at = None

        await db.commit()

    return await admin_channel_heartbeat_section(request, channel_id)


@router.get("/channels/{channel_id}/heartbeat/history", response_class=HTMLResponse)
async def admin_channel_heartbeat_history(
    request: Request,
    channel_id: uuid.UUID,
    page: int = 1,
):
    page_size = 10
    offset = (page - 1) * page_size

    async with async_session() as db:
        base = (
            select(Task)
            .where(Task.channel_id == channel_id)
            .where(Task.callback_config["source"].astext == "heartbeat")
        )
        total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        history = list((await db.execute(
            base.order_by(Task.created_at.desc()).offset(offset).limit(page_size)
        )).scalars().all())

        # Look up correlation_ids for completed tasks via Messages table
        corr_map = await _heartbeat_correlation_ids(db, history)

    return templates.TemplateResponse("admin/channel_heartbeat_history.html", {
        "request": request,
        "channel_id": channel_id,
        "history": history,
        "corr_map": corr_map,
        "page": page,
        "page_size": page_size,
        "total": total,
    })


@router.post("/channels/{channel_id}/heartbeat/fire", response_class=HTMLResponse)
async def admin_channel_heartbeat_fire(request: Request, channel_id: uuid.UUID):
    from app.services.heartbeat import fire_heartbeat

    async with async_session() as db:
        heartbeat = (await db.execute(
            select(ChannelHeartbeat).where(ChannelHeartbeat.channel_id == channel_id)
        )).scalar_one_or_none()

        if not heartbeat:
            raise HTTPException(status_code=404, detail="No heartbeat configured")

    await fire_heartbeat(heartbeat)
    return await admin_channel_heartbeat_section(request, channel_id)


# ---------------------------------------------------------------------------
# API endpoint for Slack integration (registered at /api/slack/config)
# Backward compat — reads from Channel table now.
# ---------------------------------------------------------------------------

@api_router.get("/slack/config")
async def api_slack_config(request: Request):
    """Returns Slack channel->bot mapping for the Slack integration service."""
    api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    expected = getattr(settings, "API_KEY", None)
    if expected and api_key != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

    async with async_session() as db:
        channel_rows = (await db.execute(
            select(Channel).where(Channel.integration == "slack")
        )).scalars().all()
        bot_rows = (await db.execute(select(BotRow))).scalars().all()

    channels = {}
    for row in channel_rows:
        if not row.client_id:
            continue
        slack_id = row.client_id.removeprefix("slack:")
        channels[slack_id] = {
            "bot_id": row.bot_id,
            "require_mention": row.require_mention,
            "passive_memory": row.passive_memory,
        }

    bots = {
        row.id: {
            "display_name": row.display_name or row.name,
            "icon_emoji": (row.integration_config or {}).get("slack", {}).get("icon_emoji") or None,
            "icon_url": row.avatar_url or None,
        }
        for row in bot_rows
    }

    return JSONResponse({"default_bot": settings.SLACK_DEFAULT_BOT, "channels": channels, "bots": bots})
