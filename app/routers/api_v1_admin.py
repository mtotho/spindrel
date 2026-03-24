"""Admin JSON API — /api/v1/admin/

Provides read-only admin endpoints that mirror the Jinja2/HTMX admin
dashboard, returning structured JSON for the Expo mobile client.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import get_bot, list_bots
from app.db.models import (
    BotKnowledge,
    Channel,
    Memory,
    Message,
    SandboxInstance,
    Session,
    Task,
    ToolCall,
    ToolEmbedding,
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
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    local_tools: list[str] = []
    mcp_servers: list[str] = []
    client_tools: list[str] = []
    pinned_tools: list[str] = []
    skills: list[SkillConfigOut] = []
    tool_retrieval: bool = True
    tool_similarity_threshold: Optional[float] = None
    persona: bool = False
    context_compaction: bool = True
    compaction_interval: Optional[int] = None
    compaction_keep_turns: Optional[int] = None
    audio_input: str = "transcribe"
    memory: MemoryConfigOut = MemoryConfigOut()
    knowledge: KnowledgeConfigOut = KnowledgeConfigOut()
    delegate_bots: list[str] = []
    harness_access: list[str] = []
    model_provider_id: Optional[str] = None

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
# Helpers
# ---------------------------------------------------------------------------

def _bot_to_out(bot) -> BotOut:
    """Convert a BotConfig dataclass to a BotOut Pydantic model."""
    return BotOut(
        id=bot.id,
        name=bot.name,
        model=bot.model,
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
        persona=bot.persona,
        context_compaction=bot.context_compaction,
        compaction_interval=bot.compaction_interval,
        compaction_keep_turns=bot.compaction_keep_turns,
        audio_input=bot.audio_input,
        memory=MemoryConfigOut(
            enabled=bot.memory.enabled,
            cross_channel=bot.memory.cross_channel,
            cross_client=bot.memory.cross_client,
            cross_bot=bot.memory.cross_bot,
        ),
        knowledge=KnowledgeConfigOut(enabled=bot.knowledge.enabled),
        delegate_bots=bot.delegate_bots,
        harness_access=bot.harness_access,
        model_provider_id=bot.model_provider_id,
    )


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
    try:
        bot = get_bot(bot_id)
    except HTTPException:
        raise HTTPException(status_code=404, detail=f"Bot not found: {bot_id}")
    return _bot_to_out(bot)


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
