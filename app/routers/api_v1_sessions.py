import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Attachment, Attachment as AttachmentModel, Channel, Message, Session, Task, ToolCall
from app.dependencies import ApiKeyAuth, get_db, require_scopes, verify_auth_or_user
from app.services.api_keys import has_scope
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


class PromoteScratchSessionResponse(BaseModel):
    channel_id: uuid.UUID
    primary_session_id: uuid.UUID
    demoted_session_id: uuid.UUID


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
    except HTTPException:
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
    except HTTPException:
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
    except HTTPException:
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
    except HTTPException:
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
    await store_passive_message(db, session_id, body.content, metadata, channel_id=session.channel_id)

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
        "base_prompt": bot.base_prompt if bot.base_prompt is not None else True,
        "pinned_widgets": channel_pinned_widgets,
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
    from app.services.sessions import _load_messages

    bot = get_bot(session.bot_id)

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
        context_profile_name=resolve_context_profile(session=session).name,
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
