"""Standalone helpers: audio, attachments, session resolution, user extraction."""
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.channels import (
    get_or_create_channel,
    ensure_active_session,
    is_integration_client_id,
    resolve_integration_user,
)
from app.services.sessions import load_or_create
from app.stt import transcribe as stt_transcribe

from ._schemas import ChatRequest, FileMetadata

logger = logging.getLogger(__name__)


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
        preserve_metadata=preserve_metadata,
    )

    return channel, session_id, messages, is_integration


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
