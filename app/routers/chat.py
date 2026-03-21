import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import get_bot, list_bots
from app.agent.context import set_agent_context
from app.agent.loop import run, run_stream
from app.agent.pending import resolve_pending
from app.dependencies import get_db, verify_auth
from app.services.compaction import maybe_compact, run_compaction_stream
from app.services.sessions import (
    derive_integration_session_id,
    is_integration_client_id,
    load_or_create,
    persist_turn,
    store_passive_message,
)
from app.stt import transcribe as stt_transcribe

logger = logging.getLogger(__name__)

router = APIRouter()


class Attachment(BaseModel):
    """Multimedia attachment (vision). Slack sends type=image with base64 content."""
    type: str = "image"
    content: str  # base64-encoded bytes
    mime_type: str = "image/jpeg"
    name: str = ""


class ChatRequest(BaseModel):
    message: str = ""
    session_id: Optional[uuid.UUID] = None
    client_id: str = "default"
    bot_id: str = "default"
    audio_data: Optional[str] = None  # base64-encoded audio
    audio_format: Optional[str] = None  # e.g. "m4a", "wav", "webm"
    audio_native: Optional[bool] = None  # True/False overrides bot default; None = use bot setting
    attachments: list[Attachment] = Field(default_factory=list)
    dispatch_type: Optional[str] = None  # "slack" | "webhook" | "internal" | "none"
    dispatch_config: Optional[dict] = None  # type-specific routing config
    passive: bool = False  # If True, store message but skip agent run
    msg_metadata: Optional[dict] = None  # Metadata to attach to the user message row


class ChatResponse(BaseModel):
    session_id: uuid.UUID
    response: str
    transcript: str = ""
    client_actions: list[dict] = []


def _is_integration_client(client_id: str) -> bool:
    return is_integration_client_id(client_id)


@router.get("/bots")
async def bots(_auth: str = Depends(verify_auth)):
    result = []
    for b in list_bots():
        entry: dict = {"id": b.id, "name": b.name, "model": b.model}
        if b.audio_input != "transcribe":
            entry["audio_input"] = b.audio_input
        result.append(entry)
    return result


def _resolve_audio_native(req: ChatRequest, bot) -> bool:
    """Determine whether to use native audio mode for this request.
    Per-request flag > bot YAML > default (False)."""
    if req.audio_native is not None:
        return req.audio_native
    return bot.audio_input == "native"


def _transcribe_audio_data(audio_b64: str, audio_format: str | None) -> str:
    """Decode base64 audio and transcribe via Whisper (server-side STT)."""
    import base64
    import tempfile

    raw = base64.b64decode(audio_b64)
    ext = f".{audio_format}" if audio_format else ".m4a"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=True) as tmp:
        tmp.write(raw)
        tmp.flush()
        return stt_transcribe(tmp.name)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    bot = get_bot(req.bot_id)

    # Resolve audio: if audio_data provided but not native mode, transcribe first
    audio_data = None
    audio_format = None
    message = req.message

    if req.audio_data:
        if _resolve_audio_native(req, bot):
            audio_data = req.audio_data
            audio_format = req.audio_format
            if not message:
                message = "[audio message]"
            logger.info("POST /chat  bot=%s  session=%s  native_audio fmt=%s",
                        req.bot_id, req.session_id, audio_format)
        else:
            logger.info("POST /chat  bot=%s  session=%s  transcribing audio",
                        req.bot_id, req.session_id)
            message = _transcribe_audio_data(req.audio_data, req.audio_format)
            if not message.strip():
                raise HTTPException(status_code=400, detail="No speech detected in audio")

    if not message and not req.attachments:
        raise HTTPException(status_code=400, detail="No message, audio, or attachments provided")

    if not message.strip() and req.attachments:
        message = "[User sent attachment(s)]"

    att_payload = [a.model_dump() for a in req.attachments] if req.attachments else None

    is_integration = _is_integration_client(req.client_id)
    # For integration sessions, derive stable session_id from client_id
    resolved_session_id = req.session_id
    if is_integration and resolved_session_id is None:
        resolved_session_id = derive_integration_session_id(req.client_id)

    logger.info("POST /chat  bot=%s  session=%s  passive=%s  message=%r",
                req.bot_id, resolved_session_id, req.passive, message[:80])

    try:
        session_id, messages = await load_or_create(
            db, resolved_session_id, req.client_id, req.bot_id,
            locked=is_integration,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Session error: {e}")

    # Passive path: store message without running agent
    if req.passive:
        await store_passive_message(db, session_id, message, req.msg_metadata or {})
        return ChatResponse(session_id=session_id, response="", client_actions=[])

    logger.info("Session %s loaded, %d messages", session_id, len(messages))
    logger.debug("System prompt: %s...", (messages[0]["content"][:80] + "…") if messages else "none")

    from_index = len(messages)
    correlation_id = uuid.uuid4()

    try:
        result = await run(
            messages, bot, message,
            session_id=session_id, client_id=req.client_id,
            audio_data=audio_data, audio_format=audio_format,
            attachments=att_payload,
            correlation_id=correlation_id,
            dispatch_type=req.dispatch_type,
            dispatch_config=req.dispatch_config,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM backend error: {e}")

    logger.info("Response (%d chars): %r", len(result.response), result.response[:100])
    if result.client_actions:
        logger.info("Client actions: %d", len(result.client_actions))
        logger.debug("Client actions: %s", result.client_actions)

    await persist_turn(
        db, session_id, bot, messages, from_index,
        correlation_id=correlation_id,
        msg_metadata=req.msg_metadata,
    )
    maybe_compact(session_id, bot, messages, correlation_id=correlation_id)

    return ChatResponse(
        session_id=session_id,
        response=result.response,
        transcript=result.transcript,
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

    # Resolve audio
    audio_data = None
    audio_format = None
    message = req.message

    if req.audio_data:
        if _resolve_audio_native(req, bot):
            audio_data = req.audio_data
            audio_format = req.audio_format
            if not message:
                message = "[audio message]"
            logger.info("POST /chat/stream  bot=%s  session=%s  native_audio fmt=%s",
                        req.bot_id, req.session_id, audio_format)
        else:
            logger.info("POST /chat/stream  bot=%s  session=%s  transcribing audio",
                        req.bot_id, req.session_id)
            message = _transcribe_audio_data(req.audio_data, req.audio_format)
            if not message.strip():
                raise HTTPException(status_code=400, detail="No speech detected in audio")

    if not message and not req.attachments:
        raise HTTPException(status_code=400, detail="No message, audio, or attachments provided")

    if not message.strip() and req.attachments:
        message = "[User sent attachment(s)]"

    att_payload = [a.model_dump() for a in req.attachments] if req.attachments else None

    is_integration = _is_integration_client(req.client_id)
    resolved_session_id = req.session_id
    if is_integration and resolved_session_id is None:
        resolved_session_id = derive_integration_session_id(req.client_id)

    logger.info("POST /chat/stream  bot=%s  session=%s  passive=%s  message=%r",
                req.bot_id, resolved_session_id, req.passive, message[:80])

    try:
        session_id, messages = await load_or_create(
            db, resolved_session_id, req.client_id, req.bot_id,
            locked=is_integration,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Session error: {e}")

    # Passive path: store message and return empty stream
    if req.passive:
        await store_passive_message(db, session_id, message, req.msg_metadata or {})

        async def _passive_stream():
            yield f"data: {json.dumps({'type': 'passive_stored', 'session_id': str(session_id)})}\n\n"

        return StreamingResponse(_passive_stream(), media_type="text/event-stream")

    from_index = len(messages)
    correlation_id = uuid.uuid4()

    async def event_generator():
        try:
            # _with_keepalive uses ensure_future(__anext__), so each chunk runs in a new
            # Task that copies *this* task's ContextVars — not the child that run_stream
            # sets on its first step. Prime the parent so tools (e.g. create_task) see
            # bot_id, dispatch_config, session_id on every chunk.
            set_agent_context(
                session_id=session_id,
                client_id=req.client_id,
                bot_id=bot.id,
                correlation_id=correlation_id,
                memory_cross_session=bot.memory.cross_session if bot.memory.enabled else None,
                memory_cross_client=bot.memory.cross_client if bot.memory.enabled else None,
                memory_cross_bot=bot.memory.cross_bot if bot.memory.enabled else None,
                memory_similarity_threshold=bot.memory.similarity_threshold if bot.memory.enabled else None,
                dispatch_type=req.dispatch_type,
                dispatch_config=req.dispatch_config,
            )
            stream = run_stream(
                messages, bot, message,
                session_id=session_id, client_id=req.client_id,
                audio_data=audio_data, audio_format=audio_format,
                attachments=att_payload,
                correlation_id=correlation_id,
                dispatch_type=req.dispatch_type,
                dispatch_config=req.dispatch_config,
            )
            async for event in _with_keepalive(stream):
                if await request.is_disconnected():
                    break
                if event is None:
                    yield ": keepalive\n\n"
                    continue
                event_with_session = {**event, "session_id": str(session_id)}
                yield f"data: {json.dumps(event_with_session)}\n\n"

            await persist_turn(
                db, session_id, bot, messages, from_index,
                correlation_id=correlation_id,
                msg_metadata=req.msg_metadata,
            )

            compaction_stream = run_compaction_stream(session_id, bot, messages, correlation_id=correlation_id)
            async for event in compaction_stream:
                if await request.is_disconnected():
                    break
                event_with_session = {**event, "session_id": str(session_id)}
                yield f"data: {json.dumps(event_with_session)}\n\n"
        except Exception as e:
            logger.exception("Streaming agent loop error")
            yield f"data: {json.dumps({'type': 'error', 'detail': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


SSE_KEEPALIVE_INTERVAL = 15  # seconds


async def _with_keepalive(
    agen: AsyncGenerator[dict[str, Any], None],
    interval: float = SSE_KEEPALIVE_INTERVAL,
) -> AsyncGenerator[dict[str, Any] | None, None]:
    """Wrap an async generator, yielding None as a keepalive signal when no
    event arrives within *interval* seconds.  Prevents idle SSE connections
    from being dropped by React Native's XHR layer."""
    pending = asyncio.ensure_future(agen.__anext__())
    try:
        while True:
            try:
                event = await asyncio.wait_for(asyncio.shield(pending), timeout=interval)
                yield event
                pending = asyncio.ensure_future(agen.__anext__())
            except asyncio.TimeoutError:
                yield None
            except StopAsyncIteration:
                break
    finally:
        pending.cancel()


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
