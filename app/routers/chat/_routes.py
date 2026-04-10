"""All route handlers for the chat package."""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import get_bot, list_bots
from app.agent.context import set_agent_context
from app.agent.loop import run_stream
from app.agent.pending import resolve_pending
from app.db.models import Message as MessageModel, Task as TaskModel
from app.dependencies import get_db, require_scopes
from app.services import session_locks
from app.services.channel_throttle import is_throttled as _channel_throttled, record_run as _record_channel_run
from app.services.compaction import maybe_compact
from app.services.sessions import (
    load_or_create,
    persist_turn,
    store_passive_message,
)

from ._schemas import (
    ChatRequest, CancelRequest, CancelResponse, ChatResponse,
    SecretCheckRequest, SecretCheckResponse, ToolResultRequest,
)
from ._helpers import (
    _is_integration_client, _extract_user, _create_attachments_from_metadata,
    _resolve_channel_and_session, _resolve_audio_native, _transcribe_audio_data,
)
from ._mirror import _mirror_to_integration
from ._keepalive import _with_keepalive
from ._context import prepare_bot_context
from ._multibot import (
    _background_tasks, _maybe_route_to_member_bot,
    _detect_member_mentions, _trigger_member_bot_replies, _run_member_bot_reply,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/chat/check-secrets", response_model=SecretCheckResponse)
async def check_secrets(body: SecretCheckRequest, _auth=Depends(require_scopes("chat"))):
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


@router.get("/bots")
async def bots(_auth=Depends(require_scopes("bots:read"))):
    result = []
    for b in list_bots():
        entry: dict = {"id": b.id, "name": b.name, "model": b.model}
        if b.audio_input != "transcribe":
            entry["audio_input"] = b.audio_input
        result.append(entry)
    return result


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
        channel, session_id, messages, is_integration = await _resolve_channel_and_session(
            db, req, user=user, preserve_metadata=True,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Session error: {e}")

    channel_id = channel.id

    # Multi-bot channel: if user @-tagged a member bot, route to that bot
    _primary_bot_id = bot.id
    bot, _member_config = await _maybe_route_to_member_bot(db, channel, bot, message)

    # --- Unified context preparation ---
    ctx = await prepare_bot_context(
        messages=messages,
        bot=bot,
        primary_bot_id=_primary_bot_id,
        channel_id=channel_id,
        member_config=_member_config,
        user_message=message,
        msg_metadata=req.msg_metadata,
        db=db,
    )

    logger.info("POST /chat  bot=%s  channel=%s  session=%s  passive=%s  file_metadata=%d  message=%r",
                bot.id, channel_id, session_id, req.passive, len(req.file_metadata), message[:80])

    # Passive path: store message without running agent
    if req.passive:
        await store_passive_message(db, session_id, message, req.msg_metadata or {}, channel_id=channel_id)
        return ChatResponse(session_id=session_id, response="", client_actions=[])

    # Channel throttle: prevent bot-to-bot infinite loops.
    # Human messages from the web UI are exempt.
    _sender_type = (req.msg_metadata or {}).get("sender_type", "")
    if _sender_type != "human" and _channel_throttled(str(channel_id)):
        await store_passive_message(db, session_id, message, {**(req.msg_metadata or {}), "throttled": True}, channel_id=channel_id)
        return ChatResponse(session_id=session_id, response="", client_actions=[])
    _record_channel_run(str(channel_id))

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

    # Detect secret-like patterns in user message and register for redaction
    _detected_secrets = False
    if message:
        from app.services.secret_registry import (
            detect_patterns as _detect_patterns,
            extract_pattern_values as _extract_values,
            register_runtime_secrets as _register_secrets,
            is_enabled as _secrets_enabled,
        )
        if _secrets_enabled():
            _pattern_hits = _detect_patterns(message)
            if _pattern_hits:
                _detected_secrets = True
                _secret_vals = _extract_values(message)
                if _secret_vals:
                    _register_secrets(_secret_vals)

    # Persist user message immediately so it's visible even if the agent loop crashes
    _pre_user_msg_id = None
    try:
        _user_record = MessageModel(
            session_id=session_id,
            role="user",
            content=message,
            correlation_id=correlation_id,
            metadata_=req.msg_metadata or {},
            created_at=datetime.now(timezone.utc),
        )
        db.add(_user_record)
        await db.commit()
        await db.refresh(_user_record)
        _pre_user_msg_id = _user_record.id
        # Ship the persisted row through the channel events bus so subscribers
        # can append to local state without a DB refetch.
        if channel_id:
            from app.services.channel_events import publish_message as _publish_message
            _publish_message(channel_id, _user_record)
    except Exception:
        logger.warning("Failed to pre-persist user message for session %s", session_id, exc_info=True)
        await db.rollback()

    try:
        # Apply model override (per-request takes priority over member config)
        _effective_model_override = req.model_override or ctx.model_override

        # Use run_stream() and publish events to channel event bus so UI tabs
        # watching this channel see live streaming (typing indicator, tokens, tools).
        from app.services.channel_events import publish as _publish_stream
        _api_stream_id = str(uuid.uuid4())
        _publish_stream(channel_id, "stream_start", {
            "stream_id": _api_stream_id,
            "responding_bot_id": bot.id,
            "responding_bot_name": bot.name,
        })

        response_text = ""
        response_transcript = None
        response_actions: list | None = None
        _intermediate_texts: list[str] = []
        try:
            async for event in run_stream(
                messages, bot, message,
                session_id=session_id, client_id=req.client_id,
                audio_data=audio_data, audio_format=audio_format,
                attachments=att_payload,
                correlation_id=correlation_id,
                dispatch_type=req.dispatch_type,
                dispatch_config=req.dispatch_config,
                channel_id=channel_id,
                model_override=_effective_model_override,
                provider_id_override=req.model_provider_id_override,
                system_preamble=ctx.system_preamble,
            ):
                etype = event.get("type")
                if etype == "response":
                    final_text = event.get("text", "")
                    if not (final_text or "").strip() and _intermediate_texts:
                        response_text = "\n\n".join(_intermediate_texts)
                    else:
                        response_text = final_text
                    response_actions = event.get("client_actions")
                elif etype == "assistant_text":
                    _intermediate_texts.append(event.get("text", ""))
                elif etype == "transcript":
                    response_transcript = event.get("text")
                elif etype == "delegation_post" and req.dispatch_type and req.dispatch_config:
                    from app.services.delegation import delegation_service as _ds
                    try:
                        await _ds.post_child_response(
                            dispatch_type=req.dispatch_type,
                            dispatch_config=req.dispatch_config,
                            text=event.get("text", ""),
                            bot_id=event.get("bot_id") or "",
                            reply_in_thread=event.get("reply_in_thread", False),
                            client_actions=event.get("client_actions", []),
                        )
                    except Exception:
                        logger.warning("POST /chat: delegation_post failed for bot %s", event.get("bot_id"))
                event_with_session = {**event, "session_id": str(session_id)}
                _publish_stream(channel_id, "stream_event", {
                    "stream_id": _api_stream_id,
                    "event": event_with_session,
                })
        finally:
            try:
                _publish_stream(channel_id, "stream_end", {"stream_id": _api_stream_id})
            except Exception:
                logger.warning("Failed to publish stream_end for %s", _api_stream_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM backend error: {e}")

    logger.info("Response (%d chars): %r", len(response_text), response_text[:100])
    if response_actions:
        logger.info("Client actions: %d", len(response_actions))
        logger.debug("Client actions: %s", response_actions)

    await persist_turn(
        db, session_id, bot, messages, from_index,
        correlation_id=correlation_id,
        msg_metadata=req.msg_metadata,
        channel_id=channel_id,
        pre_user_msg_id=_pre_user_msg_id,
    )
    maybe_compact(
        session_id, bot, messages,
        correlation_id=correlation_id,
        dispatch_type=req.dispatch_type,
        dispatch_config=req.dispatch_config,
    )

    # Mirror response to integration (redact if secrets detected)
    if not req.dispatch_config and response_text:
        _mirror_text = response_text
        if _detected_secrets:
            from app.services.secret_registry import redact as _redact
            _mirror_text = _redact(_mirror_text)
        await _mirror_to_integration(
            channel, _mirror_text,
            bot_id=bot.id, client_actions=response_actions,
        )

    # Multi-bot: trigger member bots @-mentioned in the user's message.
    _user_mentioned: set[str] = set()
    if channel_id:
        from app.agent.context import current_invoked_member_bots as _cimb
        _already_invoked = _cimb.get() or set()
        _um = await _detect_member_mentions(channel_id, bot.id, message, _depth=0)
        if _um:
            _um_snap = ctx.raw_snapshot  # Already deep-copied, metadata intact
            for _bid, _cfg in _um:
                if _bid in _already_invoked:
                    continue
                _user_mentioned.add(_bid)
                _um_task = asyncio.create_task(
                    _run_member_bot_reply(
                        channel_id, session_id, _bid, _cfg,
                        bot.id, _depth=1,
                        messages_snapshot=_um_snap,
                        stream_id=str(uuid.uuid4()),
                    )
                )
                _background_tasks.add(_um_task)
                _um_task.add_done_callback(_background_tasks.discard)

    # Bot-to-bot @-mention: if the response mentions a member bot, trigger its reply.
    # Pass a snapshot so member bots run lock-free.
    if response_text and channel_id:
        import copy as _copy_chat
        _snap = _copy_chat.deepcopy(ctx.raw_snapshot)
        _snap.append({
            "role": "assistant",
            "content": response_text,
            "_metadata": {"sender_id": f"bot:{bot.id}", "sender_display_name": bot.name},
        })
        task = asyncio.create_task(
            _trigger_member_bot_replies(
                channel_id, session_id, bot.id, response_text,
                messages_snapshot=_snap,
                already_invoked=_user_mentioned,
            )
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    return ChatResponse(
        session_id=session_id,
        response=response_text,
        transcript=response_transcript or "",
        client_actions=response_actions or [],
    )


@router.post("/chat/cancel", response_model=CancelResponse)
async def chat_cancel(
    req: CancelRequest,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("chat")),
):
    """Cancel an in-progress agent loop and any queued tasks for the session."""
    from sqlalchemy import select, update
    from app.services.channels import get_or_create_channel, ensure_active_session

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
        channel, session_id, messages, is_integration = await _resolve_channel_and_session(
            db, req, user=user, preserve_metadata=True,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Session error: {e}")

    channel_id = channel.id

    # Multi-bot channel: if user @-tagged a member bot, route to that bot
    _primary_bot_id = bot.id
    bot, _member_config = await _maybe_route_to_member_bot(db, channel, bot, message)

    # --- Unified context preparation ---
    ctx = await prepare_bot_context(
        messages=messages,
        bot=bot,
        primary_bot_id=_primary_bot_id,
        channel_id=channel_id,
        member_config=_member_config,
        user_message=message,
        msg_metadata=req.msg_metadata,
        db=db,
    )

    logger.info("POST /chat/stream  bot=%s  channel=%s  session=%s  passive=%s  file_metadata=%d  message=%r",
                req.bot_id, channel_id, session_id, req.passive, len(req.file_metadata), message[:80])

    # Passive path: store message and return empty stream
    if req.passive:
        await store_passive_message(db, session_id, message, req.msg_metadata or {}, channel_id=channel_id)

        async def _passive_stream():
            yield f"data: {json.dumps({'type': 'passive_stored', 'session_id': str(session_id)})}\n\n"

        return StreamingResponse(_passive_stream(), media_type="text/event-stream")

    # Channel throttle: prevent bot-to-bot infinite loops.
    # Human messages from the web UI are exempt.
    _sender_type_s = (req.msg_metadata or {}).get("sender_type", "")
    if _sender_type_s != "human" and _channel_throttled(str(channel_id)):
        await store_passive_message(db, session_id, message, {**(req.msg_metadata or {}), "throttled": True}, channel_id=channel_id)

        async def _throttled_stream():
            yield f"data: {json.dumps({'type': 'throttled', 'session_id': str(session_id), 'detail': 'Channel throttled — too many agent runs in short window'})}\n\n"

        return StreamingResponse(_throttled_stream(), media_type="text/event-stream")
    _record_channel_run(str(channel_id))

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
    # request as a Task and return a `queued` event.
    if not session_locks.acquire(session_id):
        # Clear thread_ts so the delayed response posts to the channel directly
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

        # Persist the user message to the session so the UI's DB refetch
        # includes it (prevents the optimistic message from vanishing).
        now = datetime.now(timezone.utc)
        user_msg = MessageModel(
            session_id=session_id,
            role="user",
            content=message,
            metadata_=req.msg_metadata or {},
            created_at=now,
        )
        db.add(user_msg)

        await db.commit()
        await db.refresh(queued_task)
        await db.refresh(user_msg)
        _task_id = str(queued_task.id)
        logger.info(
            "Session %s busy — queued message as task %s", session_id, _task_id
        )

        # Ship the queued user message row through the channel events bus.
        if channel_id:
            from app.services.channel_events import publish_message as _publish_message
            _publish_message(channel_id, user_msg)

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

            # Tell the initiating tab which bot is responding FIRST
            _stream_meta = {"type": "stream_meta", "responding_bot_id": bot.id, "responding_bot_name": bot.name}
            yield f"data: {json.dumps(_stream_meta)}\n\n"

            # Mirror user message to integration (skip if caller already handles delivery)
            if not req.dispatch_config:
                await _mirror_to_integration(channel, message, is_user_message=True, user=user)

            # Detect secret-like patterns in user message and emit warning
            _detected_secrets = False
            if message:
                from app.services.secret_registry import (
                    detect_patterns as _detect_patterns,
                    extract_pattern_values as _extract_values,
                    register_runtime_secrets as _register_secrets,
                    is_enabled as _secrets_enabled,
                )
                if _secrets_enabled():
                    _pattern_hits = _detect_patterns(message)
                    if _pattern_hits:
                        _detected_secrets = True
                        _secret_vals = _extract_values(message)
                        if _secret_vals:
                            _register_secrets(_secret_vals)
                        yield f"data: {json.dumps({'type': 'secret_warning', 'patterns': [{'type': p['type']} for p in _pattern_hits]})}\n\n"

            # Persist user message immediately
            _pre_user_msg_id = None
            try:
                from app.db.engine import async_session as _async_session_early
                async with _async_session_early() as _early_db:
                    _user_record = MessageModel(
                        session_id=session_id,
                        role="user",
                        content=message,
                        correlation_id=correlation_id,
                        metadata_=req.msg_metadata or {},
                        created_at=datetime.now(timezone.utc),
                    )
                    _early_db.add(_user_record)
                    await _early_db.commit()
                    await _early_db.refresh(_user_record)
                    _pre_user_msg_id = _user_record.id
                    if channel_id:
                        from app.services.channel_events import publish_message as _publish_message
                        _publish_message(channel_id, _user_record)
            except Exception:
                logger.warning("Failed to pre-persist user message for session %s", session_id, exc_info=True)

            response_text = ""
            response_actions = None
            was_cancelled = False

            # Apply model override (per-request takes priority over member config)
            _effective_model_override_s = req.model_override or ctx.model_override

            # Notify observers that streaming is starting
            from app.services.channel_events import publish as _publish_stream
            _primary_stream_id = str(uuid.uuid4())
            _publish_stream(channel_id, "stream_start", {
                "stream_id": _primary_stream_id,
                "responding_bot_id": bot.id,
                "responding_bot_name": bot.name,
            })

            # Multi-bot: fire parallel member streams for OTHER bots @-mentioned
            # in the user's message
            _user_mentioned: list[tuple[str, dict]] = []
            if channel_id:
                _user_mentioned = await _detect_member_mentions(
                    channel_id, bot.id, message, _depth=0,
                )
                if _user_mentioned:
                    _user_snap = ctx.raw_snapshot  # Already deep-copied, metadata intact
                    _auto_invoked_ids: set[str] = set()
                    for _um_bot_id, _um_config in _user_mentioned:
                        _um_sid = str(uuid.uuid4())
                        _um_task = asyncio.create_task(
                            _run_member_bot_reply(
                                channel_id, session_id, _um_bot_id, _um_config,
                                bot.id, _depth=1,
                                messages_snapshot=_user_snap,
                                stream_id=_um_sid,
                            )
                        )
                        _background_tasks.add(_um_task)
                        _um_task.add_done_callback(_background_tasks.discard)
                        _auto_invoked_ids.add(_um_bot_id)

                    # Seed context var so dedup logic skips these bots
                    from app.agent.context import current_invoked_member_bots
                    current_invoked_member_bots.set(_auto_invoked_ids)

                    # Tell the primary bot these bots are already responding
                    _auto_names = []
                    for _ai_id, _ in _user_mentioned:
                        try:
                            _ai_bot = get_bot(_ai_id)
                            _auto_names.append(f"{_ai_bot.name} (@{_ai_id})")
                        except Exception:
                            _auto_names.append(f"@{_ai_id}")
                    messages.append({
                        "role": "system",
                        "content": (
                            f"The following bots were auto-invoked by the user's @-mentions and are "
                            f"already responding in parallel: {', '.join(_auto_names)}. "
                            f"Do NOT @-mention them again in your response."
                        ),
                    })

            stream = run_stream(
                messages, bot, message,
                session_id=session_id, client_id=req.client_id,
                audio_data=audio_data, audio_format=audio_format,
                attachments=att_payload,
                correlation_id=correlation_id,
                dispatch_type=req.dispatch_type,
                dispatch_config=req.dispatch_config,
                channel_id=channel_id,
                model_override=_effective_model_override_s,
                provider_id_override=req.model_provider_id_override,
                system_preamble=ctx.system_preamble,
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
                    _publish_stream(channel_id, "stream_event", {"stream_id": _primary_stream_id, "event": event_with_session})
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
                # Relay to observers (other tabs/devices on the same channel)
                _publish_stream(channel_id, "stream_event", {"stream_id": _primary_stream_id, "event": event_with_session})

            # Persist turn with fresh DB session
            from app.db.engine import async_session as _async_session
            try:
                async with _async_session() as _stream_db:
                    await persist_turn(
                        _stream_db, session_id, bot, messages, from_index,
                        correlation_id=correlation_id,
                        msg_metadata=req.msg_metadata,
                        channel_id=channel_id,
                        pre_user_msg_id=_pre_user_msg_id,
                    )
            except Exception:
                logger.exception("CRITICAL: persist_turn failed for session %s — messages will be lost", session_id)

            # Notify observers that streaming ended (after persist so data is committed)
            _publish_stream(channel_id, "stream_end", {"stream_id": _primary_stream_id})

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

            # Mirror response to integration
            if not was_cancelled and not req.dispatch_config and response_text:
                _mirror_text = response_text
                if _detected_secrets:
                    from app.services.secret_registry import redact as _redact
                    _mirror_text = _redact(_mirror_text)
                await _mirror_to_integration(
                    channel, _mirror_text,
                    bot_id=bot.id, client_actions=response_actions,
                )

            maybe_compact(
                session_id, bot, messages,
                correlation_id=correlation_id,
                dispatch_type=req.dispatch_type,
                dispatch_config=req.dispatch_config,
                budget_utilization=_budget_utilization,
            )

            # Bot-to-bot @-mention: trigger member bot replies
            if not was_cancelled and response_text and channel_id:
                from app.agent.context import current_invoked_member_bots
                _already_invoked = set(current_invoked_member_bots.get() or ())
                if _user_mentioned:
                    _already_invoked.update(bid for bid, _ in _user_mentioned)

                import copy
                _messages_snapshot = copy.deepcopy(ctx.raw_snapshot)
                _messages_snapshot.append({
                    "role": "assistant",
                    "content": response_text,
                    "_metadata": {"sender_id": f"bot:{bot.id}", "sender_display_name": bot.name},
                })
                await _trigger_member_bot_replies(
                    channel_id, session_id, bot.id, response_text,
                    _depth=1,
                    messages_snapshot=_messages_snapshot,
                    already_invoked=_already_invoked,
                )
        except Exception as e:
            logger.exception("Streaming agent loop error")
            yield f"data: {json.dumps({'type': 'error', 'detail': str(e)})}\n\n"
            from app.services.channel_events import publish as _publish_err
            _publish_err(channel_id, "stream_end", {"stream_id": _primary_stream_id})
        finally:
            session_locks.release(session_id)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/chat/tool_result")
async def submit_tool_result(
    req: ToolResultRequest,
    _auth=Depends(require_scopes("chat")),
):
    logger.info("POST /chat/tool_result  request_id=%s  result_len=%d", req.request_id, len(req.result))
    if not resolve_pending(req.request_id, req.result):
        raise HTTPException(status_code=404, detail=f"No pending request: {req.request_id}")
    return {"status": "ok"}
