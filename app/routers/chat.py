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
from app.db.models import Message as MessageModel, Task as TaskModel
from app.dependencies import get_db, require_scopes
from app.services import session_locks
from app.services.channel_throttle import is_throttled as _channel_throttled, record_run as _record_channel_run
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

# Hold references to background asyncio tasks so they aren't GC'd before completion.
_background_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]


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
    model_provider_id_override: Optional[str] = None  # Per-turn provider override (paired with model_override)
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
    binding_config = binding.dispatch_config or {}
    logger.info(
        "Mirror: found binding type=%s client_id=%s has_dispatch_config=%s",
        integration, binding.client_id, bool(binding_config),
    )

    # Try to resolve dispatch_config via integration hook first (provides
    # credentials like server_url/password), then merge in per-binding
    # settings (text_footer, send_method) from the binding's config_fields.
    dispatch_config = None
    if binding.client_id:
        from app.agent.hooks import get_integration_meta
        meta = get_integration_meta(integration)
        if meta and meta.resolve_dispatch_config:
            dispatch_config = meta.resolve_dispatch_config(binding.client_id)
            if dispatch_config and binding_config:
                # Merge per-binding settings that the dispatcher needs
                # (e.g. send_method, text_footer for BB)
                _INTERNAL_KEYS = {"extra_wake_words", "use_bot_wake_word", "echo_suppress_window"}
                for k, v in binding_config.items():
                    if k not in _INTERNAL_KEYS and k not in dispatch_config and v not in ("", None):
                        dispatch_config[k] = v
            logger.info("Mirror: resolved dispatch_config via hook: %s", dispatch_config is not None)

    if not dispatch_config:
        if binding_config and binding_config.get("type"):
            # Binding has a full dispatch_config with type (non-config-fields style)
            dispatch_config = binding_config
        elif binding.client_id:
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


async def _maybe_route_to_member_bot(db: AsyncSession, channel, bot, message: str):
    """Check if the user @-tagged a member bot and route to it.

    Returns (BotConfig, member_config_dict) — member_config_dict is {} for the primary bot.
    Uses the same session (shared history) — only the responding bot changes.
    """
    if not message:
        return bot, {}

    from app.agent.tags import _TAG_RE
    from app.db.models import ChannelBotMember
    from sqlalchemy import select

    # Quick regex scan — look for @bot:name or plain @name patterns
    tag_matches = _TAG_RE.findall(message)
    if not tag_matches:
        return bot, {}

    # Load channel member bot rows (with config)
    result = await db.execute(
        select(ChannelBotMember).where(ChannelBotMember.channel_id == channel.id)
    )
    member_rows = {row.bot_id: row for row in result.scalars().all()}
    if not member_rows:
        return bot, {}

    # Build case-insensitive reverse lookup: lowercase(bot_id) → bot_id,
    # lowercase(display_name) → bot_id.  Consistent with _detect_member_mentions.
    name_to_id: dict[str, str] = {}
    for bot_id in member_rows:
        name_to_id[bot_id.lower()] = bot_id
        try:
            _bot_cfg = get_bot(bot_id)
            if _bot_cfg and _bot_cfg.name:
                name_to_id[_bot_cfg.name.lower()] = bot_id
        except Exception:
            pass

    # Check each tag for a member bot match
    for prefix, name in tag_matches:
        forced_type = prefix.rstrip(":") if prefix else None
        # Only consider bot-typed tags or untyped tags that match a member
        if forced_type and forced_type != "bot":
            continue
        resolved_id = name_to_id.get(name.lower())
        if resolved_id:
            try:
                member_bot = get_bot(resolved_id)
                logger.info(
                    "Routing to member bot %r in channel %s (was primary %r)",
                    resolved_id, channel.id, bot.id,
                )
                return member_bot, member_rows[resolved_id].config or {}
            except Exception:
                logger.warning("Member bot %r not found in registry", resolved_id)

    return bot, {}


def _apply_user_attribution(messages: list[dict]) -> None:
    """Add [Name]: prefix to user messages based on _metadata.sender_display_name.

    Must be called while _metadata is still present (before strip_metadata_keys).
    Safe to call alongside _rewrite_history_for_member_bot — duplicate-prefix
    check prevents double-prefixing.
    """
    for msg in messages:
        if msg.get("role") != "user":
            continue
        meta = msg.get("_metadata") or {}
        sender_name = meta.get("sender_display_name", "")
        if not sender_name:
            continue
        content = msg.get("content", "")
        # Skip multimodal messages (list content from image attachments)
        if not isinstance(content, str):
            continue
        if not content.startswith(f"[{sender_name}]:"):
            msg["content"] = f"[{sender_name}]: {content}"


def _rewrite_history_for_member_bot(
    messages: list[dict],
    member_bot_id: str,
    primary_bot_name: str | None = None,
    is_primary: bool = False,
) -> None:
    """Rewrite conversation history so a bot has proper identity.

    In a shared session, all assistant messages have role="assistant" but may
    come from different bots.  Without rewriting, the bot sees another bot's
    responses as its own (the LLM treats role=assistant as "I said that").

    This function:
    - Converts other bots' assistant messages to user messages with name prefix
    - Keeps the target bot's own assistant messages as-is
    - Adds speaker attribution to user messages
    - Drops other bots' tool_call/tool messages (not relevant to the target bot)
    - Treats untagged assistant messages (no sender_id) as coming from another bot
      (since the member bot is joining an existing conversation)
    - When ``is_primary=True``, untagged messages are treated as the primary bot's
      own (they predate multi-bot metadata and were authored by the primary bot)
    """
    member_sender_id = f"bot:{member_bot_id}"
    fallback_label = primary_bot_name or "Other bot"
    i = 0
    while i < len(messages):
        msg = messages[i]
        meta = msg.get("_metadata") or {}
        role = msg.get("role")

        # Remove hidden messages (member-mention trigger prompts, etc.)
        # These are system-injected prompts for specific bots, not real user input.
        if meta.get("hidden"):
            messages.pop(i)
            continue

        if role == "assistant":
            sender_id = meta.get("sender_id", "")
            sender_name = meta.get("sender_display_name", "")

            # If sender_id matches this bot, keep as assistant (it's our own message)
            if sender_id == member_sender_id:
                i += 1
                continue

            # Untagged messages (no sender_id) predate multi-bot metadata.
            # For the primary bot they're its own; for member bots, treat as other.
            if not sender_id and is_primary:
                i += 1
                continue

            # Otherwise — explicitly another bot, or untagged for a member bot.
            if msg.get("tool_calls"):
                # Drop tool-call messages from other bots (and their results)
                tool_call_ids = {
                    tc.get("id") for tc in msg["tool_calls"] if tc.get("id")
                }
                messages.pop(i)
                # Remove following tool result messages
                while i < len(messages) and messages[i].get("role") == "tool":
                    if messages[i].get("tool_call_id") in tool_call_ids:
                        messages.pop(i)
                    else:
                        break
                continue
            # Rewrite text-only assistant message to user with attribution
            content = msg.get("content", "")
            label = sender_name or fallback_label
            msg["role"] = "user"
            msg["content"] = f"[{label}]: {content}"
        elif role == "user":
            sender_name = meta.get("sender_display_name", "")
            if sender_name:
                content = msg.get("content", "")
                # Skip multimodal messages (list content from image attachments)
                if not isinstance(content, str):
                    i += 1
                    continue
                # Don't double-prefix if already prefixed
                if not content.startswith(f"[{sender_name}]:"):
                    msg["content"] = f"[{sender_name}]: {content}"
        i += 1


def _inject_member_config(messages: list[dict], config: dict) -> None:
    """Inject member-level config overrides as system messages."""
    parts: list[str] = []
    if config.get("system_prompt_addon"):
        parts.append(config["system_prompt_addon"])
    style = config.get("response_style")
    if style:
        style_map = {
            "brief": "Keep your responses brief and concise.",
            "normal": "Respond with a normal level of detail.",
            "detailed": "Provide detailed, thorough responses.",
        }
        parts.append(style_map.get(style, f"Response style: {style}."))
    if parts:
        messages.append({
            "role": "system",
            "content": f"[Member bot instructions for this channel]\n" + "\n".join(parts),
        })


# ---------------------------------------------------------------------------
# Bot-to-bot @-mention: when a bot's response mentions another channel bot
# (member or primary), trigger a follow-up run so that bot responds.
# ---------------------------------------------------------------------------
_MEMBER_MENTION_MAX_DEPTH = 3


async def _detect_member_mentions(
    channel_id: uuid.UUID,
    responding_bot_id: str,
    response_text: str,
    *,
    _depth: int = 0,
) -> list[tuple[str, dict]]:
    """Detect which channel bots are @-mentioned in a response.

    Returns a list of (bot_id, config) tuples for mentioned bots.
    Includes both member bots AND the primary bot — so member bots can
    mention the primary bot back for back-and-forth conversation.
    """
    if _depth >= _MEMBER_MENTION_MAX_DEPTH:
        return []
    if not response_text:
        return []

    from app.agent.tags import _TAG_RE
    from app.db.engine import async_session as _async_session
    from app.db.models import Channel, ChannelBotMember
    from sqlalchemy import select

    tag_matches = _TAG_RE.findall(response_text)
    if not tag_matches:
        return []

    # Load member bots AND the primary bot for this channel
    async with _async_session() as db:
        rows = (await db.execute(
            select(ChannelBotMember).where(ChannelBotMember.channel_id == channel_id)
        )).scalars().all()
        channel = await db.get(Channel, channel_id)

    member_map = {r.bot_id: r.config or {} for r in rows}
    # Include primary bot as a valid mention target (enables back-and-forth)
    if channel and channel.bot_id and channel.bot_id not in member_map:
        member_map[channel.bot_id] = {}
    if not member_map:
        return []

    # Build case-insensitive reverse lookup: lowercase(bot_id) → bot_id,
    # lowercase(display_name) → bot_id.  This allows @Rolland to resolve to "qa-bot".
    from app.agent.bots import get_bot as _get_bot_lookup
    name_to_id: dict[str, str] = {}
    for bot_id in member_map:
        name_to_id[bot_id.lower()] = bot_id
        try:
            _bot_cfg = _get_bot_lookup(bot_id)
            if _bot_cfg and _bot_cfg.name:
                name_to_id[_bot_cfg.name.lower()] = bot_id
        except Exception:
            pass

    # Deduplicate mentioned member bots (preserve order)
    mentioned: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for prefix, name in tag_matches:
        forced_type = prefix.rstrip(":") if prefix else None
        if forced_type and forced_type != "bot":
            continue
        resolved_id = name_to_id.get(name.lower())
        if resolved_id and resolved_id != responding_bot_id and resolved_id not in seen:
            mentioned.append((resolved_id, member_map[resolved_id]))
            seen.add(resolved_id)

    return mentioned


async def _trigger_member_bot_replies(
    channel_id: uuid.UUID,
    session_id: uuid.UUID,
    responding_bot_id: str,
    response_text: str,
    *,
    _depth: int = 0,
    messages_snapshot: list[dict] | None = None,
    already_invoked: set[str] | None = None,
) -> list[tuple[str, dict]]:
    """Parse a bot response for @-mentions of channel member bots and fire replies.

    Returns the list of (bot_id, config) tuples that were triggered (for dedup).
    Skips any bot_id in *already_invoked* (e.g. invoked via tool mid-turn).
    """
    try:
        mentioned = await _detect_member_mentions(channel_id, responding_bot_id, response_text, _depth=_depth)
    except Exception:
        logger.exception("Failed to detect member mentions in channel %s", channel_id)
        return []
    # Filter out bots already invoked (e.g. via invoke_member_bot tool)
    if already_invoked:
        mentioned = [(bid, cfg) for bid, cfg in mentioned if bid not in already_invoked]
    for bot_id, member_config in mentioned:
        stream_id = str(uuid.uuid4())
        task = asyncio.create_task(
            _run_member_bot_reply(
                channel_id, session_id, bot_id, member_config,
                responding_bot_id, _depth=_depth + 1,
                messages_snapshot=messages_snapshot,
                stream_id=stream_id,
            )
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
    return mentioned


async def _run_member_bot_reply(
    channel_id: uuid.UUID,
    session_id: uuid.UUID,
    member_bot_id: str,
    member_config: dict,
    mentioning_bot_id: str,
    *,
    _depth: int = 1,
    messages_snapshot: list[dict] | None = None,
    stream_id: str | None = None,
    invocation_message: str = "",
) -> None:
    """Execute a member bot's reply after being @-mentioned or invoked.

    When *messages_snapshot* is provided the bot runs against that snapshot
    without acquiring the session lock — enabling parallel execution.
    """
    from app.agent.bots import get_bot
    from app.db.engine import async_session as _async_session
    from app.db.models import Channel, Session
    from app.services.sessions import load_or_create, persist_turn
    from app.services.channel_events import publish as _publish_event
    from sqlalchemy import update as _sql_update

    # Anti-loop: channel throttle (uses module-level imports)
    if _channel_throttled(str(channel_id)):
        logger.info("Member bot %s reply skipped: channel %s throttled", member_bot_id, channel_id)
        return

    _sid = stream_id or str(uuid.uuid4())
    _use_snapshot = messages_snapshot is not None

    if not _use_snapshot:
        # Legacy path: wait for session lock
        acquired = False
        for _ in range(30):
            if session_locks.acquire(session_id):
                acquired = True
                break
            await asyncio.sleep(1)
        if not acquired:
            logger.warning("Member bot %s timed out waiting for session lock in channel %s", member_bot_id, channel_id)
            return

    response_text = ""
    try:
        _record_channel_run(str(channel_id))

        member_bot = get_bot(member_bot_id)
        mentioning_bot = get_bot(mentioning_bot_id)

        # Look up primary bot + workspace settings (shared by both paths)
        _primary_bot_name: str | None = None
        _primary_bot_id: str | None = None
        _ws_base_enabled = False
        async with _async_session() as db:
            _ch = await db.get(Channel, channel_id)
            if _ch and _ch.bot_id:
                _primary_bot_id = _ch.bot_id
                _pb = get_bot(_ch.bot_id)
                _primary_bot_name = _pb.name if _pb else _ch.bot_id
            from app.services.sessions import _resolve_workspace_base_prompt_enabled
            _ws_base_enabled = await _resolve_workspace_base_prompt_enabled(
                db, member_bot_id, channel_id,
            )

        if _use_snapshot:
            # Use the provided snapshot — no DB load, no lock needed.
            # System messages are per-bot context (rebuilt by assemble_context),
            # not shared state.  Strip the primary bot's system messages and
            # inject the member bot's own base messages (system prompt + persona).
            import copy
            messages = [m for m in copy.deepcopy(messages_snapshot) if m.get("role") != "system"]
            from app.services.sessions import _effective_system_prompt
            _sys = _effective_system_prompt(member_bot, workspace_base_prompt_enabled=_ws_base_enabled)
            messages.insert(0, {"role": "system", "content": _sys})
            if member_bot.persona:
                from app.agent.persona import get_persona
                _persona = await get_persona(member_bot.id, workspace_id=member_bot.shared_workspace_id)
                if _persona:
                    messages.insert(1, {"role": "system", "content": f"[PERSONA]\n{_persona}"})
        else:
            # Load session with member bot's system prompt (preserve _metadata for
            # history rewriting — we need sender_id to distinguish message authors)
            async with _async_session() as db:
                _, messages = await load_or_create(
                    db, session_id, "member-mention", member_bot_id,
                    channel_id=channel_id,
                    preserve_metadata=True,
                )

        # Rewrite history so the bot sees other bots' messages with attribution
        # (prevents it from thinking another bot's words are its own)
        _is_primary = member_bot_id == _primary_bot_id
        _rewrite_history_for_member_bot(
            messages, member_bot_id,
            primary_bot_name=_primary_bot_name,
            is_primary=_is_primary,
        )

        # Strip internal _metadata now that rewriting is done
        from app.services.sessions import strip_metadata_keys
        messages[:] = strip_metadata_keys(messages)

        # Apply member config overrides (response_style, system_prompt_addon)
        _inject_member_config(messages, member_config)

        correlation_id = uuid.uuid4()
        from_index = len(messages)

        # Identity/context as system_preamble (not user message) to avoid LLM echo.
        if invocation_message:
            _system_preamble = (
                f"You are {member_bot.name} (bot_id: {member_bot_id}). "
                f"{mentioning_bot.name} (@{mentioning_bot_id}) invoked you with this context: {invocation_message} "
                f"Read the conversation and respond naturally. Do not @-mention yourself."
            )
        else:
            _system_preamble = (
                f"You are {member_bot.name} (bot_id: {member_bot_id}). "
                f"{mentioning_bot.name} (@{mentioning_bot_id}) mentioned you. "
                f"Read the conversation and respond naturally. Do not @-mention yourself."
            )
        prompt = ""
        model_override = member_config.get("model_override")

        # Set agent context so run_stream internals have proper metadata
        from app.agent.context import set_agent_context
        set_agent_context(
            session_id=session_id,
            client_id="member-mention",
            bot_id=member_bot_id,
            correlation_id=correlation_id,
            channel_id=channel_id,
        )

        # Stream the reply so the UI shows typing indicators for the member bot.
        from app.agent.loop import run_stream
        _publish_event(channel_id, "stream_start", {
            "stream_id": _sid,
            "responding_bot_id": member_bot_id,
            "responding_bot_name": member_bot.name,
        })

        async for event in run_stream(
            messages, member_bot, prompt,
            session_id=session_id,
            client_id="member-mention",
            correlation_id=correlation_id,
            channel_id=channel_id,
            model_override=model_override,
            system_preamble=_system_preamble,
        ):
            if event.get("type") == "response":
                response_text = event.get("text", "")
            event_with_session = {**event, "session_id": str(session_id)}
            _publish_event(channel_id, "stream_event", {
                "stream_id": _sid,
                "event": event_with_session,
            })

        # Persist with metadata so UI knows this is a bot-triggered turn
        msg_metadata = {
            "trigger": "member_mention",
            "sender_type": "bot",
            "sender_display_name": mentioning_bot.name,
            "mentioning_bot_id": mentioning_bot_id,
            "hidden": True,
        }
        async with _async_session() as db:
            await persist_turn(
                db, session_id, member_bot, messages, from_index,
                correlation_id=correlation_id,
                channel_id=channel_id,
                msg_metadata=msg_metadata,
            )

        # Notify UI that streaming ended (after persist so data is committed)
        _publish_event(channel_id, "stream_end", {"stream_id": _sid})
        _publish_event(channel_id, "new_message")

        # Mirror to integration
        if response_text:
            async with _async_session() as db:
                channel = await db.get(Channel, channel_id)
            if channel:
                await _mirror_to_integration(
                    channel, response_text, bot_id=member_bot_id,
                )

        # Restore session bot_id to the channel's primary bot
        if not _use_snapshot:
            async with _async_session() as db:
                channel = await db.get(Channel, channel_id)
                if channel and channel.bot_id:
                    await db.execute(
                        _sql_update(Session)
                        .where(Session.id == session_id)
                        .values(bot_id=channel.bot_id)
                    )
                    await db.commit()

        logger.info(
            "Member bot %s replied in channel %s (mentioned by %s, depth=%d, stream=%s)",
            member_bot_id, channel_id, mentioning_bot_id, _depth, _sid,
        )

    except Exception:
        logger.exception("Member bot %s reply failed in channel %s", member_bot_id, channel_id)
        # Ensure streaming ends even on error so UI doesn't stay in streaming state
        _publish_event(channel_id, "stream_end", {"stream_id": _sid})
    finally:
        if not _use_snapshot:
            session_locks.release(session_id)

    # Chain: check if member bot's response mentions another member bot.
    # Always pass a snapshot so chained bots run lock-free (the primary bot
    # may still hold the session lock if we were invoked with a snapshot).
    if response_text:
        import copy as _copy_mod
        _chain_snapshot = _copy_mod.deepcopy(messages) if messages else None
        await _trigger_member_bot_replies(
            channel_id, session_id, member_bot_id, response_text,
            _depth=_depth,
            messages_snapshot=_chain_snapshot,
        )


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
    _primary_bot_id_nc = bot.id
    bot, _member_config = await _maybe_route_to_member_bot(db, channel, bot, message)

    # If routing changed the bot, rebuild the system prompt so the routed bot
    # runs with its OWN identity (not the channel primary's prompt).
    _is_primary_nc = bot.id == _primary_bot_id_nc
    if not _is_primary_nc:
        from app.services.sessions import _effective_system_prompt, _resolve_workspace_base_prompt_enabled
        _ws_base_nc = await _resolve_workspace_base_prompt_enabled(db, bot.id, channel_id)
        _new_sys_nc = _effective_system_prompt(bot, workspace_base_prompt_enabled=_ws_base_nc)
        messages[:] = [m for m in messages if m.get("role") != "system"]
        messages.insert(0, {"role": "system", "content": _new_sys_nc})
        if bot.persona:
            from app.agent.persona import get_persona as _get_persona_nc
            _persona_nc = await _get_persona_nc(bot.id, workspace_id=bot.shared_workspace_id)
            if _persona_nc:
                messages.insert(1, {"role": "system", "content": f"[PERSONA]\n{_persona_nc}"})

    # Rewrite history for multi-bot identity: convert other bots' assistant
    # messages to user messages with attribution, remove hidden trigger prompts.
    # Always run — it's a no-op for single-bot channels (no sender_id metadata).
    from app.agent.bots import get_bot as _get_bot_nc
    _pb_nc = _get_bot_nc(_primary_bot_id_nc) if not _is_primary_nc else None
    _rewrite_history_for_member_bot(
        messages, bot.id,
        primary_bot_name=_pb_nc.name if _pb_nc else None,
        is_primary=_is_primary_nc,
    )

    # Add [Name]: prefix to user messages so the bot can distinguish speakers
    _apply_user_attribution(messages)

    # Strip internal _metadata now that rewriting is done
    from app.services.sessions import strip_metadata_keys
    messages[:] = strip_metadata_keys(messages)

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
        _pre_user_msg_id = _user_record.id
        # Notify other UI clients viewing this channel
        from app.services.channel_events import publish as _publish_event
        _publish_event(channel_id, "new_message")
    except Exception:
        logger.warning("Failed to pre-persist user message for session %s", session_id, exc_info=True)
        await db.rollback()

    try:
        # Apply member-level config overrides
        _effective_model_override = req.model_override or _member_config.get("model_override")
        _inject_member_config(messages, _member_config)

        result = await run(
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
        pre_user_msg_id=_pre_user_msg_id,
    )
    maybe_compact(
        session_id, bot, messages,
        correlation_id=correlation_id,
        dispatch_type=req.dispatch_type,
        dispatch_config=req.dispatch_config,
    )

    # Mirror response to integration (redact if secrets detected)
    if not req.dispatch_config and result.response:
        _mirror_text = result.response
        if _detected_secrets:
            from app.services.secret_registry import redact as _redact
            _mirror_text = _redact(_mirror_text)
        await _mirror_to_integration(
            channel, _mirror_text,
            bot_id=req.bot_id, client_actions=result.client_actions,
        )

    # Multi-bot: trigger member bots @-mentioned in the user's message.
    # Skip any bots already invoked mid-turn by the invoke_member_bot tool.
    _user_mentioned_nc: set[str] = set()
    if channel_id:
        from app.agent.context import current_invoked_member_bots as _cimb_nc
        _already_invoked_nc = _cimb_nc.get() or set()
        _um_nc = await _detect_member_mentions(channel_id, bot.id, message, _depth=0)
        if _um_nc:
            import copy as _copy_um
            _um_snap = _copy_um.deepcopy(messages)
            for _bid, _cfg in _um_nc:
                if _bid in _already_invoked_nc:
                    continue  # Already fired by invoke_member_bot during the run
                _user_mentioned_nc.add(_bid)
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
    if result.response and channel_id:
        import copy as _copy_chat
        _snap = _copy_chat.deepcopy(messages)
        task = asyncio.create_task(
            _trigger_member_bot_replies(
                channel_id, session_id, bot.id, result.response,
                messages_snapshot=_snap,
                already_invoked=_user_mentioned_nc,
            )
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

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
        channel, session_id, messages, is_integration = await _resolve_channel_and_session(
            db, req, user=user, preserve_metadata=True,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Session error: {e}")

    channel_id = channel.id

    # Multi-bot channel: if user @-tagged a member bot, route to that bot
    _primary_bot_id = bot.id
    bot, _member_config = await _maybe_route_to_member_bot(db, channel, bot, message)

    # If routing changed the bot, rebuild the system prompt so the routed bot
    # runs with its OWN identity (not the channel primary's prompt).
    _is_primary_s = bot.id == _primary_bot_id
    if not _is_primary_s:
        from app.services.sessions import _effective_system_prompt, _resolve_workspace_base_prompt_enabled
        _ws_base_s = await _resolve_workspace_base_prompt_enabled(db, bot.id, channel_id)
        _new_sys = _effective_system_prompt(bot, workspace_base_prompt_enabled=_ws_base_s)
        # Replace old system prompt(s) and inject the routed bot's prompt + persona
        messages[:] = [m for m in messages if m.get("role") != "system"]
        messages.insert(0, {"role": "system", "content": _new_sys})
        if bot.persona:
            from app.agent.persona import get_persona as _get_persona_s
            _persona_s = await _get_persona_s(bot.id, workspace_id=bot.shared_workspace_id)
            if _persona_s:
                messages.insert(1, {"role": "system", "content": f"[PERSONA]\n{_persona_s}"})

    # Rewrite history for multi-bot identity: convert other bots' assistant
    # messages to user messages with attribution, remove hidden trigger prompts.
    # Always run — it's a no-op for single-bot channels (no sender_id metadata).
    from app.agent.bots import get_bot as _get_bot_s
    _pb_s = _get_bot_s(_primary_bot_id) if not _is_primary_s else None
    _rewrite_history_for_member_bot(
        messages, bot.id,
        primary_bot_name=_pb_s.name if _pb_s else None,
        is_primary=_is_primary_s,
    )

    # Add [Name]: prefix to user messages so the bot can distinguish speakers
    _apply_user_attribution(messages)

    # Strip internal _metadata now that rewriting is done
    from app.services.sessions import strip_metadata_keys
    messages[:] = strip_metadata_keys(messages)

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
        _task_id = str(queued_task.id)
        logger.info(
            "Session %s busy — queued message as task %s", session_id, _task_id
        )

        # Notify other UI clients viewing this channel
        from app.services.channel_events import publish as _publish_event
        _publish_event(channel_id, "new_message")

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
            # _with_keepalive uses ensure_future(__anext__), so each chunk runs
            # in a new Task.  The bridge in _with_keepalive propagates dynamic
            # context vars (resolved_skill_ids, model_override, etc.) across
            # Task boundaries, but we still prime the basic vars here so they
            # are present from the very first Task.
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

            # Tell the initiating tab which bot is responding FIRST (before any
            # other processing) so the typing indicator shows the correct name
            # immediately — not the channel's primary bot as a fallback.
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
                        # Register matched values so they're redacted in tool results, traces, etc.
                        _secret_vals = _extract_values(message)
                        if _secret_vals:
                            _register_secrets(_secret_vals)
                        yield f"data: {json.dumps({'type': 'secret_warning', 'patterns': [{'type': p['type']} for p in _pattern_hits]})}\n\n"

            # Persist user message immediately so it's visible even if the
            # agent loop crashes.  Uses a fresh DB session because the
            # dependency-injected one may be closed during streaming.
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
                    _pre_user_msg_id = _user_record.id
                    # Notify other UI clients viewing this channel
                    from app.services.channel_events import publish as _publish_event
                    _publish_event(channel_id, "new_message")
            except Exception:
                logger.warning("Failed to pre-persist user message for session %s", session_id, exc_info=True)

            response_text = ""
            response_actions = None
            was_cancelled = False

            # Apply member-level config overrides
            _effective_model_override_s = req.model_override or _member_config.get("model_override")
            _inject_member_config(messages, _member_config)

            # Notify observers that streaming is starting
            from app.services.channel_events import publish as _publish_stream
            _primary_stream_id = str(uuid.uuid4())
            _publish_stream(channel_id, "stream_start", {
                "stream_id": _primary_stream_id,
                "responding_bot_id": bot.id,
                "responding_bot_name": bot.name,
            })

            # Multi-bot: fire parallel member streams for OTHER bots @-mentioned
            # in the user's message (the routed bot is already handling the
            # primary stream).  This makes "@bot:a @bot:b" trigger both bots.
            _user_mentioned: list[tuple[str, dict]] = []
            if channel_id:
                _user_mentioned = await _detect_member_mentions(
                    channel_id, bot.id, message, _depth=0,
                )
                if _user_mentioned:
                    import copy as _copy_user
                    _user_snap = _copy_user.deepcopy(messages)
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

                    # Seed context var so invoke_member_bot tool won't double-fire
                    from app.agent.context import current_invoked_member_bots
                    current_invoked_member_bots.set(_auto_invoked_ids)

                    # Tell the primary bot these bots are already responding so
                    # it doesn't try to invoke them itself.
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
                            f"Do NOT use invoke_member_bot to invoke them again."
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

            # Mirror response to integration (skip if cancelled)
            # If secrets were detected in user input, redact the mirrored response
            if not was_cancelled and not req.dispatch_config and response_text:
                _mirror_text = response_text
                if _detected_secrets:
                    from app.services.secret_registry import redact as _redact
                    _mirror_text = _redact(_mirror_text)
                await _mirror_to_integration(
                    channel, _mirror_text,
                    bot_id=req.bot_id, client_actions=response_actions,
                )

            maybe_compact(
                session_id, bot, messages,
                correlation_id=correlation_id,
                dispatch_type=req.dispatch_type,
                dispatch_config=req.dispatch_config,
                budget_utilization=_budget_utilization,
            )

            # Bot-to-bot @-mention: if the response mentions a member bot, trigger its reply.
            # With stream_id-based demuxing, multiple member bots can stream in parallel.
            # Pass a snapshot of the current messages so member bots don't need the session lock.
            if not was_cancelled and response_text and channel_id:
                # Collect bots already invoked: via invoke_member_bot tool + user's message @-mentions
                from app.agent.context import current_invoked_member_bots
                _already_invoked = set(current_invoked_member_bots.get() or ())
                # Also exclude bots triggered from user's @-mentions at start of stream
                if _user_mentioned:
                    _already_invoked.update(bid for bid, _ in _user_mentioned)

                import copy
                _messages_snapshot = copy.deepcopy(messages)
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


SSE_KEEPALIVE_INTERVAL = 15  # seconds


async def _with_keepalive(
    agen: AsyncGenerator[dict[str, Any], None],
    interval: float = SSE_KEEPALIVE_INTERVAL,
) -> AsyncGenerator[dict[str, Any] | None, None]:
    """Wrap an async generator, yielding None as a keepalive signal when no
    event arrives within *interval* seconds.  Prevents idle SSE connections
    from being dropped by React Native's XHR layer.

    IMPORTANT: Each ``ensure_future(__anext__())`` runs the generator step in a
    new asyncio Task that copies the *parent's* ContextVars.  Changes made
    inside the generator (e.g. ``current_resolved_skill_ids`` set by
    ``assemble_context``) are lost when the Task ends.  To bridge them, we
    capture the child Task's context-var values after each step and restore
    them in the parent so the next Task inherits the updated state.
    """
    from app.agent.context import (
        current_resolved_skill_ids,
        current_model_override,
        current_provider_id_override,
        current_channel_model_tier_overrides,
        current_injected_tools,
        current_ephemeral_skills,
        current_ephemeral_delegates,
        current_allowed_secrets,
        task_creation_count,
        current_pending_delegation_posts,
        current_invoked_member_bots,
    )

    # Context vars that are set *inside* the generator (by assemble_context /
    # run_stream) and read by tools or inner loops.  We capture their values
    # after each generator step and restore them in the parent context.
    _BRIDGE_VARS = [
        current_resolved_skill_ids,
        current_model_override,
        current_provider_id_override,
        current_channel_model_tier_overrides,
        current_injected_tools,
        current_ephemeral_skills,
        current_ephemeral_delegates,
        current_allowed_secrets,
        task_creation_count,
        current_pending_delegation_posts,
        current_invoked_member_bots,
    ]

    _bridge: dict = {}  # ContextVar -> value, shared with child Task

    async def _next():
        result = await agen.__anext__()
        # Capture context vars from the child Task so we can restore them
        for var in _BRIDGE_VARS:
            _bridge[var] = var.get()
        return result

    pending = asyncio.ensure_future(_next())
    try:
        while True:
            try:
                event = await asyncio.wait_for(asyncio.shield(pending), timeout=interval)
                # Restore child's context changes into the parent so the
                # next ensure_future() inherits them.
                for var, val in _bridge.items():
                    var.set(val)
                yield event
                pending = asyncio.ensure_future(_next())
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
