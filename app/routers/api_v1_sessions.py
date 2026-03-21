import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Message, Session, Task
from app.dependencies import get_db, verify_auth
from app.services.sessions import store_passive_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["Sessions"])

_http = httpx.AsyncClient(timeout=10.0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _post_to_slack(channel_id: str, token: str, text: str, thread_ts: str | None = None) -> None:
    payload: dict = {"channel": channel_id, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    try:
        r = await _http.post(
            "https://slack.com/api/chat.postMessage",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        data = r.json()
        if not data.get("ok"):
            logger.warning("Slack postMessage error: %s", data.get("error"))
    except Exception:
        logger.exception("Failed to post to Slack channel %s", channel_id)


async def _fanout(session: Session, text: str, source: str | None = None) -> None:
    """Fan-out injected message to session's delivery targets."""
    label = f"[{source}] " if source else ""
    full_text = f"{label}{text}"

    # Use dispatch_config stored on session if available
    cfg = session.dispatch_config or {}
    dispatch_type = cfg.get("type")

    if dispatch_type == "slack":
        channel_id = cfg.get("channel_id")
        token = cfg.get("token") or settings.SLACK_BOT_TOKEN
        if channel_id and token:
            await _post_to_slack(channel_id, token, full_text, cfg.get("thread_ts"))
            return

    # Fallback: derive from client_id for Slack sessions without stored dispatch_config
    if session.client_id and session.client_id.startswith("slack:"):
        channel_id = session.client_id.removeprefix("slack:")
        # Strip any suffix after the channel_id (e.g. "slack:C123:thread_ts")
        channel_id = channel_id.split(":")[0]
        token = settings.SLACK_BOT_TOKEN
        if channel_id and token:
            await _post_to_slack(channel_id, token, full_text)


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


class MessageOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: Optional[str]
    created_at: datetime
    metadata: dict = {}

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
    _auth: str = Depends(verify_auth),
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
    _auth: str = Depends(verify_auth),
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
            prompt=body.content,
            status="pending",
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
    _auth: str = Depends(verify_auth),
):
    """List messages for a session, most recent first."""
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    messages = result.scalars().all()
    return [MessageOut.from_orm(m) for m in reversed(messages)]
