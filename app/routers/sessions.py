import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import get_bot
from app.agent.memory import write_memory
from app.db.models import Message, Session
from app.dependencies import get_db, verify_auth
from app.services.compaction import _generate_summary, _get_compaction_model, _messages_for_summary

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
    await db.execute(delete(Session).where(Session.id == session_id))
    await db.commit()


class SummarizeResponse(BaseModel):
    title: str
    summary: str
    memory_written: bool = False


@router.post("/{session_id}/summarize", response_model=SummarizeResponse)
async def summarize_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    """Force summarization of a session, writing to memory KB if enabled."""
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    bot = get_bot(session.bot_id)
    model = _get_compaction_model(bot)

    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at)
    )
    all_messages = [
        {"role": m.role, "content": m.content}
        for m in result.scalars().all()
    ]

    conversation = _messages_for_summary(all_messages)
    if not conversation:
        raise HTTPException(status_code=400, detail="No conversation content to summarize")

    memory_prompt = bot.memory.prompt if bot.memory.enabled else None
    title, summary, memory_content = await _generate_summary(
        conversation, model, session.summary, memory_prompt=memory_prompt,
    )

    time_range = await db.execute(
        select(func.min(Message.created_at), func.max(Message.created_at))
        .where(Message.session_id == session_id)
        .where(Message.role.in_(["user", "assistant"]))
    )
    range_start, range_end = time_range.one()

    msg_count_result = await db.execute(
        select(func.count())
        .where(Message.session_id == session_id)
        .where(Message.role.in_(["user", "assistant"]))
    )
    msg_count = msg_count_result.scalar() or 0

    await db.execute(
        update(Session)
        .where(Session.id == session_id)
        .values(title=title, summary=summary)
    )
    await db.commit()

    memory_written = False
    if bot.memory.enabled:
        content_to_store = memory_content if memory_prompt else summary
        if content_to_store:
            await write_memory(
                summary_text=content_to_store,
                client_id=session.client_id,
                session_id=session_id,
                message_range_start=range_start,
                message_range_end=range_end,
                message_count=msg_count,
            )
            memory_written = True

    return SummarizeResponse(
        title=title,
        summary=summary,
        memory_written=memory_written,
    )
