import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Attachment, Attachment as AttachmentModel, Channel, ConversationSection, Message, Project, Session, Task, ToolCall
from app.domain.errors import DomainError
from app.dependencies import ApiKeyAuth, get_db, require_scopes, verify_auth_or_user, verify_user
from app.services.api_keys import has_scope
from app.services import presence
from app.services.machine_control import (
    DEFAULT_LEASE_TTL_SECONDS,
    MAX_LEASE_TTL_SECONDS,
    build_session_machine_target_payload,
    clear_session_lease_row,
    grant_session_lease,
)
from app.services.channel_sessions import RecentSessionListOut, build_recent_session_rows
from app.services.sessions import store_passive_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["Sessions"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _fanout(session: Session, text: str, source: str | None = None) -> None:
    """Publish an injected message onto the channel-events bus.

    Renderers consume the NEW_MESSAGE event and post to the integration.
    The source label is attributed via ``ActorRef.system``. No-op when the
    session has no channel.

    NEW_MESSAGE is outbox-durable, so this enqueues an outbox row first
    (renderer delivery path) and THEN publishes to the bus (SSE path).
    """
    if session.channel_id is None:
        return

    from app.domain.actor import ActorRef
    from app.domain.channel_events import ChannelEvent, ChannelEventKind
    from app.domain.message import Message as DomainMessage
    from app.domain.payloads import MessagePayload
    from app.services.channel_events import publish_typed
    from app.services.outbox_publish import enqueue_new_message_for_channel

    actor = ActorRef.system(
        id=source or "injected",
        display_name=source or "Injected",
    )
    domain_msg = DomainMessage(
        id=uuid.uuid4(),
        session_id=session.id,
        role="system",
        content=text,
        created_at=datetime.now(timezone.utc),
        actor=actor,
        metadata={"source": source or "injected"},
        channel_id=session.channel_id,
    )
    await enqueue_new_message_for_channel(session.channel_id, domain_msg)
    publish_typed(
        session.channel_id,
        ChannelEvent(
            channel_id=session.channel_id,
            kind=ChannelEventKind.NEW_MESSAGE,
            payload=MessagePayload(message=domain_msg),
        ),
    )


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SessionCreate(BaseModel):
    bot_id: str = "default"
    client_id: str
    dispatch_config: Optional[dict] = None


class SessionOut(BaseModel):
    session_id: uuid.UUID
    created: bool


class MessageInject(BaseModel):
    content: str
    role: str = "user"
    source: Optional[str] = None      # stored in metadata, e.g. "gmail"
    run_agent: bool = False            # True → create async Task
    notify: bool = True               # True → fan-out to dispatch targets


class AttachmentBrief(BaseModel):
    id: uuid.UUID
    type: str
    filename: str
    mime_type: str
    size_bytes: int
    description: Optional[str] = None
    has_file_data: bool = False

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, att: AttachmentModel) -> "AttachmentBrief":
        return cls(
            id=att.id,
            type=att.type,
            filename=att.filename,
            mime_type=att.mime_type,
            size_bytes=att.size_bytes,
            description=att.description,
            has_file_data=att.file_data is not None,
        )


class MessageOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: Optional[str]
    tool_calls: Optional[list] = None
    tool_call_id: Optional[str] = None
    correlation_id: Optional[uuid.UUID] = None
    created_at: datetime
    metadata: dict = {}
    attachments: list[AttachmentBrief] = []

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, msg: Message) -> "MessageOut":
        return cls(
            id=msg.id,
            session_id=msg.session_id,
            role=msg.role,
            content=msg.content,
            tool_calls=msg.tool_calls,
            tool_call_id=msg.tool_call_id,
            correlation_id=msg.correlation_id,
            created_at=msg.created_at,
            metadata=msg.metadata_,
            attachments=[AttachmentBrief.from_orm(a) for a in (msg.attachments or [])],
        )


class InjectResponse(BaseModel):
    message_id: uuid.UUID
    session_id: uuid.UUID
    task_id: Optional[uuid.UUID] = None


class EphemeralContextPayload(BaseModel):
    page_name: Optional[str] = None
    url: Optional[str] = None
    tags: Optional[list[str]] = None
    payload: Optional[dict] = None
    tool_hints: Optional[list[str]] = None


class EphemeralSessionCreate(BaseModel):
    bot_id: str
    parent_channel_id: Optional[uuid.UUID] = None
    context: Optional[EphemeralContextPayload] = None


class EphemeralSessionOut(BaseModel):
    session_id: uuid.UUID
    parent_channel_id: Optional[uuid.UUID] = None


@router.get("/recent", response_model=RecentSessionListOut)
async def list_recent_sessions(
    limit: int = Query(8, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_scopes("channels.messages:read")),
):
    rows = await build_recent_session_rows(db, auth, limit=limit)
    return RecentSessionListOut(sessions=rows)


class ScratchSessionOut(BaseModel):
    """Current scratch session for (parent_channel_id, owner_user_id, bot_id).

    ``is_current=True`` on the Session row. Created on demand if none exists.
    """
    session_id: uuid.UUID
    parent_channel_id: uuid.UUID
    bot_id: str
    created_at: datetime
    is_current: bool
    title: Optional[str] = None
    summary: Optional[str] = None
    message_count: int = 0
    section_count: int = 0
    session_scope: str = "scratch"


class ScratchResetRequest(BaseModel):
    parent_channel_id: uuid.UUID
    bot_id: str


class ScratchHistoryItem(BaseModel):
    session_id: uuid.UUID
    bot_id: str
    created_at: datetime
    last_active: datetime
    is_current: bool
    message_count: int
    preview: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    section_count: int = 0
    session_scope: str = "scratch"


class SessionPatchRequest(BaseModel):
    title: str


class SessionOutDetail(BaseModel):
    session_id: uuid.UUID
    title: Optional[str] = None
    summary: Optional[str] = None


class SessionProjectInstanceOut(BaseModel):
    session_id: uuid.UUID
    project_instance_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    project_name: str | None = None
    workspace_id: uuid.UUID | None = None
    status: str | None = None
    root_path: str | None = None
    expires_at: datetime | None = None
    created_at: datetime | None = None


class SessionSummaryOut(BaseModel):
    session_id: uuid.UUID
    bot_id: str
    channel_id: Optional[uuid.UUID] = None
    parent_channel_id: Optional[uuid.UUID] = None
    session_type: str
    title: Optional[str] = None
    summary: Optional[str] = None
    created_at: datetime
    last_active: datetime
    message_count: int = 0
    section_count: int = 0
    is_current: bool = False
    session_scope: str = "session"
    project_instance_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    project_instance_status: str | None = None
    project_root_path: str | None = None


class PromoteScratchSessionResponse(BaseModel):
    channel_id: uuid.UUID
    primary_session_id: uuid.UUID
    demoted_session_id: uuid.UUID


class SessionMachineTargetLeaseOut(BaseModel):
    lease_id: str
    provider_id: str
    target_id: str
    user_id: str
    granted_at: str
    expires_at: str
    capabilities: list[str]
    handle_id: str | None = None
    connection_id: str | None = None
    ready: bool = False
    status: str | None = None
    status_label: str | None = None
    reason: str | None = None
    checked_at: str | None = None
    connected: bool
    provider_label: str | None = None
    target_label: str


class SessionMachineTargetOut(BaseModel):
    session_id: str
    lease: SessionMachineTargetLeaseOut | None = None
    targets: list[dict[str, Any]]
    ready_target_count: int | None = None
    connected_target_count: int | None = None


class SessionMachineTargetLeaseRequest(BaseModel):
    provider_id: str
    target_id: str
    ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS


def _auth_has_scope(auth, scope: str) -> bool:
    if isinstance(auth, ApiKeyAuth):
        return has_scope(auth.scopes, scope)
    scopes = getattr(auth, "_resolved_scopes", None) or []
    return bool(getattr(auth, "is_admin", False) or has_scope(scopes, scope))


def _derive_session_scope(session: Session, channel: Channel | None) -> str:
    if session.session_type == "ephemeral":
        if session.metadata_.get("demoted_from_primary"):
            return "demoted_primary"
        return "scratch"
    if channel is not None and channel.active_session_id == session.id:
        return "primary"
    return "session"


def _selector_title(session: Session, preview: str | None) -> str | None:
    title = (session.title or "").strip()
    if title:
        return title
    preview = (preview or "").strip()
    return preview or None


def _require_admin_user(user) -> None:
    if not getattr(user, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin access required")


async def _authorize_session_read(
    db: AsyncSession,
    session: Session,
    auth,
) -> tuple[Channel | None, uuid.UUID | None]:
    """Authorize metadata reads with the same channel/scratch boundaries as mutation routes."""
    from app.db.models import User

    channel_id = session.channel_id or session.parent_channel_id
    channel = await db.get(Channel, channel_id) if channel_id else None

    if session.session_type == "ephemeral" and session.owner_user_id is not None:
        auth_user = auth if isinstance(auth, User) else None
        if auth_user is None or session.owner_user_id != auth_user.id:
            raise HTTPException(status_code=404, detail="Session not found")
        if not (_auth_has_scope(auth, "chat") or _auth_has_scope(auth, "sessions:read")):
            raise HTTPException(status_code=403, detail="sessions:read required")
    elif channel is not None:
        if not (_auth_has_scope(auth, "channels.messages:read") or _auth_has_scope(auth, "sessions:read")):
            raise HTTPException(status_code=403, detail="sessions:read required")
        from app.routers.api_v1_channels import _check_protected
        _check_protected(channel, auth)
    elif not _auth_has_scope(auth, "sessions:read"):
        raise HTTPException(status_code=403, detail="sessions:read required")

    return channel, channel_id


async def _authorize_session_project_instance_write(
    db: AsyncSession,
    session: Session,
    auth,
) -> tuple[Channel | None, uuid.UUID | None]:
    """Authorize a session-scoped work-surface mutation."""
    from app.db.models import User

    channel, channel_id = await _authorize_session_read(db, session, auth)
    auth_user = auth if isinstance(auth, User) else None

    if session.session_type == "ephemeral":
        if session.owner_user_id is not None and (auth_user is None or session.owner_user_id != auth_user.id):
            raise HTTPException(status_code=404, detail="Session not found")
        if not (_auth_has_scope(auth, "chat") or _auth_has_scope(auth, "sessions:write")):
            raise HTTPException(status_code=403, detail="sessions:write required")
        return channel, channel_id

    if channel is not None:
        if not _auth_has_scope(auth, "channels.messages:write"):
            raise HTTPException(status_code=403, detail="channels.messages:write required")
        from app.routers.api_v1_channels import _check_protected
        _check_protected(channel, auth)
        return channel, channel_id

    if not _auth_has_scope(auth, "sessions:write"):
        raise HTTPException(status_code=403, detail="sessions:write required")
    return channel, channel_id


async def _session_project_instance_out(
    db: AsyncSession,
    session: Session,
    *,
    channel: Channel | None = None,
) -> SessionProjectInstanceOut:
    channel = channel if channel is not None else await db.get(Channel, session.channel_id or session.parent_channel_id) if (session.channel_id or session.parent_channel_id) else None
    project = await db.get(Project, channel.project_id) if channel is not None and channel.project_id is not None else None
    if project is None:
        return SessionProjectInstanceOut(session_id=session.id)

    if session.project_instance_id is not None:
        from app.db.models import ProjectInstance

        instance = await db.get(ProjectInstance, session.project_instance_id)
        if instance is not None:
            return SessionProjectInstanceOut(
                session_id=session.id,
                project_instance_id=instance.id,
                project_id=instance.project_id,
                project_name=project.name,
                workspace_id=instance.workspace_id,
                status=instance.status,
                root_path=instance.root_path,
                expires_at=instance.expires_at,
                created_at=instance.created_at,
            )

    return SessionProjectInstanceOut(
        session_id=session.id,
        project_id=project.id,
        project_name=project.name,
        workspace_id=project.workspace_id,
        status="shared",
        root_path=project.root_path,
        created_at=session.created_at,
    )


async def _session_stats(
    db: AsyncSession,
    sessions: list[Session],
) -> tuple[dict[uuid.UUID, int], dict[uuid.UUID, int], dict[uuid.UUID, str]]:
    if not sessions:
        return {}, {}, {}

    session_ids = [s.id for s in sessions]
    count_rows = (await db.execute(
        select(Message.session_id, func.count(Message.id))
        .where(
            Message.session_id.in_(session_ids),
            Message.role.in_(("user", "assistant")),
        )
        .group_by(Message.session_id)
    )).all()
    counts = {sid: int(c) for sid, c in count_rows}

    from app.db.models import ConversationSection

    section_count_rows = (await db.execute(
        select(ConversationSection.session_id, func.count(ConversationSection.id))
        .where(ConversationSection.session_id.in_(session_ids))
        .group_by(ConversationSection.session_id)
    )).all()
    section_counts = {
        sid: int(c)
        for sid, c in section_count_rows
        if sid is not None
    }

    preview_rows = (await db.execute(
        select(Message.session_id, Message.content, Message.created_at)
        .where(
            Message.session_id.in_(session_ids),
            Message.role == "user",
            Message.content.is_not(None),
        )
        .order_by(Message.session_id, Message.created_at.asc())
    )).all()
    previews: dict[uuid.UUID, str] = {}
    for sid, content, _ in preview_rows:
        if sid in previews:
            continue
        text = (content or "").strip().replace("\n", " ")
        if len(text) > 120:
            text = text[:120] + "…"
        previews[sid] = text

    return counts, section_counts, previews


async def _build_bootstrap_metadata(
    db: AsyncSession,
    parent_channel_id: uuid.UUID,
) -> dict[str, str] | None:
    channel = await db.get(Channel, parent_channel_id)
    if channel is None or channel.active_session_id is None:
        return None
    primary = await db.get(Session, channel.active_session_id)
    if primary is None:
        return None
    summary = (primary.summary or "").strip()
    title = (primary.title or "").strip() or "Primary session"
    if not summary:
        return None
    return {
        "bootstrap_source_session_id": str(primary.id),
        "bootstrap_source_title": title,
        "bootstrap_summary": summary,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=SessionOut, status_code=201)
async def create_session(
    body: SessionCreate,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:write")),
):
    """Create or retrieve a session for an integration client."""
    from app.agent.bots import get_bot
    from app.services.sessions import load_or_create

    try:
        get_bot(body.bot_id)
    except (HTTPException, DomainError):
        raise HTTPException(status_code=400, detail=f"Unknown bot: {body.bot_id}")

    # load_or_create handles upsert; locked=True for integration sessions
    session_id, _ = await load_or_create(db, None, body.client_id, body.bot_id, locked=True)

    created = False
    # Store dispatch_config if provided
    if body.dispatch_config:
        result = await db.execute(select(Session).where(Session.id == session_id))
        session = result.scalar_one_or_none()
        if session and not session.dispatch_config:
            session.dispatch_config = body.dispatch_config
            created = True
        elif session and session.dispatch_config != body.dispatch_config:
            session.dispatch_config = body.dispatch_config
        await db.commit()

    return SessionOut(session_id=session_id, created=created)


@router.post("/ephemeral", response_model=EphemeralSessionOut, status_code=201)
async def create_ephemeral_session(
    body: EphemeralSessionCreate,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("chat")),
):
    """Spawn a stand-alone ephemeral session for ad-hoc bot chat.

    Returns a session_id the client can use with POST /chat (via session_id param)
    and GET /sessions/{id}/messages for history.
    """
    from app.agent.bots import get_bot
    from app.services.sub_sessions import spawn_ephemeral_session

    try:
        get_bot(body.bot_id)
    except (HTTPException, DomainError):
        raise HTTPException(status_code=400, detail=f"Unknown bot: {body.bot_id}")

    if body.parent_channel_id is not None:
        from app.db.models import Channel as ChannelModel
        channel = await db.get(ChannelModel, body.parent_channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="Parent channel not found")

    context_dict: dict | None = None
    if body.context is not None:
        context_dict = body.context.model_dump(exclude_none=True)

    sub = await spawn_ephemeral_session(
        db,
        bot_id=body.bot_id,
        parent_channel_id=body.parent_channel_id,
        context=context_dict if context_dict else None,
    )
    await db.commit()

    return EphemeralSessionOut(
        session_id=sub.id,
        parent_channel_id=body.parent_channel_id,
    )


@router.get("/scratch/current", response_model=ScratchSessionOut)
async def get_current_scratch_session(
    parent_channel_id: uuid.UUID = Query(...),
    bot_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    auth_result=Depends(require_scopes("chat")),
):
    """Resolve the caller's current scratch session for ``(channel, user)``.

    Spawns one if none exists. The returned session_id is stable across
    devices — different tabs / phones / etc. hit the same row as long as
    the authenticated user hasn't reset since.
    """
    from app.agent.bots import get_bot
    from app.db.models import User
    from app.services.sub_sessions import (
        SESSION_TYPE_EPHEMERAL,
        spawn_ephemeral_session,
    )

    auth_user = auth_result if isinstance(auth_result, User) else None
    if auth_user is None:
        raise HTTPException(
            status_code=400,
            detail="Scratch sessions require an authenticated user.",
        )

    try:
        get_bot(bot_id)
    except (HTTPException, DomainError):
        raise HTTPException(status_code=400, detail=f"Unknown bot: {bot_id}")

    channel = await db.get(Channel, parent_channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Parent channel not found")

    existing = (await db.execute(
        select(Session).where(
            Session.parent_channel_id == parent_channel_id,
            Session.owner_user_id == auth_user.id,
            Session.session_type == SESSION_TYPE_EPHEMERAL,
            Session.is_current.is_(True),
        ).limit(1)
    )).scalar_one_or_none()

    if existing is not None:
        counts, section_counts, previews = await _session_stats(db, [existing])
        return ScratchSessionOut(
            session_id=existing.id,
            parent_channel_id=parent_channel_id,
            bot_id=existing.bot_id,
            created_at=existing.created_at,
            is_current=True,
            title=_selector_title(existing, previews.get(existing.id)),
            summary=existing.summary,
            message_count=counts.get(existing.id, 0),
            section_count=section_counts.get(existing.id, 0),
            session_scope=_derive_session_scope(existing, channel),
        )

    bootstrap_metadata = await _build_bootstrap_metadata(db, parent_channel_id)
    sub = await spawn_ephemeral_session(
        db,
        bot_id=bot_id,
        parent_channel_id=parent_channel_id,
        owner_user_id=auth_user.id,
        is_current=True,
    )
    if bootstrap_metadata:
        sub.metadata_ = {**(sub.metadata_ or {}), **bootstrap_metadata}
    await db.commit()
    await db.refresh(sub)

    return ScratchSessionOut(
        session_id=sub.id,
        parent_channel_id=parent_channel_id,
        bot_id=sub.bot_id,
        created_at=sub.created_at,
        is_current=True,
        title=sub.title,
        summary=sub.summary,
        message_count=0,
        section_count=0,
        session_scope=_derive_session_scope(sub, channel),
    )


@router.post("/scratch/reset", response_model=ScratchSessionOut, status_code=201)
async def reset_scratch_session(
    body: ScratchResetRequest,
    db: AsyncSession = Depends(get_db),
    auth_result=Depends(require_scopes("chat")),
):
    """Mark the current scratch session ended and spawn a fresh one.

    The old session is preserved (``is_current=False``) and remains
    queryable via ``GET /sessions/scratch/list``.
    """
    from app.agent.bots import get_bot
    from app.db.models import User
    from app.services.sub_sessions import (
        SESSION_TYPE_EPHEMERAL,
        spawn_ephemeral_session,
    )

    auth_user = auth_result if isinstance(auth_result, User) else None
    if auth_user is None:
        raise HTTPException(
            status_code=400,
            detail="Scratch sessions require an authenticated user.",
        )

    try:
        get_bot(body.bot_id)
    except (HTTPException, DomainError):
        raise HTTPException(status_code=400, detail=f"Unknown bot: {body.bot_id}")

    channel = await db.get(Channel, body.parent_channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Parent channel not found")

    # Flip any existing current scratch(es) to archived BEFORE inserting
    # the new row so the partial unique index never sees two currents.
    await db.execute(
        update(Session)
        .where(
            Session.parent_channel_id == body.parent_channel_id,
            Session.owner_user_id == auth_user.id,
            Session.session_type == SESSION_TYPE_EPHEMERAL,
            Session.is_current.is_(True),
        )
        .values(is_current=False)
    )

    bootstrap_metadata = await _build_bootstrap_metadata(db, body.parent_channel_id)
    sub = await spawn_ephemeral_session(
        db,
        bot_id=body.bot_id,
        parent_channel_id=body.parent_channel_id,
        owner_user_id=auth_user.id,
        is_current=True,
    )
    if bootstrap_metadata:
        sub.metadata_ = {**(sub.metadata_ or {}), **bootstrap_metadata}
    await db.commit()
    await db.refresh(sub)

    return ScratchSessionOut(
        session_id=sub.id,
        parent_channel_id=body.parent_channel_id,
        bot_id=sub.bot_id,
        created_at=sub.created_at,
        is_current=True,
        title=sub.title,
        summary=sub.summary,
        message_count=0,
        section_count=0,
        session_scope=_derive_session_scope(sub, channel),
    )


@router.get("/scratch/list", response_model=list[ScratchHistoryItem])
async def list_scratch_sessions(
    parent_channel_id: uuid.UUID = Query(...),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    auth_result=Depends(require_scopes("chat")),
):
    """List the caller's scratch sessions for a channel, newest first.

    Includes both the current scratch (``is_current=True``) and prior
    archived ones. Each row carries a short preview of the first user
    message for UI rendering.
    """
    from app.db.models import User
    from app.services.sub_sessions import SESSION_TYPE_EPHEMERAL

    auth_user = auth_result if isinstance(auth_result, User) else None
    if auth_user is None:
        raise HTTPException(
            status_code=400,
            detail="Scratch sessions require an authenticated user.",
        )

    rows = (await db.execute(
        select(Session)
        .where(
            Session.parent_channel_id == parent_channel_id,
            Session.owner_user_id == auth_user.id,
            Session.session_type == SESSION_TYPE_EPHEMERAL,
        )
        # Recents should reflect activity, not the implementation detail of
        # which row currently owns the scratch pointer.
        .order_by(Session.last_active.desc(), Session.created_at.desc())
        .limit(limit)
    )).scalars().all()

    if not rows:
        return []

    session_ids = [s.id for s in rows]
    counts, section_counts, preview_by_session = await _session_stats(db, rows)
    channel = await db.get(Channel, parent_channel_id)

    return [
        ScratchHistoryItem(
            session_id=s.id,
            bot_id=s.bot_id,
            created_at=s.created_at,
            last_active=s.last_active,
            is_current=bool(s.is_current),
            message_count=counts.get(s.id, 0),
            preview=preview_by_session.get(s.id),
            title=_selector_title(s, preview_by_session.get(s.id)),
            summary=s.summary,
            section_count=section_counts.get(s.id, 0),
            session_scope=_derive_session_scope(s, channel),
        )
        for s in rows
    ]


@router.get("/{session_id}/machine-target", response_model=SessionMachineTargetOut)
async def get_session_machine_target(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(verify_user),
):
    _require_admin_user(user)
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    presence.mark_active(user.id)
    payload = await build_session_machine_target_payload(db, session=session)
    return SessionMachineTargetOut(**payload)


@router.post("/{session_id}/machine-target/lease", response_model=SessionMachineTargetOut)
async def grant_session_machine_target_lease(
    session_id: uuid.UUID,
    body: SessionMachineTargetLeaseRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(verify_user),
):
    _require_admin_user(user)
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    presence.mark_active(user.id)
    try:
        await grant_session_lease(
            db,
            session=session,
            user=user,
            provider_id=body.provider_id,
            target_id=body.target_id,
            ttl_seconds=max(30, min(body.ttl_seconds, MAX_LEASE_TTL_SECONDS)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    payload = await build_session_machine_target_payload(db, session=session)
    return SessionMachineTargetOut(**payload)


@router.delete("/{session_id}/machine-target/lease", response_model=SessionMachineTargetOut)
async def clear_session_machine_target_lease(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(verify_user),
):
    _require_admin_user(user)
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await clear_session_lease_row(db, session)
    await db.commit()
    await db.refresh(session)
    payload = await build_session_machine_target_payload(db, session=session)
    return SessionMachineTargetOut(**payload)


@router.patch("/{session_id}", response_model=SessionOutDetail)
async def update_session(
    session_id: uuid.UUID,
    body: SessionPatchRequest,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    from app.db.models import User

    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="title is required")

    auth_user = auth if isinstance(auth, User) else None
    if auth_user is None:
        raise HTTPException(status_code=403, detail="User auth required")

    if session.session_type == "ephemeral":
        if session.owner_user_id != auth_user.id:
            raise HTTPException(status_code=403, detail="Scratch session not owned by user")
        if not (_auth_has_scope(auth, "chat") or _auth_has_scope(auth, "sessions:write")):
            raise HTTPException(status_code=403, detail="sessions:write required")
    else:
        channel = await db.get(Channel, session.channel_id) if session.channel_id else None
        if channel is None:
            raise HTTPException(status_code=400, detail="Channel session missing channel")
        if not _auth_has_scope(auth, "channels.messages:write"):
            raise HTTPException(status_code=403, detail="channels.messages:write required")
        from app.routers.api_v1_channels import _check_protected
        _check_protected(channel, auth)

    session.title = title
    await db.commit()
    return SessionOutDetail(session_id=session.id, title=session.title, summary=session.summary)


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Delete a session row and its transcript.

    Safety rules:
    - Active channel-primary sessions cannot be deleted directly.
    - Scratch sessions require owner-user auth.
    """
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    channel, _ = await _authorize_session_project_instance_write(db, session, auth)

    if session.session_type != "ephemeral":
        if channel is None:
            raise HTTPException(status_code=400, detail="Channel session missing channel")
        if channel.active_session_id == session.id:
            raise HTTPException(
                status_code=409,
                detail="Cannot delete the channel primary session. Set another session as primary first.",
            )

    await db.delete(session)
    await db.commit()
    return None


@router.get("/{session_id}/project-instance", response_model=SessionProjectInstanceOut)
async def get_session_project_instance(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    channel, _ = await _authorize_session_read(db, session, auth)
    return await _session_project_instance_out(db, session, channel=channel)


@router.post("/{session_id}/project-instance", response_model=SessionProjectInstanceOut)
async def create_session_project_instance(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    from app.services.project_instances import bind_fresh_project_instance_to_session

    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    channel, _ = await _authorize_session_project_instance_write(db, session, auth)
    project_id = getattr(channel, "project_id", None) if channel is not None else None
    if project_id is None:
        raise HTTPException(status_code=422, detail="Session is not attached to a Project-bound channel")
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        instance = await bind_fresh_project_instance_to_session(db, session=session, project=project)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SessionProjectInstanceOut(
        session_id=session.id,
        project_instance_id=instance.id,
        project_id=instance.project_id,
        project_name=project.name,
        workspace_id=instance.workspace_id,
        status=instance.status,
        root_path=instance.root_path,
        expires_at=instance.expires_at,
        created_at=instance.created_at,
    )


@router.delete("/{session_id}/project-instance", response_model=SessionProjectInstanceOut)
async def clear_session_project_instance(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    channel, _ = await _authorize_session_project_instance_write(db, session, auth)
    session.project_instance_id = None
    await db.commit()
    return await _session_project_instance_out(db, session, channel=channel)


class ApprovalModeOut(BaseModel):
    mode: str


class ApprovalModeIn(BaseModel):
    mode: str


@router.get("/{session_id}/approval-mode", response_model=ApprovalModeOut)
async def get_approval_mode(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_scopes("approvals:read")),
):
    """Return the current harness approval mode for the session.

    One of ``bypassPermissions`` (default) | ``acceptEdits`` | ``default`` |
    ``plan``. Authorized through ``_authorize_session_read`` so a valid
    scoped key alone isn't enough — the caller must also have visibility
    into the session's channel/owner.
    """
    from app.services.agent_harnesses.approvals import (
        DEFAULT_MODE,
        HARNESS_APPROVAL_MODE_KEY,
    )

    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await _authorize_session_read(db, session, auth)
    mode = (session.metadata_ or {}).get(HARNESS_APPROVAL_MODE_KEY) or DEFAULT_MODE
    return ApprovalModeOut(mode=mode)


@router.post("/{session_id}/approval-mode", response_model=ApprovalModeOut)
async def set_approval_mode(
    session_id: uuid.UUID,
    body: ApprovalModeIn,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_scopes("approvals:write")),
):
    """Update the harness approval mode for the session.

    Mode changes apply to the **next** turn — the in-flight turn (if any)
    captured its mode in ``TurnContext`` at start.
    """
    from app.services.agent_harnesses.approvals import (
        VALID_MODES,
        set_session_mode,
    )

    if body.mode not in VALID_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"unknown approval mode: {body.mode!r}",
        )
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await _authorize_session_read(db, session, auth)
    await set_session_mode(db, session_id, body.mode)
    return ApprovalModeOut(mode=body.mode)


class HarnessSettingsOut(BaseModel):
    model: str | None = None
    effort: str | None = None
    runtime_settings: dict[str, Any] = {}
    mode_models: dict[str, str] = {}


class HarnessSettingsPatch(BaseModel):
    """Partial update body. Missing key = no change. JSON ``null`` = clear field.

    Decoded via ``body.dict(exclude_unset=True)`` so handlers can distinguish
    "not provided" from "explicitly cleared".
    """

    model: str | None = None
    effort: str | None = None
    runtime_settings: dict[str, Any] | None = None


@router.get("/{session_id}/harness-settings", response_model=HarnessSettingsOut)
async def get_harness_settings(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_scopes("approvals:read")),
):
    """Return per-session harness settings (model / effort / runtime knobs).

    Symmetric with ``/approval-mode``: same scope tier (``approvals:read``)
    and same ``_authorize_session_read`` ownership boundary.
    """
    from app.services.agent_harnesses.settings import load_session_settings

    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await _authorize_session_read(db, session, auth)
    settings = await load_session_settings(db, session_id)
    return HarnessSettingsOut(
        model=settings.model,
        effort=settings.effort,
        runtime_settings=dict(settings.runtime_settings),
        mode_models=dict(settings.mode_models),
    )


class HarnessStatusOut(BaseModel):
    runtime: str | None = None
    harness_session_id: str | None = None
    model: str | None = None
    effort: str | None = None
    default_model: str | None = None
    default_effort: str | None = None
    effective_model: str | None = None
    effective_effort: str | None = None
    permission_mode: str | None = None
    session_plan_mode: str | None = None
    pending_hint_count: int = 0
    last_compacted_at: str | None = None
    last_turn_at: str | None = None
    usage: dict[str, Any] | None = None
    cost_usd: float | None = None
    context_window_tokens: int | None = None
    context_remaining_pct: float | None = None
    context_remaining_source: str | None = None
    context_diagnostics: dict[str, Any] | None = None
    native_compaction: dict[str, Any] | None = None
    hints: list[dict[str, Any]] = Field(default_factory=list)
    next_turn_computed_hints: list[dict[str, Any]] = Field(default_factory=list)
    next_turn_hints: list[dict[str, Any]] = Field(default_factory=list)
    last_hints_sent: list[dict[str, Any]] = Field(default_factory=list)
    effective_cwd: str | None = None
    effective_cwd_source: str | None = None
    bot_workspace_dir: str | None = None
    project_dir: dict[str, Any] | None = None
    bridge_status: dict[str, Any] = Field(default_factory=dict)
    input_manifest: dict[str, Any] | None = None
    run_inspector: dict[str, Any] = Field(default_factory=dict)
    context_note: str


def _build_harness_run_inspector(
    *,
    runtime: str | None,
    harness_meta: dict[str, Any],
    settings: Any,
    permission_mode: str | None,
    session_plan_mode: str | None,
    last_turn_at: str | None,
    workdir: str | None,
    workdir_source: str | None,
    bridge_status: dict[str, Any],
) -> dict[str, Any]:
    """Condense the last persisted harness turn into operator-debug fields."""
    input_manifest = harness_meta.get("input_manifest")
    manifest_summary: dict[str, Any] = {}
    if isinstance(input_manifest, dict):
        attachments = input_manifest.get("attachments")
        runtime_items = input_manifest.get("runtime_items")
        workspace_uploads = input_manifest.get("workspace_uploads")
        tagged_skills = input_manifest.get("tagged_skill_ids")
        manifest_summary = {
            "attachment_count": len(attachments) if isinstance(attachments, list) else 0,
            "workspace_upload_count": len(workspace_uploads) if isinstance(workspace_uploads, list) else 0,
            "tagged_skill_count": len(tagged_skills) if isinstance(tagged_skills, list) else 0,
            "runtime_item_count": len(runtime_items) if isinstance(runtime_items, list) else 0,
            "runtime_item_counts": input_manifest.get("runtime_item_counts") or {},
            "warnings": input_manifest.get("warnings") or [],
        }

    exported_tools = bridge_status.get("exported_tools")
    inventory_errors = bridge_status.get("inventory_errors")
    missing_baseline = bridge_status.get("missing_baseline_tools")
    native_slash = harness_meta.get("claude_native_slash_commands")
    latency = harness_meta.get("codex_latency_ms") or harness_meta.get("claude_latency_ms")
    dynamic_tools = harness_meta.get("codex_dynamic_tools")

    return {
        "runtime": runtime,
        "native_session_id": harness_meta.get("session_id"),
        "last_turn_at": last_turn_at,
        "cwd": workdir,
        "cwd_source": workdir_source,
        "model": getattr(settings, "model", None),
        "effort": getattr(settings, "effort", None),
        "permission_mode": permission_mode,
        "session_plan_mode": session_plan_mode,
        "latency_ms": latency if isinstance(latency, dict) else {},
        "input_manifest": manifest_summary,
        "bridge": {
            "status": bridge_status.get("status"),
            "exported_tool_count": len(exported_tools) if isinstance(exported_tools, list) else 0,
            "inventory_error_count": len(inventory_errors) if isinstance(inventory_errors, list) else 0,
            "missing_baseline_tools": missing_baseline if isinstance(missing_baseline, list) else [],
        },
        "native_inventory": {
            "claude_slash_command_count": len(native_slash) if isinstance(native_slash, list) else 0,
            "claude_slash_commands": native_slash if isinstance(native_slash, list) else [],
            "codex_dynamic_tools": dynamic_tools if isinstance(dynamic_tools, list) else [],
            "codex_thread_restart_reason": harness_meta.get("codex_thread_restart_reason"),
        },
        "error": harness_meta.get("error"),
        "interrupted": bool(harness_meta.get("interrupted")),
    }


class HarnessQuestionAnswerIn(BaseModel):
    question_id: str
    answer: str | None = None
    selected_options: list[str] = Field(default_factory=list)


class HarnessQuestionAnswerRequest(BaseModel):
    answers: list[HarnessQuestionAnswerIn]
    notes: str | None = None


class HarnessQuestionAnswerOut(BaseModel):
    interaction_id: uuid.UUID
    live_resolved: bool
    task_id: uuid.UUID | None = None


class HarnessQuestionCancelOut(BaseModel):
    interaction_id: uuid.UUID
    status: str


@router.get("/{session_id}/harness-status", response_model=HarnessStatusOut)
async def get_harness_status(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_scopes("approvals:read")),
):
    """Return lightweight native-harness state for the current session surface."""
    from app.services.agent_harnesses.approvals import load_session_mode
    from app.services.session_plan_mode import get_session_plan_mode
    from app.services.agent_harnesses.session_state import (
        HARNESS_RESUME_RESET_AT_KEY,
        context_window_from_usage,
        estimate_native_compaction_remaining_pct,
        hint_preview,
        load_bridge_status,
        load_context_hints,
        load_latest_harness_metadata,
        load_native_compaction,
        normalize_context_usage,
    )
    from app.services.agent_harnesses.settings import load_session_settings
    from app.services.agent_harnesses.project import (
        build_workspace_files_memory_hint,
        project_directory_payload,
        resolve_harness_paths,
    )
    from app.services.agent_harnesses import HARNESS_REGISTRY
    from app.services.agent_harnesses.capabilities import resolve_runtime_effective_defaults
    from app.agent.bots import get_bot

    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await _authorize_session_read(db, session, auth)
    mode = await load_session_mode(db, session_id)
    session_plan_mode = get_session_plan_mode(session)
    settings = await load_session_settings(db, session_id)
    hints = await load_context_hints(db, session_id)
    bridge_status = await load_bridge_status(db, session_id)
    harness_meta, last_turn_at = await load_latest_harness_metadata(db, session_id)
    bot = get_bot(session.bot_id)
    harness_paths = await resolve_harness_paths(
        db,
        channel_id=session.channel_id or session.parent_channel_id,
        bot=bot,
    )
    computed_hints = []
    memory_hint = build_workspace_files_memory_hint(bot, harness_paths.bot_workspace_dir)
    if memory_hint is not None:
        computed_hints.append(memory_hint)
    runtime_name = ((harness_meta or {}).get("runtime") if harness_meta else None) or bot.harness_runtime
    runtime = HARNESS_REGISTRY.get(runtime_name) if runtime_name else None
    usage = (harness_meta or {}).get("usage") if harness_meta else None
    caps = runtime.capabilities() if runtime and hasattr(runtime, "capabilities") else None
    default_model = None
    default_effort = None
    if runtime is not None:
        default_model, default_effort = await resolve_runtime_effective_defaults(runtime)
    effective_model = settings.model or default_model
    effective_effort = settings.effort or default_effort
    context_window_tokens = (
        context_window_from_usage(usage)
        or (getattr(caps, "context_window_tokens", None) if caps else None)
    )
    native_compaction = await load_native_compaction(db, session_id)
    meta = session.metadata_ or {}
    context_diagnostics = normalize_context_usage(
        usage if isinstance(usage, dict) else None,
        runtime=runtime_name,
        context_window_tokens=context_window_tokens,
        source="last_turn",
    )
    remaining_pct = context_diagnostics.get("remaining_pct")
    if not isinstance(remaining_pct, (int, float)):
        remaining_pct = None
    remaining_source = "last_turn" if remaining_pct is not None else None
    compact_created_at = None
    if native_compaction and isinstance(native_compaction.get("created_at"), str):
        try:
            compact_created_at = datetime.fromisoformat(str(native_compaction.get("created_at")))
        except ValueError:
            compact_created_at = None
    compact_is_latest = False
    if compact_created_at is not None:
        if last_turn_at is None:
            compact_is_latest = True
        else:
            try:
                compact_is_latest = compact_created_at >= last_turn_at
            except TypeError:
                compact_is_latest = compact_created_at >= last_turn_at.replace(tzinfo=timezone.utc)
    if native_compaction and native_compaction.get("status") == "completed" and compact_is_latest:
        compact_usage = native_compaction.get("usage")
        compact_remaining = estimate_native_compaction_remaining_pct(
            compact_usage if isinstance(compact_usage, dict) else None,
            context_window_tokens=context_window_tokens,
        )
        if compact_remaining is not None:
            remaining_pct = compact_remaining
            remaining_source = "native_compaction"
            compact_after = native_compaction.get("context_after")
            if isinstance(compact_after, dict):
                context_diagnostics = {
                    **compact_after,
                    "source": "native_compaction",
                    "raw_usage": compact_usage if isinstance(compact_usage, dict) else None,
                }
        elif context_window_tokens:
            remaining_pct = 100.0
            remaining_source = "native_compaction"
            context_diagnostics = {
                "runtime": runtime_name,
                "source": "native_compaction",
                "confidence": "low",
                "context_window_tokens": context_window_tokens,
                "context_tokens": None,
                "remaining_pct": 100.0,
                "source_fields": [],
                "reason": "native compact completed without usable usage telemetry",
                "raw_usage": compact_usage if isinstance(compact_usage, dict) else None,
            }
    run_inspector = _build_harness_run_inspector(
        runtime=runtime_name,
        harness_meta=harness_meta or {},
        settings=settings,
        permission_mode=mode,
        session_plan_mode=session_plan_mode,
        last_turn_at=last_turn_at.isoformat() if last_turn_at else None,
        workdir=(harness_meta or {}).get("effective_cwd") or harness_paths.workdir,
        workdir_source=(harness_meta or {}).get("effective_cwd_source") or harness_paths.source,
        bridge_status=bridge_status,
    )
    return HarnessStatusOut(
        runtime=runtime_name,
        harness_session_id=(harness_meta or {}).get("session_id") if harness_meta else None,
        model=settings.model,
        effort=settings.effort,
        default_model=default_model,
        default_effort=default_effort,
        effective_model=effective_model,
        effective_effort=effective_effort,
        permission_mode=mode,
        session_plan_mode=session_plan_mode,
        pending_hint_count=len(hints),
        last_compacted_at=meta.get(HARNESS_RESUME_RESET_AT_KEY)
        if isinstance(meta.get(HARNESS_RESUME_RESET_AT_KEY), str)
        else None,
        last_turn_at=last_turn_at.isoformat() if last_turn_at else None,
        usage=usage,
        cost_usd=(harness_meta or {}).get("cost_usd") if harness_meta else None,
        context_window_tokens=context_window_tokens,
        context_remaining_pct=remaining_pct,
        context_remaining_source=remaining_source,
        context_diagnostics=context_diagnostics,
        native_compaction=native_compaction,
        hints=[hint_preview(hint) for hint in hints],
        next_turn_computed_hints=[hint_preview(hint) for hint in computed_hints],
        next_turn_hints=[hint_preview(hint) for hint in [*hints, *computed_hints]],
        last_hints_sent=(harness_meta or {}).get("last_hints_sent") or [],
        effective_cwd=(harness_meta or {}).get("effective_cwd") or harness_paths.workdir,
        effective_cwd_source=(harness_meta or {}).get("effective_cwd_source") or harness_paths.source,
        bot_workspace_dir=(harness_meta or {}).get("bot_workspace_dir") or harness_paths.bot_workspace_dir,
        project_dir=(harness_meta or {}).get("project_dir") or project_directory_payload(harness_paths.project_dir),
        bridge_status=bridge_status,
        input_manifest=(harness_meta or {}).get("input_manifest") if harness_meta else None,
        run_inspector=run_inspector,
        context_note=(
            "Native harness context is provider-managed; Spindrel tracks resume id, "
            "native compaction events, and pending host hints for this session."
        ),
    )


@router.post(
    "/{session_id}/harness-interactions/{interaction_id}/answer",
    response_model=HarnessQuestionAnswerOut,
)
async def answer_harness_interaction(
    session_id: uuid.UUID,
    interaction_id: uuid.UUID,
    body: HarnessQuestionAnswerRequest,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_scopes("sessions:write")),
):
    """Answer a harness-native question card for the current session.

    If the SDK callback is still alive, resolving it continues the same
    harness turn. If the process restarted and no callback exists, the stored
    answer starts a fresh harness task against the same Spindrel session.
    """
    from app.services.agent_harnesses.interactions import (
        HarnessQuestionAnswer,
        answer_harness_question,
    )

    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await _authorize_session_read(db, session, auth)
    try:
        result, live_resolved = await answer_harness_question(
            db=db,
            session_id=session_id,
            interaction_id=str(interaction_id),
            answers=[
                HarnessQuestionAnswer(
                    question_id=item.question_id,
                    answer=item.answer,
                    selected_options=item.selected_options,
                )
                for item in body.answers
            ],
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    task_id: uuid.UUID | None = None
    if not live_resolved:
        answer_text = ""
        if result.answer_message_id is not None:
            answer_row = await db.get(Message, result.answer_message_id)
            answer_text = answer_row.content if answer_row and answer_row.content else ""
        task = Task(
            bot_id=session.bot_id,
            client_id=session.client_id,
            session_id=session_id,
            channel_id=session.channel_id,
            prompt=answer_text or "Continue from the harness question answer.",
            status="pending",
            task_type="api",
            dispatch_type=(session.dispatch_config or {}).get("type") or "none",
            dispatch_config=session.dispatch_config or {},
            execution_config={
                **({"pre_user_msg_id": str(result.answer_message_id)} if result.answer_message_id else {}),
                "harness_question_id": str(interaction_id),
            },
            created_at=datetime.now(timezone.utc),
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        task_id = task.id

    return HarnessQuestionAnswerOut(
        interaction_id=interaction_id,
        live_resolved=live_resolved,
        task_id=task_id,
    )


@router.post(
    "/{session_id}/harness-interactions/{interaction_id}/cancel",
    response_model=HarnessQuestionCancelOut,
)
async def cancel_harness_interaction(
    session_id: uuid.UUID,
    interaction_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_scopes("sessions:write")),
):
    """Dismiss a pending/stale harness question without sending an answer."""
    from app.services.agent_harnesses.interactions import expire_harness_question

    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await _authorize_session_read(db, session, auth)
    row = await db.get(Message, interaction_id)
    if row is None or row.session_id != session_id:
        raise HTTPException(status_code=404, detail="harness question not found")
    meta = row.metadata_ or {}
    if not isinstance(meta, dict) or meta.get("kind") != "harness_question":
        raise HTTPException(status_code=404, detail="harness question not found")

    await expire_harness_question(str(interaction_id), status="cancelled")
    return HarnessQuestionCancelOut(interaction_id=interaction_id, status="cancelled")


@router.post("/{session_id}/harness-settings", response_model=HarnessSettingsOut)
async def set_harness_settings(
    session_id: uuid.UUID,
    body: HarnessSettingsPatch,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_scopes("approvals:write")),
):
    """Patch per-session harness settings.

    Settings apply to the **next** turn — the in-flight turn captured its
    model/effort in ``TurnContext`` at start.

    NOTE: ``approvals:write`` here is intentional v1 expedience — these
    settings change runtime behavior in a policy-adjacent way. A dedicated
    ``harness:write`` (or ``sessions:write`` extension) scope may replace
    this in a future phase; do not extend ``approvals:write`` to other
    non-policy surfaces.
    """
    from app.services.agent_harnesses.settings import patch_session_settings

    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await _authorize_session_read(db, session, auth)
    patch = body.model_dump(exclude_unset=True)
    try:
        settings = await patch_session_settings(db, session_id, patch=patch)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return HarnessSettingsOut(
        model=settings.model,
        effort=settings.effort,
        runtime_settings=dict(settings.runtime_settings),
        mode_models=dict(settings.mode_models),
    )


@router.get("/{session_id}/summary", response_model=SessionSummaryOut)
async def get_session_summary(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Return lightweight session metadata for UI resume cards.

    This avoids loading transcript rows. It returns counts, timestamps,
    title/summary, and channel/scratch scope for chat surface labeling.
    """
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    channel, _ = await _authorize_session_read(db, session, auth)
    message_count = (await db.execute(
        select(func.count(Message.id)).where(
            Message.session_id == session_id,
            Message.role.in_(("user", "assistant")),
        )
    )).scalar_one()
    section_count = (await db.execute(
        select(func.count(ConversationSection.id)).where(
            ConversationSection.session_id == session_id,
        )
    )).scalar_one()

    preview = None
    if not (session.title or "").strip():
        preview = (await db.execute(
            select(Message.content)
            .where(
                Message.session_id == session_id,
                Message.role == "user",
                Message.content.is_not(None),
            )
            .order_by(Message.created_at.asc())
            .limit(1)
        )).scalar_one_or_none()
    project_instance_payload = await _session_project_instance_out(db, session, channel=channel)

    return SessionSummaryOut(
        session_id=session.id,
        bot_id=session.bot_id,
        channel_id=session.channel_id,
        parent_channel_id=session.parent_channel_id,
        session_type=session.session_type,
        title=_selector_title(session, preview),
        summary=session.summary,
        created_at=session.created_at,
        last_active=session.last_active,
        message_count=int(message_count or 0),
        section_count=int(section_count or 0),
        is_current=bool(session.is_current),
        session_scope=_derive_session_scope(session, channel),
        project_instance_id=project_instance_payload.project_instance_id,
        project_id=project_instance_payload.project_id,
        project_instance_status=project_instance_payload.status,
        project_root_path=project_instance_payload.root_path,
    )


@router.post("/{session_id}/promote-to-primary", response_model=PromoteScratchSessionResponse)
async def promote_scratch_to_primary(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    from app.db.models import User

    auth_user = auth if isinstance(auth, User) else None
    if auth_user is None:
        raise HTTPException(status_code=403, detail="User auth required")
    if not _auth_has_scope(auth, "channels.messages:write"):
        raise HTTPException(status_code=403, detail="channels.messages:write required")

    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.session_type != "ephemeral" or session.parent_channel_id is None:
        raise HTTPException(status_code=400, detail="Session is not a scratch session")
    if session.owner_user_id != auth_user.id:
        raise HTTPException(status_code=403, detail="Scratch session not owned by user")

    channel = await db.get(Channel, session.parent_channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Parent channel not found")

    from app.routers.api_v1_channels import _check_protected
    _check_protected(channel, auth)

    previous_primary_id = channel.active_session_id
    if previous_primary_id is None:
        raise HTTPException(status_code=400, detail="Channel has no active session")
    if previous_primary_id == session.id:
        raise HTTPException(status_code=400, detail="Scratch session is already primary")

    previous_primary = await db.get(Session, previous_primary_id)
    if previous_primary is None:
        raise HTTPException(status_code=404, detail="Current primary session not found")

    await db.execute(
        update(Session)
        .where(
            Session.parent_channel_id == channel.id,
            Session.owner_user_id == auth_user.id,
            Session.session_type == "ephemeral",
            Session.is_current.is_(True),
        )
        .values(is_current=False)
    )

    session.channel_id = channel.id
    session.parent_channel_id = None
    session.owner_user_id = None
    session.is_current = False
    session.session_type = "channel"
    session.metadata_ = {
        **(session.metadata_ or {}),
        "promoted_from_scratch": True,
    }

    previous_primary.channel_id = None
    previous_primary.parent_channel_id = channel.id
    previous_primary.owner_user_id = auth_user.id
    previous_primary.is_current = True
    previous_primary.session_type = "ephemeral"
    previous_primary.metadata_ = {
        **(previous_primary.metadata_ or {}),
        "demoted_from_primary": True,
    }

    channel.active_session_id = session.id
    channel.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return PromoteScratchSessionResponse(
        channel_id=channel.id,
        primary_session_id=session.id,
        demoted_session_id=previous_primary.id,
    )


@router.post("/{session_id}/messages", response_model=InjectResponse, status_code=201)
async def inject_message(
    session_id: uuid.UUID,
    body: MessageInject,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:write")),
):
    """
    Inject a message into a session from an external integration.

    - `notify=true` (default): fans out to the session's dispatch targets (e.g. Slack)
    - `run_agent=true`: schedules an async agent Task that will process this message
    """
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    metadata = {"source": body.source} if body.source else {}
    await store_passive_message(db, session_id, body.content, metadata, channel_id=session.channel_id, role=body.role)

    # Retrieve the stored message id
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    msg = result.scalar_one()
    await db.commit()

    task_id: uuid.UUID | None = None

    if body.notify:
        await _fanout(session, body.content, body.source)

    if body.run_agent:
        # Forward the pre-persisted user message id so persist_turn skips it
        # at the end of the agent loop. See app/agent/tasks.py _run_one_task.
        task = Task(
            bot_id=session.bot_id,
            client_id=session.client_id,
            session_id=session_id,
            channel_id=session.channel_id,
            prompt=body.content,
            status="pending",
            task_type="api",
            dispatch_type=(session.dispatch_config or {}).get("type") or "none",
            dispatch_config=session.dispatch_config or {},
            execution_config={"pre_user_msg_id": str(msg.id)},
            created_at=datetime.now(timezone.utc),
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        task_id = task.id

    return InjectResponse(message_id=msg.id, session_id=session_id, task_id=task_id)


@router.get("/{session_id}/messages", response_model=list[MessageOut])
async def list_messages(
    session_id: uuid.UUID,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:read")),
):
    """List messages for a session, most recent first."""
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    result = await db.execute(
        select(Message)
        .options(selectinload(Message.attachments))
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    messages = list(result.scalars().all())
    messages.reverse()

    # Recover orphaned attachments (send_file creates with message_id=NULL)
    if session.channel_id:
        await _recover_orphan_attachments(db, session.channel_id, messages)

    return [MessageOut.from_orm(m) for m in messages]


# ---------------------------------------------------------------------------
# Tool call result fetch — session-scoped, used by the rich tool result UI
# to lazy-fetch full bodies that exceeded the inline envelope cap.
# ---------------------------------------------------------------------------


class ToolCallResultOut(BaseModel):
    """Full untruncated body of a tool call result."""

    id: uuid.UUID
    tool_name: str
    content_type: str = "text/plain"
    body: str
    byte_size: int


@router.get("/{session_id}/tool-calls/{tool_call_id}/result", response_model=ToolCallResultOut)
async def get_session_tool_call_result(
    session_id: uuid.UUID,
    tool_call_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:read")),
):
    """Return the full untruncated body of a tool call result.

    The rich tool-result envelope (``Message.metadata.tool_results[i]``) caps
    inline body at 4KB to keep SSE / metadata payloads small. When the body
    exceeds the cap, the envelope sets ``truncated=true`` and points to a
    ``record_id``. The web UI fetches the full body via this endpoint when
    the user clicks "Show full output".

    Auth boundary: ``sessions:read`` plus a check that the tool_call belongs
    to the path session. Mirrors the admin endpoint at
    ``app/routers/api_v1_tool_calls.py:155`` (which uses ``logs:read`` and
    isn't reachable from the UI).
    """
    row = await db.get(ToolCall, tool_call_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Tool call not found")
    if row.session_id != session_id:
        raise HTTPException(status_code=404, detail="Tool call not found in this session")

    body = row.result or ""
    return ToolCallResultOut(
        id=row.id,
        tool_name=row.tool_name,
        # Mimetype isn't persisted on the tool_calls row — the envelope on
        # the Message metadata carries it. Default to text/plain; the UI
        # already has the envelope context to know what renderer to use.
        content_type="text/plain",
        body=body,
        byte_size=len(body.encode("utf-8")),
    )


async def _recover_orphan_attachments(
    db: AsyncSession,
    channel_id: uuid.UUID,
    messages: list[Message],
) -> None:
    """Link orphaned attachments (message_id=NULL) to the nearest assistant message."""
    orphan_result = await db.execute(
        select(Attachment)
        .where(
            Attachment.channel_id == channel_id,
            Attachment.message_id.is_(None),
        )
    )
    orphans = list(orphan_result.scalars().all())
    if not orphans:
        return

    logger.warning(
        "Found %d orphaned attachment(s) in channel %s — recovering",
        len(orphans), channel_id,
    )
    assistant_msgs = [m for m in messages if m.role == "assistant"]
    if not assistant_msgs:
        return

    linked = 0
    for att in orphans:
        best = None
        for m in assistant_msgs:
            if m.created_at >= att.created_at:
                best = m
                break
        if best is None:
            best = assistant_msgs[-1]
        att.message_id = best.id
        if not hasattr(best, "attachments") or best.attachments is None:
            best.attachments = []
        best.attachments.append(att)
        linked += 1

    if linked:
        await db.commit()
        logger.info("Recovered %d orphan attachment(s) in channel %s", linked, channel_id)


# ---------------------------------------------------------------------------
# Context debug — replay what the LLM would see
# ---------------------------------------------------------------------------


class ContextMessage(BaseModel):
    role: str
    content: str | None = None
    tool_calls: Any | None = None
    tool_call_id: str | None = None
    chars: int = 0


class ContextDebugOut(BaseModel):
    session_id: uuid.UUID
    bot_id: str
    message_count: int
    total_chars: int
    messages: list[ContextMessage]


# ---------------------------------------------------------------------------
# Real-time session events (SSE) — for channel-less ephemeral sessions
# ---------------------------------------------------------------------------


@router.get("/{session_id}/events")
async def session_events(
    session_id: uuid.UUID,
    since: int | None = None,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:read")),
):
    """SSE stream of events for a channel-less ephemeral session.

    Mirrors ``GET /api/v1/channels/{channel_id}/events`` but keyed on
    session_id. The turn worker publishes to the in-memory bus under
    ``bus_key = channel_id or session_id``; for ephemeral sessions without
    a parent channel, the session_id itself is the bus key and this
    endpoint is the subscriber entry point.

    Reconnect semantics (since, replay_lapsed, keepalive) match the
    channel-events endpoint exactly.
    """
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.close()

    import asyncio
    import json
    from fastapi.responses import StreamingResponse
    from app.domain.channel_events import ChannelEventKind
    from app.services.channel_events import (
        event_to_sse_dict,
        get_shutdown_event,
        subscribe,
    )

    async def _event_stream():
        shutdown = get_shutdown_event()
        async_gen = subscribe(session_id, since=since)
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
            if not pending.done():
                pending.cancel()
                try:
                    await pending
                except (asyncio.CancelledError, Exception):
                    pass
            await async_gen.aclose()

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{session_id}/config-overhead")
async def session_config_overhead(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:read")),
):
    """Overhead estimate (tools + skills + system prompt) for a session.

    Mirrors ``GET /api/v1/admin/channels/{id}/config-overhead`` for ephemeral
    and sub-sessions so the dock can show the same yellow/red indicator.
    Applies the parent channel's overrides when present so the estimate
    matches what the LLM actually sees at turn time.
    """
    from dataclasses import asdict
    from app.agent.bots import get_bot
    from app.agent.context_budget import get_model_context_window
    from app.db.models import Channel
    from app.services.context_estimate import estimate_bot_context
    from app.services.widget_context import fetch_channel_pin_dicts

    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    bot = get_bot(session.bot_id)

    # Inherit overrides from the parent channel when the session is
    # channel-scoped. Channel-less ephemeral sessions use the bot defaults.
    channel = None
    if session.channel_id is not None:
        channel = (await db.execute(
            select(Channel).where(Channel.id == session.channel_id)
        )).scalar_one_or_none()

    local_tools = list(bot.local_tools)
    mcp_servers = list(bot.mcp_servers)
    client_tools = list(bot.client_tools or [])
    skills = [{"id": s.id, "mode": s.mode or "on_demand"} for s in bot.skills]

    channel_pinned_widgets: list[dict] = []
    effective_model = bot.model
    if channel is not None:
        disabled_local = set(channel.local_tools_disabled or [])
        disabled_mcp = set(channel.mcp_servers_disabled or [])
        disabled_client = set(channel.client_tools_disabled or [])
        if disabled_local:
            local_tools = [t for t in local_tools if t not in disabled_local]
        if disabled_mcp:
            mcp_servers = [s for s in mcp_servers if s not in disabled_mcp]
        if disabled_client:
            client_tools = [t for t in client_tools if t not in disabled_client]
        channel_pinned_widgets = await fetch_channel_pin_dicts(db, channel.id)
        effective_model = channel.model_override or bot.model

    draft: dict = {
        "name": bot.name,
        "model": effective_model,
        "system_prompt": bot.system_prompt or "",
        "persona": bool(bot.persona),
        "persona_content": "",
        "local_tools": local_tools,
        "mcp_servers": mcp_servers,
        "client_tools": client_tools,
        "pinned_tools": list(bot.pinned_tools or []),
        "skills": skills,
        "tool_retrieval": bot.tool_retrieval if bot.tool_retrieval is not None else True,
        "tool_similarity_threshold": bot.tool_similarity_threshold,
        "memory_enabled": bot.memory.enabled if bot.memory else False,
        "memory_similarity_threshold": getattr(bot.memory, "similarity_threshold", None),
        "memory_max_inject_chars": getattr(bot.memory, "max_inject_chars", None),
        "filesystem_indexes": bot.filesystem_indexes or [],
        "delegation_config": {"delegate_bots": list(bot.delegate_bots)} if bot.delegate_bots else {},
        "history_mode": bot.history_mode,
        "context_pruning": bot.context_pruning,
        "audio_input": bot.audio_input or "transcribe",
        "pinned_widgets": channel_pinned_widgets,
        "channel_config": channel.config if channel is not None else {},
    }

    result = await estimate_bot_context(draft=draft, bot_id=bot.id)

    provider_id = None
    if "/" in effective_model:
        provider_id, _ = effective_model.split("/", 1)
    context_window = get_model_context_window(effective_model, provider_id)

    return {
        "lines": [asdict(line) for line in result.lines],
        "total_chars": result.total_chars,
        "approx_tokens": result.approx_tokens,
        "context_window": context_window,
        "overhead_pct": round(result.approx_tokens / context_window, 4) if context_window else None,
        "disclaimer": result.disclaimer,
    }


@router.get("/{session_id}/context", response_model=ContextDebugOut)
async def get_session_context(
    session_id: uuid.UUID,
    query: str = Query("hello", description="Simulated user query for RAG retrieval"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:read")),
):
    """Return the full assembled context the LLM would see for a session.

    Useful for debugging context injection — shows every system message,
    memory, knowledge chunk, section index, etc. in order.
    """
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    from app.agent.bots import get_bot
    from app.agent.context_assembly import AssemblyResult, assemble_context
    from app.agent.context_profiles import resolve_context_profile
    from app.db.models import Channel
    from app.services.sessions import _load_messages

    bot = get_bot(session.bot_id)
    channel = await db.get(Channel, session.channel_id) if session.channel_id else None

    # Load messages the same way the agent loop does
    messages = await _load_messages(db, session)

    # Run context assembly (mutates messages in-place)
    result = AssemblyResult()
    async for _event in assemble_context(
        messages=messages,
        bot=bot,
        user_message=query,
        session_id=session_id,
        client_id=session.client_id,
        correlation_id=None,
        channel_id=session.channel_id,
        audio_data=None,
        audio_format=None,
        attachments=None,
        native_audio=False,
        result=result,
        context_profile_name=resolve_context_profile(session=session, channel=channel).name,
    ):
        pass  # drain events — we only want the final messages list

    # Build response
    out_messages = []
    total_chars = 0
    for m in messages:
        content = m.get("content")
        content_str = str(content) if content is not None else None
        chars = len(content_str) if content_str else 0
        total_chars += chars
        out_messages.append(ContextMessage(
            role=m.get("role", "unknown"),
            content=content_str,
            tool_calls=m.get("tool_calls"),
            tool_call_id=m.get("tool_call_id"),
            chars=chars,
        ))

    return ContextDebugOut(
        session_id=session_id,
        bot_id=session.bot_id,
        message_count=len(out_messages),
        total_chars=total_chars,
        messages=out_messages,
    )
