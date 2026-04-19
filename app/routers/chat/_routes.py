"""Chat HTTP handlers — validate, enqueue a turn, return 202.

Phase E of the Integration Delivery refactor. POST ``/chat`` and POST
``/chat/stream`` no longer drive the agent loop in-band. They:

1. Resolve the channel and active session.
2. Apply the same throttle / pause / session-lock policy as before.
3. Call ``start_turn(...)``, which spawns the background turn worker.
4. Return ``202 Accepted`` with ``{session_id, turn_id, stream_id}``.

The turn worker (``app/services/turn_worker.py``) drives ``run_stream``,
publishes typed ``ChannelEvent``s to the channel-events bus, persists the
turn (which fans out to integrations via the outbox + drainer), and
publishes ``TURN_ENDED`` when done. Subscribers tail
``GET /api/v1/channels/{id}/events?since=N``.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import get_bot, list_bots
from app.agent.pending import resolve_pending
from app.config import settings as _settings
from app.db.models import Message as MessageModel, Task as TaskModel
from app.dependencies import get_db, require_scopes
from app.services import session_locks
from app.services.channel_throttle import is_throttled as _channel_throttled, record_run as _record_channel_run
from app.services.sessions import (
    store_passive_message,
)
from app.services.turns import SessionBusyError, TurnHandle, start_turn

from ._context import prepare_bot_context
from ._helpers import (
    _create_attachments_from_metadata,
    _extract_user,
    _resolve_audio_native,
    _resolve_channel_and_session,
    _transcribe_audio_data,
    _try_resolve_sub_session_chat,
)
from ._multibot import _maybe_route_to_member_bot
from ._schemas import (
    CancelRequest,
    CancelResponse,
    ChatRequest,
    SecretCheckRequest,
    SecretCheckResponse,
    ToolResultRequest,
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


async def _enqueue_chat_turn(
    req: ChatRequest,
    db: AsyncSession,
    auth_result,
) -> JSONResponse:
    """Shared body for POST /chat and POST /chat/stream.

    Validates the request, resolves the channel/session, applies throttle
    and pause policy, calls ``start_turn``, returns ``202 Accepted``.
    """
    user = _extract_user(auth_result)
    bot = get_bot(req.bot_id)

    if not req.msg_metadata and user is not None:
        req.msg_metadata = {
            "source": "web",
            "sender_type": "human",
            "sender_id": f"user:{user.id}",
            "sender_display_name": user.display_name,
        }

    audio_data = None
    audio_format = None
    message = req.message

    if req.audio_data:
        if _resolve_audio_native(req, bot):
            audio_data = req.audio_data
            audio_format = req.audio_format
            if not message:
                message = "[audio message]"
            logger.info(
                "POST /chat  bot=%s  session=%s  native_audio fmt=%s",
                req.bot_id, req.session_id, audio_format,
            )
        else:
            logger.info(
                "POST /chat  bot=%s  session=%s  transcribing audio",
                req.bot_id, req.session_id,
            )
            from app.agent.hooks import HookContext, fire_hook_with_override
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

    # --- Sub-session follow-up branch ----------------------------------
    # A POST whose ``session_id`` names a terminal pipeline run's
    # sub-session routes through a dedicated shorter path: the parent
    # channel is used only for bus routing + membership auth, history
    # scope is the sub-session's own Messages, the bot is forced to
    # the run's task.bot_id, and outbox writes are suppressed so external
    # renderers (Slack etc.) don't receive the follow-up.
    sub_chat = await _try_resolve_sub_session_chat(db, req, user=user)
    if sub_chat is not None:
        return await _enqueue_sub_session_turn(
            req=req,
            user=user,
            bot=get_bot(req.bot_id),
            message=message,
            att_payload=att_payload,
            audio_data=audio_data,
            audio_format=audio_format,
            sub_chat=sub_chat,
            db=db,
        )
    # --- End sub-session branch ---------------------------------------

    try:
        channel, session_id, messages, _is_integration = await _resolve_channel_and_session(
            db, req, user=user, preserve_metadata=True,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Session error: {e}")

    channel_id = channel.id

    # Multi-bot channel: if user @-tagged a member bot, route to that bot.
    _primary_bot_id = bot.id
    bot, _member_config = await _maybe_route_to_member_bot(db, channel, bot, message)

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

    logger.info(
        "POST /chat  bot=%s  channel=%s  session=%s  passive=%s  file_metadata=%d  message=%r",
        bot.id, channel_id, session_id, req.passive, len(req.file_metadata), message[:80],
    )

    # Passive path: store message without running agent.
    if req.passive:
        await store_passive_message(
            db, session_id, message, req.msg_metadata or {}, channel_id=channel_id,
        )
        return JSONResponse(
            {"session_id": str(session_id), "passive": True},
            status_code=202,
        )

    # Channel throttle: prevent bot-to-bot infinite loops. Human messages from
    # the web UI are exempt.
    _sender_type = (req.msg_metadata or {}).get("sender_type", "")
    if _sender_type != "human" and _channel_throttled(str(channel_id)):
        await store_passive_message(
            db, session_id, message,
            {**(req.msg_metadata or {}), "throttled": True},
            channel_id=channel_id,
        )
        return JSONResponse(
            {"session_id": str(session_id), "throttled": True},
            status_code=202,
        )
    _record_channel_run(str(channel_id))

    # System pause: queue or drop new traffic while paused.
    if _settings.SYSTEM_PAUSED:
        if _settings.SYSTEM_PAUSE_BEHAVIOR == "drop":
            return JSONResponse(
                {"detail": "System is paused. Messages are being dropped."},
                status_code=503,
            )
        queued_task = TaskModel(
            bot_id=req.bot_id,
            client_id=req.client_id,
            session_id=session_id,
            channel_id=channel_id,
            prompt=message,
            status="pending",
            created_at=datetime.now(timezone.utc),
        )
        db.add(queued_task)
        await db.commit()
        await db.refresh(queued_task)
        logger.info("System paused — queued message as task %s", queued_task.id)
        return JSONResponse(
            {
                "session_id": str(session_id),
                "queued": True,
                "task_id": str(queued_task.id),
                "reason": "system_paused",
            },
            status_code=202,
        )

    # Pre-allocate a user message UUID so attachments can be linked at
    # creation time instead of via the fragile orphan-linking sweep in
    # persist_turn (which races with concurrent turns). The message row
    # itself is also pre-persisted here so the attachment FK resolves —
    # turn_worker's _persist_and_publish_user_message is idempotent on
    # pre_allocated_id (it will find the existing row and only publish).
    pre_user_msg_id: uuid.UUID | None = None
    if req.file_metadata:
        pre_user_msg_id = uuid.uuid4()
        _stub_meta = dict(req.msg_metadata or {})
        db.add(MessageModel(
            id=pre_user_msg_id,
            session_id=session_id,
            role="user",
            content=message,
            metadata_=_stub_meta,
            created_at=datetime.now(timezone.utc),
        ))
        await db.commit()
        if req.msg_metadata is None:
            req.msg_metadata = {}
        req.msg_metadata["_pre_user_msg_id"] = str(pre_user_msg_id)

    # Eager attachment records so the agent loop can see them.
    # Capture the created rows and thread their UUIDs into ``att_payload``
    # so the LLM can reference them directly (e.g. via
    # ``generate_image(attachment_ids=...)``) instead of hallucinating a
    # UUID for a fresh upload it has never been told the id of.
    if req.file_metadata:
        source = (req.msg_metadata or {}).get("source", "web")
        created_attachments = await _create_attachments_from_metadata(
            req.file_metadata, channel_id, source, bot_id=req.bot_id,
            message_id=pre_user_msg_id,
        )
        if att_payload:
            # file_metadata covers every upload (images + text), while
            # att_payload only contains vision-eligible entries. Match by
            # (filename, size_bytes) to thread the id onto the right
            # payload entry — filename alone can collide for duplicate
            # uploads in the same turn.
            _by_key = {
                (att.filename, att.size_bytes): str(att.id)
                for att in created_attachments
            }
            for entry in att_payload:
                key = (entry.get("name"), None)
                # Size isn't on the Attachment pydantic model, so fall
                # back to filename-only lookup when we can't match the
                # exact key.
                matched_id: str | None = None
                for (fname, _size), aid in _by_key.items():
                    if fname == entry.get("name"):
                        matched_id = aid
                        break
                if matched_id:
                    entry["attachment_id"] = matched_id

    # Spawn the background turn worker. start_turn returns immediately.
    try:
        handle: TurnHandle = await start_turn(
            channel_id=channel_id,
            session_id=session_id,
            bot=bot,
            primary_bot_id=_primary_bot_id,
            messages=messages,
            user_message=message,
            ctx=ctx,
            req=req,
            user=user,
            audio_data=audio_data,
            audio_format=audio_format,
            att_payload=att_payload,
        )
    except SessionBusyError:
        # Session has an in-flight turn — queue this message as a Task so
        # the task worker picks it up after the active loop releases the lock.
        queued_task = TaskModel(
            bot_id=req.bot_id,
            client_id=req.client_id,
            session_id=session_id,
            channel_id=channel_id,
            prompt=message,
            status="pending",
            created_at=datetime.now(timezone.utc),
        )
        db.add(queued_task)
        # Persist the user message so the UI's DB refetch sees it
        # (prevents the optimistic message from vanishing). When
        # file_metadata is present the row was already pre-persisted above
        # so attachment FKs could resolve — skip re-insert in that case.
        if not pre_user_msg_id:
            _queued_meta = dict(req.msg_metadata or {})
            _queued_meta.pop("_pre_user_msg_id", None)  # strip internal key
            _queued_kw: dict = dict(
                session_id=session_id,
                role="user",
                content=message,
                metadata_=_queued_meta,
                created_at=datetime.now(timezone.utc),
            )
            user_msg = MessageModel(**_queued_kw)
            db.add(user_msg)
        await db.commit()
        await db.refresh(queued_task)
        logger.info(
            "Session %s busy — queued message as task %s",
            session_id, queued_task.id,
        )
        return JSONResponse(
            {
                "session_id": str(session_id),
                "queued": True,
                "task_id": str(queued_task.id),
            },
            status_code=202,
        )

    return JSONResponse(
        {
            "session_id": str(handle.session_id),
            "channel_id": str(handle.channel_id),
            "turn_id": str(handle.turn_id),
        },
        status_code=202,
    )


async def _enqueue_sub_session_turn(
    *,
    req: ChatRequest,
    user,
    bot,
    message: str,
    att_payload: list[dict] | None,
    audio_data: str | None,
    audio_format: str | None,
    sub_chat,
    db: AsyncSession,
) -> JSONResponse:
    """Shorter chat-enqueue path for a sub-session follow-up turn.

    Mirrors the core of ``_enqueue_chat_turn`` but:
    - History scope is the sub-session's own Messages (already loaded).
    - Session id is the sub-session id.
    - Channel id (for bus routing) is the parent channel's id.
    - ``session_scoped=True`` flows through ``start_turn`` so the worker
      suppresses outbox writes and tags published events with session_id
      (so the parent-channel UI filter drops them and the run-view modal
      picks them up via its session filter).
    - No multi-bot @-routing (a run's bot is fixed).
    - No passive / throttle / system-pause / attachment-eager-insert paths
      (all unnecessary for a web-originated follow-up on a terminal run).
    """
    sub_entry = sub_chat.entry
    parent_channel = sub_chat.parent_channel
    session_id = sub_entry.session.id
    messages = sub_chat.messages

    # For channel-less ephemeral sessions, parent_channel may be None.
    # start_turn requires a channel_id; raise HTTP 400 if unavailable.
    if parent_channel is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "This ephemeral session has no parent channel — "
                "a parent_channel_id is required to enqueue a turn."
            ),
        )
    channel_id = parent_channel.id

    ctx = await prepare_bot_context(
        messages=messages,
        bot=bot,
        primary_bot_id=bot.id,
        channel_id=channel_id,
        member_config=None,
        user_message=message,
        msg_metadata=req.msg_metadata,
        db=db,
    )

    task_id_str = str(sub_entry.source_task.id) if sub_entry.source_task is not None else "ephemeral"
    logger.info(
        "POST /chat  sub_session  bot=%s  channel=%s  session=%s  task=%s  message=%r",
        bot.id, channel_id, session_id, task_id_str, message[:80],
    )

    try:
        handle: TurnHandle = await start_turn(
            channel_id=channel_id,
            session_id=session_id,
            bot=bot,
            primary_bot_id=bot.id,
            messages=messages,
            user_message=message,
            ctx=ctx,
            req=req,
            user=user,
            audio_data=audio_data,
            audio_format=audio_format,
            att_payload=att_payload,
            session_scoped=True,
        )
    except SessionBusyError:
        # The sub-session lock is held only while a follow-up turn is in
        # flight (we gate entry on terminal pipeline status, so the
        # pipeline's own lock already released). A concurrent follow-up
        # lands as 202 queued — same semantics as the channel path.
        queued_task = TaskModel(
            bot_id=req.bot_id,
            client_id=req.client_id,
            session_id=session_id,
            channel_id=None,
            prompt=message,
            status="pending",
            created_at=datetime.now(timezone.utc),
        )
        db.add(queued_task)
        _queued_meta = dict(req.msg_metadata or {})
        db.add(MessageModel(
            id=uuid.uuid4(),
            session_id=session_id,
            role="user",
            content=message,
            metadata_=_queued_meta,
            created_at=datetime.now(timezone.utc),
        ))
        await db.commit()
        await db.refresh(queued_task)
        logger.info(
            "Sub-session %s busy — queued follow-up as task %s",
            session_id, queued_task.id,
        )
        return JSONResponse(
            {
                "session_id": str(session_id),
                "queued": True,
                "task_id": str(queued_task.id),
            },
            status_code=202,
        )

    return JSONResponse(
        {
            "session_id": str(handle.session_id),
            "channel_id": str(handle.channel_id),
            "turn_id": str(handle.turn_id),
            "session_scoped": True,
        },
        status_code=202,
    )


@router.post("/chat")
async def chat(
    req: ChatRequest,
    db: AsyncSession = Depends(get_db),
    auth_result=Depends(require_scopes("chat")),
):
    return await _enqueue_chat_turn(req, db, auth_result)


@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    db: AsyncSession = Depends(get_db),
    auth_result=Depends(require_scopes("chat")),
):
    """Compatibility shim for the Slack/Discord subprocesses.

    Returns the same 202 as POST /chat. The legacy SSE long-poll body is
    gone — subscribers consume the channel-events bus directly.
    """
    return await _enqueue_chat_turn(req, db, auth_result)


@router.post("/chat/cancel", response_model=CancelResponse)
async def chat_cancel(
    req: CancelRequest,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("chat")),
):
    """Cancel an in-progress agent loop and any queued tasks for the session."""
    from sqlalchemy import select, update
    from app.services.channels import ensure_active_session, get_or_create_channel

    channel = await get_or_create_channel(db, client_id=req.client_id, bot_id=req.bot_id)
    session_id = await ensure_active_session(db, channel)
    await db.commit()

    cancelled = session_locks.request_cancel(session_id)

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


@router.post("/chat/tool_result")
async def submit_tool_result(
    req: ToolResultRequest,
    _auth=Depends(require_scopes("chat")),
):
    logger.info(
        "POST /chat/tool_result  request_id=%s  result_len=%d",
        req.request_id, len(req.result),
    )
    if not resolve_pending(req.request_id, req.result):
        raise HTTPException(status_code=404, detail=f"No pending request: {req.request_id}")
    return {"status": "ok"}
