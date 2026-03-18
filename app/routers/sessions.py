import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import get_bot
from app.config import settings
from app.db.models import Memory, Message, Session
from app.dependencies import get_db, verify_auth
from app.services.compaction import run_compaction_forced

router = APIRouter(prefix="/sessions", tags=["sessions"])


class SessionSummary(BaseModel):
    id: uuid.UUID
    client_id: str
    bot_id: str
    title: Optional[str] = None
    created_at: datetime
    last_active: datetime

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: Optional[str] = None
    tool_calls: Optional[list] = None
    tool_call_id: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionDetail(BaseModel):
    session: SessionSummary
    messages: list[MessageOut]


@router.get("", response_model=list[SessionSummary])
async def list_sessions(
    client_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    stmt = select(Session).order_by(Session.last_active.desc())
    if client_id:
        stmt = stmt.where(Session.client_id == client_id)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()
    return SessionDetail(session=session, messages=messages)


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    # If bot (or global) is configured to wipe memory on session delete, delete memories first.
    # Otherwise the FK uses ON DELETE SET NULL and memories are kept with session_id=NULL.
    try:
        bot = get_bot(session.bot_id)
        wipe = bot.memory.wipe_on_session_delete
    except HTTPException:
        wipe = settings.WIPE_MEMORY_ON_SESSION_DELETE
    if wipe:
        await db.execute(delete(Memory).where(Memory.session_id == session_id))
    await db.execute(delete(Session).where(Session.id == session_id))
    await db.commit()


class SummarizeResponse(BaseModel):
    title: str
    summary: str


@router.post("/{session_id}/summarize", response_model=SummarizeResponse)
async def summarize_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    """Force full compaction: memory phase (if bot has memory/persona/knowledge) then summary. Sets watermark so the summary is used on next load."""
    try:
        session = await db.get(Session, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        bot = get_bot(session.bot_id)
        title, summary = await run_compaction_forced(session_id, bot, db)
        await db.commit()
        return SummarizeResponse(title=title, summary=summary)
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail="Session not found")
        if "no conversation" in str(e).lower():
            raise HTTPException(status_code=400, detail="No conversation content to summarize")
        if "no messages" in str(e).lower():
            raise HTTPException(status_code=400, detail="No messages in session")
        raise HTTPException(status_code=400, detail=str(e))
