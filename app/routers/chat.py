import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import get_bot, list_bots
from app.agent.loop import run
from app.dependencies import get_db, verify_auth
from app.services.sessions import load_or_create, persist_turn

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[uuid.UUID] = None
    client_id: str = "default"
    bot_id: str = "default"


class ChatResponse(BaseModel):
    session_id: uuid.UUID
    response: str


@router.get("/bots")
async def bots(_auth: str = Depends(verify_auth)):
    return [{"id": b.id, "name": b.name, "model": b.model} for b in list_bots()]


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    bot = get_bot(req.bot_id)
    logger.info("POST /chat  bot=%s  session=%s  message=%r", req.bot_id, req.session_id, req.message[:80])

    try:
        session_id, messages = await load_or_create(
            db, req.session_id, req.client_id, req.bot_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Session error: {e}")

    logger.info("Session %s loaded, %d existing messages, system_prompt=%r",
                session_id, len(messages), messages[0]["content"][:60] if messages else "none")

    from_index = len(messages)

    try:
        response_text = await run(messages, bot, req.message)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM backend error: {e}")

    logger.info("Response (%d chars): %r", len(response_text), response_text[:100])

    await persist_turn(db, session_id, messages, from_index)

    return ChatResponse(session_id=session_id, response=response_text)
