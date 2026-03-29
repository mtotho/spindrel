"""Public API v1 — Channel endpoints."""
import logging
import uuid
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Attachment, Channel, ChannelHeartbeat, ChannelIntegration, KnowledgeAccess, Message, Session, Task
from app.dependencies import ApiKeyAuth, get_db, require_scopes, verify_auth_or_user
from app.services.channels import (
    apply_channel_visibility, get_or_create_channel, ensure_active_session,
    reset_channel_session, switch_channel_session,
    bind_integration, unbind_integration, adopt_integration,
)
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
    private: bool = False


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
    client_id: Optional[str]
    integration: Optional[str]
    active_session_id: Optional[uuid.UUID]
    require_mention: bool
    passive_memory: bool
    private: bool = False
    user_id: Optional[uuid.UUID] = None
    model_override: Optional[str] = None
    model_provider_id_override: Optional[str] = None
    integrations: list[IntegrationBindingOut] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class IntegrationBindRequest(BaseModel):
    integration_type: str
    client_id: str
    dispatch_config: Optional[dict] = None
    display_name: Optional[str] = None


class IntegrationAdoptRequest(BaseModel):
    target_channel_id: uuid.UUID


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


class ChannelListItemOut(ChannelOut):
    """Extended channel item with optional heartbeat status."""
    heartbeat_enabled: Optional[bool] = None
    heartbeat_next_run_at: Optional[datetime] = None


class ChannelConfigOut(BaseModel):
    """Flat composite of channel settings + heartbeat config."""
    # Identity (read-only)
    id: uuid.UUID
    name: str
    bot_id: str
    client_id: Optional[str] = None
    integration: Optional[str] = None
    active_session_id: Optional[uuid.UUID] = None
    # Behavior
    require_mention: bool = True
    passive_memory: bool = True
    allow_bot_messages: bool = False
    workspace_rag: bool = True
    thinking_display: str = "append"
    max_iterations: Optional[int] = None
    task_max_run_seconds: Optional[int] = None
    channel_prompt: Optional[str] = None
    # Model
    model_override: Optional[str] = None
    model_provider_id_override: Optional[str] = None
    # Fallback models
    fallback_models: list[dict] = []
    # Compaction
    context_compaction: bool = True
    compaction_interval: Optional[int] = None
    compaction_keep_turns: Optional[int] = None
    compaction_prompt_template_id: Optional[uuid.UUID] = None
    memory_knowledge_compaction_prompt: Optional[str] = None
    history_mode: Optional[str] = None
    # Elevation
    elevation_enabled: Optional[bool] = None
    elevation_threshold: Optional[float] = None
    elevated_model: Optional[str] = None
    # Tool overrides
    local_tools_override: Optional[list[str]] = None
    local_tools_disabled: Optional[list[str]] = None
    mcp_servers_override: Optional[list[str]] = None
    mcp_servers_disabled: Optional[list[str]] = None
    client_tools_override: Optional[list[str]] = None
    client_tools_disabled: Optional[list[str]] = None
    pinned_tools_override: Optional[list[str]] = None
    skills_override: Optional[list[dict]] = None
    skills_disabled: Optional[list[str]] = None
    skills_extra: Optional[list[dict]] = None
    workspace_skills_enabled: Optional[bool] = None
    workspace_base_prompt_enabled: Optional[bool] = None
    channel_workspace_enabled: Optional[bool] = None
    index_segments: list[dict] = []
    # Heartbeat (prefixed)
    heartbeat_enabled: bool = False
    heartbeat_interval_minutes: int = 60
    heartbeat_model: str = ""
    heartbeat_model_provider_id: Optional[str] = None
    heartbeat_fallback_models: list[dict] = []
    heartbeat_prompt: str = ""
    heartbeat_prompt_template_id: Optional[uuid.UUID] = None
    heartbeat_dispatch_results: bool = True
    heartbeat_trigger_response: bool = False
    heartbeat_quiet_start: Optional[str] = None
    heartbeat_quiet_end: Optional[str] = None
    heartbeat_timezone: Optional[str] = None
    heartbeat_max_run_seconds: Optional[int] = None
    heartbeat_last_run_at: Optional[datetime] = None
    heartbeat_next_run_at: Optional[datetime] = None
    # Timestamps
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChannelConfigUpdate(BaseModel):
    """Writable channel + heartbeat fields. All optional, exclude_unset semantics."""
    # Behavior
    require_mention: Optional[bool] = None
    passive_memory: Optional[bool] = None
    allow_bot_messages: Optional[bool] = None
    workspace_rag: Optional[bool] = None
    thinking_display: Optional[str] = None
    max_iterations: Optional[int] = None
    task_max_run_seconds: Optional[int] = None
    channel_prompt: Optional[str] = None
    # Model
    model_override: Optional[str] = None
    model_provider_id_override: Optional[str] = None
    # Fallback models
    fallback_models: list[dict] = []
    # Compaction
    context_compaction: Optional[bool] = None
    compaction_interval: Optional[int] = None
    compaction_keep_turns: Optional[int] = None
    compaction_prompt_template_id: Optional[uuid.UUID] = None
    memory_knowledge_compaction_prompt: Optional[str] = None
    history_mode: Optional[str] = None
    # Elevation
    elevation_enabled: Optional[bool] = None
    elevation_threshold: Optional[float] = None
    elevated_model: Optional[str] = None
    # Tool overrides
    local_tools_override: Optional[list[str]] = None
    local_tools_disabled: Optional[list[str]] = None
    mcp_servers_override: Optional[list[str]] = None
    mcp_servers_disabled: Optional[list[str]] = None
    client_tools_override: Optional[list[str]] = None
    client_tools_disabled: Optional[list[str]] = None
    pinned_tools_override: Optional[list[str]] = None
    skills_override: Optional[list[dict]] = None
    skills_disabled: Optional[list[str]] = None
    skills_extra: Optional[list[dict]] = None
    workspace_skills_enabled: Optional[bool] = None
    workspace_base_prompt_enabled: Optional[bool] = None
    channel_workspace_enabled: Optional[bool] = None
    index_segments: Optional[list[dict]] = None
    # Heartbeat (prefixed)
    heartbeat_enabled: Optional[bool] = None
    heartbeat_interval_minutes: Optional[int] = None
    heartbeat_model: Optional[str] = None
    heartbeat_model_provider_id: Optional[str] = None
    heartbeat_fallback_models: Optional[list[dict]] = None
    heartbeat_prompt: Optional[str] = None
    heartbeat_prompt_template_id: Optional[uuid.UUID] = None
    heartbeat_dispatch_results: Optional[bool] = None
    heartbeat_trigger_response: Optional[bool] = None
    heartbeat_quiet_start: Optional[str] = None
    heartbeat_quiet_end: Optional[str] = None
    heartbeat_timezone: Optional[str] = None
    heartbeat_max_run_seconds: Optional[int] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=ChannelOut, status_code=201)
async def create_channel(
    body: ChannelCreate,
    db: AsyncSession = Depends(get_db),
    auth_result=Depends(require_scopes("channels:write")),
):
    """Create or retrieve a channel."""
    from app.agent.bots import get_bot
    from app.db.models import User
    try:
        get_bot(body.bot_id)
    except HTTPException:
        raise HTTPException(status_code=400, detail=f"Unknown bot: {body.bot_id}")

    user_id = auth_result.id if isinstance(auth_result, User) else None

    channel = await get_or_create_channel(
        db,
        client_id=body.client_id,
        bot_id=body.bot_id,
        name=body.name,
        integration=body.integration,
        dispatch_config=body.dispatch_config,
        private=body.private,
        user_id=user_id,
    )
    await ensure_active_session(db, channel)
    await db.commit()
    await db.refresh(channel, ["integrations"])
    return ChannelOut.model_validate(channel)


@router.get("", response_model=Union[list[ChannelListItemOut], list[ChannelOut]])
async def list_channels(
    integration: Optional[str] = None,
    bot_id: Optional[str] = None,
    include_heartbeat: bool = Query(False, description="Include heartbeat_enabled and heartbeat_next_run_at"),
    db: AsyncSession = Depends(get_db),
    auth_result=Depends(require_scopes("channels:read")),
):
    """List channels with optional filters."""
    stmt = select(Channel).options(selectinload(Channel.integrations)).order_by(Channel.created_at.desc())
    stmt = apply_channel_visibility(stmt, auth_result)
    if integration:
        stmt = stmt.where(Channel.integration == integration)
    if bot_id:
        stmt = stmt.where(Channel.bot_id == bot_id)
    channels = (await db.execute(stmt)).scalars().all()

    if not include_heartbeat:
        return [ChannelOut.model_validate(ch) for ch in channels]

    # Batch-load heartbeat rows
    channel_ids = [ch.id for ch in channels]
    hb_map: dict[uuid.UUID, ChannelHeartbeat] = {}
    if channel_ids:
        hb_rows = (await db.execute(
            select(ChannelHeartbeat).where(ChannelHeartbeat.channel_id.in_(channel_ids))
        )).scalars().all()
        hb_map = {hb.channel_id: hb for hb in hb_rows}

    result = []
    for ch in channels:
        item = ChannelListItemOut.model_validate(ch)
        hb = hb_map.get(ch.id)
        item.heartbeat_enabled = hb.enabled if hb else False
        item.heartbeat_next_run_at = hb.next_run_at if hb else None
        result.append(item)
    return result


@router.get("/{channel_id}", response_model=ChannelOut)
async def get_channel(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels:read")),
):
    """Get channel info."""
    result = await db.execute(
        select(Channel).options(selectinload(Channel.integrations)).where(Channel.id == channel_id)
    )
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return ChannelOut.model_validate(channel)


@router.get("/{channel_id}/config", response_model=ChannelConfigOut)
async def get_channel_config(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels.config:read")),
):
    """Get all channel settings + heartbeat config in a single flat response."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    heartbeat = (await db.execute(
        select(ChannelHeartbeat).where(ChannelHeartbeat.channel_id == channel_id)
    )).scalar_one_or_none()

    return _build_config_out(channel, heartbeat)


@router.api_route("/{channel_id}/config", methods=["PUT", "PATCH"], response_model=ChannelConfigOut)
async def update_channel_config(
    channel_id: uuid.UUID,
    body: ChannelConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Update any subset of channel settings + heartbeat config in one call.

    Scope requirements depend on which fields are set:
    - Heartbeat fields only → ``channels.heartbeat:write``
    - Non-heartbeat fields (or both) → ``channels.config:write``
    ``channels.config:write`` always covers heartbeat as a parent scope.
    """
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    updates = body.model_dump(exclude_unset=True)
    now = datetime.now(timezone.utc)

    # Split into channel fields vs heartbeat fields
    hb_updates: dict = {}
    ch_updates: dict = {}
    for key, value in updates.items():
        if key.startswith("heartbeat_"):
            hb_updates[key.removeprefix("heartbeat_")] = value
        else:
            ch_updates[key] = value

    # Enforce scopes based on which fields are being modified
    if isinstance(_auth, ApiKeyAuth):
        from app.services.api_keys import has_scope
        if ch_updates:
            if not has_scope(_auth.scopes, "channels.config:write"):
                raise HTTPException(status_code=403, detail="Missing required scope: channels.config:write")
        if hb_updates:
            if not has_scope(_auth.scopes, "channels.heartbeat:write"):
                raise HTTPException(status_code=403, detail="Missing required scope: channels.heartbeat:write")

    # Apply channel updates
    if ch_updates:
        for field, value in ch_updates.items():
            setattr(channel, field, value)
        channel.updated_at = now

    # Apply heartbeat updates
    heartbeat: ChannelHeartbeat | None = None
    if hb_updates:
        heartbeat = (await db.execute(
            select(ChannelHeartbeat).where(ChannelHeartbeat.channel_id == channel_id)
        )).scalar_one_or_none()

        if heartbeat is None:
            heartbeat = ChannelHeartbeat(channel_id=channel_id, enabled=False)
            db.add(heartbeat)

        for field, value in hb_updates.items():
            if field == "interval_minutes" and value is not None:
                value = max(1, value)
            elif field == "model":
                # model is nullable=False; coerce None → ""
                value = value.strip() if value else ""
            elif field == "model_provider_id" and value is not None:
                value = value.strip() or None
            elif field == "prompt":
                # prompt is nullable=False; coerce None → ""
                value = value.strip() if value else ""
            elif field == "quiet_start":
                value = dt_time.fromisoformat(value) if value else None
            elif field == "quiet_end":
                value = dt_time.fromisoformat(value) if value else None
            setattr(heartbeat, field, value)

        heartbeat.updated_at = now

        # Auto-schedule / clear next_run_at
        if heartbeat.enabled and heartbeat.next_run_at is None:
            from app.services.heartbeat import next_aligned_time
            heartbeat.next_run_at = next_aligned_time(now, heartbeat.interval_minutes)
        elif not heartbeat.enabled:
            heartbeat.next_run_at = None

    await db.commit()
    await db.refresh(channel)

    if heartbeat is None:
        heartbeat = (await db.execute(
            select(ChannelHeartbeat).where(ChannelHeartbeat.channel_id == channel_id)
        )).scalar_one_or_none()
    elif hb_updates:
        await db.refresh(heartbeat)

    return _build_config_out(channel, heartbeat)


def _build_config_out(channel: Channel, heartbeat: ChannelHeartbeat | None) -> ChannelConfigOut:
    """Build flat ChannelConfigOut from channel + optional heartbeat."""
    data = {
        "id": channel.id,
        "name": channel.name,
        "bot_id": channel.bot_id,
        "client_id": channel.client_id,
        "integration": channel.integration,
        "active_session_id": channel.active_session_id,
        "require_mention": channel.require_mention,
        "passive_memory": channel.passive_memory,
        "allow_bot_messages": channel.allow_bot_messages,
        "workspace_rag": channel.workspace_rag,
        "thinking_display": channel.thinking_display,
        "max_iterations": channel.max_iterations,
        "task_max_run_seconds": channel.task_max_run_seconds,
        "channel_prompt": channel.channel_prompt,
        "model_override": channel.model_override,
        "model_provider_id_override": channel.model_provider_id_override,
        "fallback_models": channel.fallback_models or [],
        "context_compaction": channel.context_compaction,
        "compaction_interval": channel.compaction_interval,
        "compaction_keep_turns": channel.compaction_keep_turns,
        "compaction_prompt_template_id": channel.compaction_prompt_template_id,
        "memory_knowledge_compaction_prompt": channel.memory_knowledge_compaction_prompt,
        "history_mode": channel.history_mode,
        "elevation_enabled": channel.elevation_enabled,
        "elevation_threshold": channel.elevation_threshold,
        "elevated_model": channel.elevated_model,
        "local_tools_override": channel.local_tools_override,
        "local_tools_disabled": channel.local_tools_disabled,
        "mcp_servers_override": channel.mcp_servers_override,
        "mcp_servers_disabled": channel.mcp_servers_disabled,
        "client_tools_override": channel.client_tools_override,
        "client_tools_disabled": channel.client_tools_disabled,
        "pinned_tools_override": channel.pinned_tools_override,
        "skills_override": channel.skills_override,
        "skills_disabled": channel.skills_disabled,
        "skills_extra": channel.skills_extra,
        "workspace_skills_enabled": channel.workspace_skills_enabled,
        "workspace_base_prompt_enabled": channel.workspace_base_prompt_enabled,
        "channel_workspace_enabled": channel.channel_workspace_enabled,
        "index_segments": channel.index_segments or [],
        "created_at": channel.created_at,
        "updated_at": channel.updated_at,
    }

    if heartbeat:
        data.update({
            "heartbeat_enabled": heartbeat.enabled,
            "heartbeat_interval_minutes": heartbeat.interval_minutes,
            "heartbeat_model": heartbeat.model,
            "heartbeat_model_provider_id": heartbeat.model_provider_id,
            "heartbeat_fallback_models": heartbeat.fallback_models or [],
            "heartbeat_prompt": heartbeat.prompt,
            "heartbeat_prompt_template_id": heartbeat.prompt_template_id,
            "heartbeat_dispatch_results": heartbeat.dispatch_results,
            "heartbeat_trigger_response": heartbeat.trigger_response,
            "heartbeat_quiet_start": heartbeat.quiet_start.strftime("%H:%M") if heartbeat.quiet_start else None,
            "heartbeat_quiet_end": heartbeat.quiet_end.strftime("%H:%M") if heartbeat.quiet_end else None,
            "heartbeat_timezone": heartbeat.timezone,
            "heartbeat_max_run_seconds": heartbeat.max_run_seconds,
            "heartbeat_last_run_at": heartbeat.last_run_at,
            "heartbeat_next_run_at": heartbeat.next_run_at,
        })

    return ChannelConfigOut(**data)


@router.delete("/{channel_id}", status_code=204)
async def delete_channel(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels:write")),
):
    """Delete a channel and all associated data (integrations, heartbeat cascade; sessions/tasks/etc set null)."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    await db.delete(channel)
    await db.commit()


@router.put("/{channel_id}", response_model=ChannelOut)
async def update_channel(
    channel_id: uuid.UUID,
    body: ChannelUpdate,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels:write")),
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
    await db.refresh(channel, ["integrations"])
    return ChannelOut.model_validate(channel)


@router.post("/{channel_id}/messages", response_model=InjectResponse, status_code=201)
async def inject_channel_message(
    channel_id: uuid.UUID,
    body: MessageInject,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels.messages:write")),
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
        from app.config import settings as _settings
        if _settings.SYSTEM_PAUSED and _settings.SYSTEM_PAUSE_BEHAVIOR == "drop":
            raise HTTPException(status_code=503, detail="System is paused. Messages are being dropped.")

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
    _auth=Depends(require_scopes("channels.messages:write")),
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
    _auth=Depends(require_scopes("channels.messages:write")),
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
    _auth=Depends(require_scopes("channels:read")),
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
    _auth=Depends(require_scopes("channels.messages:read")),
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
    _auth=Depends(require_scopes("channels:read")),
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


# ---------------------------------------------------------------------------
# Integration bindings
# ---------------------------------------------------------------------------

@router.get("/{channel_id}/integrations", response_model=list[IntegrationBindingOut])
async def list_channel_integrations(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels.integrations:read")),
):
    """List integration bindings for a channel."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    bindings = (await db.execute(
        select(ChannelIntegration)
        .where(ChannelIntegration.channel_id == channel_id)
        .order_by(ChannelIntegration.created_at)
    )).scalars().all()
    return [IntegrationBindingOut.model_validate(b) for b in bindings]


@router.post("/{channel_id}/integrations", response_model=IntegrationBindingOut, status_code=201)
async def bind_channel_integration(
    channel_id: uuid.UUID,
    body: IntegrationBindRequest,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels.integrations:write")),
):
    """Bind an integration to a channel."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # Check for duplicate client_id
    existing = (await db.execute(
        select(ChannelIntegration).where(ChannelIntegration.client_id == body.client_id)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"client_id '{body.client_id}' is already bound to channel {existing.channel_id}",
        )

    binding = await bind_integration(
        db,
        channel_id=channel_id,
        integration_type=body.integration_type,
        client_id=body.client_id,
        dispatch_config=body.dispatch_config,
        display_name=body.display_name,
    )
    await db.commit()
    await db.refresh(binding)
    return IntegrationBindingOut.model_validate(binding)


@router.delete("/{channel_id}/integrations/{binding_id}", status_code=204)
async def unbind_channel_integration(
    channel_id: uuid.UUID,
    binding_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels.integrations:write")),
):
    """Remove an integration binding from a channel."""
    binding = await db.get(ChannelIntegration, binding_id)
    if not binding or binding.channel_id != channel_id:
        raise HTTPException(status_code=404, detail="Binding not found")

    await unbind_integration(db, binding_id)
    await db.commit()


@router.post("/{channel_id}/integrations/{binding_id}/adopt", response_model=IntegrationBindingOut)
async def adopt_channel_integration(
    channel_id: uuid.UUID,
    binding_id: uuid.UUID,
    body: IntegrationAdoptRequest,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels.integrations:write")),
):
    """Move an integration binding to another channel."""
    binding = await db.get(ChannelIntegration, binding_id)
    if not binding or binding.channel_id != channel_id:
        raise HTTPException(status_code=404, detail="Binding not found")

    try:
        binding = await adopt_integration(db, binding_id, body.target_channel_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await db.commit()
    await db.refresh(binding)
    return IntegrationBindingOut.model_validate(binding)
