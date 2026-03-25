"""Channel CRUD + tab endpoints: sessions, heartbeat, memories, tasks, plans,
compression, knowledge, enriched."""
from __future__ import annotations

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
    KnowledgeAccess,
    Memory,
    Message,
    Plan,
    Session,
    Task,
    TraceEvent,
)
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
    prompt: str = ""
    prompt_template_id: Optional[uuid.UUID] = None
    dispatch_results: bool = True
    trigger_response: bool = False
    quiet_start: Optional[str] = None
    quiet_end: Optional[str] = None
    timezone: Optional[str] = None
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_heartbeat(cls, hb: ChannelHeartbeat) -> "HeartbeatConfigOut":
        data = {c: getattr(hb, c) for c in [
            "id", "channel_id", "enabled", "interval_minutes", "model",
            "model_provider_id", "prompt", "prompt_template_id",
            "dispatch_results", "trigger_response",
            "timezone", "last_run_at", "next_run_at", "created_at", "updated_at",
        ]}
        data["quiet_start"] = hb.quiet_start.strftime("%H:%M") if hb.quiet_start else None
        data["quiet_end"] = hb.quiet_end.strftime("%H:%M") if hb.quiet_end else None
        return cls(**data)


class HeartbeatHistoryTaskOut(BaseModel):
    id: uuid.UUID
    status: str
    created_at: datetime
    run_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    correlation_id: Optional[uuid.UUID] = None

    model_config = {"from_attributes": True}


class HeartbeatOut(BaseModel):
    config: Optional[HeartbeatConfigOut] = None
    history: list[HeartbeatHistoryTaskOut] = []
    total_history: int = 0


class HeartbeatUpdate(BaseModel):
    enabled: Optional[bool] = None
    interval_minutes: int = Field(60, ge=1)
    model: str = ""
    model_provider_id: Optional[str] = None
    prompt: str = ""
    prompt_template_id: Optional[uuid.UUID] = None
    dispatch_results: bool = True
    trigger_response: bool = False
    quiet_start: Optional[str] = None  # "HH:MM" or null
    quiet_end: Optional[str] = None    # "HH:MM" or null
    timezone: Optional[str] = None


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


class CompressionStatsOut(BaseModel):
    compression_enabled: bool = False
    compression_model: str = ""
    compression_threshold: int = 20000
    compression_keep_turns: int = 2
    total_compressions: int = 0
    total_chars_saved: int = 0
    total_msgs_saved: int = 0
    avg_reduction_pct: float = 0.0
    avg_ratio: float = 0.0
    avg_original: int = 0
    avg_compressed: int = 0


class CompressionEventOut(BaseModel):
    id: uuid.UUID
    session_id: Optional[uuid.UUID] = None
    correlation_id: Optional[uuid.UUID] = None
    original_chars: int = 0
    compressed_chars: int = 0
    original_messages: int = 0
    compressed_messages: int = 0
    created_at: datetime


class CompressionOut(BaseModel):
    stats: CompressionStatsOut
    events: list[CompressionEventOut] = []


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
    workspace_rag: bool = True
    context_compaction: bool = True
    compaction_interval: Optional[int] = None
    compaction_keep_turns: Optional[int] = None
    memory_knowledge_compaction_prompt: Optional[str] = None
    compaction_prompt_template_id: Optional[uuid.UUID] = None
    context_compression: Optional[bool] = None
    compression_model: Optional[str] = None
    compression_threshold: Optional[int] = None
    compression_keep_turns: Optional[int] = None
    compression_prompt: Optional[str] = None
    # Summarizer (auto-resume after idle)
    summarizer_enabled: bool = False
    summarizer_threshold_minutes: Optional[int] = None
    summarizer_message_count: Optional[int] = None
    summarizer_target_size: Optional[int] = None
    summarizer_prompt: Optional[str] = None
    summarizer_model: Optional[str] = None
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
    workspace_rag: Optional[bool] = None
    context_compaction: Optional[bool] = None
    compaction_interval: Optional[int] = None
    compaction_keep_turns: Optional[int] = None
    memory_knowledge_compaction_prompt: Optional[str] = None
    compaction_prompt_template_id: Optional[uuid.UUID] = None
    context_compression: Optional[bool] = None
    compression_model: Optional[str] = None
    compression_threshold: Optional[int] = None
    compression_keep_turns: Optional[int] = None
    compression_prompt: Optional[str] = None
    # Summarizer (auto-resume after idle)
    summarizer_enabled: Optional[bool] = None
    summarizer_threshold_minutes: Optional[int] = None
    summarizer_message_count: Optional[int] = None
    summarizer_target_size: Optional[int] = None
    summarizer_prompt: Optional[str] = None
    summarizer_model: Optional[str] = None
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
        stmt.offset(offset).limit(page_size)
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


@router.put("/channels/{channel_id}/settings", response_model=ChannelSettingsOut)
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

    config_out = HeartbeatConfigOut.from_orm_heartbeat(heartbeat) if heartbeat else None

    history_out = [
        HeartbeatHistoryTaskOut(
            id=t.id,
            status=t.status,
            created_at=t.created_at,
            run_at=t.run_at,
            completed_at=t.completed_at,
            error=t.error,
            correlation_id=corr_map.get(t.id),
        )
        for t in history
    ]

    return HeartbeatOut(
        config=config_out,
        history=history_out,
        total_history=total_history,
    )


@router.put("/channels/{channel_id}/heartbeat", response_model=HeartbeatConfigOut)
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

    if body.enabled is not None:
        heartbeat.enabled = body.enabled
    heartbeat.interval_minutes = max(1, body.interval_minutes)
    heartbeat.model = body.model.strip()
    heartbeat.model_provider_id = body.model_provider_id.strip() if body.model_provider_id else None
    heartbeat.prompt = body.prompt.strip()
    heartbeat.prompt_template_id = body.prompt_template_id
    heartbeat.dispatch_results = body.dispatch_results
    heartbeat.trigger_response = body.trigger_response
    heartbeat.updated_at = now

    if heartbeat.enabled and heartbeat.next_run_at is None:
        heartbeat.next_run_at = now + timedelta(minutes=heartbeat.interval_minutes)

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
    """Fire heartbeat immediately."""
    from app.services.heartbeat import fire_heartbeat

    heartbeat = (await db.execute(
        select(ChannelHeartbeat).where(ChannelHeartbeat.channel_id == channel_id)
    )).scalar_one_or_none()

    if not heartbeat:
        raise HTTPException(status_code=404, detail="No heartbeat configured")

    await fire_heartbeat(heartbeat)

    await db.refresh(heartbeat)
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
# Compression
# ---------------------------------------------------------------------------

@router.get("/channels/{channel_id}/compression", response_model=CompressionOut)
async def admin_channel_compression(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Get compression stats from TraceEvent context_compressed events."""
    from app.services.compression import (
        _is_compression_enabled,
        _get_compression_model,
        _get_compression_threshold,
        _get_compression_keep_turns,
    )

    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    session_ids = (await db.execute(
        select(Session.id).where(Session.channel_id == channel_id)
    )).scalars().all()

    events = []
    if session_ids:
        events = (await db.execute(
            select(TraceEvent)
            .where(
                TraceEvent.session_id.in_(session_ids),
                TraceEvent.event_type == "context_compressed",
            )
            .order_by(TraceEvent.created_at.desc())
            .limit(50)
        )).scalars().all()

    bot_cfg = get_bot(channel.bot_id)
    compression_enabled = _is_compression_enabled(bot_cfg, channel) if bot_cfg else False
    compression_model = _get_compression_model(bot_cfg, channel) if bot_cfg else ""
    compression_threshold = _get_compression_threshold(bot_cfg, channel) if bot_cfg else 20000
    compression_keep_turns = _get_compression_keep_turns(bot_cfg, channel) if bot_cfg else 2

    total_compressions = len(events)
    total_chars_saved = 0
    total_msgs_saved = 0
    total_original = 0
    total_compressed = 0
    for e in events:
        d = e.data or {}
        orig = d.get("original_chars", 0)
        comp = d.get("compressed_chars", 0)
        total_original += orig
        total_compressed += comp
        total_chars_saved += orig - comp
        total_msgs_saved += d.get("original_messages", 0) - d.get("compressed_messages", 0)

    stats = CompressionStatsOut(
        compression_enabled=compression_enabled,
        compression_model=compression_model,
        compression_threshold=compression_threshold,
        compression_keep_turns=compression_keep_turns,
        total_compressions=total_compressions,
        total_chars_saved=total_chars_saved,
        total_msgs_saved=total_msgs_saved,
        avg_reduction_pct=((1 - total_compressed / total_original) * 100) if total_original > 0 else 0,
        avg_ratio=(total_original / total_compressed) if total_compressed > 0 else 0,
        avg_original=total_original // max(total_compressions, 1),
        avg_compressed=total_compressed // max(total_compressions, 1),
    )

    events_out = [
        CompressionEventOut(
            id=e.id,
            session_id=e.session_id,
            correlation_id=e.correlation_id,
            original_chars=(e.data or {}).get("original_chars", 0),
            compressed_chars=(e.data or {}).get("compressed_chars", 0),
            original_messages=(e.data or {}).get("original_messages", 0),
            compressed_messages=(e.data or {}).get("compressed_messages", 0),
            created_at=e.created_at,
        )
        for e in events
    ]

    return CompressionOut(stats=stats, events=events_out)


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
        "compression": asdict(result.compression),
        "effective_settings": {
            k: {"value": v.value, "source": v.source}
            for k, v in result.effective_settings.items()
        },
        "disclaimer": result.disclaimer,
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
