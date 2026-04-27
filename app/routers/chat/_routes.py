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
from app.db.models import Bot as BotRow, Message as MessageModel, Session, Task as TaskModel, User
from app.dependencies import get_db, require_scopes
from app.services.bots_visibility import apply_bot_visibility
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
async def bots(
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_scopes("bots:read")),
):
    all_bots = list_bots()

    # Non-admin users see only bots they own or have been granted. API-key
    # principals and admins see everything.
    visible_ids: set[str] | None = None
    user = auth if isinstance(auth, User) else None
    if user is not None and not user.is_admin:
        from sqlalchemy import select as _select
        stmt = apply_bot_visibility(_select(BotRow.id), user)
        rows = await db.execute(stmt)
        visible_ids = {row[0] for row in rows.all()}

    result = []
    for b in all_bots:
        if visible_ids is not None and b.id not in visible_ids:
            continue
        entry: dict = {
            "id": b.id,
            "name": b.name,
            "model": b.model,
            "harness_runtime": getattr(b, "harness_runtime", None),
            "shared_workspace_id": getattr(b, "shared_workspace_id", None),
            "memory_scheme": getattr(b, "memory_scheme", None),
            "history_mode": getattr(b, "history_mode", None),
        }
        if b.audio_input != "transcribe":
            entry["audio_input"] = b.audio_input
        result.append(entry)
    return result


async def _maybe_route_inbound_thread(db: AsyncSession, req: ChatRequest) -> None:
    """Lazily resolve a Spindrel thread session for an inbound thread reply.

    Stamps ``req.session_id`` in place when the dispatch_config identifies
    a native integration thread (e.g. Slack ``thread_ts``). No-ops
    otherwise. The downstream ``_try_resolve_sub_session_chat`` picks up
    the populated session_id and routes through the sub-session branch.

    Integration-generic: delegates to the integration's
    ``IntegrationMeta.extract_thread_ref_from_dispatch`` hook. Any
    integration that wants inbound thread mirroring just registers its
    own hook in its ``hooks.py``.
    """
    from app.agent.hooks import get_integration_meta
    from app.db.models import Channel as ChannelModel
    from app.services.channels import resolve_channel_by_client_id
    from app.services.sub_sessions import resolve_or_spawn_external_thread_session

    meta = get_integration_meta(req.dispatch_type or "")
    if meta is None or meta.extract_thread_ref_from_dispatch is None:
        return
    try:
        ref = meta.extract_thread_ref_from_dispatch(req.dispatch_config or {})
    except Exception:
        logger.warning(
            "extract_thread_ref_from_dispatch failed for %s",
            req.dispatch_type, exc_info=True,
        )
        return
    if not ref:
        return

    # Resolve the parent channel via client_id. We rely on the integration
    # having set up a channel for this client_id already (ensure_channel
    # contract) — if it hasn't, the fall-through channel-resolution path
    # in ``_resolve_channel_and_session`` still runs without a session_id.
    channel: ChannelModel | None = None
    if req.client_id:
        channel = await resolve_channel_by_client_id(db, req.client_id)
    if channel is None:
        return

    try:
        sub = await resolve_or_spawn_external_thread_session(
            db,
            integration_id=req.dispatch_type or "",
            channel=channel,
            ref=ref,
            bot_id=req.bot_id or channel.bot_id,
        )
    except Exception:
        logger.warning(
            "resolve_or_spawn_external_thread_session failed (integration=%s ref=%s)",
            req.dispatch_type, ref, exc_info=True,
        )
        return

    await db.commit()
    req.session_id = sub.id
    logger.info(
        "inbound thread routed: integration=%s ref=%s session=%s",
        req.dispatch_type, ref, sub.id,
    )


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

    if user is not None:
        req.msg_metadata = {
            **(req.msg_metadata or {}),
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

    # --- External thread auto-routing ----------------------------------
    # When an inbound integration event carries a native thread id (Slack
    # ``thread_ts``, Discord thread channel, etc.) and the caller did not
    # specify a ``session_id`` explicitly, resolve-or-spawn the matching
    # Spindrel thread sub-session and rewrite ``req.session_id`` so the
    # sub-session branch below catches it. Keeps the thread UX in sync
    # across platforms without Slack-specific code on the chat router.
    if req.session_id is None and req.dispatch_type and req.dispatch_config:
        await _maybe_route_inbound_thread(db, req)

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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Session error: {e}")

    channel_id = channel.id
    session_scoped_delivery = req.external_delivery == "none"

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
            execution_config={"session_scoped": True, "external_delivery": req.external_delivery}
            if session_scoped_delivery else None,
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
                "session_scoped": session_scoped_delivery,
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
            session_scoped=session_scoped_delivery,
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
            execution_config={"session_scoped": True, "external_delivery": req.external_delivery}
            if session_scoped_delivery else None,
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
                "session_scoped": session_scoped_delivery,
            },
            status_code=202,
        )

    _attention_item_id = (req.msg_metadata or {}).get("attention_item_id")
    if _attention_item_id:
        try:
            from app.services.workspace_attention import actor_label, mark_attention_responded
            await mark_attention_responded(
                db,
                uuid.UUID(str(_attention_item_id)),
                response_message_id=pre_user_msg_id,
                responded_by=actor_label(user),
            )
        except Exception:
            logger.warning(
                "Failed to mark attention item responded: %s",
                _attention_item_id,
                exc_info=True,
            )

    return JSONResponse(
        {
            "session_id": str(handle.session_id),
            "channel_id": str(handle.channel_id),
            "turn_id": str(handle.turn_id),
            "session_scoped": session_scoped_delivery,
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
    # The turn worker publishes on session_id as the bus key in that case,
    # and the UI subscribes via GET /api/v1/sessions/{id}/events.
    channel_id = parent_channel.id if parent_channel is not None else None

    # ``session_scoped=True`` for every sub-session (thread, ephemeral,
    # pipeline/eval follow-up) so the worker tags ``session_id`` on bus
    # payloads — the web UI filters by session_id to only show events on
    # its thread. Outbox fanout is decided separately inside
    # ``persist_turn``: thread sessions mirror to parent-channel
    # integrations via walkup + ``Session.integration_thread_refs``;
    # other sub-sessions stay modal-only.

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
        bot.id, channel_id or "<none>", session_id, task_id_str, message[:80],
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
            "channel_id": str(handle.channel_id) if handle.channel_id else None,
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
    from sqlalchemy import update
    from app.services.channels import ensure_active_session, get_or_create_channel

    if req.session_id is not None:
        session_id = req.session_id
        if req.channel_id is not None:
            session = await db.get(Session, session_id)
            if session is not None and session.channel_id not in (None, req.channel_id):
                raise HTTPException(status_code=404, detail="Session does not belong to this channel.")
    else:
        channel = await get_or_create_channel(
            db,
            channel_id=req.channel_id,
            client_id=req.client_id,
            bot_id=req.bot_id,
        )
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

    # Phase 3: also expire any pending harness approvals so the UI flips them
    # to expired immediately instead of waiting on the 300s row timeout.
    from app.services.agent_harnesses.approvals import (
        cancel_pending_harness_approvals_for_session,
    )
    try:
        await cancel_pending_harness_approvals_for_session(session_id)
    except Exception:
        logger.exception(
            "chat/cancel: failed to cancel pending harness approvals for %s",
            session_id,
        )
    from app.services.agent_harnesses.interactions import (
        cancel_pending_harness_questions_for_session,
    )
    try:
        await cancel_pending_harness_questions_for_session(session_id)
    except Exception:
        logger.exception(
            "chat/cancel: failed to cancel pending harness questions for %s",
            session_id,
        )

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
