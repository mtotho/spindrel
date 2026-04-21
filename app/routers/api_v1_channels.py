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

from app.db.models import (
    Attachment, Channel, ChannelBotMember, ChannelHeartbeat, ChannelIntegration,
    Message, Session, Skill, Task, ToolApproval, ToolCall, TraceEvent,
)
from app.dependencies import (
    ApiKeyAuth,
    assert_admin_or_channel_owner,
    get_db,
    require_admin_and_scope,
    require_scopes,
    verify_auth_or_user,
)
from app.services.channels import (
    apply_channel_visibility, get_or_create_channel, ensure_active_session,
    reset_channel_session, switch_channel_session,
    bind_integration, unbind_integration, adopt_integration,
)
from app.services import session_locks
from app.services.sessions import store_passive_message
from app.tools.local.search_history import _build_query, _serialize_messages

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/channels", tags=["Channels"])


def _check_protected(channel: Channel, auth) -> None:
    """Raise 403 if the channel is protected and auth is a non-admin API key."""
    if not channel.protected:
        return
    if isinstance(auth, ApiKeyAuth) and "admin" not in auth.scopes:
        raise HTTPException(
            status_code=403,
            detail="Protected channel — admin scope required",
        )


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
    # Admin-only: assign a specific owner. Non-admin callers always become the
    # owner regardless of this field (enforced below).
    user_id: Optional[str] = None
    # Wizard fields (all optional for backwards compatibility)
    workspace_schema_template_id: Optional[str] = None  # UUID string
    category: Optional[str] = None
    model_override: Optional[str] = None
    activate_integrations: Optional[list[str]] = None
    member_bot_ids: Optional[list[str]] = None


class ChannelBotMemberOut(BaseModel):
    id: uuid.UUID
    channel_id: uuid.UUID
    bot_id: str
    bot_name: Optional[str] = None
    config: dict = {}
    created_at: datetime

    model_config = {"from_attributes": True}


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
    protected: bool = False
    user_id: Optional[uuid.UUID] = None
    model_override: Optional[str] = None
    model_provider_id_override: Optional[str] = None
    integrations: list[IntegrationBindingOut] = []
    member_bots: list[ChannelBotMemberOut] = []
    workspace_id: Optional[uuid.UUID] = None
    resolved_workspace_id: Optional[str] = None
    config: dict = {}
    category: Optional[str] = None
    tags: list[str] = []
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
    protected: bool = False
    # Behavior
    require_mention: bool = True
    passive_memory: bool = True
    allow_bot_messages: bool = False
    workspace_rag: bool = True
    thinking_display: str = "append"
    tool_output_display: str = "compact"
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
    # Tool restrictions
    local_tools_disabled: Optional[list[str]] = None
    mcp_servers_disabled: Optional[list[str]] = None
    client_tools_disabled: Optional[list[str]] = None
    workspace_base_prompt_enabled: Optional[bool] = None
    workspace_schema_template_id: Optional[uuid.UUID] = None
    workspace_schema_content: Optional[str] = None
    index_segments: list[dict] = []
    # Carapace overrides
    carapaces_extra: Optional[list[str]] = None
    carapaces_disabled: Optional[list[str]] = None
    # Model tier overrides
    model_tier_overrides: dict = {}
    # Chat-screen layout mode. Controls which dashboard zones render on the
    # chat screen (rail / header chips / right dock). Persisted in
    # ``Channel.config["layout_mode"]``.
    #   ``full``             — every zone renders (default)
    #   ``rail-header-chat`` — rail + header chips; dock hidden
    #   ``rail-chat``        — rail only; header chips + dock hidden
    #   ``dashboard-only``   — chat screen replaced by a card that points
    #                          users at ``/widgets/channel/:id``
    layout_mode: str = "full"
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
    heartbeat_skip_tool_approval: bool = False
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
    tool_output_display: Optional[str] = None
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
    # Tool restrictions
    local_tools_disabled: Optional[list[str]] = None
    mcp_servers_disabled: Optional[list[str]] = None
    client_tools_disabled: Optional[list[str]] = None
    workspace_base_prompt_enabled: Optional[bool] = None
    workspace_schema_template_id: Optional[uuid.UUID] = None
    workspace_schema_content: Optional[str] = None
    index_segments: Optional[list[dict]] = None
    # Carapace overrides
    carapaces_extra: Optional[list[str]] = None
    carapaces_disabled: Optional[list[str]] = None
    # Model tier overrides
    model_tier_overrides: Optional[dict] = None
    # Chat-screen layout mode (see ChannelConfigOut.layout_mode for semantics).
    # Accepted values: ``full | rail-header-chat | rail-chat | dashboard-only``.
    layout_mode: Optional[str] = None
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
    heartbeat_skip_tool_approval: Optional[bool] = None


def _enrich_bot_members(channel: Channel) -> list[ChannelBotMemberOut]:
    """Enrich bot member rows with bot names from the registry."""
    from app.agent.bots import get_bot as _get_bot
    result = []
    for bm in (channel.bot_members or []):
        out = ChannelBotMemberOut.model_validate(bm)
        try:
            out.bot_name = _get_bot(bm.bot_id).name
        except Exception:
            out.bot_name = bm.bot_id
        result.append(out)
    return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=ChannelOut, status_code=201)
async def create_channel(
    body: ChannelCreate,
    db: AsyncSession = Depends(get_db),
    auth_result=Depends(require_scopes("channels:write")),
):
    """Create or retrieve a channel.

    Supports optional wizard fields for one-call channel setup:
    model_override, workspace_schema_template_id, category, activate_integrations.
    """
    from app.agent.bots import ensure_default_bot, get_bot
    from app.db.models import PromptTemplate, User

    # Self-heal: if the default bot was deleted or never seeded, re-create it
    if body.bot_id == "default":
        await ensure_default_bot()

    try:
        get_bot(body.bot_id)
    except HTTPException:
        raise HTTPException(status_code=400, detail=f"Unknown bot: {body.bot_id}")

    # Non-admins always own what they create. Admins may reassign by passing
    # body.user_id. Matches the Phase 3/4 invariant: scope governs API surface;
    # ownership governs row access.
    auth_user = auth_result if isinstance(auth_result, User) else None
    if auth_user and not auth_user.is_admin:
        user_id = auth_user.id
    elif body.user_id:
        try:
            user_id = uuid.UUID(body.user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid user_id")
    elif auth_user:
        user_id = auth_user.id
    else:
        user_id = None

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

    # --- Wizard post-creation setup ---
    if body.model_override is not None:
        channel.model_override = body.model_override

    # Workspace is on by every channel — provision the dir up-front so
    # downstream features (file browser, MC, HTML widgets) just work.
    try:
        bot = get_bot(channel.bot_id)
        from app.services.channel_workspace import ensure_channel_workspace
        ensure_channel_workspace(str(channel.id), bot, display_name=channel.name)
    except Exception:
        pass  # non-fatal

    if body.workspace_schema_template_id is not None:
        try:
            tpl_uuid = uuid.UUID(body.workspace_schema_template_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid workspace_schema_template_id")
        tpl = await db.get(PromptTemplate, tpl_uuid)
        if not tpl:
            raise HTTPException(status_code=400, detail="Template not found")
        channel.workspace_schema_template_id = tpl_uuid

    if body.category is not None:
        cat = body.category.strip() if body.category else ""
        meta = dict(channel.metadata_ or {})
        if cat:
            meta["category"] = cat
        else:
            meta.pop("category", None)
        channel.metadata_ = meta

    # Activation warnings (collected but don't fail creation)
    activation_warnings: list[dict] = []
    if body.activate_integrations:
        from integrations import get_activation_manifests
        manifests = get_activation_manifests()
        for int_type in body.activate_integrations:
            manifest = manifests.get(int_type)
            if not manifest:
                activation_warnings.append({"code": "unknown_integration", "message": f"No activation manifest for '{int_type}'"})
                continue
            # Check if already activated
            existing = (await db.execute(
                select(ChannelIntegration).where(
                    ChannelIntegration.channel_id == channel.id,
                    ChannelIntegration.integration_type == int_type,
                    ChannelIntegration.activated == True,  # noqa: E712
                )
            )).scalar_one_or_none()
            if existing:
                continue
            # Resolve proper client_id from binding config if available
            act_client_id = f"mc-activated:{int_type}:{channel.id}"
            try:
                act_client_id = _resolve_activation_client_id(int_type, channel.id)
            except Exception:
                pass

            # Re-activate existing deactivated row if present
            inactive = (await db.execute(
                select(ChannelIntegration).where(
                    ChannelIntegration.channel_id == channel.id,
                    ChannelIntegration.integration_type == int_type,
                    ChannelIntegration.activated == False,  # noqa: E712
                )
            )).scalar_one_or_none()
            if inactive:
                inactive.activated = True
                inactive.client_id = act_client_id
                db.add(inactive)
            else:
                ci = ChannelIntegration(
                    channel_id=channel.id,
                    integration_type=int_type,
                    client_id=act_client_id,
                    activated=True,
                )
                db.add(ci)


    # Add member bots if specified
    if body.member_bot_ids:
        for mbid in body.member_bot_ids:
            if mbid == body.bot_id:
                continue  # skip primary bot
            try:
                get_bot(mbid)
            except HTTPException:
                continue  # skip unknown bots silently
            bm = ChannelBotMember(channel_id=channel.id, bot_id=mbid)
            db.add(bm)

    await db.commit()
    await db.refresh(channel, ["integrations", "bot_members"])
    out = ChannelOut.model_validate(channel)
    out.category = (channel.metadata_ or {}).get("category")
    out.tags = (channel.metadata_ or {}).get("tags", [])
    out.member_bots = _enrich_bot_members(channel)
    return out


@router.get("", response_model=Union[list[ChannelListItemOut], list[ChannelOut]])
async def list_channels(
    integration: Optional[str] = None,
    bot_id: Optional[str] = None,
    include_heartbeat: bool = Query(False, description="Include heartbeat_enabled and heartbeat_next_run_at"),
    db: AsyncSession = Depends(get_db),
    auth_result=Depends(require_scopes("channels:read")),
):
    """List channels with optional filters."""
    stmt = select(Channel).options(selectinload(Channel.integrations), selectinload(Channel.bot_members)).order_by(Channel.created_at.desc())
    stmt = apply_channel_visibility(stmt, auth_result)
    if integration:
        stmt = stmt.where(Channel.integration == integration)
    if bot_id:
        from app.services.channels import bot_channel_filter
        stmt = stmt.where(bot_channel_filter(bot_id))
    channels = (await db.execute(stmt)).scalars().all()

    def _enrich(ch: Channel) -> ChannelOut:
        out = ChannelOut.model_validate(ch)
        ws_id_str = str(ch.workspace_id) if ch.workspace_id else None
        try:
            from app.agent.bots import get_bot
            bot = get_bot(ch.bot_id)
            out.resolved_workspace_id = ws_id_str or bot.shared_workspace_id
        except Exception:
            out.resolved_workspace_id = ws_id_str
        out.category = (ch.metadata_ or {}).get("category")
        out.tags = (ch.metadata_ or {}).get("tags", [])
        out.member_bots = _enrich_bot_members(ch)
        return out

    if not include_heartbeat:
        return [_enrich(ch) for ch in channels]

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
        ws_id_str = str(ch.workspace_id) if ch.workspace_id else None
        try:
            from app.agent.bots import get_bot as _get_bot
            _b = _get_bot(ch.bot_id)
            item.resolved_workspace_id = ws_id_str or _b.shared_workspace_id
        except Exception:
            item.resolved_workspace_id = ws_id_str
        item.category = (ch.metadata_ or {}).get("category")
        item.tags = (ch.metadata_ or {}).get("tags", [])
        hb = hb_map.get(ch.id)
        item.heartbeat_enabled = hb.enabled if hb else False
        item.heartbeat_next_run_at = hb.next_run_at if hb else None
        result.append(item)
    return result


@router.get("/{channel_id}", response_model=ChannelOut)
async def get_channel(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_scopes("channels:read")),
):
    """Get channel info."""
    stmt = select(Channel).options(
        selectinload(Channel.integrations), selectinload(Channel.bot_members),
    ).where(Channel.id == channel_id)
    stmt = apply_channel_visibility(stmt, auth)
    channel = (await db.execute(stmt)).scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    out = ChannelOut.model_validate(channel)
    ws_id_str = str(channel.workspace_id) if channel.workspace_id else None
    try:
        from app.agent.bots import get_bot
        bot = get_bot(channel.bot_id)
        out.resolved_workspace_id = ws_id_str or bot.shared_workspace_id
    except Exception:
        out.resolved_workspace_id = ws_id_str
        logger.debug("Could not resolve workspace_id for channel %s bot %s", channel.id, channel.bot_id)
    out.category = (channel.metadata_ or {}).get("category")
    out.tags = (channel.metadata_ or {}).get("tags", [])
    out.member_bots = _enrich_bot_members(channel)
    return out


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
    _auth=Depends(require_scopes("channels:write")),
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
    assert_admin_or_channel_owner(channel, _auth)

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

    # Validate model tier override names
    if ch_updates.get("model_tier_overrides"):
        from app.services.server_config import VALID_TIER_NAMES
        invalid = set(ch_updates["model_tier_overrides"].keys()) - VALID_TIER_NAMES
        if invalid:
            raise HTTPException(status_code=422, detail=f"Invalid tier names: {sorted(invalid)}. Valid: {sorted(VALID_TIER_NAMES)}")

    # Validate layout_mode against the known set. Unknown values would quietly
    # render as ``full`` on the client, but we reject at the API so admins
    # can't end up with a typo'd mode that's a no-op.
    if "layout_mode" in ch_updates and ch_updates["layout_mode"] is not None:
        _valid_layout = {"full", "rail-header-chat", "rail-chat", "dashboard-only"}
        if ch_updates["layout_mode"] not in _valid_layout:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid layout_mode. Valid: {sorted(_valid_layout)}",
            )

    # layout_mode is stored inside the channel's JSONB config, not as a top-
    # level column. Split it out so the generic setattr loop below doesn't
    # try to write to a non-existent attribute.
    layout_mode_update = ch_updates.pop("layout_mode", None) if "layout_mode" in ch_updates else None

    # Apply channel updates
    if ch_updates:
        for field, value in ch_updates.items():
            setattr(channel, field, value)
        channel.updated_at = now

    # Apply layout_mode via the JSONB config dict. deepcopy + flag_modified so
    # SQLAlchemy picks up the mutation (JSONB in-place edits don't auto-flag).
    if layout_mode_update is not None:
        import copy as _copy
        from sqlalchemy.orm.attributes import flag_modified
        cfg = _copy.deepcopy(channel.config or {})
        cfg["layout_mode"] = layout_mode_update
        channel.config = cfg
        flag_modified(channel, "config")
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
        "tool_output_display": channel.tool_output_display,
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
        "local_tools_disabled": channel.local_tools_disabled,
        "mcp_servers_disabled": channel.mcp_servers_disabled,
        "client_tools_disabled": channel.client_tools_disabled,
        "workspace_base_prompt_enabled": channel.workspace_base_prompt_enabled,
        "workspace_schema_template_id": channel.workspace_schema_template_id,
        "workspace_schema_content": channel.workspace_schema_content,
        "index_segments": channel.index_segments or [],
        "carapaces_extra": channel.carapaces_extra,
        "carapaces_disabled": channel.carapaces_disabled,
        "model_tier_overrides": channel.model_tier_overrides or {},
        "layout_mode": (channel.config or {}).get("layout_mode", "full"),
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
            "heartbeat_skip_tool_approval": heartbeat.skip_tool_approval,
            "heartbeat_last_run_at": heartbeat.last_run_at,
            "heartbeat_next_run_at": heartbeat.next_run_at,
        })

    return ChannelConfigOut(**data)


@router.delete("/{channel_id}", status_code=204)
async def delete_channel(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_scopes("channels:write")),
):
    """Delete a channel and all associated data (integrations, heartbeat cascade; conversations/tasks/etc set null)."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    assert_admin_or_channel_owner(channel, auth)

    # Cascade the channel's implicit widget dashboard (if any). No FK wires
    # this — ``channel:<uuid>`` slugs aren't backed by a foreign key, so we
    # delete explicitly. Safe on channels that never opened their dashboard.
    from app.services.dashboards import channel_slug, delete_dashboard
    try:
        await delete_dashboard(db, channel_slug(channel_id))
    except HTTPException as exc:
        if exc.status_code != 404:
            raise

    await db.delete(channel)
    await db.commit()


@router.put("/{channel_id}", response_model=ChannelOut)
async def update_channel(
    channel_id: uuid.UUID,
    body: ChannelUpdate,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_scopes("channels:write")),
):
    """Update channel settings."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    assert_admin_or_channel_owner(channel, auth)

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
    """Inject a message into a channel's active conversation."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    _check_protected(channel, _auth)

    session_id = await ensure_active_session(db, channel)
    await db.commit()

    metadata = {"source": body.source} if body.source else {}
    await store_passive_message(db, session_id, body.content, metadata, channel_id=channel_id)

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

        # Forward the pre-persisted user message id so persist_turn skips it
        # at the end of the agent loop. See app/agent/tasks.py _run_one_task.
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
            execution_config={"pre_user_msg_id": str(msg.id)},
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
    """Start a fresh conversation on a channel. Previous conversation is preserved."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    _check_protected(channel, _auth)

    previous = channel.active_session_id
    new_session_id = await reset_channel_session(db, channel)

    return ResetResponse(
        channel_id=channel_id,
        new_session_id=new_session_id,
        previous_session_id=previous,
    )


class CompactResponse(BaseModel):
    status: str
    title: str
    summary_length: int


@router.post("/{channel_id}/compact", response_model=CompactResponse)
async def compact_channel(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels.messages:write")),
):
    """Force-compact the channel's active conversation."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    _check_protected(channel, _auth)
    if not channel.active_session_id:
        raise HTTPException(status_code=400, detail="Channel has no active conversation")

    from app.agent.bots import get_bot
    from app.services.compaction import run_compaction_forced

    bot = get_bot(channel.bot_id)
    title, summary = await run_compaction_forced(channel.active_session_id, bot, db)
    await db.commit()

    return CompactResponse(status="ok", title=title, summary_length=len(summary))


class SwitchSessionRequest(BaseModel):
    session_id: uuid.UUID


@router.post("/{channel_id}/switch-session", response_model=ResetResponse)
async def switch_session(
    channel_id: uuid.UUID,
    body: SwitchSessionRequest,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels.messages:write")),
):
    """Switch a channel to a previous conversation."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    _check_protected(channel, _auth)

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
    """Search messages across all conversations in a channel."""
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
# Session status (for UI polling during background processing)
# ---------------------------------------------------------------------------

class SessionStatusOut(BaseModel):
    processing: bool
    pending_tasks: int


@router.get("/{channel_id}/session-status", response_model=SessionStatusOut)
async def get_session_status(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels:read")),
):
    """Check if the channel is currently processing.

    Returns whether the agent loop is running and how many pending/running tasks
    are queued.  Cheap enough to poll at ~3 s intervals from the UI.
    """
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    session_id = channel.active_session_id
    if not session_id:
        return SessionStatusOut(processing=False, pending_tasks=0)

    processing = session_locks.is_active(session_id)

    pending_count_result = await db.execute(
        select(func.count())
        .where(
            Task.session_id == session_id,
            Task.status.in_(["pending", "running"]),
        )
    )
    pending_tasks = pending_count_result.scalar() or 0

    return SessionStatusOut(processing=processing, pending_tasks=pending_tasks)


# ---------------------------------------------------------------------------
# Channel state snapshot — chat rehydration (Phase 3)
# ---------------------------------------------------------------------------
#
# The SSE stream carries *deltas*. On mount, tab-wake, or reconnect the UI
# calls this endpoint once to seed whatever in-flight state already exists
# on the server: running/awaiting-approval tool calls, auto-injected skills,
# and pending approvals. The snapshot + the SSE stream together produce the
# same UI as a never-interrupted live session — regardless of whether the
# 256-event replay buffer in channel_events.py still covers the gap.
#
# An "active turn" is a correlation_id with a ToolCall/TraceEvent in the
# last 10 minutes AND no terminal assistant Message row. The turn_id the
# UI keys on IS the correlation_id (see turn_worker.py:94).

ACTIVE_TURN_WINDOW = timedelta(minutes=10)


class ActiveTurnToolCallOut(BaseModel):
    id: uuid.UUID
    tool_name: str
    arguments: dict
    status: str  # running | awaiting_approval | done | error | denied | expired
    is_error: bool = False
    approval_id: Optional[uuid.UUID] = None
    approval_reason: Optional[str] = None
    capability: Optional[dict] = None


class ActiveTurnSkillOut(BaseModel):
    skill_id: str
    skill_name: str
    similarity: float
    source: str


class ActiveTurnOut(BaseModel):
    turn_id: uuid.UUID
    bot_id: str
    is_primary: bool
    tool_calls: list[ActiveTurnToolCallOut]
    auto_injected_skills: list[ActiveTurnSkillOut]


class ChannelStateOut(BaseModel):
    active_turns: list[ActiveTurnOut]
    pending_approvals: list[dict]


@router.get("/{channel_id}/state", response_model=ChannelStateOut)
async def get_channel_state(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels:read")),
):
    """Snapshot of the chat's in-flight state.

    Paired with the SSE stream: the UI calls this once on mount (and on
    reconnect) to rehydrate turn cards, approval prompts, and auto-injected
    skill chips. Together they replace the fragile 256-event replay buffer.
    """
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    pending_approvals = await _snapshot_pending_approvals(db, channel_id)

    session_id = channel.active_session_id
    if not session_id:
        return ChannelStateOut(active_turns=[], pending_approvals=pending_approvals)

    cutoff = datetime.now(timezone.utc) - ACTIVE_TURN_WINDOW
    active_turns = await _snapshot_active_turns(
        db, session_id=session_id, channel_bot_id=channel.bot_id, cutoff=cutoff,
    )
    return ChannelStateOut(active_turns=active_turns, pending_approvals=pending_approvals)


class ChatZonesOut(BaseModel):
    rail: list[dict]
    header: list[dict]
    dock: list[dict]


@router.get("/{channel_id}/chat-zones", response_model=ChatZonesOut)
async def get_channel_chat_zones(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels:read")),
):
    """Channel dashboard pins grouped by chat-side zone.

    Zone is stored on each pin (``widget_dashboard_pins.zone``) and authored
    directly via the multi-canvas editor at ``/widgets/channel/:id``. Pins
    whose zone is ``grid`` are dashboard-only and excluded from the response.
    """
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    from app.services.channel_chat_zones import resolve_chat_zones
    zones = await resolve_chat_zones(db, channel_id)
    return ChatZonesOut(
        rail=zones["rail"],
        header=zones["header"],
        dock=zones["dock"],
    )


# ---------------------------------------------------------------------------
# Context introspection — channel-scoped.
#
# Authentication accepts either:
#   - ``channels:read`` scope (user JWTs, admin API keys, bot API keys that
#     opt into the scope), OR
#   - a widget-minted JWT whose ``pin_id`` resolves to a dashboard for this
#     channel. The pin itself proves the widget is authorized to observe
#     its host channel — scope is redundant in that path.
#
# These endpoints mirror the admin-prefixed ones in
# ``app/routers/api_v1_admin/channels.py`` (which delegate to the same
# service helpers). Exposing them under the public ``/channels/`` prefix —
# with the pin-implicit auth path — lets bot-authenticated HTML widgets
# (e.g. the Context Tracker) render a steady-state snapshot without
# demanding extra scopes on every bot's API key.
# ---------------------------------------------------------------------------

async def _auth_channel_context(
    channel_id: uuid.UUID,
    auth,
    db: AsyncSession,
) -> None:
    """Raise 403 unless the caller has channel-scoped read access.

    Access is granted when any of the following holds:

    * ``auth`` is a :class:`~app.db.models.User` (hydrated with scopes — users
      are allowed if they carry ``channels:read`` or are admin).
    * ``auth`` is an :class:`ApiKeyAuth` with ``channels:read`` (or a broader
      scope that covers it) on its key.
    * ``auth`` is a widget-minted :class:`ApiKeyAuth` whose ``pin_id`` belongs
      to a dashboard for *this* channel (slug ``channel:<channel_id>``).
    """
    from app.services.api_keys import has_scope
    from app.db.models import WidgetDashboardPin, User as _User

    # Static "admin" / bypass scopes — covered by `has_scope` below for
    # ApiKeyAuth; separately handled for User.
    if isinstance(auth, _User):
        scopes = getattr(auth, "_resolved_scopes", None) or []
        if auth.is_admin or "admin" in scopes or "channels:read" in scopes:
            return
    elif isinstance(auth, ApiKeyAuth):
        if has_scope(auth.scopes, "channels:read"):
            return
        # Widget-token implicit-channel-access path. The pin proves the
        # widget lives on this channel's dashboard; no further scope needed.
        if auth.pin_id is not None:
            pin = await db.get(WidgetDashboardPin, auth.pin_id)
            if (
                pin is not None
                and pin.dashboard_key == f"channel:{channel_id}"
            ):
                return

    raise HTTPException(status_code=403, detail="channels:read required")


@router.get("/{channel_id}/context-budget")
async def get_channel_context_budget(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Latest context budget (utilization / consumed / total tokens) for this channel.

    Reads the most recent ``context_injection_summary`` trace event on any
    session. Returns sentinel ``{"utilization": null, ...}`` when no turn
    has fired yet.
    """
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    await _auth_channel_context(channel_id, auth, db)

    from app.services.context_breakdown import fetch_latest_context_budget
    return await fetch_latest_context_budget(channel_id, db)


@router.get("/{channel_id}/context-breakdown")
async def get_channel_context_breakdown(
    channel_id: uuid.UUID,
    mode: str = "last_turn",
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Per-category context breakdown for this channel's active session.

    See the admin variant for ``mode`` semantics.
    """
    await _auth_channel_context(channel_id, auth, db)

    from app.services.context_breakdown import compute_context_breakdown
    from dataclasses import asdict

    if mode not in {"last_turn", "next_turn"}:
        raise HTTPException(status_code=422, detail="mode must be 'last_turn' or 'next_turn'")

    try:
        result = await compute_context_breakdown(str(channel_id), db, mode=mode)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "channel_id": result.channel_id,
        "session_id": result.session_id,
        "bot_id": result.bot_id,
        "categories": [asdict(c) for c in result.categories],
        "total_chars": result.total_chars,
        "total_tokens_approx": result.total_tokens_approx,
        "compaction": asdict(result.compaction),
        "reranking": asdict(result.reranking),
        "context_budget": result.context_budget,
        "mode": mode,
        "disclaimer": result.disclaimer,
    }


async def _snapshot_pending_approvals(db: AsyncSession, channel_id: uuid.UUID) -> list[dict]:
    """Reuse the shape Phase 1 already returns for pending approvals.

    Mirrors ``ApprovalOut`` in ``api_v1_approvals`` so the UI can feed both
    through the same component without two schemas. Returned as dicts rather
    than a cross-router import to keep this module's dependency surface tight.
    """
    from app.tools.registry import get_tool_safety_tier

    stmt = (
        select(ToolApproval)
        .where(
            ToolApproval.channel_id == channel_id,
            ToolApproval.status == "pending",
        )
        .order_by(ToolApproval.created_at.desc())
        .limit(50)
    )
    rows = (await db.execute(stmt)).scalars().all()
    result: list[dict] = []
    for r in rows:
        result.append({
            "id": str(r.id),
            "session_id": str(r.session_id) if r.session_id else None,
            "channel_id": str(r.channel_id) if r.channel_id else None,
            "bot_id": r.bot_id,
            "client_id": r.client_id,
            "correlation_id": str(r.correlation_id) if r.correlation_id else None,
            "tool_name": r.tool_name,
            "tool_type": r.tool_type,
            "arguments": r.arguments or {},
            "policy_rule_id": str(r.policy_rule_id) if r.policy_rule_id else None,
            "reason": r.reason,
            "status": r.status,
            "decided_by": r.decided_by,
            "decided_at": r.decided_at.isoformat() if r.decided_at else None,
            "dispatch_type": r.dispatch_type,
            "dispatch_metadata": r.dispatch_metadata,
            "approval_metadata": r.approval_metadata,
            "tool_call_id": str(r.tool_call_id) if r.tool_call_id else None,
            "timeout_seconds": r.timeout_seconds,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "safety_tier": get_tool_safety_tier(r.tool_name),
        })
    return result


async def _snapshot_active_turns(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    channel_bot_id: str,
    cutoff: datetime,
) -> list[ActiveTurnOut]:
    # Candidate correlation_ids — any ToolCall, skill_index TraceEvent, or
    # turn_started TraceEvent in the window. turn_started is the canonical
    # lifecycle signal (written by app/services/turn_worker.py +
    # app/routers/chat/_multibot.py on every turn) so a pure-text streaming
    # reply with no tools and no skills still appears here; skipping this
    # is the bug that lets the UI ghost reconciler kill live turns when the
    # snapshot refetches on window focus.
    tc_rows = (await db.execute(
        select(ToolCall).where(
            ToolCall.session_id == session_id,
            ToolCall.created_at >= cutoff,
            ToolCall.correlation_id.is_not(None),
        )
    )).scalars().all()
    te_rows = (await db.execute(
        select(TraceEvent).where(
            TraceEvent.session_id == session_id,
            TraceEvent.created_at >= cutoff,
            TraceEvent.event_type.in_(("skill_index", "turn_started")),
            TraceEvent.correlation_id.is_not(None),
        )
    )).scalars().all()

    by_corr: dict[uuid.UUID, dict] = {}
    for r in tc_rows:
        slot = by_corr.setdefault(r.correlation_id, {"bot_id": r.bot_id, "tool_calls": [], "skills": []})
        slot["tool_calls"].append(r)
        if not slot["bot_id"] and r.bot_id:
            slot["bot_id"] = r.bot_id
    for r in te_rows:
        slot = by_corr.setdefault(r.correlation_id, {"bot_id": r.bot_id, "tool_calls": [], "skills": []})
        # Only skill_index events feed the auto-injected skills list.
        # turn_started is a lifecycle marker — presence is enough.
        if r.event_type == "skill_index":
            slot["skills"].append(r)
        if not slot["bot_id"] and r.bot_id:
            slot["bot_id"] = r.bot_id

    if not by_corr:
        return []

    # Drop correlation_ids whose turn already produced a terminal assistant
    # Message — those are completed, not active.
    done_rows = (await db.execute(
        select(Message.correlation_id).where(
            Message.correlation_id.in_(list(by_corr.keys())),
            Message.role == "assistant",
        )
    )).scalars().all()
    for corr_id in done_rows:
        by_corr.pop(corr_id, None)

    if not by_corr:
        return []

    # Resolve skill names once for every auto_injected id across all turns.
    skill_ids: set[str] = set()
    for slot in by_corr.values():
        for te in slot["skills"]:
            data = te.data or {}
            for sid in data.get("auto_injected") or []:
                if sid:
                    skill_ids.add(str(sid))
    skill_names: dict[str, str] = {}
    if skill_ids:
        rows = (await db.execute(
            select(Skill.id, Skill.name).where(Skill.id.in_(list(skill_ids)))
        )).all()
        skill_names = {sid: name for sid, name in rows}

    # Resolve approval_id / capability for every awaiting_approval ToolCall
    # in one round trip, then fold in.
    awaiting_ids = [
        tc.id for slot in by_corr.values() for tc in slot["tool_calls"]
        if tc.status == "awaiting_approval"
    ]
    approvals_by_tc: dict[uuid.UUID, ToolApproval] = {}
    if awaiting_ids:
        appr_rows = (await db.execute(
            select(ToolApproval).where(ToolApproval.tool_call_id.in_(awaiting_ids))
        )).scalars().all()
        for a in appr_rows:
            if a.tool_call_id:
                approvals_by_tc[a.tool_call_id] = a

    turns: list[ActiveTurnOut] = []
    for corr_id, slot in by_corr.items():
        bot_id = slot["bot_id"] or channel_bot_id
        tc_outs: list[ActiveTurnToolCallOut] = []
        for tc in sorted(slot["tool_calls"], key=lambda r: r.created_at):
            appr = approvals_by_tc.get(tc.id)
            capability = None
            approval_reason = None
            if appr is not None:
                if appr.approval_metadata and isinstance(appr.approval_metadata, dict):
                    capability = appr.approval_metadata.get("_capability")
                approval_reason = appr.reason
            tc_outs.append(ActiveTurnToolCallOut(
                id=tc.id,
                tool_name=tc.tool_name,
                arguments=tc.arguments or {},
                status=tc.status,
                is_error=bool(tc.error),
                approval_id=appr.id if appr else None,
                approval_reason=approval_reason,
                capability=capability,
            ))
        # Collapse multiple skill_index TraceEvents (one per iteration) into
        # a single auto_injected set, keyed by skill_id so we don't double-render.
        skill_outs: list[ActiveTurnSkillOut] = []
        _seen_skills: set[str] = set()
        for te in sorted(slot["skills"], key=lambda r: r.created_at):
            data = te.data or {}
            ranking = {
                str(r.get("skill_id")): float(r.get("similarity") or 0.0)
                for r in (data.get("ranking_scores") or [])
                if isinstance(r, dict) and r.get("skill_id")
            }
            for sid in data.get("auto_injected") or []:
                key = str(sid or "")
                if not key or key in _seen_skills:
                    continue
                _seen_skills.add(key)
                skill_outs.append(ActiveTurnSkillOut(
                    skill_id=key,
                    skill_name=skill_names.get(key, key),
                    similarity=ranking.get(key, 0.0),
                    source="auto_inject",
                ))
        turns.append(ActiveTurnOut(
            turn_id=corr_id,
            bot_id=bot_id,
            is_primary=(bot_id == channel_bot_id),
            tool_calls=tc_outs,
            auto_injected_skills=skill_outs,
        ))
    # Primary first, then insertion order is dict iteration order (Python 3.7+).
    turns.sort(key=lambda t: (0 if t.is_primary else 1))
    return turns


# ---------------------------------------------------------------------------
# Real-time channel events (SSE)
# ---------------------------------------------------------------------------

@router.get("/{channel_id}/events")
async def channel_events(
    channel_id: uuid.UUID,
    since: int | None = None,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels:read")),
):
    """SSE stream of channel events.

    Events carry a per-channel monotonic `seq` number. Clients can
    reconnect with `?since=<last_seq>` to replay any events they missed
    while disconnected. If the replay buffer no longer covers `since`,
    a `replay_lapsed` sentinel is emitted first so the client knows to
    refetch history from REST and resume from the new seq.

    `new_message` and `message_updated` events ship the full Message row
    in their payload — clients can append to local state without a DB
    refetch.

    Keepalive comments sent every 15s to prevent connection drops.
    """
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    import asyncio
    import json
    from app.domain.channel_events import ChannelEventKind
    from app.services.channel_events import (
        event_to_sse_dict,
        get_shutdown_event,
        subscribe,
    )

    async def _event_stream():
        shutdown = get_shutdown_event()
        async_gen = subscribe(channel_id, since=since)
        pending = asyncio.ensure_future(async_gen.__anext__())
        try:
            while not shutdown.is_set():
                try:
                    event = await asyncio.wait_for(asyncio.shield(pending), timeout=15.0)
                    if event.kind is ChannelEventKind.SHUTDOWN:
                        break
                    payload = event_to_sse_dict(event)
                    yield f"data: {json.dumps(payload)}\n\n"
                    pending = asyncio.ensure_future(async_gen.__anext__())
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                except StopAsyncIteration:
                    break
        finally:
            # Tear down the inner subscriber generator cleanly. Order
            # matters: cancel the in-flight ``__anext__`` future AND
            # await its completion before calling ``aclose()`` — calling
            # ``aclose`` while the generator is still running its
            # ``await q.get()`` raises ``RuntimeError: aclose():
            # asynchronous generator is already running``. Awaiting the
            # cancelled future first lets the underlying coroutine drive
            # itself out of the suspension point so ``aclose`` has a
            # quiescent generator to throw GeneratorExit into.
            pending.cancel()
            try:
                await pending
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
            except Exception:  # noqa: BLE001 — best effort, generator about to be closed
                pass
            try:
                await async_gen.aclose()
            except (RuntimeError, StopAsyncIteration):
                pass

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
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
    _auth=Depends(require_admin_and_scope("channels.integrations:write")),
):
    """Bind an integration to a channel."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # Check for duplicate binding within the same channel
    existing = (await db.execute(
        select(ChannelIntegration).where(
            ChannelIntegration.client_id == body.client_id,
            ChannelIntegration.channel_id == channel_id,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"client_id '{body.client_id}' is already bound to this channel",
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
    _auth=Depends(require_admin_and_scope("channels.integrations:write")),
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
    _auth=Depends(require_admin_and_scope("channels.integrations:write")),
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


# ---------------------------------------------------------------------------
# Integration activation
# ---------------------------------------------------------------------------

class ActivationOut(BaseModel):
    integration_type: str
    activated: bool
    manifest: Optional[dict] = None
    warnings: list[dict] = []


class AvailableIntegrationOut(BaseModel):
    integration_type: str
    description: str
    requires_workspace: bool
    activated: bool
    carapaces: list[str] = []
    tools: list[str] = []
    has_system_prompt: bool = False
    version: Optional[str] = None
    includes: list[str] = []
    chat_hud: list[dict] = []
    chat_hud_presets: dict[str, dict] = {}
    activation_config: dict = {}
    config_fields: list[dict] = []
    included_by: list[str] = []


def _resolve_activation_client_id(integration_type: str, channel_id: uuid.UUID) -> str:
    """Resolve a proper client_id for activation from the integration's binding config.

    If the integration declares ``auto_client_id`` in its binding config (e.g.
    ``"gmail:{GMAIL_EMAIL}"``), substitute setting values and return the result.
    Falls back to ``mc-activated:{channel_id}`` if no auto_client_id or the
    required settings aren't configured.
    """
    from integrations import discover_binding_metadata
    from app.services.integration_settings import get_value

    binding = discover_binding_metadata().get(integration_type)
    if not binding:
        return f"mc-activated:{integration_type}:{channel_id}"

    template = binding.get("auto_client_id")
    if not template:
        return f"mc-activated:{integration_type}:{channel_id}"

    # Substitute {VAR_NAME} placeholders with setting values
    import re
    def _sub(m: re.Match) -> str:
        return get_value(integration_type, m.group(1))

    resolved = re.sub(r"\{(\w+)\}", _sub, template)

    # If any placeholder resolved to empty, fall back
    prefix = binding.get("client_id_prefix", "")
    if resolved == prefix or not resolved or resolved == template:
        return f"mc-activated:{integration_type}:{channel_id}"

    return resolved



@router.post("/{channel_id}/integrations/{integration_type}/activate", response_model=ActivationOut)
async def activate_integration(
    channel_id: uuid.UUID,
    integration_type: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_admin_and_scope("channels.integrations:write")),
):
    """Activate an integration on a channel. Creates/updates ChannelIntegration with activated=true."""
    from integrations import get_activation_manifests

    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    manifests = get_activation_manifests()
    manifest = manifests.get(integration_type)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"No activation manifest for '{integration_type}'")

    # Find or create ChannelIntegration row
    existing = (await db.execute(
        select(ChannelIntegration).where(
            ChannelIntegration.channel_id == channel_id,
            ChannelIntegration.integration_type == integration_type,
            ChannelIntegration.activated == True,  # noqa: E712
        )
    )).scalar_one_or_none()

    if existing:
        # Already activated
        return ActivationOut(
            integration_type=integration_type,
            activated=True,
            manifest=manifest,
            warnings=[],
        )

    # Check for existing inactive rows we can reuse. Prefer a binding
    # with a real integration prefix (e.g. bb:, slack:) over an
    # mc-activated: stub — the real binding has the correct client_id
    # for dispatch resolution and must not be overwritten.
    inactive_rows = (await db.execute(
        select(ChannelIntegration).where(
            ChannelIntegration.channel_id == channel_id,
            ChannelIntegration.integration_type == integration_type,
            ChannelIntegration.activated == False,  # noqa: E712
        )
    )).scalars().all()

    # Pick the best row: real-prefix binding > mc-activated stub
    real_binding = next(
        (r for r in inactive_rows if not r.client_id.startswith("mc-activated:")),
        None,
    )
    inactive = real_binding or (inactive_rows[0] if inactive_rows else None)

    if inactive:
        inactive.activated = True
        # Only set client_id on mc-activated stubs — never overwrite a
        # real binding's client_id (e.g. bb:chat_guid).
        if inactive.client_id.startswith("mc-activated:"):
            client_id = f"mc-activated:{integration_type}:{channel_id}"
            try:
                client_id = _resolve_activation_client_id(integration_type, channel_id)
            except Exception:
                pass
            inactive.client_id = client_id
        db.add(inactive)
    else:
        new_client_id = f"mc-activated:{integration_type}:{channel_id}"
        try:
            new_client_id = _resolve_activation_client_id(integration_type, channel_id)
        except Exception:
            pass
        ci = ChannelIntegration(
            channel_id=channel_id,
            integration_type=integration_type,
            client_id=new_client_id,
            activated=True,
        )
        db.add(ci)

    await db.commit()

    # Auto-activate included integrations
    for included_id in manifest.get("includes", []):
        included_manifest = manifests.get(included_id)
        if not included_manifest:
            continue
        already = (await db.execute(
            select(ChannelIntegration).where(
                ChannelIntegration.channel_id == channel_id,
                ChannelIntegration.integration_type == included_id,
                ChannelIntegration.activated == True,  # noqa: E712
            )
        )).scalar_one_or_none()
        if already:
            continue
        inc_client_id = f"mc-activated:{included_id}:{channel_id}"
        try:
            inc_client_id = _resolve_activation_client_id(included_id, channel_id)
        except Exception:
            pass
        inc_inactive = (await db.execute(
            select(ChannelIntegration).where(
                ChannelIntegration.channel_id == channel_id,
                ChannelIntegration.integration_type == included_id,
                ChannelIntegration.activated == False,  # noqa: E712
            )
        )).scalar_one_or_none()
        if inc_inactive:
            inc_inactive.activated = True
            inc_inactive.client_id = inc_client_id
            db.add(inc_inactive)
        else:
            db.add(ChannelIntegration(
                channel_id=channel_id,
                integration_type=included_id,
                client_id=inc_client_id,
                activated=True,
            ))

    if manifest.get("includes"):
        await db.commit()

    # Run feature validation
    warnings: list[dict] = []
    try:
        from app.services.feature_validation import validate_activation
        ws = await validate_activation(channel.bot_id, integration_type)
        warnings = [w.to_dict() for w in ws]
    except Exception:
        pass

    return ActivationOut(
        integration_type=integration_type,
        activated=True,
        manifest=manifest,
        warnings=warnings,
    )


@router.post("/{channel_id}/integrations/{integration_type}/deactivate")
async def deactivate_integration(
    channel_id: uuid.UUID,
    integration_type: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_admin_and_scope("channels.integrations:write")),
):
    """Deactivate an integration on a channel."""
    from integrations import get_activation_manifests

    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    manifests = get_activation_manifests()

    result = await db.execute(
        select(ChannelIntegration).where(
            ChannelIntegration.channel_id == channel_id,
            ChannelIntegration.integration_type == integration_type,
            ChannelIntegration.activated == True,  # noqa: E712
        )
    )
    rows = result.scalars().all()
    for row in rows:
        row.activated = False
        db.add(row)

    # Flush so the "still_needed" queries below see the deactivated rows
    await db.flush()

    # Deactivate included integrations if no other active integration still includes them
    manifest = manifests.get(integration_type, {})
    for included_id in manifest.get("includes", []):
        # Check if any OTHER active integration still includes this one
        still_needed = False
        for other_type, other_manifest in manifests.items():
            if other_type == integration_type:
                continue
            if included_id not in other_manifest.get("includes", []):
                continue
            other_active = (await db.execute(
                select(ChannelIntegration).where(
                    ChannelIntegration.channel_id == channel_id,
                    ChannelIntegration.integration_type == other_type,
                    ChannelIntegration.activated == True,  # noqa: E712
                )
            )).scalar_one_or_none()
            if other_active:
                still_needed = True
                break
        if not still_needed:
            inc_result = await db.execute(
                select(ChannelIntegration).where(
                    ChannelIntegration.channel_id == channel_id,
                    ChannelIntegration.integration_type == included_id,
                    ChannelIntegration.activated == True,  # noqa: E712
                )
            )
            for inc_row in inc_result.scalars().all():
                inc_row.activated = False
                db.add(inc_row)

    await db.commit()
    return {"ok": True, "integration_type": integration_type, "activated": False}


@router.get("/{channel_id}/integrations/available", response_model=list[AvailableIntegrationOut])
async def list_available_integrations(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels.integrations:read")),
):
    """List all integrations that declare activation blocks, with current status."""
    from integrations import get_activation_manifests, get_chat_huds, get_chat_hud_presets

    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    manifests = get_activation_manifests()
    huds = get_chat_huds()
    hud_presets = get_chat_hud_presets()

    # Load full ChannelIntegration rows to get activated status + activation_config
    ci_result = await db.execute(
        select(ChannelIntegration).where(
            ChannelIntegration.channel_id == channel_id,
            ChannelIntegration.activated == True,  # noqa: E712
        )
    )
    ci_rows = {ci.integration_type: ci for ci in ci_result.scalars().all()}

    from app.agent.carapaces import resolve_carapaces

    result = []
    for itype, manifest in manifests.items():
        carapace_ids = manifest.get("carapaces", [])
        resolved = resolve_carapaces(carapace_ids) if carapace_ids else None
        tool_names: list[str] = []
        has_system_prompt = False
        if resolved:
            tool_names = list(resolved.local_tools)
            has_system_prompt = len(resolved.system_prompt_fragments) > 0

        ci_row = ci_rows.get(itype)
        activation_config = (ci_row.activation_config or {}) if ci_row else {}

        result.append(AvailableIntegrationOut(
            integration_type=itype,
            description=manifest.get("description", ""),
            requires_workspace=manifest.get("requires_workspace", False),
            activated=itype in ci_rows,
            carapaces=carapace_ids,
            tools=tool_names,
            has_system_prompt=has_system_prompt,
            version=manifest.get("version"),
            includes=manifest.get("includes", []),
            chat_hud=huds.get(itype, []),
            chat_hud_presets=hud_presets.get(itype, {}),
            activation_config=activation_config,
            config_fields=manifest.get("config_fields", []),
        ))

    # Second pass: populate included_by — for each integration that has
    # includes, mark each included integration as included_by the parent.
    by_type = {r.integration_type: r for r in result}
    for r in result:
        for included_id in r.includes:
            included = by_type.get(included_id)
            if included:
                included.included_by.append(r.integration_type)

    return result


class ActivationConfigUpdate(BaseModel):
    config: dict


@router.patch("/{channel_id}/integrations/{integration_type}/config")
async def update_activation_config(
    channel_id: uuid.UUID,
    integration_type: str,
    body: ActivationConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_admin_and_scope("channels.integrations:write")),
):
    """Merge values into the activation_config JSONB of a ChannelIntegration row."""
    ci = (await db.execute(
        select(ChannelIntegration).where(
            ChannelIntegration.channel_id == channel_id,
            ChannelIntegration.integration_type == integration_type,
            ChannelIntegration.activated == True,  # noqa: E712
        )
    )).scalar_one_or_none()

    if not ci:
        raise HTTPException(status_code=404, detail="Activated integration not found on this channel")

    import copy
    from sqlalchemy.orm.attributes import flag_modified

    merged = copy.deepcopy(ci.activation_config or {})
    merged.update(body.config)
    ci.activation_config = merged
    flag_modified(ci, "activation_config")
    await db.commit()
    return {"ok": True, "activation_config": merged}


# ---------------------------------------------------------------------------
# Bot Members (multi-bot channels)
# ---------------------------------------------------------------------------

class AddBotMemberRequest(BaseModel):
    bot_id: str


class UpdateBotMemberConfigRequest(BaseModel):
    max_rounds: Optional[int] = None
    auto_respond: Optional[bool] = None
    response_style: Optional[str] = None
    system_prompt_addon: Optional[str] = None
    model_override: Optional[str] = None
    priority: Optional[int] = None


@router.get("/{channel_id}/bot-members", response_model=list[ChannelBotMemberOut])
async def list_bot_members(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels:read")),
):
    """List member bots for a channel."""
    result = await db.execute(
        select(ChannelBotMember)
        .where(ChannelBotMember.channel_id == channel_id)
        .order_by(ChannelBotMember.created_at)
    )
    members = result.scalars().all()
    from app.agent.bots import get_bot as _get_bot
    out = []
    for bm in members:
        item = ChannelBotMemberOut.model_validate(bm)
        try:
            item.bot_name = _get_bot(bm.bot_id).name
        except Exception:
            item.bot_name = bm.bot_id
        out.append(item)
    return out


@router.post("/{channel_id}/bot-members", response_model=ChannelBotMemberOut, status_code=201)
async def add_bot_member(
    channel_id: uuid.UUID,
    body: AddBotMemberRequest,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels:write")),
):
    """Add a member bot to a channel."""
    from app.agent.bots import get_bot as _get_bot

    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # Validate bot exists
    try:
        bot_cfg = _get_bot(body.bot_id)
    except HTTPException:
        raise HTTPException(status_code=400, detail=f"Unknown bot: {body.bot_id}")

    # Don't allow adding the primary bot as a member
    if body.bot_id == channel.bot_id:
        raise HTTPException(status_code=400, detail="Cannot add the primary bot as a member")

    # Check for duplicate
    existing = (await db.execute(
        select(ChannelBotMember).where(
            ChannelBotMember.channel_id == channel_id,
            ChannelBotMember.bot_id == body.bot_id,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Bot is already a member of this channel")

    bm = ChannelBotMember(channel_id=channel_id, bot_id=body.bot_id)
    db.add(bm)
    await db.commit()
    await db.refresh(bm)

    out = ChannelBotMemberOut.model_validate(bm)
    out.bot_name = bot_cfg.name
    return out


@router.delete("/{channel_id}/bot-members/{bot_id}", status_code=204)
async def remove_bot_member(
    channel_id: uuid.UUID,
    bot_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels:write")),
):
    """Remove a member bot from a channel."""
    result = await db.execute(
        select(ChannelBotMember).where(
            ChannelBotMember.channel_id == channel_id,
            ChannelBotMember.bot_id == bot_id,
        )
    )
    bm = result.scalar_one_or_none()
    if not bm:
        raise HTTPException(status_code=404, detail="Bot member not found")
    await db.delete(bm)
    await db.commit()


_VALID_RESPONSE_STYLES = {"brief", "normal", "detailed"}
_VALID_CONFIG_KEYS = {"max_rounds", "auto_respond", "response_style", "system_prompt_addon", "model_override", "priority"}


@router.patch("/{channel_id}/bot-members/{bot_id}/config", response_model=ChannelBotMemberOut)
async def update_bot_member_config(
    channel_id: uuid.UUID,
    bot_id: str,
    body: UpdateBotMemberConfigRequest,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels:write")),
):
    """Update per-member config for a bot member. Setting a field to null removes it."""
    import copy
    from sqlalchemy.orm.attributes import flag_modified

    result = await db.execute(
        select(ChannelBotMember).where(
            ChannelBotMember.channel_id == channel_id,
            ChannelBotMember.bot_id == bot_id,
        )
    )
    bm = result.scalar_one_or_none()
    if not bm:
        raise HTTPException(status_code=404, detail="Bot member not found")

    # Validate response_style if provided
    updates = body.model_dump(exclude_unset=True)
    if "response_style" in updates and updates["response_style"] is not None:
        if updates["response_style"] not in _VALID_RESPONSE_STYLES:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid response_style: must be one of {sorted(_VALID_RESPONSE_STYLES)}",
            )

    # Deep-copy + merge + flag_modified (standard JSONB mutation pattern)
    new_config = copy.deepcopy(bm.config or {})
    for key, value in updates.items():
        if key not in _VALID_CONFIG_KEYS:
            continue
        if value is None:
            new_config.pop(key, None)
        else:
            new_config[key] = value
    bm.config = new_config
    flag_modified(bm, "config")

    await db.commit()
    await db.refresh(bm)

    from app.agent.bots import get_bot as _get_bot
    out = ChannelBotMemberOut.model_validate(bm)
    try:
        out.bot_name = _get_bot(bm.bot_id).name
    except Exception:
        out.bot_name = bm.bot_id
    return out


# ---------------------------------------------------------------------------
# Pinned panels
# ---------------------------------------------------------------------------

class PinPanelRequest(BaseModel):
    path: str
    position: str = "right"


class PinPanelOut(BaseModel):
    path: str
    position: str
    pinned_at: str
    pinned_by: str


@router.post(
    "/{channel_id}/pins",
    response_model=PinPanelOut,
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def pin_file(
    channel_id: uuid.UUID,
    body: PinPanelRequest,
    db: AsyncSession = Depends(get_db),
):
    """Pin a workspace file to a channel's side rail."""
    import copy
    from sqlalchemy.orm.attributes import flag_modified

    ch = (await db.execute(
        select(Channel).where(Channel.id == channel_id)
    )).scalar_one_or_none()
    if not ch:
        raise HTTPException(404, "Channel not found")

    if body.position not in ("right", "bottom"):
        raise HTTPException(422, "position must be 'right' or 'bottom'")

    cfg = copy.deepcopy(ch.config or {})
    panels = cfg.setdefault("pinned_panels", [])
    # Deduplicate by path (replace existing)
    panels = [p for p in panels if p["path"] != body.path]
    now_iso = datetime.now(timezone.utc).isoformat()
    entry = {
        "path": body.path,
        "position": body.position,
        "pinned_at": now_iso,
        "pinned_by": "user",
    }
    panels.append(entry)
    cfg["pinned_panels"] = panels
    ch.config = cfg
    flag_modified(ch, "config")

    await db.commit()

    # Invalidate pinned-path cache
    from app.services.pinned_panels import invalidate_channel
    await invalidate_channel(channel_id)

    return PinPanelOut(**entry)


@router.delete(
    "/{channel_id}/pins",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def unpin_file(
    channel_id: uuid.UUID,
    path: str = Query(..., description="Path of the file to unpin"),
    db: AsyncSession = Depends(get_db),
):
    """Unpin a workspace file from a channel's side rail."""
    import copy
    from sqlalchemy.orm.attributes import flag_modified

    ch = (await db.execute(
        select(Channel).where(Channel.id == channel_id)
    )).scalar_one_or_none()
    if not ch:
        raise HTTPException(404, "Channel not found")

    cfg = copy.deepcopy(ch.config or {})
    panels = cfg.get("pinned_panels", [])
    new_panels = [p for p in panels if p["path"] != path]
    if len(new_panels) == len(panels):
        raise HTTPException(404, "File is not pinned")
    cfg["pinned_panels"] = new_panels
    ch.config = cfg
    flag_modified(ch, "config")

    await db.commit()

    # Invalidate pinned-path cache
    from app.services.pinned_panels import invalidate_channel
    await invalidate_channel(channel_id)

    return {"ok": True}


# Channel-scoped widget pins now live on the implicit channel dashboard
# (``widget_dashboards`` slug ``channel:<uuid>``). The frontend reads/writes
# them directly through ``/api/v1/widgets/dashboard`` at that slug — there is
# no channel-scoped pin CRUD endpoint anymore.
