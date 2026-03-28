"""Channel CRUD + tab endpoints: sessions, heartbeat, memories, tasks, plans,
knowledge, enriched."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent.bots import get_bot
from app.db.models import (
    BotKnowledge,
    Channel,
    ChannelHeartbeat,
    HeartbeatRun,
    KnowledgeAccess,
    Memory,
    Message,
    Plan,
    Session,
    Task,
    TraceEvent,
)
from app.config import settings
from app.dependencies import get_db, verify_auth_or_user
from app.services.channels import apply_channel_visibility

from ._helpers import _heartbeat_correlation_ids
from ._schemas import MemoryListOut, MemoryOut

router = APIRouter()


# ---------------------------------------------------------------------------
# Channel schemas
# ---------------------------------------------------------------------------

class IntegrationBindingOut(BaseModel):
    id: uuid.UUID
    channel_id: uuid.UUID
    integration_type: str
    client_id: str
    dispatch_config: Optional[dict] = None
    display_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChannelOut(BaseModel):
    id: uuid.UUID
    name: str
    bot_id: str
    client_id: Optional[str] = None
    integration: Optional[str] = None
    active_session_id: Optional[uuid.UUID] = None
    require_mention: bool = True
    passive_memory: bool = True
    private: bool = False
    user_id: Optional[uuid.UUID] = None
    display_name: Optional[str] = None
    model_override: Optional[str] = None
    model_provider_id_override: Optional[str] = None
    integrations: list[IntegrationBindingOut] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChannelListOut(BaseModel):
    channels: list[ChannelOut]
    total: int
    page: int
    page_size: int


class ChannelEntitySummary(BaseModel):
    session_count: int = 0
    message_count: int = 0
    memory_count: int = 0
    task_count: int = 0
    active_session_message_count: int = 0


class ChannelDetailOut(BaseModel):
    channel: ChannelOut
    entities: ChannelEntitySummary

    model_config = {"from_attributes": True}


class SessionOut(BaseModel):
    id: uuid.UUID
    client_id: str
    bot_id: str
    created_at: datetime
    last_active: datetime
    title: Optional[str] = None
    depth: int = 0
    locked: bool = False
    source_task_id: Optional[uuid.UUID] = None
    message_count: int = 0
    is_active: bool = False

    model_config = {"from_attributes": True}


class SessionListOut(BaseModel):
    sessions: list[SessionOut]


class HeartbeatConfigOut(BaseModel):
    id: uuid.UUID
    channel_id: uuid.UUID
    enabled: bool = False
    interval_minutes: int = 60
    model: str = ""
    model_provider_id: Optional[str] = None
    fallback_models: list[dict] = []
    prompt: str = ""
    prompt_template_id: Optional[uuid.UUID] = None
    workspace_file_path: Optional[str] = None
    workspace_id: Optional[uuid.UUID] = None
    dispatch_results: bool = True
    trigger_response: bool = False
    quiet_start: Optional[str] = None
    quiet_end: Optional[str] = None
    timezone: Optional[str] = None
    max_run_seconds: Optional[int] = None
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_heartbeat(cls, hb: ChannelHeartbeat) -> "HeartbeatConfigOut":
        data = {c: getattr(hb, c) for c in [
            "id", "channel_id", "enabled", "interval_minutes", "model",
            "model_provider_id", "fallback_models", "prompt", "prompt_template_id",
            "workspace_file_path", "workspace_id",
            "dispatch_results", "trigger_response",
            "timezone", "max_run_seconds",
            "last_run_at", "next_run_at", "created_at", "updated_at",
        ]}
        data["quiet_start"] = hb.quiet_start.strftime("%H:%M") if hb.quiet_start else None
        data["quiet_end"] = hb.quiet_end.strftime("%H:%M") if hb.quiet_end else None
        return cls(**data)


class HeartbeatHistoryRunOut(BaseModel):
    id: uuid.UUID
    status: str
    run_at: datetime
    completed_at: Optional[datetime] = None
    result: Optional[str] = None
    error: Optional[str] = None
    correlation_id: Optional[uuid.UUID] = None

    model_config = {"from_attributes": True}


class HeartbeatOut(BaseModel):
    config: Optional[HeartbeatConfigOut] = None
    history: list[HeartbeatHistoryRunOut] = []
    total_history: int = 0
    default_max_run_seconds: int = settings.TASK_MAX_RUN_SECONDS


class HeartbeatUpdate(BaseModel):
    enabled: Optional[bool] = None
    interval_minutes: int = Field(60, ge=1)
    model: str = ""
    model_provider_id: Optional[str] = None
    fallback_models: list[dict] = []
    prompt: str = ""
    prompt_template_id: Optional[uuid.UUID] = None
    workspace_file_path: Optional[str] = None
    workspace_id: Optional[uuid.UUID] = None
    dispatch_results: bool = True
    trigger_response: bool = False
    quiet_start: Optional[str] = None  # "HH:MM" or null
    quiet_end: Optional[str] = None    # "HH:MM" or null
    timezone: Optional[str] = None
    max_run_seconds: Optional[int] = None


class TaskOut(BaseModel):
    id: uuid.UUID
    status: str
    bot_id: str
    prompt: str
    result: Optional[str] = None
    error: Optional[str] = None
    dispatch_type: str = "none"
    task_type: str = "agent"
    recurrence: Optional[str] = None
    created_at: datetime
    scheduled_at: Optional[datetime] = None
    run_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TaskListOut(BaseModel):
    tasks: list[TaskOut]


class PlanItemOut(BaseModel):
    id: uuid.UUID
    position: int
    content: str
    status: str = "pending"
    notes: Optional[str] = None
    updated_at: datetime

    model_config = {"from_attributes": True}


class PlanOut(BaseModel):
    id: uuid.UUID
    bot_id: str
    title: str
    description: Optional[str] = None
    status: str = "active"
    created_at: datetime
    updated_at: datetime
    items: list[PlanItemOut] = []

    model_config = {"from_attributes": True}


class PlanListOut(BaseModel):
    plans: list[PlanOut]


class ChannelSettingsOut(BaseModel):
    """All channel settings — superset of ChannelOut."""
    id: uuid.UUID
    name: str
    bot_id: str
    client_id: Optional[str] = None
    integration: Optional[str] = None
    active_session_id: Optional[uuid.UUID] = None
    require_mention: bool = True
    passive_memory: bool = True
    private: bool = False
    user_id: Optional[uuid.UUID] = None
    allow_bot_messages: bool = False
    workspace_rag: bool = True
    max_iterations: Optional[int] = None
    task_max_run_seconds: Optional[int] = None
    context_compaction: bool = True
    compaction_interval: Optional[int] = None
    compaction_keep_turns: Optional[int] = None
    memory_knowledge_compaction_prompt: Optional[str] = None
    compaction_prompt_template_id: Optional[uuid.UUID] = None
    compaction_workspace_file_path: Optional[str] = None
    compaction_workspace_id: Optional[uuid.UUID] = None
    history_mode: Optional[str] = None
    compaction_model: Optional[str] = None
    trigger_heartbeat_before_compaction: Optional[bool] = None
    # Memory flush (dedicated pre-compaction memory save)
    memory_flush_enabled: Optional[bool] = None
    memory_flush_model: Optional[str] = None
    memory_flush_model_provider_id: Optional[str] = None
    memory_flush_prompt: Optional[str] = None
    memory_flush_prompt_template_id: Optional[uuid.UUID] = None
    memory_flush_workspace_file_path: Optional[str] = None
    memory_flush_workspace_id: Optional[uuid.UUID] = None
    section_index_count: Optional[int] = None
    section_index_verbosity: Optional[str] = None
    elevation_enabled: Optional[bool] = None
    elevation_threshold: Optional[float] = None
    elevated_model: Optional[str] = None
    model_override: Optional[str] = None
    model_provider_id_override: Optional[str] = None
    # Tool / skill overrides
    local_tools_override: Optional[list[str]] = None
    local_tools_disabled: Optional[list[str]] = None
    mcp_servers_override: Optional[list[str]] = None
    mcp_servers_disabled: Optional[list[str]] = None
    client_tools_override: Optional[list[str]] = None
    client_tools_disabled: Optional[list[str]] = None
    pinned_tools_override: Optional[list[str]] = None
    skills_override: Optional[list[dict]] = None
    skills_disabled: Optional[list[str]] = None
    # Workspace overrides (null = inherit from workspace)
    workspace_skills_enabled: Optional[bool] = None
    workspace_base_prompt_enabled: Optional[bool] = None

    model_config = {"from_attributes": True}


class ChannelSettingsUpdate(BaseModel):
    """Writable channel settings."""
    name: Optional[str] = None
    bot_id: Optional[str] = None
    require_mention: Optional[bool] = None
    passive_memory: Optional[bool] = None
    private: Optional[bool] = None
    user_id: Optional[uuid.UUID] = None
    allow_bot_messages: Optional[bool] = None
    workspace_rag: Optional[bool] = None
    max_iterations: Optional[int] = None
    task_max_run_seconds: Optional[int] = None
    context_compaction: Optional[bool] = None
    compaction_interval: Optional[int] = None
    compaction_keep_turns: Optional[int] = None
    memory_knowledge_compaction_prompt: Optional[str] = None
    compaction_prompt_template_id: Optional[uuid.UUID] = None
    compaction_workspace_file_path: Optional[str] = None
    compaction_workspace_id: Optional[uuid.UUID] = None
    history_mode: Optional[str] = None
    compaction_model: Optional[str] = None
    trigger_heartbeat_before_compaction: Optional[bool] = None
    # Memory flush (dedicated pre-compaction memory save)
    memory_flush_enabled: Optional[bool] = None
    memory_flush_model: Optional[str] = None
    memory_flush_model_provider_id: Optional[str] = None
    memory_flush_prompt: Optional[str] = None
    memory_flush_prompt_template_id: Optional[uuid.UUID] = None
    memory_flush_workspace_file_path: Optional[str] = None
    memory_flush_workspace_id: Optional[uuid.UUID] = None
    section_index_count: Optional[int] = None
    section_index_verbosity: Optional[str] = None
    elevation_enabled: Optional[bool] = None
    elevation_threshold: Optional[float] = None
    elevated_model: Optional[str] = None
    model_override: Optional[str] = None
    model_provider_id_override: Optional[str] = None
    # Tool / skill overrides (set to null to clear → revert to inherit)
    local_tools_override: Optional[list[str]] = None
    local_tools_disabled: Optional[list[str]] = None
    mcp_servers_override: Optional[list[str]] = None
    mcp_servers_disabled: Optional[list[str]] = None
    client_tools_override: Optional[list[str]] = None
    client_tools_disabled: Optional[list[str]] = None
    pinned_tools_override: Optional[list[str]] = None
    skills_override: Optional[list[dict]] = None
    skills_disabled: Optional[list[str]] = None
    # Workspace overrides (null = inherit from workspace)
    workspace_skills_enabled: Optional[bool] = None
    workspace_base_prompt_enabled: Optional[bool] = None


# ---------------------------------------------------------------------------
# Channel list / detail
# ---------------------------------------------------------------------------

@router.get("/channels", response_model=ChannelListOut)
async def admin_channels_list(
    integration: Optional[str] = Query(None, description="Filter by integration type"),
    bot_id: Optional[str] = Query(None, description="Filter by bot_id"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(25, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
    auth_result=Depends(verify_auth_or_user),
):
    """List channels with pagination and optional filters."""
    stmt = select(Channel).order_by(Channel.updated_at.desc())
    stmt = apply_channel_visibility(stmt, auth_result)
    if integration:
        stmt = stmt.where(Channel.integration == integration)
    if bot_id:
        stmt = stmt.where(Channel.bot_id == bot_id)

    total = (await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )).scalar_one()

    offset = (page - 1) * page_size
    channels = (await db.execute(
        stmt.options(selectinload(Channel.integrations)).offset(offset).limit(page_size)
    )).scalars().all()

    return ChannelListOut(
        channels=[ChannelOut.model_validate(ch) for ch in channels],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/channels/{channel_id}", response_model=ChannelDetailOut)
async def admin_channel_detail(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Channel detail with linked entity counts."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    session_count = (await db.execute(
        select(func.count()).select_from(Session)
        .where(Session.channel_id == channel_id)
    )).scalar_one()

    message_count = (await db.execute(
        select(func.count()).select_from(Message)
        .join(Session, Message.session_id == Session.id)
        .where(Session.channel_id == channel_id)
    )).scalar_one()

    memory_count = (await db.execute(
        select(func.count()).select_from(Memory)
        .where(Memory.channel_id == channel_id)
    )).scalar_one()

    task_count = (await db.execute(
        select(func.count()).select_from(Task)
        .where(Task.channel_id == channel_id)
    )).scalar_one()

    active_msg_count = 0
    if channel.active_session_id:
        active_msg_count = (await db.execute(
            select(func.count()).select_from(Message)
            .where(Message.session_id == channel.active_session_id)
        )).scalar_one()

    return ChannelDetailOut(
        channel=ChannelOut.model_validate(channel),
        entities=ChannelEntitySummary(
            session_count=session_count,
            message_count=message_count,
            memory_count=memory_count,
            task_count=task_count,
            active_session_message_count=active_msg_count,
        ),
    )


# ---------------------------------------------------------------------------
# Channel settings
# ---------------------------------------------------------------------------

@router.get("/channels/{channel_id}/settings", response_model=ChannelSettingsOut)
async def admin_channel_settings(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Get full channel settings."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return ChannelSettingsOut.model_validate(channel)


@router.api_route("/channels/{channel_id}/settings", methods=["PUT", "PATCH"], response_model=ChannelSettingsOut)
async def admin_channel_settings_update(
    channel_id: uuid.UUID,
    body: ChannelSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Update channel settings."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    updates = body.model_dump(exclude_unset=True)
    if "bot_id" in updates:
        try:
            get_bot(updates["bot_id"])
        except HTTPException:
            raise HTTPException(status_code=400, detail=f"Unknown bot: {updates['bot_id']}")

    for field, value in updates.items():
        setattr(channel, field, value)

    # When heartbeat trigger is enabled, clear the memory phase prompt fields
    if updates.get("trigger_heartbeat_before_compaction"):
        channel.memory_knowledge_compaction_prompt = None
        channel.compaction_workspace_file_path = None
        channel.compaction_workspace_id = None
        channel.compaction_prompt_template_id = None

    channel.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(channel)
    return ChannelSettingsOut.model_validate(channel)


# ---------------------------------------------------------------------------
# Effective tools (resolved with channel overrides)
# ---------------------------------------------------------------------------

class EffectiveToolsOut(BaseModel):
    local_tools: list[str]
    mcp_servers: list[str]
    client_tools: list[str]
    pinned_tools: list[str]
    skills: list[dict]
    mode: dict  # per-category mode: "inherit" | "override" | "disabled"


@router.get("/channels/{channel_id}/effective-tools", response_model=EffectiveToolsOut)
async def admin_channel_effective_tools(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Return the resolved tool/skill lists after applying channel overrides."""
    from app.agent.channel_overrides import resolve_effective_tools

    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    bot = get_bot(channel.bot_id)
    eff = resolve_effective_tools(bot, channel)

    def _mode(override, disabled):
        if override is not None:
            return "override"
        if disabled is not None:
            return "disabled"
        return "inherit"

    return EffectiveToolsOut(
        local_tools=eff.local_tools,
        mcp_servers=eff.mcp_servers,
        client_tools=eff.client_tools,
        pinned_tools=eff.pinned_tools,
        skills=[{"id": s.id, "mode": s.mode, "similarity_threshold": s.similarity_threshold} for s in eff.skills],
        mode={
            "local_tools": _mode(channel.local_tools_override, channel.local_tools_disabled),
            "mcp_servers": _mode(channel.mcp_servers_override, channel.mcp_servers_disabled),
            "client_tools": _mode(channel.client_tools_override, channel.client_tools_disabled),
            "pinned_tools": "override" if channel.pinned_tools_override is not None else "inherit",
            "skills": _mode(channel.skills_override, channel.skills_disabled),
        },
    )


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@router.get("/channels/{channel_id}/sessions", response_model=SessionListOut)
async def admin_channel_sessions(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """List sessions for a channel (last 20, ordered by last_active desc, with message counts)."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

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

    return SessionListOut(
        sessions=[
            SessionOut(
                id=s.id,
                client_id=s.client_id,
                bot_id=s.bot_id,
                created_at=s.created_at,
                last_active=s.last_active,
                title=s.title,
                depth=s.depth,
                locked=s.locked,
                message_count=msg_counts.get(s.id, 0),
                is_active=(s.id == channel.active_session_id),
            )
            for s in sessions
        ],
    )


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------

@router.get("/channels/{channel_id}/heartbeat", response_model=HeartbeatOut)
async def admin_channel_heartbeat_get(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Get heartbeat config and recent history for a channel."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    heartbeat = (await db.execute(
        select(ChannelHeartbeat).where(ChannelHeartbeat.channel_id == channel_id)
    )).scalar_one_or_none()

    config_out = HeartbeatConfigOut.from_orm_heartbeat(heartbeat) if heartbeat else None

    # Read from heartbeat_runs table (new), fall back to legacy Task rows
    history_out: list[HeartbeatHistoryRunOut] = []
    total_history = 0

    if heartbeat:
        runs_stmt = (
            select(HeartbeatRun)
            .where(HeartbeatRun.heartbeat_id == heartbeat.id)
            .order_by(HeartbeatRun.run_at.desc())
            .limit(10)
        )
        runs = list((await db.execute(runs_stmt)).scalars().all())
        total_history = (await db.execute(
            select(func.count()).select_from(
                select(HeartbeatRun.id)
                .where(HeartbeatRun.heartbeat_id == heartbeat.id)
                .subquery()
            )
        )).scalar_one()

        if runs:
            history_out = [
                HeartbeatHistoryRunOut(
                    id=r.id,
                    status=r.status,
                    run_at=r.run_at,
                    completed_at=r.completed_at,
                    result=r.result[:500] if r.result else None,
                    error=r.error,
                    correlation_id=r.correlation_id,
                )
                for r in runs
            ]
        else:
            # Fallback: read from legacy Task rows for historical data
            history_stmt = (
                select(Task)
                .where(Task.channel_id == channel_id)
                .where(Task.callback_config["source"].astext == "heartbeat")
                .order_by(Task.created_at.desc())
                .limit(10)
            )
            legacy_history = list((await db.execute(history_stmt)).scalars().all())
            corr_map = await _heartbeat_correlation_ids(db, legacy_history)
            total_history = (await db.execute(
                select(func.count()).select_from(
                    select(Task.id)
                    .where(Task.channel_id == channel_id)
                    .where(Task.callback_config["source"].astext == "heartbeat")
                    .subquery()
                )
            )).scalar_one()
            history_out = [
                HeartbeatHistoryRunOut(
                    id=t.id,
                    status=t.status,
                    run_at=t.run_at or t.created_at,
                    completed_at=t.completed_at,
                    result=t.result[:500] if t.result else None,
                    error=t.error,
                    correlation_id=corr_map.get(t.id),
                )
                for t in legacy_history
            ]

    return HeartbeatOut(
        config=config_out,
        history=history_out,
        total_history=total_history,
    )


@router.api_route("/channels/{channel_id}/heartbeat", methods=["PUT", "PATCH"], response_model=HeartbeatConfigOut)
async def admin_channel_heartbeat_update(
    channel_id: uuid.UUID,
    body: HeartbeatUpdate,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Update heartbeat settings."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    now = datetime.now(timezone.utc)

    heartbeat = (await db.execute(
        select(ChannelHeartbeat).where(ChannelHeartbeat.channel_id == channel_id)
    )).scalar_one_or_none()

    if heartbeat is None:
        heartbeat = ChannelHeartbeat(
            channel_id=channel_id,
            enabled=False,
        )
        db.add(heartbeat)

    updates = body.model_dump(exclude_unset=True)
    if "enabled" in updates:
        heartbeat.enabled = updates["enabled"]
    if "interval_minutes" in updates:
        heartbeat.interval_minutes = max(1, updates["interval_minutes"])
    if "model" in updates:
        heartbeat.model = updates["model"].strip() if updates["model"] else ""
    if "model_provider_id" in updates:
        heartbeat.model_provider_id = updates["model_provider_id"].strip() if updates["model_provider_id"] else None
    if "prompt" in updates:
        heartbeat.prompt = updates["prompt"].strip() if updates["prompt"] else ""
    if "prompt_template_id" in updates:
        heartbeat.prompt_template_id = updates["prompt_template_id"]
    if "workspace_file_path" in updates:
        heartbeat.workspace_file_path = updates["workspace_file_path"]
    if "workspace_id" in updates:
        heartbeat.workspace_id = updates["workspace_id"]
    if "dispatch_results" in updates:
        heartbeat.dispatch_results = updates["dispatch_results"]
    if "trigger_response" in updates:
        heartbeat.trigger_response = updates["trigger_response"]
    if "quiet_start" in updates:
        heartbeat.quiet_start = dt_time.fromisoformat(updates["quiet_start"]) if updates["quiet_start"] else None
    if "quiet_end" in updates:
        heartbeat.quiet_end = dt_time.fromisoformat(updates["quiet_end"]) if updates["quiet_end"] else None
    if "timezone" in updates:
        heartbeat.timezone = updates["timezone"]
    if "max_run_seconds" in updates:
        heartbeat.max_run_seconds = updates["max_run_seconds"]
    heartbeat.updated_at = now

    if heartbeat.enabled:
        if heartbeat.next_run_at is None:
            # First enable — schedule from now
            heartbeat.next_run_at = now + timedelta(minutes=heartbeat.interval_minutes)
        elif "interval_minutes" in updates:
            # Interval changed — reschedule relative to last run (or now if never ran)
            base = heartbeat.last_run_at or now
            heartbeat.next_run_at = base + timedelta(minutes=heartbeat.interval_minutes)
            # If the new schedule is already past, fire on next poll
            if heartbeat.next_run_at <= now:
                heartbeat.next_run_at = now

    await db.commit()
    await db.refresh(heartbeat)
    return HeartbeatConfigOut.model_validate(heartbeat)


@router.post("/channels/{channel_id}/heartbeat/toggle", response_model=HeartbeatConfigOut)
async def admin_channel_heartbeat_toggle(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Toggle heartbeat enabled state."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    now = datetime.now(timezone.utc)

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
        heartbeat.next_run_at = now + timedelta(minutes=heartbeat.interval_minutes)
    elif not heartbeat.enabled:
        heartbeat.next_run_at = None

    await db.commit()
    await db.refresh(heartbeat)
    return HeartbeatConfigOut.model_validate(heartbeat)


@router.post("/channels/{channel_id}/heartbeat/fire", response_model=HeartbeatConfigOut)
async def admin_channel_heartbeat_fire(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Fire heartbeat immediately (non-blocking — spawns in background)."""
    import asyncio
    from app.services.heartbeat import _safe_fire_heartbeat

    heartbeat = (await db.execute(
        select(ChannelHeartbeat).where(ChannelHeartbeat.channel_id == channel_id)
    )).scalar_one_or_none()

    if not heartbeat:
        raise HTTPException(status_code=404, detail="No heartbeat configured")

    asyncio.create_task(_safe_fire_heartbeat(heartbeat))

    return HeartbeatConfigOut.model_validate(heartbeat)


# ---------------------------------------------------------------------------
# Memories
# ---------------------------------------------------------------------------

@router.get("/channels/{channel_id}/memories", response_model=MemoryListOut)
async def admin_channel_memories(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """List recent memories for a channel (15, ordered by created_at desc)."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    memories = (await db.execute(
        select(Memory)
        .where(Memory.channel_id == channel_id)
        .order_by(Memory.created_at.desc())
        .limit(15)
    )).scalars().all()

    return MemoryListOut(
        memories=[
            MemoryOut(
                id=m.id,
                session_id=m.session_id,
                client_id=m.client_id,
                bot_id=m.bot_id,
                content=m.content,
                message_count=m.message_count,
                correlation_id=m.correlation_id,
                created_at=m.created_at,
            )
            for m in memories
        ],
    )


# ---------------------------------------------------------------------------
# Tasks (channel-scoped)
# ---------------------------------------------------------------------------

@router.get("/channels/{channel_id}/tasks", response_model=TaskListOut)
async def admin_channel_tasks(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """List recent tasks for a channel (10, ordered by created_at desc)."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    tasks = (await db.execute(
        select(Task)
        .where(Task.channel_id == channel_id)
        .order_by(Task.created_at.desc())
        .limit(10)
    )).scalars().all()

    return TaskListOut(
        tasks=[
            TaskOut(
                id=t.id,
                status=t.status,
                bot_id=t.bot_id,
                prompt=t.prompt,
                result=t.result,
                error=t.error,
                dispatch_type=t.dispatch_type,
                task_type=t.task_type,
                recurrence=t.recurrence,
                created_at=t.created_at,
                scheduled_at=t.scheduled_at,
                run_at=t.run_at,
                completed_at=t.completed_at,
            )
            for t in tasks
        ],
    )


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

@router.get("/channels/{channel_id}/plans", response_model=PlanListOut)
async def admin_channel_plans(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """List plans with items for a channel."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    plans = (await db.execute(
        select(Plan)
        .options(selectinload(Plan.items))
        .where(Plan.channel_id == channel_id)
        .order_by(Plan.updated_at.desc())
    )).scalars().all()

    return PlanListOut(
        plans=[
            PlanOut(
                id=p.id,
                bot_id=p.bot_id,
                title=p.title,
                description=p.description,
                status=p.status,
                created_at=p.created_at,
                updated_at=p.updated_at,
                items=[
                    PlanItemOut(
                        id=item.id,
                        position=item.position,
                        content=item.content,
                        status=item.status,
                        notes=item.notes,
                        updated_at=item.updated_at,
                    )
                    for item in p.items
                ],
            )
            for p in plans
        ],
    )


# ---------------------------------------------------------------------------
# Knowledge
# ---------------------------------------------------------------------------

@router.get("/channels/{channel_id}/knowledge")
async def get_channel_knowledge(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Return knowledge entries scoped to this channel."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    stmt = (
        select(BotKnowledge, KnowledgeAccess.mode)
        .join(KnowledgeAccess, KnowledgeAccess.knowledge_id == BotKnowledge.id)
        .where(
            KnowledgeAccess.scope_type == "channel",
            KnowledgeAccess.scope_key == str(channel_id),
        )
        .order_by(BotKnowledge.updated_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            "id": str(k.id),
            "title": k.name,
            "content": k.content[:500] if k.content else None,
            "content_length": len(k.content) if k.content else 0,
            "bot_id": k.bot_id,
            "mode": mode,
            "updated_at": k.updated_at.isoformat() if k.updated_at else None,
        }
        for k, mode in rows
    ]


# ---------------------------------------------------------------------------
# Backfill sections
# ---------------------------------------------------------------------------

class BackfillRequest(BaseModel):
    chunk_size: int = Field(50, ge=1, le=500, description="Messages per section (user+assistant only)")
    model: Optional[str] = None
    provider_id: Optional[str] = None
    history_mode: Optional[str] = None  # "file" or "structured"; default: resolve from channel/bot
    clear_existing: bool = False  # delete all existing sections before backfilling


@router.post("/channels/{channel_id}/backfill-sections")
async def admin_channel_backfill_sections(
    channel_id: uuid.UUID,
    body: BackfillRequest = BackfillRequest(),
    _auth: str = Depends(verify_auth_or_user),
):
    """Fire-and-forget backfill — returns a task_id for polling progress."""
    import asyncio
    from app.services.compaction import _drain_backfill

    task_id = str(uuid.uuid4())
    asyncio.create_task(_drain_backfill(
        channel_id=channel_id,
        task_id=task_id,
        chunk_size=body.chunk_size,
        model=body.model,
        provider_id=body.provider_id,
        history_mode=body.history_mode,
        clear_existing=body.clear_existing,
    ))
    return {"task_id": task_id}


@router.get("/channels/{channel_id}/backfill-status/{task_id}")
async def admin_channel_backfill_status(
    channel_id: uuid.UUID,
    task_id: str,
    _auth: str = Depends(verify_auth_or_user),
):
    """Poll backfill progress by task_id."""
    from app.services.compaction import _BACKFILL_JOBS

    job = _BACKFILL_JOBS.get(task_id)
    if not job:
        raise HTTPException(status_code=404, detail="Backfill job not found")
    return job


@router.post("/channels/{channel_id}/repair-section-periods")
async def admin_repair_section_periods(
    channel_id: uuid.UUID,
    _auth: str = Depends(verify_auth_or_user),
):
    """Backfill missing period_start/period_end on sections from message timestamps."""
    from app.services.compaction import repair_section_periods
    repaired = await repair_section_periods(channel_id)
    return {"repaired": repaired}


# ---------------------------------------------------------------------------
# Conversation sections list
# ---------------------------------------------------------------------------

@router.get("/channels/{channel_id}/sections")
async def admin_channel_sections(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """List all conversation sections for a channel, ordered by sequence."""
    import math
    import os
    from app.db.models import ConversationSection
    from app.services.compaction import count_eligible_messages, _get_workspace_root

    rows = (
        await db.execute(
            select(ConversationSection)
            .where(ConversationSection.channel_id == channel_id)
            .order_by(ConversationSection.sequence)
        )
    ).scalars().all()

    # Resolve workspace root for file existence checks
    ws_root = None
    channel = await db.get(Channel, channel_id)
    if channel:
        try:
            bot = get_bot(channel.bot_id)
            ws_root = _get_workspace_root(bot)
        except Exception:
            pass

    def _file_exists(s) -> bool | None:
        if not s.transcript_path:
            return None
        if not ws_root:
            return None
        return os.path.isfile(os.path.join(ws_root, s.transcript_path))

    sections_out = []
    files_ok = 0
    files_missing = 0
    files_none = 0
    periods_missing = 0
    for s in rows:
        fe = _file_exists(s)
        if fe is True:
            files_ok += 1
        elif fe is False:
            files_missing += 1
        else:
            files_none += 1
        if not s.period_start:
            periods_missing += 1
        sections_out.append({
            "id": str(s.id),
            "sequence": s.sequence,
            "title": s.title,
            "summary": s.summary,
            "transcript_path": s.transcript_path,
            "message_count": s.message_count,
            "chunk_size": s.chunk_size,
            "period_start": s.period_start.isoformat() if s.period_start else None,
            "period_end": s.period_end.isoformat() if s.period_end else None,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "view_count": s.view_count,
            "last_viewed_at": s.last_viewed_at.isoformat() if s.last_viewed_at else None,
            "tags": s.tags or [],
            "file_exists": fe,
        })

    # Coverage stats
    total_messages = await count_eligible_messages(channel_id)
    covered_messages = sum(s.message_count for s in rows)
    remaining_messages = max(0, total_messages - covered_messages)
    last_chunk = rows[-1].chunk_size if rows else 50
    estimated_remaining = math.ceil(remaining_messages / last_chunk) if remaining_messages > 0 else 0

    return {
        "sections": sections_out,
        "total": len(rows),
        "stats": {
            "total_messages": total_messages,
            "covered_messages": covered_messages,
            "estimated_remaining": estimated_remaining,
            "files_ok": files_ok,
            "files_missing": files_missing,
            "files_none": files_none,
            "periods_missing": periods_missing,
        },
    }


@router.get("/channels/{channel_id}/section-index-preview")
async def admin_section_index_preview(
    channel_id: uuid.UUID,
    count: int = Query(10, ge=0, le=100),
    verbosity: str = Query("standard"),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Preview the section index that would be injected into context."""
    from app.db.models import ConversationSection
    from app.services.compaction import format_section_index

    if verbosity not in ("compact", "standard", "detailed"):
        raise HTTPException(status_code=400, detail="verbosity must be compact, standard, or detailed")

    rows = (
        await db.execute(
            select(ConversationSection)
            .where(ConversationSection.channel_id == channel_id)
            .order_by(ConversationSection.sequence.desc())
            .limit(count)
        )
    ).scalars().all()

    if not rows:
        return {"content": "", "section_count": 0, "chars": 0}

    content = format_section_index(rows, verbosity=verbosity)
    return {"content": content, "section_count": len(rows), "chars": len(content)}


# ---------------------------------------------------------------------------
# Context breakdown
# ---------------------------------------------------------------------------

@router.get("/channels/{channel_id}/context-breakdown")
async def admin_channel_context_breakdown(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Compute a detailed context breakdown for the channel's active session."""
    from app.services.context_breakdown import compute_context_breakdown
    from dataclasses import asdict

    try:
        result = await compute_context_breakdown(str(channel_id), db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Convert dataclasses to dicts for JSON serialization
    return {
        "channel_id": result.channel_id,
        "session_id": result.session_id,
        "bot_id": result.bot_id,
        "categories": [asdict(c) for c in result.categories],
        "total_chars": result.total_chars,
        "total_tokens_approx": result.total_tokens_approx,
        "compaction": asdict(result.compaction),
        "reranking": asdict(result.reranking),
        "effective_settings": {
            k: {"value": v.value, "source": v.source}
            for k, v in result.effective_settings.items()
        },
        "disclaimer": result.disclaimer,
    }


@router.get("/channels/{channel_id}/context-preview")
async def admin_channel_context_preview(
    channel_id: uuid.UUID,
    include_history: bool = Query(False, description="Include conversation messages from the active session"),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Render a preview of all system messages that would be injected before a user message."""
    from app.agent.base_prompt import render_base_prompt, resolve_workspace_base_prompt
    from app.agent.bots import get_bot as _get_bot_fn
    from app.agent.persona import get_persona
    from app.db.models import ConversationSection, Skill as SkillRow
    from app.services.compaction import _get_history_mode, format_section_index

    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    bot = _get_bot_fn(channel.bot_id)
    blocks: list[dict] = []  # {"label": str, "role": str, "content": str}

    # --- System prompt blocks (shown separately for clarity) ---
    if settings.GLOBAL_BASE_PROMPT:
        blocks.append({"label": "Global Base Prompt", "role": "system", "content": settings.GLOBAL_BASE_PROMPT.rstrip()})

    ws_base = None
    ws_base_enabled = False
    if bot.shared_workspace_id:
        from app.db.models import SharedWorkspaceBot as _SWBot, SharedWorkspace as _SW
        _swb = (await db.execute(
            select(_SWBot).where(_SWBot.bot_id == bot.id)
        )).scalar_one_or_none()
        if _swb:
            _sw = await db.get(_SW, _swb.workspace_id)
            if _sw:
                ws_base_enabled = _sw.workspace_base_prompt_enabled
        if channel.workspace_base_prompt_enabled is not None:
            ws_base_enabled = channel.workspace_base_prompt_enabled
        if ws_base_enabled:
            ws_base = resolve_workspace_base_prompt(bot.shared_workspace_id, bot.id)

    if ws_base:
        blocks.append({"label": "Workspace Base Prompt", "role": "system", "content": ws_base.rstrip()})
    else:
        base = render_base_prompt(bot)
        if base:
            blocks.append({"label": "Base Prompt", "role": "system", "content": base.rstrip()})

    if bot.system_prompt:
        blocks.append({"label": "Bot System Prompt", "role": "system", "content": bot.system_prompt.rstrip()})

    if bot.memory.enabled and bot.memory.prompt:
        blocks.append({"label": "Memory Guidelines", "role": "system", "content": bot.memory.prompt.strip()})

    # --- Persona ---
    if bot.persona:
        persona_text = await get_persona(bot.id, workspace_id=bot.shared_workspace_id)
        if persona_text:
            blocks.append({"label": "Persona", "role": "system", "content": f"[PERSONA]\n{persona_text}"})

    # --- Datetime ---
    try:
        from zoneinfo import ZoneInfo
        from datetime import timezone as _tz_mod
        _tz = ZoneInfo(settings.TIMEZONE)
        from datetime import datetime as _dt
        _now_local = _dt.now(_tz)
        _now_utc = _dt.now(_tz_mod.utc)
        blocks.append({"label": "Date/Time", "role": "system", "content": f"Current time: {_now_local.strftime('%Y-%m-%d %H:%M %Z')} ({_now_utc.strftime('%H:%M UTC')})"})
    except Exception:
        blocks.append({"label": "Date/Time", "role": "system", "content": "(timezone unavailable)"})

    # --- Pinned skills ---
    pinned_skills = [s for s in bot.skills if s.mode == "pinned"]
    if pinned_skills:
        ids = [s.id for s in pinned_skills]
        rows = (await db.execute(select(SkillRow).where(SkillRow.id.in_(ids)))).scalars().all()
        if rows:
            content = "\n\n---\n\n".join(r.content for r in rows if r.content)
            blocks.append({"label": f"Pinned Skills ({len(rows)})", "role": "system", "content": f"Pinned skill context:\n\n{content}"})

    # --- On-demand skill index ---
    od_skills = [s for s in bot.skills if s.mode == "on_demand"]
    if od_skills:
        ids = [s.id for s in od_skills]
        rows = (await db.execute(select(SkillRow.id, SkillRow.name).where(SkillRow.id.in_(ids)))).all()
        if rows:
            index_lines = "\n".join(f"- {r.id}: {r.name}" for r in rows)
            blocks.append({"label": f"Skill Index ({len(rows)})", "role": "system", "content": f"Available skills (use get_skill to retrieve full content):\n{index_lines}"})

    # --- RAG skills placeholder ---
    rag_skills = [s for s in bot.skills if s.mode == "rag"]
    if rag_skills:
        blocks.append({"label": f"RAG Skills ({len(rag_skills)})", "role": "system", "content": "[RAG skill chunks — varies by query similarity]"})

    # --- Delegate bot index ---
    if bot.delegate_bots:
        lines = []
        for did in bot.delegate_bots:
            try:
                db_ = _get_bot_fn(did)
                desc = (db_.system_prompt or "").strip().splitlines()[0][:120] if db_.system_prompt else ""
                lines.append(f"  \u2022 {did} \u2014 {db_.name}" + (f": {desc}" if desc else ""))
            except Exception:
                lines.append(f"  \u2022 {did}")
        blocks.append({"label": f"Delegation Index ({len(bot.delegate_bots)})", "role": "system", "content": "Available sub-agents (delegate via delegate_to_agent or @bot-id in your reply):\n" + "\n".join(lines)})

    # --- Memory / Knowledge placeholders ---
    if bot.memory.enabled:
        blocks.append({"label": "Memory (RAG)", "role": "system", "content": "[Memory recall — varies by query similarity against stored memories]"})
    if bot.knowledge.enabled:
        blocks.append({"label": "Knowledge (RAG)", "role": "system", "content": "[Knowledge retrieval — varies by query similarity against saved docs]"})

    # --- Section index (file mode) ---
    hist_mode = _get_history_mode(bot, channel)
    if hist_mode == "file":
        si_count = channel.section_index_count if channel.section_index_count is not None else 10
        if si_count > 0:
            si_verbosity = channel.section_index_verbosity or "standard"
            si_rows = (await db.execute(
                select(ConversationSection)
                .where(ConversationSection.channel_id == channel_id)
                .order_by(ConversationSection.sequence.desc())
                .limit(si_count)
            )).scalars().all()
            if si_rows:
                si_text = format_section_index(si_rows, verbosity=si_verbosity)
                blocks.append({"label": f"Section Index ({len(si_rows)} sections)", "role": "system", "content": si_text})
            else:
                blocks.append({"label": "Section Index", "role": "system", "content": "[No sections yet — run backfill first]"})

    # --- Workspace filesystem placeholder ---
    if bot.workspace.enabled and bot.workspace.indexing.enabled:
        blocks.append({"label": "Workspace Files (RAG)", "role": "system", "content": "[Workspace file chunks — varies by query similarity]"})

    # --- Channel prompt ---
    if channel.channel_prompt:
        blocks.append({"label": "Channel Prompt", "role": "system", "content": channel.channel_prompt})

    # --- Conversation history (optional) ---
    conversation_blocks: list[dict] = []
    if include_history and channel.active_session_id:
        active_session = await db.get(Session, channel.active_session_id)

        if active_session and active_session.summary:
            conversation_blocks.append({"label": "Compaction Summary", "role": "system", "content": active_session.summary})

        # Only show messages after watermark (post-compaction)
        msg_query = select(Message).where(
            Message.session_id == channel.active_session_id,
        ).order_by(Message.created_at)

        if active_session and active_session.summary_message_id:
            watermark_msg = await db.get(Message, active_session.summary_message_id)
            if watermark_msg:
                msg_query = msg_query.where(Message.created_at > watermark_msg.created_at)

        msgs = (await db.execute(msg_query)).scalars().all()
        for m in msgs:
            if m.role == "system":
                continue
            conversation_blocks.append({
                "label": m.role.capitalize(),
                "role": m.role,
                "content": m.content[:10000] if m.content else "",
            })

    total_chars = sum(len(b["content"]) for b in blocks + conversation_blocks)

    return {
        "blocks": blocks,
        "conversation": conversation_blocks,
        "total_chars": total_chars,
        "total_tokens_approx": max(1, total_chars // 4) if total_chars > 0 else 0,
        "history_mode": hist_mode,
    }


# ---------------------------------------------------------------------------
# Enriched (display name resolution)
# ---------------------------------------------------------------------------

async def _resolve_display_names(channels: list) -> dict[uuid.UUID, str]:
    """Resolve display names for channels from their integrations."""
    from app.config import settings as app_settings

    result: dict[uuid.UUID, str] = {}

    by_integration: dict[str, list] = {}
    for ch in channels:
        if ch.integration:
            by_integration.setdefault(ch.integration, []).append(ch)

    slack_channels = by_integration.get("slack", [])
    if slack_channels and app_settings.SLACK_BOT_TOKEN:
        import httpx
        token = app_settings.SLACK_BOT_TOKEN
        async with httpx.AsyncClient(timeout=5.0) as client:
            for ch in slack_channels:
                if not ch.client_id:
                    continue
                slack_id = ch.client_id.removeprefix("slack:")
                try:
                    r = await client.get(
                        "https://slack.com/api/conversations.info",
                        params={"channel": slack_id},
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    data = r.json()
                    if data.get("ok"):
                        info = data.get("channel") or {}
                        name = info.get("name_normalized") or info.get("name")
                        if name:
                            result[ch.id] = f"#{name}"
                except Exception:
                    pass

    return result


@router.get("/channels-enriched", response_model=ChannelListOut)
async def admin_channels_enriched(
    integration: Optional[str] = Query(None),
    bot_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    auth_result=Depends(verify_auth_or_user),
):
    """List channels with integration-resolved display names."""
    stmt_base = select(Channel).order_by(Channel.updated_at.desc())
    stmt_base = apply_channel_visibility(stmt_base, auth_result)
    if integration:
        stmt_base = stmt_base.where(Channel.integration == integration)
    if bot_id:
        stmt_base = stmt_base.where(Channel.bot_id == bot_id)

    total = (await db.execute(
        select(func.count()).select_from(stmt_base.subquery())
    )).scalar_one()

    stmt = stmt_base.options(selectinload(Channel.integrations))

    offset = (page - 1) * page_size
    channels = (await db.execute(
        stmt.offset(offset).limit(page_size)
    )).scalars().all()

    display_names = await _resolve_display_names(channels)

    enriched = []
    for ch in channels:
        out = ChannelOut.model_validate(ch)
        out.display_name = display_names.get(ch.id)
        enriched.append(out)

    return ChannelListOut(
        channels=enriched,
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Available integrations
# ---------------------------------------------------------------------------

@router.get("/channels/integrations/available")
async def available_integrations(
    _auth=Depends(verify_auth_or_user),
):
    """List registered integration types (from discovery + dispatcher registry)."""
    from app.agent import dispatchers as disp_mod
    from integrations import discover_integrations

    # Collect from dispatcher registry
    types = set(disp_mod._registry.keys()) - {"none", "webhook", "internal"}

    # Collect from integration discovery
    for integration_id, _ in discover_integrations():
        types.add(integration_id)

    return sorted(types)
