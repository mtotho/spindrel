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

import base64
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
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
from app.services.recent_attachments import RecentInlineImageContext, recent_inline_image_context
from app.services.channel_member_turns import maybe_route_to_member_bot
from app.services.turn_context import prepare_bot_context
from app.services.turns import SessionBusyError, TurnHandle, start_turn
from app.services.audio_input import AudioInputError, decode_base64_audio
from app.agent.recording import _record_trace_event
from app.utils import safe_create_task

from ._helpers import (
    _create_attachments_from_metadata,
    _extract_user,
    _resolve_audio_native,
    _resolve_channel_and_session,
    _transcribe_audio_data,
    _try_resolve_sub_session_chat,
)
from app.schemas.chat import (
    CancelRequest,
    CancelResponse,
    ChatRequest,
    FileMetadata,
    SecretCheckRequest,
    SecretCheckResponse,
    ToolResultRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()
_BUSY_CHAT_BURST_DELAY_SECONDS = 2


@dataclass
class _PreparedChatInput:
    message: str
    audio_data: str | None
    audio_format: str | None
    att_payload: list[dict] | None
    recent_image_context: RecentInlineImageContext | None = None


@dataclass
class _NormalChatRun:
    channel: Any
    session_id: uuid.UUID
    messages: list[dict]
    bot: Any
    primary_bot_id: str
    ctx: Any
    session_scoped_delivery: bool


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


def _apply_web_user_metadata(req: ChatRequest, user: User | None) -> None:
    if user is None:
        return
    req.msg_metadata = {
        **(req.msg_metadata or {}),
        "source": "web",
        "sender_type": "human",
        "sender_id": f"user:{user.id}",
        "sender_display_name": user.display_name,
    }


async def _prepare_chat_input(req: ChatRequest) -> _PreparedChatInput:
    audio_data = None
    audio_format = None
    message = req.message

    if req.audio_data:
        try:
            decoded_audio = decode_base64_audio(req.audio_data, req.audio_format)
        except AudioInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if _resolve_audio_native(req):
            audio_data = req.audio_data
            audio_format = decoded_audio.format
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

            override = await fire_hook_with_override("before_transcription", HookContext(
                bot_id=req.bot_id,
                extra={
                    "audio_format": req.audio_format or "m4a",
                    "audio_size_bytes": len(decoded_audio.data),
                    "source": "chat",
                },
            ))
            if isinstance(override, str) and override.strip():
                message = override
            else:
                message = await _transcribe_audio_data(req.audio_data, req.audio_format)
            if not message.strip():
                raise HTTPException(status_code=400, detail="No speech detected in audio")

    if not message and not req.attachments:
        raise HTTPException(status_code=400, detail="No message, audio, or attachments provided")

    if not message.strip() and req.attachments:
        message = "[User sent attachment(s)]"

    return _PreparedChatInput(
        message=message,
        audio_data=audio_data,
        audio_format=audio_format,
        att_payload=[a.model_dump() for a in req.attachments] if req.attachments else None,
    )


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


async def _maybe_enqueue_sub_session_chat(
    *,
    req: ChatRequest,
    db: AsyncSession,
    user: User | None,
    prepared: _PreparedChatInput,
) -> JSONResponse | None:
    if req.session_id is None and req.dispatch_type and req.dispatch_config:
        await _maybe_route_inbound_thread(db, req)

    sub_chat = await _try_resolve_sub_session_chat(db, req, user=user)
    if sub_chat is None:
        return None
    return await _enqueue_sub_session_turn(
        req=req,
        user=user,
        bot=get_bot(req.bot_id),
        message=prepared.message,
        att_payload=prepared.att_payload,
        audio_data=prepared.audio_data,
        audio_format=prepared.audio_format,
        sub_chat=sub_chat,
        db=db,
    )


async def _resolve_normal_chat_run(
    *,
    req: ChatRequest,
    db: AsyncSession,
    user: User | None,
    bot,
    message: str,
) -> _NormalChatRun:
    try:
        channel, session_id, messages, _is_integration = await _resolve_channel_and_session(
            db, req, user=user, preserve_metadata=True,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Session error: {exc}") from exc

    primary_bot_id = bot.id
    bot, member_config = await maybe_route_to_member_bot(db, channel, bot, message)
    ctx = await prepare_bot_context(
        messages=messages,
        bot=bot,
        primary_bot_id=primary_bot_id,
        channel_id=channel.id,
        member_config=member_config,
        user_message=message,
        msg_metadata=req.msg_metadata,
        db=db,
    )
    return _NormalChatRun(
        channel=channel,
        session_id=session_id,
        messages=messages,
        bot=bot,
        primary_bot_id=primary_bot_id,
        ctx=ctx,
        session_scoped_delivery=req.external_delivery == "none",
    )


async def _queue_channel_task(
    *,
    db: AsyncSession,
    req: ChatRequest,
    run: _NormalChatRun,
    message: str,
    pre_user_msg_id: uuid.UUID | None = None,
    delay_seconds: int = 0,
) -> TaskModel:
    execution_config = (
        {"session_scoped": True, "external_delivery": req.external_delivery}
        if run.session_scoped_delivery
        else {}
    )
    if pre_user_msg_id is not None:
        execution_config["pre_user_msg_id"] = str(pre_user_msg_id)
    queued_task = TaskModel(
        bot_id=req.bot_id,
        client_id=req.client_id,
        session_id=run.session_id,
        channel_id=run.channel.id,
        prompt=message,
        status="pending",
        task_type="api",
        created_at=datetime.now(timezone.utc),
        scheduled_at=(
            datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
            if delay_seconds > 0
            else None
        ),
        execution_config=execution_config or None,
    )
    db.add(queued_task)
    return queued_task


def _chat_burst_delivery_config(req: ChatRequest, run: _NormalChatRun) -> dict[str, Any]:
    execution_config: dict[str, Any] = {
        "chat_burst": True,
        "burst_user_msg_ids": [],
    }
    if run.session_scoped_delivery:
        execution_config["session_scoped"] = True
        execution_config["external_delivery"] = req.external_delivery
    return execution_config


def _task_matches_chat_burst_policy(task: TaskModel, req: ChatRequest, run: _NormalChatRun) -> bool:
    ecfg = task.execution_config if isinstance(task.execution_config, dict) else {}
    if ecfg.get("chat_burst") is not True:
        return False
    if bool(ecfg.get("session_scoped")) != bool(run.session_scoped_delivery):
        return False
    if run.session_scoped_delivery and ecfg.get("external_delivery") != req.external_delivery:
        return False
    return True


async def _find_pending_chat_burst_task(
    *,
    db: AsyncSession,
    req: ChatRequest,
    run: _NormalChatRun,
) -> TaskModel | None:
    rows = await db.execute(
        select(TaskModel)
        .where(
            TaskModel.status == "pending",
            TaskModel.task_type == "api",
            TaskModel.session_id == run.session_id,
            TaskModel.channel_id == run.channel.id,
            TaskModel.bot_id == req.bot_id,
        )
        .order_by(TaskModel.created_at.asc())
    )
    for task in rows.scalars().all():
        if _task_matches_chat_burst_policy(task, req, run):
            return task
    return None


async def _build_chat_burst_prompt(
    *,
    db: AsyncSession,
    user_msg_ids: list[uuid.UUID],
) -> str:
    if not user_msg_ids:
        return "[QUEUED CHAT BURST]\nThe user sent follow-up messages while you were responding."
    rows = await db.execute(
        select(MessageModel)
        .where(MessageModel.id.in_(user_msg_ids))
    )
    by_id = {msg.id: msg for msg in rows.scalars().all()}
    ordered = [by_id[msg_id] for msg_id in user_msg_ids if msg_id in by_id]
    lines = [
        "[QUEUED CHAT BURST]",
        "The user sent these messages while you were responding. Reply once, addressing them together in order.",
        "",
    ]
    for idx, msg in enumerate(ordered, start=1):
        content = (msg.content or "").strip() or "[empty message]"
        lines.append(f"{idx}. {content}")
    return "\n".join(lines)


async def _queue_or_append_chat_burst_task(
    *,
    db: AsyncSession,
    req: ChatRequest,
    run: _NormalChatRun,
    queued_user_msg_id: uuid.UUID,
) -> tuple[TaskModel, bool, int]:
    queued_task = await _find_pending_chat_burst_task(db=db, req=req, run=run)
    coalesced = queued_task is not None
    if queued_task is None:
        execution_config = _chat_burst_delivery_config(req, run)
        execution_config["pre_user_msg_id"] = str(queued_user_msg_id)
        execution_config["burst_user_msg_ids"] = [str(queued_user_msg_id)]
        queued_task = TaskModel(
            bot_id=req.bot_id,
            client_id=req.client_id,
            session_id=run.session_id,
            channel_id=run.channel.id,
            prompt=await _build_chat_burst_prompt(db=db, user_msg_ids=[queued_user_msg_id]),
            status="pending",
            task_type="api",
            created_at=datetime.now(timezone.utc),
            scheduled_at=datetime.now(timezone.utc) + timedelta(seconds=_BUSY_CHAT_BURST_DELAY_SECONDS),
            execution_config=execution_config,
        )
        db.add(queued_task)
        return queued_task, coalesced, 1

    execution_config = dict(queued_task.execution_config or {})
    raw_ids = execution_config.get("burst_user_msg_ids") or []
    user_msg_ids: list[uuid.UUID] = []
    for raw_id in raw_ids:
        try:
            user_msg_ids.append(uuid.UUID(str(raw_id)))
        except (TypeError, ValueError):
            continue
    if queued_user_msg_id not in user_msg_ids:
        user_msg_ids.append(queued_user_msg_id)
    execution_config["chat_burst"] = True
    execution_config["burst_user_msg_ids"] = [str(msg_id) for msg_id in user_msg_ids]
    execution_config["pre_user_msg_id"] = str(user_msg_ids[0])
    queued_task.execution_config = execution_config
    queued_task.prompt = await _build_chat_burst_prompt(db=db, user_msg_ids=user_msg_ids)
    queued_task.scheduled_at = datetime.now(timezone.utc) + timedelta(seconds=_BUSY_CHAT_BURST_DELAY_SECONDS)
    return queued_task, coalesced, len(user_msg_ids)


async def _maybe_short_circuit_normal_chat(
    *,
    req: ChatRequest,
    db: AsyncSession,
    run: _NormalChatRun,
    message: str,
) -> JSONResponse | None:
    if req.passive:
        await store_passive_message(
            db, run.session_id, message, req.msg_metadata or {}, channel_id=run.channel.id,
        )
        return JSONResponse(
            {"session_id": str(run.session_id), "passive": True},
            status_code=202,
        )

    sender_type = (req.msg_metadata or {}).get("sender_type", "")
    if sender_type != "human" and _channel_throttled(str(run.channel.id)):
        await store_passive_message(
            db, run.session_id, message,
            {**(req.msg_metadata or {}), "throttled": True},
            channel_id=run.channel.id,
        )
        return JSONResponse(
            {"session_id": str(run.session_id), "throttled": True},
            status_code=202,
        )
    _record_channel_run(str(run.channel.id))

    if not _settings.SYSTEM_PAUSED:
        return None
    if _settings.SYSTEM_PAUSE_BEHAVIOR == "drop":
        return JSONResponse(
            {"detail": "System is paused. Messages are being dropped."},
            status_code=503,
        )
    queued_task = await _queue_channel_task(db=db, req=req, run=run, message=message)
    await db.commit()
    await db.refresh(queued_task)
    logger.info("System paused — queued message as task %s", queued_task.id)
    return JSONResponse(
        {
            "session_id": str(run.session_id),
            "queued": True,
            "task_id": str(queued_task.id),
            "reason": "system_paused",
            "session_scoped": run.session_scoped_delivery,
        },
        status_code=202,
    )


async def _prepare_attachment_records(
    *,
    req: ChatRequest,
    db: AsyncSession,
    run: _NormalChatRun,
    prepared: _PreparedChatInput,
) -> uuid.UUID | None:
    pre_user_msg_id: uuid.UUID | None = None
    file_metadata = list(req.file_metadata or [])
    if not file_metadata and prepared.att_payload:
        file_metadata = _file_metadata_from_inline_attachments(req, prepared.att_payload)
    if not file_metadata:
        return pre_user_msg_id

    pre_user_msg_id = uuid.uuid4()
    db.add(MessageModel(
        id=pre_user_msg_id,
        session_id=run.session_id,
        role="user",
        content=prepared.message,
        metadata_=dict(req.msg_metadata or {}),
        created_at=datetime.now(timezone.utc),
    ))
    await db.commit()
    if req.msg_metadata is None:
        req.msg_metadata = {}
    req.msg_metadata["_pre_user_msg_id"] = str(pre_user_msg_id)

    source = (req.msg_metadata or {}).get("source", "web")
    created_attachments = await _create_attachments_from_metadata(
        file_metadata, run.channel.id, source, bot_id=req.bot_id,
        message_id=pre_user_msg_id,
    )
    if prepared.att_payload:
        for entry in prepared.att_payload:
            matched_id = None
            for attachment in created_attachments:
                if attachment.filename == entry.get("name"):
                    matched_id = str(attachment.id)
                    break
            if matched_id:
                entry["attachment_id"] = matched_id
    return pre_user_msg_id


def _file_metadata_from_inline_attachments(
    req: ChatRequest,
    attachments: list[dict],
) -> list[FileMetadata]:
    posted_by = (req.msg_metadata or {}).get("sender_id")
    result: list[FileMetadata] = []
    for idx, entry in enumerate(attachments, start=1):
        content = entry.get("content")
        if not isinstance(content, str) or not content:
            continue
        mime_type = entry.get("mime_type") or "application/octet-stream"
        name = entry.get("name") or f"attachment-{idx}"
        try:
            size_bytes = len(base64.b64decode(content, validate=False))
        except Exception:
            size_bytes = 0
        result.append(FileMetadata(
            filename=name,
            mime_type=mime_type,
            size_bytes=size_bytes,
            posted_by=posted_by,
            file_data=content,
        ))
    return result


async def _carry_forward_recent_image_context(
    *,
    db: AsyncSession,
    run: _NormalChatRun,
    prepared: _PreparedChatInput,
    pre_user_msg_id: uuid.UUID | None,
) -> None:
    if prepared.att_payload:
        return
    recent_context = await recent_inline_image_context(
        db,
        session_id=run.session_id,
        before_message_id=pre_user_msg_id,
    )
    if recent_context:
        prepared.att_payload = recent_context.payloads
        prepared.recent_image_context = recent_context


def _emit_recent_attachment_context_trace(
    *,
    run: _NormalChatRun,
    correlation_id: uuid.UUID,
    current_message_id: uuid.UUID | None,
    recent_context: RecentInlineImageContext | None,
) -> None:
    if recent_context is None:
        return
    safe_create_task(
        _record_trace_event(
            correlation_id=correlation_id,
            session_id=run.session_id,
            bot_id=getattr(run.bot, "id", None),
            client_id=None,
            event_type="recent_attachment_context",
            event_name="recent_chat_image",
            count=len(recent_context.payloads),
            data=recent_context.trace_data(current_message_id=current_message_id),
        ),
        name=f"recent-attachment-context:{correlation_id}",
    )


async def _start_or_queue_normal_turn(
    *,
    req: ChatRequest,
    db: AsyncSession,
    user: User | None,
    run: _NormalChatRun,
    prepared: _PreparedChatInput,
    pre_user_msg_id: uuid.UUID | None,
) -> tuple[JSONResponse, bool]:
    try:
        handle: TurnHandle = await start_turn(
            channel_id=run.channel.id,
            session_id=run.session_id,
            bot=run.bot,
            primary_bot_id=run.primary_bot_id,
            messages=run.messages,
            user_message=prepared.message,
            ctx=run.ctx,
            req=req,
            user=user,
            audio_data=prepared.audio_data,
            audio_format=prepared.audio_format,
            att_payload=prepared.att_payload,
            session_scoped=run.session_scoped_delivery,
        )
    except SessionBusyError:
        queued_user_msg_id = pre_user_msg_id
        if not pre_user_msg_id:
            queued_user_msg_id = uuid.uuid4()
            queued_meta = dict(req.msg_metadata or {})
            queued_meta.pop("_pre_user_msg_id", None)
            db.add(MessageModel(
                id=queued_user_msg_id,
                session_id=run.session_id,
                role="user",
                content=prepared.message,
                metadata_=queued_meta,
                created_at=datetime.now(timezone.utc),
            ))
        queued_task, coalesced, queued_message_count = await _queue_or_append_chat_burst_task(
            db=db,
            req=req,
            run=run,
            queued_user_msg_id=queued_user_msg_id,
        )
        await db.commit()
        await db.refresh(queued_task)
        logger.info(
            "Session %s busy — %s chat burst task %s (%d message(s))",
            run.session_id,
            "appended to" if coalesced else "queued",
            queued_task.id,
            queued_message_count,
        )
        return JSONResponse(
            {
                "session_id": str(run.session_id),
                "queued": True,
                "task_id": str(queued_task.id),
                "session_scoped": run.session_scoped_delivery,
                "coalesced": coalesced,
                "queued_message_count": queued_message_count,
            },
            status_code=202,
        ), False

    _emit_recent_attachment_context_trace(
        run=run,
        correlation_id=handle.turn_id,
        current_message_id=pre_user_msg_id,
        recent_context=prepared.recent_image_context,
    )
    return JSONResponse(
        {
            "session_id": str(handle.session_id),
            "channel_id": str(handle.channel_id),
            "turn_id": str(handle.turn_id),
            "session_scoped": run.session_scoped_delivery,
        },
        status_code=202,
    ), True


async def _mark_attention_item_responded(
    *,
    req: ChatRequest,
    db: AsyncSession,
    user: User | None,
    pre_user_msg_id: uuid.UUID | None,
) -> None:
    attention_item_id = (req.msg_metadata or {}).get("attention_item_id")
    if not attention_item_id:
        return
    try:
        from app.services.workspace_attention import actor_label, mark_attention_responded
        await mark_attention_responded(
            db,
            uuid.UUID(str(attention_item_id)),
            response_message_id=pre_user_msg_id,
            responded_by=actor_label(user),
        )
    except Exception:
        logger.warning(
            "Failed to mark attention item responded: %s",
            attention_item_id,
            exc_info=True,
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
    _apply_web_user_metadata(req, user)
    prepared = await _prepare_chat_input(req)

    # Wrap passive/webhook/environment-sourced inbound bodies before they flow
    # into LLM context. Active human integration turns (Slack/Discord/etc.)
    # remain normal user turns; the integration source is transport metadata,
    # not an instruction to demote the human's request to environment data.
    from app.security.prompt_sanitize import (
        is_trusted_human_turn_metadata,
        is_untrusted_source,
        wrap_untrusted_content,
    )
    _meta = req.msg_metadata or {}
    _src = _meta.get("source")
    if is_untrusted_source(_src) and prepared.message and not is_trusted_human_turn_metadata(_meta):
        prepared.message = wrap_untrusted_content(prepared.message, source=str(_src))

    sub_session_response = await _maybe_enqueue_sub_session_chat(
        req=req,
        db=db,
        user=user,
        prepared=prepared,
    )
    if sub_session_response is not None:
        return sub_session_response

    run = await _resolve_normal_chat_run(
        req=req,
        db=db,
        user=user,
        bot=bot,
        message=prepared.message,
    )

    logger.info(
        "POST /chat  bot=%s  channel=%s  session=%s  passive=%s  file_metadata=%d  message=%r",
        run.bot.id, run.channel.id, run.session_id, req.passive,
        len(req.file_metadata), prepared.message[:80],
    )

    short_circuit_response = await _maybe_short_circuit_normal_chat(
        req=req,
        db=db,
        run=run,
        message=prepared.message,
    )
    if short_circuit_response is not None:
        return short_circuit_response

    pre_user_msg_id = await _prepare_attachment_records(
        req=req,
        db=db,
        run=run,
        prepared=prepared,
    )
    await _carry_forward_recent_image_context(
        db=db,
        run=run,
        prepared=prepared,
        pre_user_msg_id=pre_user_msg_id,
    )
    response, turn_started = await _start_or_queue_normal_turn(
        req=req,
        db=db,
        user=user,
        run=run,
        prepared=prepared,
        pre_user_msg_id=pre_user_msg_id,
    )
    if turn_started:
        await _mark_attention_item_responded(
            req=req,
            db=db,
            user=user,
            pre_user_msg_id=pre_user_msg_id,
        )
    return response


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
        queued_user_msg_id = uuid.uuid4()
        queued_task = TaskModel(
            bot_id=req.bot_id,
            client_id=req.client_id,
            session_id=session_id,
            channel_id=None,
            prompt=message,
            status="pending",
            task_type="api",
            created_at=datetime.now(timezone.utc),
            scheduled_at=datetime.now(timezone.utc) + timedelta(seconds=10),
            execution_config={"session_scoped": True, "pre_user_msg_id": str(queued_user_msg_id)},
        )
        db.add(queued_task)
        _queued_meta = dict(req.msg_metadata or {})
        db.add(MessageModel(
            id=queued_user_msg_id,
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
