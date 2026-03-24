import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Attachment as AttachmentModel, Message, Session, Task
from app.dependencies import get_db, verify_auth_or_user
from app.services.sessions import store_passive_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["Sessions"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _fanout(session: Session, text: str, source: str | None = None) -> None:
    """Fan-out injected message to session's delivery targets via dispatcher registry."""
    cfg = session.dispatch_config or {}
    dispatch_type = cfg.get("type")
    if not dispatch_type or dispatch_type == "none":
        return
    from app.agent import dispatchers
    label = f"[{source}] " if source else ""
    await dispatchers.get(dispatch_type).post_message(cfg, f"{label}{text}")


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
    _auth: str = Depends(verify_auth_or_user),
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
    _auth: str = Depends(verify_auth_or_user),
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
    await store_passive_message(db, session_id, body.content, metadata)

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
    _auth: str = Depends(verify_auth_or_user),
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
    messages = result.scalars().all()
    return [MessageOut.from_orm(m) for m in reversed(messages)]
