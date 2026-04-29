"""Standalone helpers: audio, attachments, session resolution, user extraction."""
import logging
import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Message as MessageModel, Session
from app.services.channels import (
    get_or_create_channel,
    ensure_active_session,
    is_integration_client_id,
    resolve_integration_user,
)
from app.services.sessions import load_or_create
from app.services.sub_session_bus import SubSessionEntry, resolve_sub_session_entry
from app.services.sub_sessions import SESSION_TYPE_EPHEMERAL, SESSION_TYPE_THREAD
from app.stt import transcribe as stt_transcribe

from app.schemas.chat import ChatRequest, FileMetadata

logger = logging.getLogger(__name__)


TERMINAL_TASK_STATUSES = frozenset({"complete", "failed", "cancelled"})


@dataclass(frozen=True)
class SubSessionChatEntry:
    """Resolved context for a session-scoped chat POST (sub-session follow-up)."""

    entry: SubSessionEntry
    parent_channel: Channel | None  # None for channel-less ephemeral sessions
    messages: list[dict]


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
) -> list:
    """Create attachment records from file metadata.

    Returns the list of created Attachment rows so callers can thread the
    generated UUIDs back into the turn's ``att_payload`` — without this the
    LLM has no way to name a freshly-uploaded image when calling tools like
    ``generate_image(attachment_ids=...)`` and resorts to hallucinating a UUID.
    """
    from app.services.attachments import create_attachment

    logger.info("Creating %d attachment(s) for channel %s", len(file_metadata), channel_id)
    created: list = []
    for fm in file_metadata:
        try:
            import base64 as _b64
            raw_bytes = _b64.b64decode(fm.file_data) if fm.file_data else None
            att = await create_attachment(
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
            created.append(att)
        except Exception:
            logger.warning("Failed to create attachment for %s", fm.filename, exc_info=True)
    return created


async def _resolve_channel_and_session(
    db: AsyncSession,
    req: ChatRequest,
    user=None,
    preserve_metadata: bool = False,
):
    """Resolve channel + session from the request. Returns (channel, session_id, messages, is_integration)."""
    from app.db.models import Channel

    is_integration = _is_integration_client(req.client_id)

    # Web UI channels: private by default, owned by the logged-in user
    extra_kwargs: dict = {}
    if not is_integration and user is not None:
        extra_kwargs["user_id"] = user.id
        extra_kwargs["private"] = True

    # Integration user resolution: if sender_id is "<prefix>:<uid>", look up
    # the system user that owns the external identity. The integration id
    # (and thus the prefix) comes from the hook-registry so this path does
    # not hard-code any single integration.
    if is_integration and user is None and req.msg_metadata:
        from app.agent.hooks import get_integration_meta, integration_id_from_sender_id

        sender_id = (req.msg_metadata or {}).get("sender_id", "")
        integration_id = integration_id_from_sender_id(sender_id)
        if integration_id:
            meta = get_integration_meta(integration_id)
            prefix = meta.client_id_prefix if meta else f"{integration_id}:"
            external_uid = sender_id.removeprefix(prefix)
            resolved = await resolve_integration_user(db, integration_id, external_uid)
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

    # Resolve session: explicit session_id takes precedence. Explicit channel
    # sessions may target historical/secondary sessions, but those sends must
    # be web-only unless the target is the channel's active primary session.
    resolved_session_id = req.session_id
    if resolved_session_id is not None:
        explicit_session = await db.get(Session, resolved_session_id)
        if explicit_session is not None and explicit_session.channel_id != channel.id:
            raise HTTPException(
                status_code=404,
                detail="Session does not belong to this channel.",
            )
        if (
            req.external_delivery == "channel"
            and explicit_session is not None
            and resolved_session_id != channel.active_session_id
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Only the primary session can mirror to channel integrations. "
                    "Send with external_delivery='none' or make the session primary first."
                ),
            )
    if resolved_session_id is None:
        resolved_session_id = await ensure_active_session(db, channel)
        await db.commit()

    session_id, messages = await load_or_create(
        db, resolved_session_id, req.client_id, req.bot_id,
        locked=is_integration,
        channel_id=channel.id,
        preserve_metadata=preserve_metadata,
        model_override=req.model_override,
        provider_id_override=req.model_provider_id_override,
    )

    return channel, session_id, messages, is_integration


async def _try_resolve_sub_session_chat(
    db: AsyncSession,
    req: ChatRequest,
    user,
) -> SubSessionChatEntry | None:
    """Detect a session-scoped POST (sub-session follow-up) and resolve its context.

    Returns a ``SubSessionChatEntry`` when ``req.session_id`` names a valid
    sub-session (type ``pipeline_run`` / ``eval``) with a terminal source
    task and the caller is a member of its parent channel. Returns ``None``
    for any "this is a normal channel-scoped POST" case so the caller falls
    through to :func:`_resolve_channel_and_session`.

    Raises ``HTTPException`` on positive-match failure modes (non-terminal
    task, user not a member of the parent channel, non-matching bot).

    Scope of v1: only terminal sub-sessions accept follow-up turns. Mid-run
    push-back (composer-while-pipeline-runs) is Phase E — deliberately
    blocked here so a misconfigured UI can't spawn a user turn on top of
    an in-flight pipeline's history.
    """
    from fastapi import HTTPException

    if req.session_id is None:
        return None

    sub = await resolve_sub_session_entry(db, req.session_id)
    if sub is None:
        return None

    if sub.session.session_type in (SESSION_TYPE_EPHEMERAL, SESSION_TYPE_THREAD):
        # --- Ephemeral / thread session path: skip terminal-task gate ---
        # Authorize: if a parent channel exists, check membership;
        # otherwise allow any authenticated caller.
        parent_channel: Channel | None = None
        if sub.parent_channel_id is not None:
            parent_channel = await db.get(Channel, sub.parent_channel_id)
            if parent_channel is None:
                raise HTTPException(
                    status_code=404,
                    detail="Parent channel for this session no longer exists.",
                )
            if user is not None:
                caller_ok = (
                    parent_channel.user_id is None
                    or parent_channel.user_id == user.id
                )
                if not caller_ok:
                    raise HTTPException(
                        status_code=403,
                        detail="You are not a member of this session's parent channel.",
                    )
        # Bot identity comes from the session itself — don't override from req.
    else:
        # --- Pipeline/eval session path: terminal-only gate (v1) ---
        task = sub.source_task
        if task.status not in TERMINAL_TASK_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Pipeline run is {task.status!r} — follow-up turns are only "
                    "accepted after the run reaches a terminal state. "
                    "(Mid-run push-back is not yet supported.)"
                ),
            )

        # --- Caller authorization: must be a member of the parent channel ---
        parent_channel = await db.get(Channel, sub.parent_channel_id)
        if parent_channel is None:
            raise HTTPException(
                status_code=404,
                detail="Parent channel for this sub-session no longer exists.",
            )
        if user is not None:
            caller_ok = (
                parent_channel.user_id is None
                or parent_channel.user_id == user.id
            )
            if not caller_ok:
                raise HTTPException(
                    status_code=403,
                    detail="You are not a member of this pipeline run's parent channel.",
                )

        # --- Bot identity is forced to task.bot_id ---
        # If the client sent a different bot_id, normalize silently — the
        # sub-session's bot is not user-selectable in v1.
        if task.bot_id:
            req.bot_id = task.bot_id

    # --- Load Messages from the sub-session itself (history scope = sub-session only) ---
    rows = (
        await db.execute(
            select(MessageModel)
            .where(MessageModel.session_id == sub.session.id)
            .order_by(MessageModel.created_at)
        )
    ).scalars().all()
    messages: list[dict] = []
    for r in rows:
        meta = dict(r.metadata_ or {})
        m: dict = {
            "role": r.role,
            "content": r.content,
            "_metadata": meta,
        }
        if r.tool_calls:
            m["tool_calls"] = r.tool_calls
        if r.tool_call_id:
            m["tool_call_id"] = r.tool_call_id
        messages.append(m)

    return SubSessionChatEntry(
        entry=sub,
        parent_channel=parent_channel,
        messages=messages,
    )


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
