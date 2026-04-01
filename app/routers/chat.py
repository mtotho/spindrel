import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import get_bot, list_bots
from app.agent.context import set_agent_context
from app.agent.loop import run, run_stream
from app.agent.pending import resolve_pending
from app.db.models import Task as TaskModel
from app.dependencies import get_db, require_scopes, verify_auth_or_user
from app.services import session_locks
from app.services.channels import get_or_create_channel, ensure_active_session, is_integration_client_id, resolve_integration_user
from app.services.compaction import maybe_compact
from app.services.sessions import (
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


class FileMetadata(BaseModel):
    """Metadata about an attached file for server-side attachment tracking."""
    url: str | None = None
    filename: str = "attachment"
    mime_type: str = "application/octet-stream"
    size_bytes: int = 0
    posted_by: str | None = None
    file_data: str | None = None  # base64-encoded file bytes


class ChatRequest(BaseModel):
    message: str = ""
    channel_id: Optional[uuid.UUID] = None  # Preferred for channel targeting
    session_id: Optional[uuid.UUID] = None  # backward compat; resolves to channel
    client_id: str = "default"
    bot_id: str = "default"
    audio_data: Optional[str] = None  # base64-encoded audio
    audio_format: Optional[str] = None  # e.g. "m4a", "wav", "webm"
    audio_native: Optional[bool] = None  # True/False overrides bot default; None = use bot setting
    attachments: list[Attachment] = Field(default_factory=list)
    file_metadata: list[FileMetadata] = Field(default_factory=list)  # server-side attachment tracking
    dispatch_type: Optional[str] = None  # "slack" | "webhook" | "internal" | "none"
    dispatch_config: Optional[dict] = None  # type-specific routing config
    model_override: Optional[str] = None  # Per-turn model override (highest priority)
    passive: bool = False  # If True, store message but skip agent run
    msg_metadata: Optional[dict] = None  # Metadata to attach to the user message row


class CancelRequest(BaseModel):
    client_id: str
    bot_id: str


class CancelResponse(BaseModel):
    cancelled: bool
    queued_tasks_cancelled: int = 0


class ChatResponse(BaseModel):
    session_id: uuid.UUID
    response: str
    transcript: str = ""
    client_actions: list[dict] = []


class SecretCheckRequest(BaseModel):
    message: str


class SecretCheckResponse(BaseModel):
    has_secrets: bool
    exact_matches: int = 0
    pattern_matches: list[dict] = Field(default_factory=list)


@router.post("/chat/check-secrets", response_model=SecretCheckResponse)
async def check_secrets(body: SecretCheckRequest, _auth=Depends(verify_auth_or_user)):
    """Pre-flight check: detect known secrets or secret-like patterns in user input."""
    from app.services.secret_registry import check_user_input
    result = check_user_input(body.message)
    if result is None:
        return SecretCheckResponse(has_secrets=False)
    # Strip match content and positions from pattern matches — only expose the type
    safe_patterns = [{"type": pm["type"]} for pm in result.get("pattern_matches", [])]
    return SecretCheckResponse(
        has_secrets=True,
        exact_matches=result.get("exact_matches", 0),
        pattern_matches=safe_patterns,
    )


def _is_integration_client(client_id: str) -> bool:
    return is_integration_client_id(client_id)


def _extract_user(auth_result):
    """Extract User object from auth_result if JWT-authenticated, else None."""
    from app.db.models import User
    return auth_result if isinstance(auth_result, User) else None


async def _create_attachments_from_metadata(
    file_metadata: list[FileMetadata],
    channel_id: uuid.UUID | None,
    source_integration: str,
    bot_id: str | None = None,
    message_id: uuid.UUID | None = None,
) -> None:
    """Create attachment records from file metadata."""
    from app.services.attachments import create_attachment

    logger.info("Creating %d attachment(s) for channel %s", len(file_metadata), channel_id)
    for fm in file_metadata:
        try:
            import base64 as _b64
            raw_bytes = _b64.b64decode(fm.file_data) if fm.file_data else None
            await create_attachment(
                message_id=message_id,
                channel_id=channel_id,
                filename=fm.filename,
                mime_type=fm.mime_type,
                size_bytes=fm.size_bytes,
                posted_by=fm.posted_by,
                source_integration=source_integration,
                file_data=raw_bytes,
                url=fm.url,
                bot_id=bot_id,
            )
        except Exception:
            logger.warning("Failed to create attachment for %s", fm.filename, exc_info=True)


async def _resolve_channel_and_session(
    db: AsyncSession,
    req: ChatRequest,
    user=None,
):
    """Resolve channel + session from the request. Returns (channel, session_id, messages, is_integration)."""
    from app.db.models import Channel

    is_integration = _is_integration_client(req.client_id)

    # Web UI channels: private by default, owned by the logged-in user
    extra_kwargs: dict = {}
    if not is_integration and user is not None:
        extra_kwargs["user_id"] = user.id
        extra_kwargs["private"] = True

    # Integration user resolution: if sender_id is "slack:U123", look up system user
    if is_integration and user is None and req.msg_metadata:
        sender_id = (req.msg_metadata or {}).get("sender_id", "")
        if sender_id.startswith("slack:"):
            slack_uid = sender_id.removeprefix("slack:")
            resolved = await resolve_integration_user(db, "slack", slack_uid)
            if resolved:
                extra_kwargs["user_id"] = resolved.id
                if req.msg_metadata:
                    req.msg_metadata["sender_display_name"] = resolved.display_name

    # Resolve channel
    channel = await get_or_create_channel(
        db,
        channel_id=req.channel_id,
        client_id=req.client_id,
        bot_id=req.bot_id,
        dispatch_config=req.dispatch_config if is_integration else None,
        **extra_kwargs,
    )

    # Resolve session: explicit session_id takes precedence
    resolved_session_id = req.session_id
    if resolved_session_id is None:
        resolved_session_id = await ensure_active_session(db, channel)
        await db.commit()

    session_id, messages = await load_or_create(
        db, resolved_session_id, req.client_id, req.bot_id,
        locked=is_integration,
        channel_id=channel.id,
    )

    return channel, session_id, messages, is_integration


async def _resolve_mirror_target(channel) -> tuple[str | None, dict | None]:
    """Resolve integration type and dispatch_config for mirroring.

    Checks Channel-level fields first, then falls back to ChannelIntegration
    bindings table (used when integration was bound via the UI).
    """
    if channel.integration and channel.dispatch_config:
        logger.debug("Mirror target from channel fields: %s", channel.integration)
        return channel.integration, channel.dispatch_config

    # Fallback: check ChannelIntegration bindings
    from sqlalchemy import select
    from app.db.engine import async_session
    from app.db.models import ChannelIntegration

    try:
        async with async_session() as db:
            result = await db.execute(
                select(ChannelIntegration)
                .where(ChannelIntegration.channel_id == channel.id)
                .limit(1)
            )
            binding = result.scalar_one_or_none()
    except Exception:
        logger.warning("Failed to query ChannelIntegration for channel %s", channel.id, exc_info=True)
        return None, None

    if not binding:
        logger.debug("No ChannelIntegration binding for channel %s", channel.id)
        return None, None

    integration = binding.integration_type
    dispatch_config = binding.dispatch_config
    logger.info(
        "Mirror: found binding type=%s client_id=%s has_dispatch_config=%s",
        integration, binding.client_id, dispatch_config is not None,
    )

    # If binding has no dispatch_config, try to construct one from client_id
    if not dispatch_config and binding.client_id:
        # Ask the integration's registered resolver first
        from app.agent.hooks import get_integration_meta
        meta = get_integration_meta(integration)
        if meta and meta.resolve_dispatch_config:
            dispatch_config = meta.resolve_dispatch_config(binding.client_id)
            logger.info("Mirror: resolved dispatch_config via hook: %s", dispatch_config is not None)
        else:
            # Legacy fallback: Slack-style token lookup
            prefix = f"{integration}:"
            native_id = binding.client_id.removeprefix(prefix) if binding.client_id.startswith(prefix) else None
            if native_id:
                from app.services.integration_settings import get_value
                token = get_value(integration, f"{integration.upper()}_BOT_TOKEN")
                if token:
                    dispatch_config = {"channel_id": native_id, "token": token}

    return integration, dispatch_config


async def _mirror_to_integration(
    channel, text: str, *,
    bot_id: str | None = None,
    is_user_message: bool = False,
    user=None,
    client_actions: list[dict] | None = None,
) -> None:
    """Fire-and-forget mirror to channel's integration dispatcher."""
    integration, dispatch_config = await _resolve_mirror_target(channel)
    if not integration or not dispatch_config:
        logger.debug("Mirror skipped: no integration=%s or dispatch_config=%s", integration, dispatch_config is not None)
        return
    logger.info("Mirroring %s message to %s (is_user=%s)", "user" if is_user_message else "bot", integration, is_user_message)
    from app.agent import dispatchers
    try:
        # For user messages with authenticated user: use their display name + icon
        # For anonymous user messages: fall back to [web] prefix
        user_attrs: dict = {}
        if is_user_message and user:
            from app.agent.hooks import get_user_attribution
            user_attrs = get_user_attribution(integration, user)
        elif is_user_message:
            text = f"[web] {text}"

        await dispatchers.get(integration).post_message(
            dispatch_config, text,
            bot_id=bot_id if not is_user_message else None,
            client_actions=client_actions,
            reply_in_thread=False,
            **user_attrs,
        )
    except Exception:
        logger.warning("Mirror to %s failed", integration, exc_info=True)


@router.get("/bots")
async def bots(_auth=Depends(require_scopes("bots:read"))):
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


async def _transcribe_audio_data(audio_b64: str, audio_format: str | None) -> str:
    """Decode base64 audio and transcribe via Whisper (server-side STT).

    Runs in a thread to avoid blocking the event loop (Whisper is CPU-bound).
    """
    import asyncio
    import base64
    import tempfile

    def _sync_transcribe() -> str:
        raw = base64.b64decode(audio_b64)
        ext = f".{audio_format}" if audio_format else ".m4a"
        with tempfile.NamedTemporaryFile(suffix=ext, delete=True) as tmp:
            tmp.write(raw)
            tmp.flush()
            return stt_transcribe(tmp.name)

    return await asyncio.to_thread(_sync_transcribe)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    db: AsyncSession = Depends(get_db),
    auth_result=Depends(require_scopes("chat")),
):
    user = _extract_user(auth_result)
    bot = get_bot(req.bot_id)

    # Auto-inject web UI metadata when caller doesn't supply any
    if not req.msg_metadata and user is not None:
        req.msg_metadata = {
            "source": "web",
            "sender_type": "human",
            "sender_id": f"user:{user.id}",
            "sender_display_name": user.display_name,
        }

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
            # Fire before_transcription hook — integrations can override STT
            from app.agent.hooks import fire_hook_with_override, HookContext
            # Estimate byte size from base64 length (avoids decoding just for size)
            _audio_size_est = len(req.audio_data) * 3 // 4
            _override = await fire_hook_with_override("before_transcription", HookContext(
                bot_id=req.bot_id,
                extra={
                    "audio_format": req.audio_format or "m4a",
                    "audio_size_bytes": _audio_size_est,
                    "source": "chat",
                },
            ))
            if isinstance(_override, str) and _override.strip():
                message = _override
            else:
                message = await _transcribe_audio_data(req.audio_data, req.audio_format)
            if not message.strip():
                raise HTTPException(status_code=400, detail="No speech detected in audio")

    if not message and not req.attachments:
        raise HTTPException(status_code=400, detail="No message, audio, or attachments provided")

    if not message.strip() and req.attachments:
        message = "[User sent attachment(s)]"

    att_payload = [a.model_dump() for a in req.attachments] if req.attachments else None

    try:
        channel, session_id, messages, is_integration = await _resolve_channel_and_session(db, req, user=user)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Session error: {e}")

    channel_id = channel.id

    logger.info("POST /chat  bot=%s  channel=%s  session=%s  passive=%s  file_metadata=%d  message=%r",
                req.bot_id, channel_id, session_id, req.passive, len(req.file_metadata), message[:80])

    # Passive path: store message without running agent
    if req.passive:
        await store_passive_message(db, session_id, message, req.msg_metadata or {})
        return ChatResponse(session_id=session_id, response="", client_actions=[])

    logger.info("Session %s loaded, %d messages", session_id, len(messages))
    logger.debug("System prompt: %s...", (messages[0]["content"][:80] + "…") if messages else "none")

    # Create attachment records immediately so they're available during the agent loop
    if req.file_metadata:
        source = (req.msg_metadata or {}).get("source", "web")
        await _create_attachments_from_metadata(
            req.file_metadata, channel_id, source, bot_id=req.bot_id,
        )

    from_index = len(messages)
    correlation_id = uuid.uuid4()

    # Mirror user message to integration (skip if caller already handles delivery)
    if not req.dispatch_config:
        await _mirror_to_integration(channel, message, is_user_message=True, user=user)

    try:
        result = await run(
            messages, bot, message,
            session_id=session_id, client_id=req.client_id,
            audio_data=audio_data, audio_format=audio_format,
            attachments=att_payload,
            correlation_id=correlation_id,
            dispatch_type=req.dispatch_type,
            dispatch_config=req.dispatch_config,
            channel_id=channel_id,
            model_override=req.model_override,
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
        channel_id=channel_id,
    )
    maybe_compact(
        session_id, bot, messages,
        correlation_id=correlation_id,
        dispatch_type=req.dispatch_type,
        dispatch_config=req.dispatch_config,
    )

    # Mirror response to integration
    if not req.dispatch_config and result.response:
        await _mirror_to_integration(
            channel, result.response,
            bot_id=req.bot_id, client_actions=result.client_actions,
        )

    return ChatResponse(
        session_id=session_id,
        response=result.response,
        transcript=result.transcript,
        client_actions=result.client_actions,
    )


@router.post("/chat/cancel", response_model=CancelResponse)
async def chat_cancel(
    req: CancelRequest,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("chat")),
):
    """Cancel an in-progress agent loop and any queued tasks for the session."""
    from sqlalchemy import select, update

    # Resolve channel → active session
    channel = await get_or_create_channel(db, client_id=req.client_id, bot_id=req.bot_id)
    session_id = await ensure_active_session(db, channel)
    await db.commit()

    # Request cancellation of the in-progress loop
    cancelled = session_locks.request_cancel(session_id)

    # Cancel pending queued tasks for this session
    result = await db.execute(
        update(TaskModel)
        .where(TaskModel.session_id == session_id, TaskModel.status == "pending")
        .values(status="failed")
    )
    queued_cancelled = result.rowcount  # type: ignore[attr-defined]
    await db.commit()

    logger.info(
        "POST /chat/cancel  client=%s  bot=%s  session=%s  active_cancelled=%s  queued=%d",
        req.client_id, req.bot_id, session_id, cancelled, queued_cancelled,
    )
    return CancelResponse(cancelled=cancelled, queued_tasks_cancelled=queued_cancelled)


@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth_result=Depends(require_scopes("chat")),
):
    user = _extract_user(auth_result)
    bot = get_bot(req.bot_id)

    # Auto-inject web UI metadata when caller doesn't supply any
    if not req.msg_metadata and user is not None:
        req.msg_metadata = {
            "source": "web",
            "sender_type": "human",
            "sender_id": f"user:{user.id}",
            "sender_display_name": user.display_name,
        }

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
            message = await _transcribe_audio_data(req.audio_data, req.audio_format)
            if not message.strip():
                raise HTTPException(status_code=400, detail="No speech detected in audio")

    if not message and not req.attachments:
        raise HTTPException(status_code=400, detail="No message, audio, or attachments provided")

    if not message.strip() and req.attachments:
        message = "[User sent attachment(s)]"

    att_payload = [a.model_dump() for a in req.attachments] if req.attachments else None

    try:
        channel, session_id, messages, is_integration = await _resolve_channel_and_session(db, req, user=user)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Session error: {e}")

    channel_id = channel.id

    logger.info("POST /chat/stream  bot=%s  channel=%s  session=%s  passive=%s  file_metadata=%d  message=%r",
                req.bot_id, channel_id, session_id, req.passive, len(req.file_metadata), message[:80])

    # Passive path: store message and return empty stream
    if req.passive:
        await store_passive_message(db, session_id, message, req.msg_metadata or {})

        async def _passive_stream():
            yield f"data: {json.dumps({'type': 'passive_stored', 'session_id': str(session_id)})}\n\n"

        return StreamingResponse(_passive_stream(), media_type="text/event-stream")

    # System pause check: block new processing while paused
    from app.config import settings as _settings
    if _settings.SYSTEM_PAUSED:
        if _settings.SYSTEM_PAUSE_BEHAVIOR == "drop":
            async def _paused_drop():
                yield f"data: {json.dumps({'type': 'error', 'detail': 'System is paused. Messages are being dropped.'})}\n\n"
            return StreamingResponse(_paused_drop(), media_type="text/event-stream")

        # Queue mode: create a pending Task
        queued_task = TaskModel(
            bot_id=req.bot_id,
            client_id=req.client_id,
            session_id=session_id,
            channel_id=channel_id,
            prompt=message,
            status="pending",
            dispatch_type=req.dispatch_type,
            dispatch_config=req.dispatch_config,
            created_at=datetime.now(timezone.utc),
        )
        db.add(queued_task)
        await db.commit()
        await db.refresh(queued_task)
        _paused_task_id = str(queued_task.id)
        logger.info("System paused — queued message as task %s", _paused_task_id)

        async def _paused_queue():
            yield f"data: {json.dumps({'type': 'queued', 'session_id': str(session_id), 'task_id': _paused_task_id, 'reason': 'system_paused'})}\n\n"
        return StreamingResponse(_paused_queue(), media_type="text/event-stream")

    # Session locking: if a RAG loop is already running for this session, queue the
    # request as a Task and return a `queued` event.  The Task worker will run the
    # message once the current loop finishes and dispatch the response via the
    # integration-agnostic dispatcher system.
    if not session_locks.acquire(session_id):
        # Clear thread_ts so the delayed response posts to the channel directly
        # (not as a thread reply to the original message).
        queued_dispatch_config = (
            {**req.dispatch_config, "thread_ts": None}
            if req.dispatch_config
            else req.dispatch_config
        )
        queued_task = TaskModel(
            bot_id=req.bot_id,
            client_id=req.client_id,
            session_id=session_id,
            channel_id=channel_id,
            prompt=message,
            status="pending",
            dispatch_type=req.dispatch_type,
            dispatch_config=queued_dispatch_config,
            created_at=datetime.now(timezone.utc),
        )
        db.add(queued_task)
        await db.commit()
        await db.refresh(queued_task)
        _task_id = str(queued_task.id)
        logger.info(
            "Session %s busy — queued message as task %s", session_id, _task_id
        )

        async def _queued_stream():
            yield f"data: {json.dumps({'type': 'queued', 'session_id': str(session_id), 'task_id': _task_id})}\n\n"

        return StreamingResponse(_queued_stream(), media_type="text/event-stream")

    # Create attachment records immediately so they're available during the agent loop
    if req.file_metadata:
        source = (req.msg_metadata or {}).get("source", "web")
        await _create_attachments_from_metadata(
            req.file_metadata, channel_id, source, bot_id=req.bot_id,
        )

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
                channel_id=channel_id,
                memory_cross_channel=None,  # DB memory deprecated
                memory_cross_client=None,
                memory_cross_bot=None,
                memory_similarity_threshold=None,
                dispatch_type=req.dispatch_type,
                dispatch_config=req.dispatch_config,
            )

            # Mirror user message to integration (skip if caller already handles delivery)
            if not req.dispatch_config:
                await _mirror_to_integration(channel, message, is_user_message=True, user=user)

            response_text = ""
            response_actions = None
            was_cancelled = False

            stream = run_stream(
                messages, bot, message,
                session_id=session_id, client_id=req.client_id,
                audio_data=audio_data, audio_format=audio_format,
                attachments=att_payload,
                correlation_id=correlation_id,
                dispatch_type=req.dispatch_type,
                dispatch_config=req.dispatch_config,
                channel_id=channel_id,
                model_override=req.model_override,
            )
            _budget_utilization = None
            async for event in _with_keepalive(stream):
                if await request.is_disconnected():
                    break
                if event is None:
                    yield ": keepalive\n\n"
                    continue
                if event.get("type") == "cancelled":
                    was_cancelled = True
                    # Record cancellation in conversation history
                    messages.append({"role": "user", "content": "[STOP]"})
                    messages.append({"role": "assistant", "content": "[Cancelled by user]"})
                    event_with_session = {**event, "session_id": str(session_id)}
                    yield f"data: {json.dumps(event_with_session)}\n\n"
                    break
                # Capture budget utilization for compaction trigger
                if event.get("type") == "context_budget":
                    _budget_utilization = event.get("utilization")
                # Capture response for mirroring
                if event.get("type") == "response":
                    response_text = event.get("text", "")
                    response_actions = event.get("client_actions")
                event_with_session = {**event, "session_id": str(session_id)}
                yield f"data: {json.dumps(event_with_session)}\n\n"

            # Use a fresh DB session — the dependency-injected `db` may be
            # closed by FastAPI before this streaming generator finishes.
            from app.db.engine import async_session as _async_session
            try:
                async with _async_session() as _stream_db:
                    await persist_turn(
                        _stream_db, session_id, bot, messages, from_index,
                        correlation_id=correlation_id,
                        msg_metadata=req.msg_metadata,
                        channel_id=channel_id,
                    )
            except Exception:
                logger.exception("CRITICAL: persist_turn failed for session %s — messages will be lost", session_id)

            # If SSE disconnected before the "response" event, extract from messages
            if not response_text and not was_cancelled:
                for _msg in reversed(messages[from_index:]):
                    if _msg.get("role") == "assistant":
                        _c = _msg.get("content", "")
                        if isinstance(_c, str) and _c:
                            response_text = _c
                            break
                        elif isinstance(_c, list):
                            for _blk in _c:
                                if isinstance(_blk, dict) and _blk.get("type") == "text":
                                    response_text = _blk.get("text", "")
                                    break
                            if response_text:
                                break

            # Mirror response to integration (skip if cancelled)
            if not was_cancelled and not req.dispatch_config and response_text:
                await _mirror_to_integration(
                    channel, response_text,
                    bot_id=req.bot_id, client_actions=response_actions,
                )

            maybe_compact(
                session_id, bot, messages,
                correlation_id=correlation_id,
                dispatch_type=req.dispatch_type,
                dispatch_config=req.dispatch_config,
                budget_utilization=_budget_utilization,
            )
        except Exception as e:
            logger.exception("Streaming agent loop error")
            yield f"data: {json.dumps({'type': 'error', 'detail': str(e)})}\n\n"
        finally:
            session_locks.release(session_id)

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
    _auth=Depends(require_scopes("chat")),
):
    logger.info("POST /chat/tool_result  request_id=%s  result_len=%d", req.request_id, len(req.result))
    if not resolve_pending(req.request_id, req.result):
        raise HTTPException(status_code=404, detail=f"No pending request: {req.request_id}")
    return {"status": "ok"}
