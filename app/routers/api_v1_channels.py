"""Public API v1 — Channel endpoints."""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Attachment, Channel, KnowledgeAccess, Message, Session, Task
from app.dependencies import get_db, verify_auth_or_user
from app.services.channels import apply_channel_visibility, get_or_create_channel, ensure_active_session, reset_channel_session, switch_channel_session
from app.services.sessions import store_passive_message
from app.tools.local.search_history import _build_query, _serialize_messages

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/channels", tags=["Channels"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ChannelCreate(BaseModel):
    client_id: Optional[str] = None
    bot_id: str = "default"
    name: Optional[str] = None
    integration: Optional[str] = None
    dispatch_config: Optional[dict] = None


class ChannelOut(BaseModel):
    id: uuid.UUID
    name: str
    bot_id: str
    client_id: Optional[str]
    integration: Optional[str]
    active_session_id: Optional[uuid.UUID]
    require_mention: bool
    passive_memory: bool
    private: bool = False
    user_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChannelUpdate(BaseModel):
    name: Optional[str] = None
    bot_id: Optional[str] = None
    require_mention: Optional[bool] = None
    passive_memory: Optional[bool] = None
    attachment_retention_days: Optional[int] = None
    attachment_max_size_bytes: Optional[int] = None
    attachment_types_allowed: Optional[list[str]] = None


class MessageInject(BaseModel):
    content: str
    role: str = "user"
    source: Optional[str] = None
    run_agent: bool = False


class InjectResponse(BaseModel):
    message_id: uuid.UUID
    session_id: uuid.UUID
    task_id: Optional[uuid.UUID] = None


class ResetResponse(BaseModel):
    channel_id: uuid.UUID
    new_session_id: uuid.UUID
    previous_session_id: Optional[uuid.UUID]


class KnowledgeAccessOut(BaseModel):
    id: uuid.UUID
    knowledge_id: uuid.UUID
    knowledge_name: Optional[str] = None
    scope_type: str
    scope_key: Optional[str]
    mode: str

    model_config = {"from_attributes": True}


class HistoryMessageOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content_preview: str
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=ChannelOut, status_code=201)
async def create_channel(
    body: ChannelCreate,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Create or retrieve a channel."""
    from app.agent.bots import get_bot
    try:
        get_bot(body.bot_id)
    except HTTPException:
        raise HTTPException(status_code=400, detail=f"Unknown bot: {body.bot_id}")

    channel = await get_or_create_channel(
        db,
        client_id=body.client_id,
        bot_id=body.bot_id,
        name=body.name,
        integration=body.integration,
        dispatch_config=body.dispatch_config,
    )
    await ensure_active_session(db, channel)
    await db.commit()
    return ChannelOut.from_orm(channel)


@router.get("", response_model=list[ChannelOut])
async def list_channels(
    integration: Optional[str] = None,
    bot_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    auth_result=Depends(verify_auth_or_user),
):
    """List channels with optional filters."""
    stmt = select(Channel).order_by(Channel.created_at.desc())
    stmt = apply_channel_visibility(stmt, auth_result)
    if integration:
        stmt = stmt.where(Channel.integration == integration)
    if bot_id:
        stmt = stmt.where(Channel.bot_id == bot_id)
    channels = (await db.execute(stmt)).scalars().all()
    return [ChannelOut.from_orm(ch) for ch in channels]


@router.get("/{channel_id}", response_model=ChannelOut)
async def get_channel(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Get channel info."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return ChannelOut.from_orm(channel)


@router.put("/{channel_id}", response_model=ChannelOut)
async def update_channel(
    channel_id: uuid.UUID,
    body: ChannelUpdate,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Update channel settings."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    if body.name is not None:
        channel.name = body.name
    if body.bot_id is not None:
        from app.agent.bots import get_bot
        try:
            get_bot(body.bot_id)
        except HTTPException:
            raise HTTPException(status_code=400, detail=f"Unknown bot: {body.bot_id}")
        channel.bot_id = body.bot_id
    if body.require_mention is not None:
        channel.require_mention = body.require_mention
    if body.passive_memory is not None:
        channel.passive_memory = body.passive_memory
    if body.attachment_retention_days is not None:
        channel.attachment_retention_days = body.attachment_retention_days
    if body.attachment_max_size_bytes is not None:
        channel.attachment_max_size_bytes = body.attachment_max_size_bytes
    if body.attachment_types_allowed is not None:
        channel.attachment_types_allowed = body.attachment_types_allowed

    channel.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(channel)
    return ChannelOut.from_orm(channel)


@router.post("/{channel_id}/messages", response_model=InjectResponse, status_code=201)
async def inject_channel_message(
    channel_id: uuid.UUID,
    body: MessageInject,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Inject a message into a channel's active session."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    session_id = await ensure_active_session(db, channel)
    await db.commit()

    metadata = {"source": body.source} if body.source else {}
    await store_passive_message(db, session_id, body.content, metadata)

    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    msg = result.scalar_one()
    await db.commit()

    task_id: uuid.UUID | None = None
    if body.run_agent:
        task = Task(
            bot_id=channel.bot_id,
            client_id=channel.client_id,
            session_id=session_id,
            channel_id=channel_id,
            prompt=body.content,
            status="pending",
            task_type="api",
            dispatch_type=channel.integration or "none",
            dispatch_config=channel.dispatch_config or {},
            created_at=datetime.now(timezone.utc),
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        task_id = task.id

    return InjectResponse(message_id=msg.id, session_id=session_id, task_id=task_id)


@router.post("/{channel_id}/reset", response_model=ResetResponse)
async def reset_channel(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Reset a channel's session. Old session preserved, new one becomes active."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    previous = channel.active_session_id
    new_session_id = await reset_channel_session(db, channel)

    return ResetResponse(
        channel_id=channel_id,
        new_session_id=new_session_id,
        previous_session_id=previous,
    )


class SwitchSessionRequest(BaseModel):
    session_id: uuid.UUID


@router.post("/{channel_id}/switch-session", response_model=ResetResponse)
async def switch_session(
    channel_id: uuid.UUID,
    body: SwitchSessionRequest,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Switch a channel's active session to an existing session."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    previous = channel.active_session_id
    try:
        await switch_channel_session(db, channel, body.session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ResetResponse(
        channel_id=channel_id,
        new_session_id=body.session_id,
        previous_session_id=previous,
    )


@router.get("/{channel_id}/knowledge", response_model=list[KnowledgeAccessOut])
async def list_channel_knowledge(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """List knowledge entries accessible to this channel."""
    from app.db.models import BotKnowledge
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    entries = (await db.execute(
        select(KnowledgeAccess)
        .join(BotKnowledge, KnowledgeAccess.knowledge_id == BotKnowledge.id)
        .where(
            KnowledgeAccess.scope_type == "channel",
            KnowledgeAccess.scope_key == str(channel_id),
        )
        .order_by(BotKnowledge.name)
    )).scalars().all()

    result = []
    for e in entries:
        bk = await db.get(BotKnowledge, e.knowledge_id)
        result.append(KnowledgeAccessOut(
            id=e.id,
            knowledge_id=e.knowledge_id,
            knowledge_name=bk.name if bk else None,
            scope_type=e.scope_type,
            scope_key=e.scope_key,
            mode=e.mode,
        ))
    return result


@router.get("/{channel_id}/messages/search", response_model=list[HistoryMessageOut])
async def search_channel_messages(
    channel_id: uuid.UUID,
    q: Optional[str] = Query(None, description="Keyword to search for"),
    start_date: Optional[str] = Query(None, description="ISO 8601 start date"),
    end_date: Optional[str] = Query(None, description="ISO 8601 end date"),
    role: str = Query("all", description="Filter by role: user, assistant, all"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Search messages across all sessions in a channel."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    stmt = _build_query(
        channel_id=channel_id,
        bot_id=channel.bot_id,
        query=q,
        start_date=start_date,
        end_date=end_date,
        role=role,
        limit=limit,
        offset=offset,
    )

    messages = (await db.execute(stmt)).scalars().all()
    return [HistoryMessageOut(**m) for m in _serialize_messages(messages)]


class AttachmentStatsOut(BaseModel):
    channel_id: uuid.UUID
    total_count: int
    with_file_data_count: int
    total_size_bytes: int
    oldest_created_at: Optional[datetime] = None
    effective_config: dict

    model_config = {"from_attributes": True}


@router.get("/{channel_id}/attachment-stats", response_model=AttachmentStatsOut)
async def get_attachment_stats(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Get attachment storage stats and effective retention config for a channel."""
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

    from app.services.attachment_retention import get_effective_retention
    effective = get_effective_retention(channel)

    return AttachmentStatsOut(
        channel_id=channel_id,
        total_count=row.total_count,
        with_file_data_count=row.with_file_data_count,
        total_size_bytes=row.total_size_bytes,
        oldest_created_at=row.oldest_created_at,
        effective_config=effective,
    )
