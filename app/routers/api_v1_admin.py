"""Admin JSON API — /api/v1/admin/

Provides admin endpoints that mirror the Jinja2/HTMX admin
dashboard, returning structured JSON for the Expo client.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent.bots import get_bot, list_bots
from app.db.models import (
    Bot as BotRow,
    BotKnowledge,
    BotPersona,
    Channel,
    ChannelHeartbeat,
    KnowledgeAccess,
    Memory,
    Message,
    Plan,
    SandboxInstance,
    SandboxProfile,
    Session,
    Skill as SkillRow,
    Task,
    ToolCall,
    ToolEmbedding,
    TraceEvent,
)
from app.dependencies import get_db, verify_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin API"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class DashboardStats(BaseModel):
    bot_count: int
    session_count: int
    memory_count: int
    knowledge_count: int
    tool_count: int
    tool_call_count: int
    sandbox_running_count: int


class MemoryConfigOut(BaseModel):
    enabled: bool = False
    cross_channel: bool = False
    cross_client: bool = False
    cross_bot: bool = False
    prompt: Optional[str] = None
    similarity_threshold: float = 0.45

    model_config = {"from_attributes": True}


class KnowledgeConfigOut(BaseModel):
    enabled: bool = False

    model_config = {"from_attributes": True}


class SkillConfigOut(BaseModel):
    id: str
    mode: str = "on_demand"
    similarity_threshold: Optional[float] = None

    model_config = {"from_attributes": True}


class BotOut(BaseModel):
    id: str
    name: str
    model: str
    system_prompt: str = ""
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    local_tools: list[str] = []
    mcp_servers: list[str] = []
    client_tools: list[str] = []
    pinned_tools: list[str] = []
    skills: list[SkillConfigOut] = []
    tool_retrieval: bool = True
    tool_similarity_threshold: Optional[float] = None
    tool_result_config: dict = {}
    compression_config: dict = {}
    persona: bool = False
    persona_content: Optional[str] = None
    context_compaction: bool = True
    compaction_interval: Optional[int] = None
    compaction_keep_turns: Optional[int] = None
    compaction_model: Optional[str] = None
    audio_input: str = "transcribe"
    memory: MemoryConfigOut = MemoryConfigOut()
    memory_max_inject_chars: Optional[int] = None
    knowledge: KnowledgeConfigOut = KnowledgeConfigOut()
    knowledge_max_inject_chars: Optional[int] = None
    delegate_bots: list[str] = []
    harness_access: list[str] = []
    model_provider_id: Optional[str] = None
    integration_config: dict = {}
    workspace: dict = Field(default_factory=lambda: {"enabled": False})
    docker_sandbox_profiles: list[str] = []
    elevation_enabled: Optional[bool] = None
    elevation_threshold: Optional[float] = None
    elevated_model: Optional[str] = None
    attachment_summarization_enabled: Optional[bool] = None
    attachment_summary_model: Optional[str] = None
    attachment_text_max_chars: Optional[int] = None
    attachment_vision_concurrency: Optional[int] = None
    delegation_config: dict = {}
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    model_config = {"from_attributes": True}


class BotListOut(BaseModel):
    bots: list[BotOut]
    total: int


class ChannelOut(BaseModel):
    id: uuid.UUID
    name: str
    bot_id: str
    client_id: Optional[str] = None
    integration: Optional[str] = None
    active_session_id: Optional[uuid.UUID] = None
    require_mention: bool = True
    passive_memory: bool = True
    display_name: Optional[str] = None  # Integration-resolved name
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


# ---------------------------------------------------------------------------
# Channel tab response schemas
# ---------------------------------------------------------------------------

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
    dispatch_results: bool = True
    trigger_response: bool = False
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


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
    interval_minutes: int = Field(60, ge=1)
    model: str = ""
    model_provider_id: Optional[str] = None
    prompt: str = ""
    dispatch_results: bool = True
    trigger_response: bool = False


class MemoryOut(BaseModel):
    id: uuid.UUID
    session_id: Optional[uuid.UUID] = None
    client_id: str
    bot_id: str
    content: str
    message_count: Optional[int] = None
    correlation_id: Optional[uuid.UUID] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MemoryListOut(BaseModel):
    memories: list[MemoryOut]


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bot_to_out(bot, *, persona_content: str | None = None) -> BotOut:
    """Convert a BotConfig dataclass to a BotOut Pydantic model."""
    return BotOut(
        id=bot.id,
        name=bot.name,
        model=bot.model,
        system_prompt=bot.system_prompt,
        display_name=bot.display_name,
        avatar_url=bot.avatar_url,
        local_tools=bot.local_tools,
        mcp_servers=bot.mcp_servers,
        client_tools=bot.client_tools,
        pinned_tools=bot.pinned_tools,
        skills=[
            SkillConfigOut(id=s.id, mode=s.mode, similarity_threshold=s.similarity_threshold)
            for s in bot.skills
        ],
        tool_retrieval=bot.tool_retrieval,
        tool_similarity_threshold=bot.tool_similarity_threshold,
        tool_result_config=getattr(bot, "tool_result_config", {}),
        compression_config=getattr(bot, "compression_config", {}),
        persona=bot.persona,
        persona_content=persona_content,
        context_compaction=bot.context_compaction,
        compaction_interval=bot.compaction_interval,
        compaction_keep_turns=bot.compaction_keep_turns,
        compaction_model=getattr(bot, "compaction_model", None),
        audio_input=bot.audio_input,
        memory=MemoryConfigOut(
            enabled=bot.memory.enabled,
            cross_channel=bot.memory.cross_channel,
            cross_client=bot.memory.cross_client,
            cross_bot=bot.memory.cross_bot,
            prompt=bot.memory.prompt,
            similarity_threshold=bot.memory.similarity_threshold,
        ),
        memory_max_inject_chars=getattr(bot, "memory_max_inject_chars", None),
        knowledge=KnowledgeConfigOut(enabled=bot.knowledge.enabled),
        knowledge_max_inject_chars=getattr(bot, "knowledge_max_inject_chars", None),
        delegate_bots=bot.delegate_bots,
        harness_access=bot.harness_access,
        model_provider_id=bot.model_provider_id,
        integration_config=getattr(bot, "integration_config", {}),
        workspace=getattr(bot, "workspace", {"enabled": False}),
        docker_sandbox_profiles=getattr(bot, "docker_sandbox_profiles", []),
        elevation_enabled=getattr(bot, "elevation_enabled", None),
        elevation_threshold=getattr(bot, "elevation_threshold", None),
        elevated_model=getattr(bot, "elevated_model", None),
        attachment_summarization_enabled=getattr(bot, "attachment_summarization_enabled", None),
        attachment_summary_model=getattr(bot, "attachment_summary_model", None),
        attachment_text_max_chars=getattr(bot, "attachment_text_max_chars", None),
        attachment_vision_concurrency=getattr(bot, "attachment_vision_concurrency", None),
        delegation_config=getattr(bot, "delegation_config", {}),
        created_at=bot.created_at.isoformat() if hasattr(bot, "created_at") and bot.created_at else None,
        updated_at=bot.updated_at.isoformat() if hasattr(bot, "updated_at") and bot.updated_at else None,
    )


async def _heartbeat_correlation_ids(
    db: AsyncSession, tasks: list[Task],
) -> dict[uuid.UUID, uuid.UUID]:
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

    # Fallback: trace events for tasks with no message match
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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/stats", response_model=DashboardStats)
async def admin_stats(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    """Dashboard overview stats — mirrors the /admin index page."""
    session_count = (await db.execute(
        select(func.count()).select_from(Session)
    )).scalar_one()
    memory_count = (await db.execute(
        select(func.count()).select_from(Memory)
    )).scalar_one()
    knowledge_count = (await db.execute(
        select(func.count()).select_from(BotKnowledge)
    )).scalar_one()
    tool_count = (await db.execute(
        select(func.count()).select_from(ToolEmbedding)
    )).scalar_one()
    tool_call_count = (await db.execute(
        select(func.count()).select_from(ToolCall)
    )).scalar_one()
    sandbox_running = (await db.execute(
        select(func.count()).select_from(SandboxInstance)
        .where(SandboxInstance.status == "running")
    )).scalar_one()

    bots = list_bots()

    return DashboardStats(
        bot_count=len(bots),
        session_count=session_count,
        memory_count=memory_count,
        knowledge_count=knowledge_count,
        tool_count=tool_count,
        tool_call_count=tool_call_count,
        sandbox_running_count=sandbox_running,
    )


@router.get("/bots", response_model=BotListOut)
async def admin_bots_list(
    _auth: str = Depends(verify_auth),
):
    """List all bots with full config."""
    bots = list_bots()
    return BotListOut(
        bots=[_bot_to_out(b) for b in bots],
        total=len(bots),
    )


@router.get("/bots/{bot_id}", response_model=BotOut)
async def admin_bot_detail(
    bot_id: str,
    _auth: str = Depends(verify_auth),
):
    """Get a single bot's full config."""
    from app.agent.persona import get_persona
    try:
        bot = get_bot(bot_id)
    except HTTPException:
        raise HTTPException(status_code=404, detail=f"Bot not found: {bot_id}")
    persona_content = await get_persona(bot_id)
    return _bot_to_out(bot, persona_content=persona_content)


@router.get("/channels", response_model=ChannelListOut)
async def admin_channels_list(
    integration: Optional[str] = Query(None, description="Filter by integration type"),
    bot_id: Optional[str] = Query(None, description="Filter by bot_id"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(25, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    """List channels with pagination and optional filters."""
    stmt = select(Channel).order_by(Channel.updated_at.desc())
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
    _auth: str = Depends(verify_auth),
):
    """Channel detail with linked entity counts."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # Session count for this channel
    session_count = (await db.execute(
        select(func.count()).select_from(Session)
        .where(Session.channel_id == channel_id)
    )).scalar_one()

    # Total message count across all sessions in this channel
    message_count = (await db.execute(
        select(func.count()).select_from(Message)
        .join(Session, Message.session_id == Session.id)
        .where(Session.channel_id == channel_id)
    )).scalar_one()

    # Memory count for this channel
    memory_count = (await db.execute(
        select(func.count()).select_from(Memory)
        .where(Memory.channel_id == channel_id)
    )).scalar_one()

    # Task count for this channel
    task_count = (await db.execute(
        select(func.count()).select_from(Task)
        .where(Task.channel_id == channel_id)
    )).scalar_one()

    # Active session message count
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
# Channel settings (full read/write)
# ---------------------------------------------------------------------------

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
    context_compression: Optional[bool] = None
    compression_model: Optional[str] = None
    compression_threshold: Optional[int] = None
    compression_keep_turns: Optional[int] = None
    elevation_enabled: Optional[bool] = None
    elevation_threshold: Optional[float] = None
    elevated_model: Optional[str] = None

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
    context_compression: Optional[bool] = None
    compression_model: Optional[str] = None
    compression_threshold: Optional[int] = None
    compression_keep_turns: Optional[int] = None
    elevation_enabled: Optional[bool] = None
    elevation_threshold: Optional[float] = None
    elevated_model: Optional[str] = None


@router.get("/channels/{channel_id}/settings", response_model=ChannelSettingsOut)
async def admin_channel_settings(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
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
    _auth: str = Depends(verify_auth),
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
# Channel tab endpoints — sessions, heartbeat, memories, tasks, plans,
# compression
# ---------------------------------------------------------------------------

@router.get("/channels/{channel_id}/sessions", response_model=SessionListOut)
async def admin_channel_sessions(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
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


@router.get("/channels/{channel_id}/heartbeat", response_model=HeartbeatOut)
async def admin_channel_heartbeat_get(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    """Get heartbeat config and recent history for a channel."""
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

    config_out = HeartbeatConfigOut.model_validate(heartbeat) if heartbeat else None

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
    _auth: str = Depends(verify_auth),
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

    heartbeat.interval_minutes = max(1, body.interval_minutes)
    heartbeat.model = body.model.strip()
    heartbeat.model_provider_id = body.model_provider_id.strip() if body.model_provider_id else None
    heartbeat.prompt = body.prompt.strip()
    heartbeat.dispatch_results = body.dispatch_results
    heartbeat.trigger_response = body.trigger_response
    heartbeat.updated_at = now

    # If enabled and next_run_at not set, schedule first run
    if heartbeat.enabled and heartbeat.next_run_at is None:
        heartbeat.next_run_at = now + timedelta(minutes=heartbeat.interval_minutes)

    await db.commit()
    await db.refresh(heartbeat)
    return HeartbeatConfigOut.model_validate(heartbeat)


@router.post("/channels/{channel_id}/heartbeat/toggle", response_model=HeartbeatConfigOut)
async def admin_channel_heartbeat_toggle(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
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
    _auth: str = Depends(verify_auth),
):
    """Fire heartbeat immediately."""
    from app.services.heartbeat import fire_heartbeat

    heartbeat = (await db.execute(
        select(ChannelHeartbeat).where(ChannelHeartbeat.channel_id == channel_id)
    )).scalar_one_or_none()

    if not heartbeat:
        raise HTTPException(status_code=404, detail="No heartbeat configured")

    await fire_heartbeat(heartbeat)

    # Re-fetch after fire (fire_heartbeat updates last_run_at/next_run_at)
    await db.refresh(heartbeat)
    return HeartbeatConfigOut.model_validate(heartbeat)


@router.get("/channels/{channel_id}/memories", response_model=MemoryListOut)
async def admin_channel_memories(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
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


@router.get("/tasks")
async def admin_list_tasks(
    status: Optional[str] = None,
    bot_id: Optional[str] = None,
    channel_id: Optional[uuid.UUID] = None,
    task_type: Optional[str] = None,
    after: Optional[str] = None,
    before: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth),
):
    """List tasks with optional filters. `after`/`before` are ISO datetime strings filtering on scheduled_at or created_at."""
    stmt = select(Task).order_by(Task.scheduled_at.asc().nullslast(), Task.created_at.asc())
    count_stmt = select(func.count()).select_from(Task)

    if status:
        stmt = stmt.where(Task.status == status)
        count_stmt = count_stmt.where(Task.status == status)
    if bot_id:
        stmt = stmt.where(Task.bot_id == bot_id)
        count_stmt = count_stmt.where(Task.bot_id == bot_id)
    if channel_id:
        stmt = stmt.where(Task.channel_id == channel_id)
        count_stmt = count_stmt.where(Task.channel_id == channel_id)
    if task_type:
        stmt = stmt.where(Task.task_type == task_type)
        count_stmt = count_stmt.where(Task.task_type == task_type)
    if after:
        from datetime import datetime as dt
        after_dt = dt.fromisoformat(after)
        time_col = func.coalesce(Task.scheduled_at, Task.created_at)
        stmt = stmt.where(time_col >= after_dt)
        count_stmt = count_stmt.where(time_col >= after_dt)
    if before:
        from datetime import datetime as dt
        before_dt = dt.fromisoformat(before)
        time_col = func.coalesce(Task.scheduled_at, Task.created_at)
        stmt = stmt.where(time_col < before_dt)
        count_stmt = count_stmt.where(time_col < before_dt)

    total = (await db.execute(count_stmt)).scalar_one()
    tasks = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()

    return {
        "tasks": [
            {
                "id": str(t.id),
                "status": t.status,
                "bot_id": t.bot_id,
                "prompt": t.prompt,
                "result": t.result[:500] if t.result else None,
                "error": t.error,
                "dispatch_type": t.dispatch_type,
                "task_type": t.task_type,
                "recurrence": t.recurrence,
                "channel_id": str(t.channel_id) if t.channel_id else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "scheduled_at": t.scheduled_at.isoformat() if t.scheduled_at else None,
                "run_at": t.run_at.isoformat() if t.run_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            }
            for t in tasks
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/channels/{channel_id}/tasks", response_model=TaskListOut)
async def admin_channel_tasks(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
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


@router.get("/channels/{channel_id}/plans", response_model=PlanListOut)
async def admin_channel_plans(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
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


@router.get("/channels/{channel_id}/compression", response_model=CompressionOut)
async def admin_channel_compression(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
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

    # Get all session IDs for this channel
    session_ids = (await db.execute(
        select(Session.id).where(Session.channel_id == channel_id)
    )).scalars().all()

    # Query compression trace events
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

    # Resolve effective compression config
    bot_cfg = get_bot(channel.bot_id)
    compression_enabled = _is_compression_enabled(bot_cfg, channel) if bot_cfg else False
    compression_model = _get_compression_model(bot_cfg, channel) if bot_cfg else ""
    compression_threshold = _get_compression_threshold(bot_cfg, channel) if bot_cfg else 20000
    compression_keep_turns = _get_compression_keep_turns(bot_cfg, channel) if bot_cfg else 2

    # Compute aggregate stats
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
# Models (provider-grouped) + completions
# ---------------------------------------------------------------------------

class ModelOut(BaseModel):
    id: str
    display: str
    max_tokens: Optional[int] = None


class ModelGroupOut(BaseModel):
    provider_id: Optional[str] = None
    provider_name: str
    provider_type: str
    models: list[ModelOut]


class CompletionItem(BaseModel):
    value: str
    label: str


@router.get("/models", response_model=list[ModelGroupOut])
async def admin_models(
    _auth: str = Depends(verify_auth),
):
    """List all available LLM models grouped by provider."""
    from app.services.providers import get_available_models_grouped
    try:
        groups = await get_available_models_grouped()
    except Exception:
        groups = []
    return [
        ModelGroupOut(
            provider_id=g.get("provider_id"),
            provider_name=g["provider_name"],
            provider_type=g["provider_type"],
            models=[ModelOut(id=m["id"], display=m["display"], max_tokens=m.get("max_tokens")) for m in g["models"]],
        )
        for g in groups
    ]


@router.get("/completions", response_model=list[CompletionItem])
async def admin_completions(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    """Get @-tag completions for skills, tools, and tool-packs."""
    from app.tools.packs import get_tool_packs

    all_skills = (await db.execute(
        select(SkillRow).order_by(SkillRow.name)
    )).scalars().all()
    tool_names = (await db.execute(
        select(ToolEmbedding.tool_name).distinct().order_by(ToolEmbedding.tool_name)
    )).scalars().all()
    packs = get_tool_packs()

    items: list[CompletionItem] = []
    for s in all_skills:
        items.append(CompletionItem(value=f"skill:{s.id}", label=f"skill:{s.id} — {s.name}"))
    for t in tool_names:
        items.append(CompletionItem(value=f"tool:{t}", label=f"tool:{t}"))
    for k, v in sorted(packs.items()):
        items.append(CompletionItem(value=f"tool-pack:{k}", label=f"tool-pack:{k} — {len(v)} tools"))
    return items


# ---------------------------------------------------------------------------
# Integration display name resolution
# ---------------------------------------------------------------------------

async def _resolve_display_names(channels: list) -> dict[uuid.UUID, str]:
    """Resolve display names for channels from their integrations.

    Integration-agnostic: dispatches to per-integration resolvers.
    Returns {channel_id: display_name} for channels that have resolved names.
    """
    from app.config import settings as app_settings

    result: dict[uuid.UUID, str] = {}

    # Group channels by integration type
    by_integration: dict[str, list] = {}
    for ch in channels:
        if ch.integration:
            by_integration.setdefault(ch.integration, []).append(ch)

    # Slack resolver
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

    # Discord resolver (placeholder for future)
    # discord_channels = by_integration.get("discord", [])
    # ...

    return result


@router.get("/channels-enriched", response_model=ChannelListOut)
async def admin_channels_enriched(
    integration: Optional[str] = Query(None),
    bot_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    """List channels with integration-resolved display names."""
    stmt = select(Channel).order_by(Channel.updated_at.desc())
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
# Channel knowledge
# ---------------------------------------------------------------------------
@router.get("/channels/{channel_id}/knowledge")
async def get_channel_knowledge(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth),
):
    """Return knowledge entries scoped to this channel."""
    # Knowledge scoped to this channel via knowledge_access table
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
            "title": k.title,
            "content": k.content[:500] if k.content else None,
            "content_length": len(k.content) if k.content else 0,
            "bot_id": k.bot_id,
            "mode": mode,
            "created_at": k.created_at.isoformat() if k.created_at else None,
            "updated_at": k.updated_at.isoformat() if k.updated_at else None,
        }
        for k, mode in rows
    ]


# ---------------------------------------------------------------------------
# Bot editor data (bot + available options for tools/skills/etc)
# ---------------------------------------------------------------------------

class ToolGroupOut(BaseModel):
    integration: str
    is_core: bool
    packs: list[dict] = []
    total: int = 0


class SkillOptionOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None


class BotEditorDataOut(BaseModel):
    bot: BotOut
    tool_groups: list[ToolGroupOut] = []
    mcp_servers: list[str] = []
    client_tools: list[str] = []
    all_skills: list[SkillOptionOut] = []
    all_bots: list[dict] = []
    all_harnesses: list[str] = []
    all_sandbox_profiles: list[dict] = []


@router.get("/bots/{bot_id}/editor-data")
async def admin_bot_editor_data(
    bot_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    """Get bot config + all available options for the editor UI."""
    from app.agent.bots import list_bots as _list_bots
    from app.agent.persona import get_persona
    from app.services.harness import harness_service
    from app.tools.mcp import _servers
    from app.tools.client_tools import _client_tools

    try:
        bot = get_bot(bot_id)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Bot not found: {bot_id}")

    # Gather data in parallel
    import asyncio
    persona_content, all_skills_rows, tool_rows, sandbox_rows = await asyncio.gather(
        get_persona(bot_id),
        _fetch_all_skills(db),
        _fetch_tool_rows(db),
        _fetch_sandbox_profiles(db),
    )

    # Build tool groups
    tool_groups = _build_tool_groups(tool_rows)
    mcp_servers = sorted(_servers.keys())
    client_tools = sorted(_client_tools.keys())

    # Skills
    all_skills = [
        SkillOptionOut(
            id=s.id,
            name=s.name,
            description=(s.content or "")[:200].split("\n")[0] if s.content else None,
        )
        for s in all_skills_rows
    ]

    # Other bots (exclude self)
    all_bots_out = [
        {"id": b.id, "name": b.name}
        for b in _list_bots()
        if b.id != bot_id
    ]

    # Harnesses
    all_harnesses = harness_service.list_harnesses()

    # Sandbox profiles
    sandbox_profiles = [
        {"name": p.name, "description": getattr(p, "description", None)}
        for p in sandbox_rows
    ]

    return BotEditorDataOut(
        bot=_bot_to_out(bot, persona_content=persona_content),
        tool_groups=[ToolGroupOut(**g) for g in tool_groups],
        mcp_servers=mcp_servers,
        client_tools=client_tools,
        all_skills=all_skills,
        all_bots=all_bots_out,
        all_harnesses=all_harnesses,
        all_sandbox_profiles=sandbox_profiles,
    )


async def _fetch_all_skills(db: AsyncSession):
    return (await db.execute(select(SkillRow).order_by(SkillRow.name))).scalars().all()


async def _fetch_tool_rows(db: AsyncSession):
    return (await db.execute(
        select(
            ToolEmbedding.tool_name,
            ToolEmbedding.server_name,
            ToolEmbedding.source_integration,
            ToolEmbedding.source_file,
        ).order_by(ToolEmbedding.server_name.nullsfirst(), ToolEmbedding.tool_name)
    )).all()


async def _fetch_sandbox_profiles(db: AsyncSession):
    return (await db.execute(
        select(SandboxProfile)
        .where(SandboxProfile.enabled == True)  # noqa: E712
        .order_by(SandboxProfile.name)
    )).scalars().all()


def _build_tool_groups(tool_rows) -> list[dict]:
    from collections import defaultdict
    integration_packs: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in tool_rows:
        if r.server_name is not None:
            continue
        intg = r.source_integration or "core"
        pack = (r.source_file or "misc").replace(".py", "")
        integration_packs[intg][pack].append({"name": r.tool_name})

    ordered = (["core"] if "core" in integration_packs else []) + sorted(
        k for k in integration_packs if k != "core"
    )
    groups = []
    for intg_id in ordered:
        packs_dict = integration_packs[intg_id]
        groups.append({
            "integration": intg_id,
            "is_core": intg_id == "core",
            "packs": [
                {"pack": pn, "tools": sorted(packs_dict[pn], key=lambda t: t["name"])}
                for pn in sorted(packs_dict)
            ],
            "total": sum(len(v) for v in packs_dict.values()),
        })
    return groups


# ---------------------------------------------------------------------------
# Bot update (JSON PUT)
# ---------------------------------------------------------------------------

class BotUpdateIn(BaseModel):
    name: Optional[str] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    model_provider_id: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    local_tools: Optional[list[str]] = None
    mcp_servers: Optional[list[str]] = None
    client_tools: Optional[list[str]] = None
    pinned_tools: Optional[list[str]] = None
    skills: Optional[list[dict]] = None
    tool_retrieval: Optional[bool] = None
    tool_similarity_threshold: Optional[float] = None
    tool_result_config: Optional[dict] = None
    compression_config: Optional[dict] = None
    persona: Optional[bool] = None
    persona_content: Optional[str] = None
    context_compaction: Optional[bool] = None
    compaction_interval: Optional[int] = None
    compaction_keep_turns: Optional[int] = None
    compaction_model: Optional[str] = None
    audio_input: Optional[str] = None
    memory_config: Optional[dict] = None
    knowledge_config: Optional[dict] = None
    memory_max_inject_chars: Optional[int] = None
    knowledge_max_inject_chars: Optional[int] = None
    integration_config: Optional[dict] = None
    workspace: Optional[dict] = None
    docker_sandbox_profiles: Optional[list[str]] = None
    delegation_config: Optional[dict] = None
    elevation_enabled: Optional[bool] = None
    elevation_threshold: Optional[float] = None
    elevated_model: Optional[str] = None
    attachment_summarization_enabled: Optional[bool] = None
    attachment_summary_model: Optional[str] = None
    attachment_text_max_chars: Optional[int] = None
    attachment_vision_concurrency: Optional[int] = None


@router.put("/bots/{bot_id}", response_model=BotOut)
async def admin_bot_update(
    bot_id: str,
    data: BotUpdateIn = Body(...),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    """Update a bot's config via JSON."""
    from app.agent.bots import reload_bots
    from app.agent.persona import get_persona, write_persona

    row = await db.get(BotRow, bot_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Bot not found: {bot_id}")

    # Apply updates for each non-None field
    updates = data.model_dump(exclude_none=True)

    # Handle persona_content separately (stored in bot_persona table)
    persona_content_val = updates.pop("persona_content", None)

    # Handle memory_config → memory_config JSONB
    if "memory_config" in updates:
        row.memory_config = updates.pop("memory_config")
    if "knowledge_config" in updates:
        row.knowledge_config = updates.pop("knowledge_config")

    # Map skills list[dict] → skills JSONB
    if "skills" in updates:
        row.skills = updates.pop("skills")

    # Apply remaining scalar/JSONB fields
    for key, val in updates.items():
        if hasattr(row, key):
            setattr(row, key, val)

    row.updated_at = datetime.now(timezone.utc)
    await db.commit()

    # Write persona content if provided
    if persona_content_val is not None:
        await write_persona(bot_id, persona_content_val)

    # Reload bot registry
    await reload_bots()

    # Return updated bot
    bot = get_bot(bot_id)
    pc = await get_persona(bot_id)
    return _bot_to_out(bot, persona_content=pc)
