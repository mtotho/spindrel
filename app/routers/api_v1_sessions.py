import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Attachment, Attachment as AttachmentModel, Message, Session, Task
from app.dependencies import get_db, require_scopes
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
            created_at=msg.created_at,
            metadata=msg.metadata_,
            attachments=[AttachmentBrief.from_orm(a) for a in (msg.attachments or [])],
        )


class InjectResponse(BaseModel):
    message_id: uuid.UUID
    session_id: uuid.UUID
    task_id: Optional[uuid.UUID] = None


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
