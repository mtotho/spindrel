import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import get_bot, list_bots
from app.agent.loop import run, run_stream
from app.agent.pending import resolve_pending
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
    client_actions: list[dict] = []


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
        result = await run(messages, bot, req.message)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM backend error: {e}")

    logger.info("Response (%d chars): %r", len(result.response), result.response[:100])
    if result.client_actions:
        logger.info("Client actions: %s", result.client_actions)

    await persist_turn(db, session_id, bot, messages, from_index)

    return ChatResponse(
        session_id=session_id,
        response=result.response,
        client_actions=result.client_actions,
    )


@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    bot = get_bot(req.bot_id)
    logger.info("POST /chat/stream  bot=%s  session=%s  message=%r", req.bot_id, req.session_id, req.message[:80])

    try:
        session_id, messages = await load_or_create(
            db, req.session_id, req.client_id, req.bot_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Session error: {e}")

    from_index = len(messages)

    async def event_generator():
        try:
            async for event in run_stream(messages, bot, req.message):
                if await request.is_disconnected():
                    break
                event_with_session = {**event, "session_id": str(session_id)}
                yield f"data: {json.dumps(event_with_session)}\n\n"
        except Exception as e:
            logger.exception("Streaming agent loop error")
            yield f"data: {json.dumps({'type': 'error', 'detail': str(e)})}\n\n"
        finally:
            await persist_turn(db, session_id, bot, messages, from_index)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


class ToolResultRequest(BaseModel):
    request_id: str
    result: str


@router.post("/chat/tool_result")
async def submit_tool_result(
    req: ToolResultRequest,
    _auth: str = Depends(verify_auth),
):
    logger.info("POST /chat/tool_result  request_id=%s  result_len=%d", req.request_id, len(req.result))
    if not resolve_pending(req.request_id, req.result):
        raise HTTPException(status_code=404, detail=f"No pending request: {req.request_id}")
    return {"status": "ok"}
