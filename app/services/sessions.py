import json
import logging
import re
import uuid
from typing import Any
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import BotConfig, get_bot
from app.agent.context_profiles import (
    resolve_context_profile,
    trim_messages_to_recent_turns,
)
from app.agent.persona import get_persona
from app.db.engine import async_session
from sqlalchemy.orm import selectinload

from app.db.models import Attachment, Channel, Message, Session, SharedWorkspace, SharedWorkspaceBot
from app.services.session_plan_mode import build_plan_mode_system_context
from app.services.tool_presentation import normalize_persisted_tool_calls


logger = logging.getLogger(__name__)

_ASSISTANT_HISTORY_COMPACT_THRESHOLD = 400


async def _resolve_workspace_base_prompt_enabled(
    db: AsyncSession, bot_id: str, channel_id: uuid.UUID | None,
) -> bool:
    """Check if workspace base prompt override is enabled for this bot+channel.

    Resolution: channel override → workspace setting → False
    """
    if not channel_id:
        return False
    ch = await db.get(Channel, channel_id)
    if not ch:
        return False
    # If channel has explicit override, use it
    if ch.workspace_base_prompt_enabled is not None:
        return ch.workspace_base_prompt_enabled
    # Look up workspace via bot membership
    swb = (await db.execute(
        select(SharedWorkspaceBot)
        .where(SharedWorkspaceBot.bot_id == bot_id)
    )).scalar_one_or_none()
    if not swb:
        return False
    ws = await db.get(SharedWorkspace, swb.workspace_id)
    if not ws:
        return False
    return ws.workspace_base_prompt_enabled


from app.services.channels import INTEGRATION_CLIENT_PREFIXES as _INTEGRATION_CLIENT_PREFIXES


def is_integration_client_id(client_id: str | None) -> bool:
    """True when client_id is an external integration channel (stable derived session)."""
    if not client_id:
        return False
    return any(client_id.startswith(p) for p in _INTEGRATION_CLIENT_PREFIXES)


def derive_integration_session_id(client_id: str) -> uuid.UUID:
    """Derive a stable session_id from client_id alone (channel-scoped, bot-independent)."""
    return uuid.uuid5(uuid.NAMESPACE_DNS, client_id)


async def upsert_integration_session(
    db: AsyncSession, client_id: str, bot_id: str
) -> uuid.UUID:
    """Ensure an integration session exists for client_id. Returns the session_id."""
    session_id = derive_integration_session_id(client_id)
    stmt = (
        pg_insert(Session)
        .values(
            id=session_id,
            client_id=client_id,
            bot_id=bot_id,
            locked=True,
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    await db.execute(stmt)
    await db.commit()
    return session_id


def normalize_stored_content(content: str | None) -> str | list[Any] | None:
    """DB stores JSON-encoded multimodal user turns; reload as a list for the LLM.

    Only returns a list when every item is a dict with a "type" key — the shape produced
    by _content_for_db(). Plain text that happens to start with "[" (e.g. Slack passive
    messages, user messages like '["a","b"]') stays as a string to avoid Anthropic 400s.
    """
    if content is None:
        return None
    if isinstance(content, str) and content.startswith("["):
        try:
            parsed = json.loads(content)
            if (
                isinstance(parsed, list)
                and parsed
                and all(isinstance(item, dict) and "type" in item for item in parsed)
            ):
                return parsed
        except json.JSONDecodeError:
            pass
    return content


def _redact_images_for_db(content: list[Any]) -> list[Any]:
    """Avoid multi‑MB rows: replace data-URL image parts with a text placeholder before persisting."""
    out: list[Any] = []
    for part in content:
        if not isinstance(part, dict):
            out.append(part)
            continue
        if part.get("type") != "image_url":
            out.append(part)
            continue
        url = (part.get("image_url") or {}).get("url", "")
        if isinstance(url, str) and url.startswith("data:"):
            # Text marker — never reload a fake image part (invalid media types break Claude, etc.)
            out.append({"type": "text", "text": "[image — not available in this session]"})
        else:
            out.append(part)
    return out


# Lines that match these patterns are stripped from assistant content
# before persistence. They are the visible signature of the historical
# enrichment leak: the LLM was copying ``[attached: …] / → To fetch
# full file, call: get_attachment("…") / (Use get_attachment tool …)``
# straight out of its own enriched conversation history into fresh
# assistant turns. Stripping enrichment from the load path
# (`_enrich_content_with_attachments`) only stops *new* leaks; once a
# bad turn has been persisted, the LLM keeps reading its own past
# output and reproducing the pattern. This sanitizer breaks that
# feedback loop on write, and the same helper is used by the one-time
# DB backfill to clean stored rows.
_ATTACHMENT_HINT_LINE_PATTERNS = (
    re.compile(r'^[ \t]*\[attached:[^\]]*\][ \t]*$', re.MULTILINE),
    re.compile(
        r'^[ \t]*→[ \t]*To fetch full file,[^\n]*$',
        re.MULTILINE,
    ),
    re.compile(
        r'^[ \t]*\(\s*Use get_attachment tool[^)]*\)[ \t]*$',
        re.MULTILINE,
    ),
    # The post-fix XML tag form. Less copy-prone but defended against
    # the same way for symmetry — if a future model starts echoing it,
    # we don't want to bake it into history again.
    re.compile(r'^[ \t]*<attachment\s+[^>]*/>[ \t]*$', re.MULTILINE),
)


def _strip_leaked_attachment_hints(text: str) -> str:
    """Remove enrichment-hint lines that the LLM reproduced into its own output.

    Idempotent. Returns the input untouched when no pattern matches so
    the common case (clean LLM output) is a no-op. Collapses any
    leftover triple+ blank lines that the strip can leave behind.
    """
    if not isinstance(text, str) or not text:
        return text
    cleaned = text
    for pat in _ATTACHMENT_HINT_LINE_PATTERNS:
        cleaned = pat.sub("", cleaned)
    if cleaned == text:
        return text
    # Collapse runs of blank lines introduced by the strip and trim
    # trailing whitespace so the persisted text doesn't acquire a
    # ragged tail.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.rstrip()


def _sanitize_assistant_content_for_db(content: Any) -> Any:
    """Apply ``_strip_leaked_attachment_hints`` to a message-content payload.

    Handles both the plain-string and the multimodal-list shapes that
    assistant messages can carry. Non-text parts (image_url, audio,
    etc.) pass through unchanged.
    """
    if isinstance(content, str):
        return _strip_leaked_attachment_hints(content)
    if isinstance(content, list):
        out: list = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                txt = part.get("text", "")
                stripped = _strip_leaked_attachment_hints(txt)
                if stripped != txt:
                    part = {**part, "text": stripped}
            out.append(part)
        return out
    return content


def _content_for_db(msg: dict) -> str | dict | list | None:
    raw = msg.get("content")
    # Sanitize assistant output before persistence so leaked enrichment
    # hints don't get baked into history and re-fed to the LLM on the
    # next turn. User / tool / system content passes through unchanged.
    if msg.get("role") == "assistant":
        raw = _sanitize_assistant_content_for_db(raw)
    if isinstance(raw, list):
        return json.dumps(_redact_images_for_db(raw))
    return raw


def _effective_system_prompt(
    bot: BotConfig,
    workspace_base_prompt_enabled: bool = False,
    channel=None,
    model_override: str | None = None,
    provider_id_override: str | None = None,
) -> str:
    """Server prompt + optional workspace prompt + bot system prompt.

    If workspace_base_prompt_enabled and the bot belongs to a shared workspace,
    reads common/prompts/base.md (+ bots/{bot_id}/prompts/base.md) from the
    workspace filesystem and appends it after the global base prompt.

    Framework prompts (GLOBAL_BASE_PROMPT, MEMORY_SCHEME_PROMPT) pass through
    ``prompt_dialect.render`` to apply the resolved provider's prompt_style.
    The bot's own ``system_prompt`` is appended verbatim — user-authored text
    is never transformed.
    """
    from app.agent.context import current_system_prompt_override
    _override = current_system_prompt_override.get()
    if _override is not None:
        return _override
    from app.agent.base_prompt import resolve_workspace_base_prompt
    from app.config import settings as _settings
    from app.services.prompt_dialect import render as _dialect_render
    from app.services.providers import resolve_prompt_style

    _style = resolve_prompt_style(
        bot,
        channel,
        model_override=model_override,
        provider_id_override=provider_id_override,
    )
    parts = []

    # Global base prompt: org-wide instructions prepended before everything
    if _settings.GLOBAL_BASE_PROMPT:
        parts.append(_dialect_render(_settings.GLOBAL_BASE_PROMPT, _style).rstrip())

    ws_base = None
    if workspace_base_prompt_enabled and getattr(bot, "shared_workspace_id", None):
        ws_base = resolve_workspace_base_prompt(bot.shared_workspace_id, bot.id)

    if ws_base:
        # User/workspace-authored base — pass through verbatim
        parts.append(ws_base.rstrip())

    # Resolve system prompt from workspace file if configured
    _sys_prompt = bot.system_prompt
    if getattr(bot, "system_prompt_workspace_file", False):
        from app.services.prompt_resolution import resolve_workspace_file_prompt
        _ws_prompt = resolve_workspace_file_prompt(
            bot.shared_workspace_id,
            f"bots/{bot.id}/system_prompt.md",
            "",
        )
        if _ws_prompt:
            _sys_prompt = _ws_prompt
    # Bot's own system_prompt is user-authored — verbatim, never dialect-transformed
    parts.append(_sys_prompt.rstrip())
    if getattr(bot, "memory_scheme", None) == "workspace-files":
        from app.config import settings as _cfg
        from app.services.memory_scheme import get_memory_rel_path
        _mem_rel = get_memory_rel_path(bot)
        from app.config import DEFAULT_MEMORY_SCHEME_PROMPT
        _tmpl = _cfg.MEMORY_SCHEME_PROMPT.strip() if _cfg.MEMORY_SCHEME_PROMPT else ""
        # Render dialect FIRST so {%...%} markers are gone before .format() runs.
        _rendered = _dialect_render(_tmpl or DEFAULT_MEMORY_SCHEME_PROMPT, _style)
        _prompt = _rendered.format(memory_rel=_mem_rel).strip()
        parts.append(_prompt)
    # DB memory prompt injection removed (deprecated)
    return "\n\n".join(parts)


async def load_or_create(
    db: AsyncSession,
    session_id: uuid.UUID | None,
    client_id: str,
    bot_id: str,
    locked: bool = False,
    channel_id: uuid.UUID | None = None,
    preserve_metadata: bool = False,
    context_profile_name: str | None = None,
    model_override: str | None = None,
    provider_id_override: str | None = None,
) -> tuple[uuid.UUID, list[dict]]:
    if session_id is not None:
        existing = await db.get(Session, session_id)
        if existing is not None:
            # Update bot_id if the channel has been remapped to a different bot
            if existing.bot_id != bot_id:
                await db.execute(
                    update(Session).where(Session.id == session_id).values(bot_id=bot_id)
                )
                await db.commit()
                await db.refresh(existing)
            messages = await _load_messages(
                db,
                existing,
                preserve_metadata=preserve_metadata,
                context_profile_name=context_profile_name,
                model_override=model_override,
                provider_id_override=provider_id_override,
            )
            return session_id, messages

    if session_id is None:
        session_id = uuid.uuid4()

    bot = get_bot(bot_id)
    session = Session(
        id=session_id, client_id=client_id, bot_id=bot_id,
        locked=locked, channel_id=channel_id,
    )
    db.add(session)

    ws_base_enabled = await _resolve_workspace_base_prompt_enabled(db, bot_id, channel_id)
    channel = await db.get(Channel, channel_id) if channel_id else None
    system_content = _effective_system_prompt(
        bot,
        workspace_base_prompt_enabled=ws_base_enabled,
        channel=channel,
        model_override=model_override,
        provider_id_override=provider_id_override,
    )
    system_msg = Message(
        session_id=session_id,
        role="system",
        content=system_content,
    )
    db.add(system_msg)
    await db.commit()

    # Build initial message list with persona if enabled
    messages = [{"role": "system", "content": system_content}]
    if bot.persona:
        persona_layer = await get_persona(bot.id, workspace_id=bot.shared_workspace_id)
        if persona_layer:
            messages.append({"role": "system", "content": f"[PERSONA]\n{persona_layer}"})

    return session_id, messages



def _format_passive_context(passive_msgs: list[dict]) -> str:
    """Format passive channel messages as a system context block."""
    lines = ["[Channel context — ambient messages not directed at the bot]"]
    for m in passive_msgs:
        meta = m.get("_metadata") or {}
        sender = meta.get("sender_id") or "user"
        content = m.get("content") or ""
        if isinstance(content, list):
            content = " ".join(
                p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
            )
        lines.append(f"  {sender}: {content}")
    return "\n".join(lines)



async def _load_messages(
    db: AsyncSession,
    session: Session,
    *,
    preserve_metadata: bool = False,
    context_profile_name: str | None = None,
    model_override: str | None = None,
    provider_id_override: str | None = None,
) -> list[dict]:
    """Load messages for a session, using compacted summary when available.

    When preserve_metadata=True, the internal ``_metadata`` dict is kept on each
    message so callers can inspect ``sender_id`` etc.  The caller is responsible
    for stripping it before passing messages to the LLM (use ``strip_metadata_keys``).
    """
    bot = get_bot(session.bot_id)
    ws_base_enabled = await _resolve_workspace_base_prompt_enabled(
        db, session.bot_id, session.channel_id,
    )

    persona_layer = None
    if bot.persona:
        persona_layer = await get_persona(bot.id, workspace_id=bot.shared_workspace_id)

    def _base_messages() -> list[dict]:
        msgs = [{
            "role": "system",
            "content": _effective_system_prompt(
                bot,
                workspace_base_prompt_enabled=ws_base_enabled,
                channel=_channel,
                model_override=model_override,
                provider_id_override=provider_id_override,
            ),
        }]
        if persona_layer:
            msgs.append({"role": "system", "content": f"[PERSONA]\n{persona_layer}"})
        for extra in build_plan_mode_system_context(session):
            msgs.append({"role": "system", "content": f"[PLAN MODE]\n{extra}"})
        return msgs

    def _split_passive_active(msgs: list[dict]) -> tuple[list[dict], list[dict]]:
        passive = [m for m in msgs if (m.get("_metadata") or {}).get("passive")]
        active = [m for m in msgs if not (m.get("_metadata") or {}).get("passive")]
        return passive, active

    def _filter_profile_history(msgs: list[dict]) -> list[dict]:
        if not context_profile.name.startswith("chat"):
            return msgs
        return [m for m in msgs if not _is_background_context_message(m)]

    def _inject_channel_context(messages: list[dict], passive: list[dict]) -> list[dict]:
        if passive:
            messages.append({"role": "system", "content": _format_passive_context(passive)})
        return messages

    def _inject_bootstrap_context(messages: list[dict], active_count: int) -> None:
        meta = session.metadata_ or {}
        bootstrap_summary = (meta.get("bootstrap_summary") or "").strip()
        if not bootstrap_summary or active_count > 0:
            return
        bootstrap_title = (meta.get("bootstrap_source_title") or "Primary session").strip()
        bootstrap_session_id = meta.get("bootstrap_source_session_id")
        pointer = (
            f"\nUse read_conversation_history(section='index') for this scratch session. "
            f"The originating primary session was {bootstrap_title!r}"
            + (f" (session {bootstrap_session_id})." if bootstrap_session_id else ".")
        )
        messages.append({
            "role": "system",
            "content": (
                f"Initial bootstrap from the current primary session ({bootstrap_title}):\n\n"
                f"{bootstrap_summary}{pointer}"
            ),
        })

    # Load channel once for history mode
    _channel: Channel | None = None
    if session.channel_id:
        _channel = await db.get(Channel, session.channel_id)
    context_profile = resolve_context_profile(
        session=session,
        profile_name=context_profile_name,
        channel=_channel,
    )

    def _convert_msgs(orm_msgs: list[Message]) -> list[dict]:
        return [_message_to_dict(m, enrich_attachments=True) for m in orm_msgs]

    if session.summary and session.summary_message_id and bot.context_compaction:
        # Resolve history mode
        from app.services.compaction import _get_history_mode
        _history_mode = _get_history_mode(bot, _channel)

        watermark_msg = await db.get(Message, session.summary_message_id)
        if watermark_msg is not None:
            recent_result = await db.execute(
                select(Message)
                .options(selectinload(Message.attachments))
                .where(Message.session_id == session.id)
                .where(Message.created_at > watermark_msg.created_at)
                .order_by(Message.created_at)
            )
            recent_orm = [m for m in recent_result.scalars().all() if m.role != "system"]
            recent = _convert_msgs(recent_orm)
            passive, active = _split_passive_active(recent)
            passive = [m for m in passive if not _is_internal_history_message(m)]
            passive = _filter_profile_history(passive)
            active = _filter_profile_history(active)
            active = _rewrite_active_history_for_model(_filter_old_heartbeats(active))
            messages = _base_messages()

            if _history_mode == "file" and session.channel_id:
                # File mode: section index is injected by context_assembly.py
                # with proper count/verbosity — skip executive summary here to
                # avoid duplicating section titles+summaries in context.
                pass
            elif context_profile.include_compaction_summary and _history_mode == "structured":
                # Structured mode: inject compact executive summary (section retrieval happens in context_assembly)
                messages.append({"role": "system", "content": f"Executive summary of conversation history:\n\n{session.summary}"})
            elif context_profile.include_compaction_summary:
                # Default summary mode
                messages.append({"role": "system", "content": f"Summary of the conversation so far:\n\n{session.summary}"})

            _inject_channel_context(messages, passive)
            _inject_bootstrap_context(messages, len(active))
            active = trim_messages_to_recent_turns(active, context_profile.live_history_turns)
            if active:
                messages.append({"role": "system", "content": "--- BEGIN RECENT CONVERSATION HISTORY ---"})
                messages.extend(active)
                messages.append({"role": "system", "content": "--- END RECENT CONVERSATION HISTORY ---"})
            return _sanitize_tool_messages(messages if preserve_metadata else _strip_metadata_keys(messages))
        else:
            # watermark gone but summary exists — inject summary + all non-system messages
            logger.warning("Watermark message missing for session %s, falling back to summary + full history", session.id)
            result = await db.execute(
                select(Message)
                .options(selectinload(Message.attachments))
                .where(Message.session_id == session.id)
                .order_by(Message.created_at)
            )
            all_orm = list(result.scalars().all())
            all_msgs = _convert_msgs(all_orm)
            non_system = [m for m in all_msgs if m["role"] != "system"]
            passive, active = _split_passive_active(non_system)
            passive = [m for m in passive if not _is_internal_history_message(m)]
            passive = _filter_profile_history(passive)
            active = _filter_profile_history(active)
            active = _rewrite_active_history_for_model(_filter_old_heartbeats(active))
            messages = _base_messages()
            if context_profile.include_compaction_summary and (_history_mode != "file" or not session.channel_id):
                # In file mode, section index is injected by context_assembly.py —
                # skip executive summary here to avoid duplication.
                messages.append({"role": "system", "content": f"Summary of the conversation so far:\n\n{session.summary}"})
            _inject_channel_context(messages, passive)
            _inject_bootstrap_context(messages, len(active))
            active = trim_messages_to_recent_turns(active, context_profile.live_history_turns)
            if active:
                messages.append({"role": "system", "content": "--- BEGIN RECENT CONVERSATION HISTORY ---"})
                messages.extend(active)
                messages.append({"role": "system", "content": "--- END RECENT CONVERSATION HISTORY ---"})
            return _sanitize_tool_messages(messages if preserve_metadata else _strip_metadata_keys(messages))

    result = await db.execute(
        select(Message)
        .options(selectinload(Message.attachments))
        .where(Message.session_id == session.id)
        .order_by(Message.created_at)
    )
    all_orm = list(result.scalars().all())
    all_msgs = _convert_msgs(all_orm)
    non_system_msgs = [m for m in all_msgs if m["role"] != "system"]
    passive, active = _split_passive_active(non_system_msgs)
    passive = [m for m in passive if not _is_internal_history_message(m)]
    passive = _filter_profile_history(passive)
    active = _filter_profile_history(active)
    active = _rewrite_active_history_for_model(_filter_old_heartbeats(active))
    active = trim_messages_to_recent_turns(active, context_profile.live_history_turns)
    messages = _base_messages()
    _inject_channel_context(messages, passive)
    _inject_bootstrap_context(messages, len(active))
    messages.extend(active)
    return _sanitize_tool_messages(messages if preserve_metadata else _strip_metadata_keys(messages))


def strip_metadata_keys(messages: list[dict]) -> list[dict]:
    """Public wrapper for stripping internal ``_metadata`` keys.

    Call after history rewriting when messages were loaded with
    ``preserve_metadata=True``.
    """
    return _strip_metadata_keys(messages)


# ===== Cluster 15 persist_turn stage helpers =====
# Six helpers compose the per-turn persistence pipeline: filter ephemeral/system
# rows, build per-row metadata, insert message rows, fan out outbox enqueues
# (channel + thread variants), link orphan attachments, and publish to the
# in-memory bus. `persist_turn` itself is now a linear driver.


def _filter_messages_to_persist(
    messages: list[dict],
    from_index: int,
    *,
    pre_user_msg_id: uuid.UUID | None,
) -> list[dict]:
    """Drop ephemeral system rows and (when the first user message is already persisted) skip it."""
    new_messages = [m for m in messages[from_index:] if m.get("role") != "system"]
    if pre_user_msg_id:
        _skipped = False
        filtered: list[dict] = []
        for m in new_messages:
            if not _skipped and m.get("role") == "user":
                _skipped = True
                continue
            filtered.append(m)
        new_messages = filtered
    return new_messages


async def _enqueue_outbox_for_channel(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID,
    persisted_records: list[Message],
) -> None:
    """Outbox enqueue for a normal channel turn — one row per (record, target) pair."""
    from app.domain.channel_events import ChannelEvent, ChannelEventKind
    from app.domain.message import Message as DomainMessage
    from app.domain.payloads import MessagePayload
    from app.services import outbox as _outbox
    from app.services.dispatch_resolution import resolve_targets

    channel_row = await db.get(Channel, channel_id)
    if channel_row is None:
        return
    targets = await resolve_targets(channel_row)
    logger.debug(
        "persist_turn: resolved %d external target(s) for channel %s (%s): %s",
        len(targets),
        channel_id,
        getattr(channel_row, "name", None),
        [integration_id for integration_id, _target in targets],
    )
    for record in persisted_records:
        if _should_suppress_external_delivery(record):
            logger.debug(
                "persist_turn: skipping external delivery for internal row %s "
                "(channel=%s role=%s metadata=%s)",
                record.id,
                channel_id,
                record.role,
                record.metadata_ or {},
            )
            continue
        domain_msg = DomainMessage.from_orm(record, channel_id=channel_id)
        event = ChannelEvent(
            channel_id=channel_id,
            kind=ChannelEventKind.NEW_MESSAGE,
            payload=MessagePayload(message=domain_msg),
        )
        await _outbox.enqueue(db, channel_id, event, targets)


async def _enqueue_outbox_for_thread(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    persisted_records: list[Message],
) -> None:
    """Outbox enqueue for a thread sub-session turn — mirrors the parent channel's targets,
    layered with thread-specific refs from `Session.integration_thread_refs`."""
    session_row = await db.get(Session, session_id)
    if session_row is None or session_row.session_type != "thread":
        return
    from app.domain.channel_events import ChannelEvent, ChannelEventKind
    from app.domain.message import Message as DomainMessage
    from app.domain.payloads import MessagePayload
    from app.services import outbox as _outbox
    from app.services.dispatch_resolution import (
        apply_session_thread_refs,
        resolve_targets,
    )
    from app.services.sub_session_bus import resolve_bus_channel_id

    bus_ch = await resolve_bus_channel_id(db, session_id)
    if bus_ch is None:
        return
    channel_row = await db.get(Channel, bus_ch)
    if channel_row is None:
        return
    targets = await resolve_targets(channel_row)
    targets = apply_session_thread_refs(session_row, targets)
    for record in persisted_records:
        if _should_suppress_external_delivery(record):
            logger.debug(
                "persist_turn: skipping thread external delivery for internal row %s "
                "(session=%s role=%s metadata=%s)",
                record.id,
                session_id,
                record.role,
                record.metadata_ or {},
            )
            continue
        domain_msg = DomainMessage.from_orm(record, channel_id=None)
        event = ChannelEvent(
            channel_id=bus_ch,
            kind=ChannelEventKind.NEW_MESSAGE,
            payload=MessagePayload(message=domain_msg),
        )
        await _outbox.enqueue(db, bus_ch, event, targets)


def _should_suppress_external_delivery(record: Message) -> bool:
    meta = record.metadata_ or {}
    return bool(meta.get("suppress_outbox") or meta.get("hidden"))


async def _link_orphan_attachments(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID,
    first_user_msg_id: uuid.UUID | None,
    last_assistant_msg_id: uuid.UUID | None,
) -> None:
    """Link unattached attachments to user/assistant messages from this turn.

    User uploads (`posted_by IS NULL`) → first user message.
    Bot/tool-created (`posted_by IS NOT NULL`, e.g. `send_file`) → last assistant message.
    Commits its own update.
    """
    try:
        from app.db.models import Attachment
        linked_count = 0
        if first_user_msg_id:
            res = await db.execute(
                update(Attachment)
                .where(
                    Attachment.channel_id == channel_id,
                    Attachment.message_id.is_(None),
                    Attachment.posted_by.is_(None),
                )
                .values(message_id=first_user_msg_id)
            )
            linked_count += res.rowcount
        if last_assistant_msg_id:
            res = await db.execute(
                update(Attachment)
                .where(
                    Attachment.channel_id == channel_id,
                    Attachment.message_id.is_(None),
                    Attachment.posted_by.isnot(None),
                )
                .values(message_id=last_assistant_msg_id)
            )
            linked_count += res.rowcount
        if linked_count:
            await db.commit()
            logger.info(
                "Linked %d orphan attachment(s) in channel %s (user_msg=%s, asst_msg=%s)",
                linked_count, channel_id, first_user_msg_id, last_assistant_msg_id,
            )
        else:
            logger.debug(
                "No orphan attachments to link in channel %s (user_msg=%s, asst_msg=%s)",
                channel_id, first_user_msg_id, last_assistant_msg_id,
            )
    except Exception:
        logger.exception(
            "Failed to link orphan attachments in channel %s (user_msg=%s, asst_msg=%s)",
            channel_id, first_user_msg_id, last_assistant_msg_id,
        )


async def _publish_persisted_messages_to_bus(
    db: AsyncSession,
    *,
    bus_channel: uuid.UUID,
    persisted_records: list[Message],
) -> None:
    """Re-read persisted rows with attachments eagerly loaded and publish each to the in-memory bus."""
    try:
        from app.domain.channel_events import ChannelEvent, ChannelEventKind
        from app.domain.message import Message as DomainMessage
        from app.domain.payloads import MessagePayload
        from app.services.outbox_publish import publish_to_bus

        record_ids = [r.id for r in persisted_records]
        fresh_rows = (await db.execute(
            select(Message)
            .options(selectinload(Message.attachments))
            .where(Message.id.in_(record_ids))
            .order_by(Message.created_at)
        )).scalars().all()
        for row in fresh_rows:
            try:
                domain_msg = DomainMessage.from_orm(row, channel_id=bus_channel)
                event = ChannelEvent(
                    channel_id=bus_channel,
                    kind=ChannelEventKind.NEW_MESSAGE,
                    payload=MessagePayload(message=domain_msg),
                )
                publish_to_bus(bus_channel, event)
            except Exception:
                logger.warning(
                    "Failed to publish persisted message %s for channel %s",
                    row.id, bus_channel, exc_info=True,
                )
    except Exception:
        logger.exception("Failed publish loop for channel %s", bus_channel)


async def persist_turn(
    db: AsyncSession,
    session_id: uuid.UUID,
    bot: BotConfig,
    messages: list[dict],
    from_index: int,
    correlation_id: uuid.UUID | None = None,
    msg_metadata: dict | None = None,
    channel_id: uuid.UUID | None = None,
    is_heartbeat: bool = False,
    pre_user_msg_id: uuid.UUID | None = None,
    hide_messages: bool = False,
    suppress_outbox: bool = False,
) -> uuid.UUID | None:
    """Persist new messages from a turn. Returns the first user message ID (for attachment linking).

    If pre_user_msg_id is set, the first user message was already persisted
    before the agent loop and should be skipped here. The pre-persisted ID
    is used for attachment linking.

    Outbox enqueues happen INSIDE the same transaction as the message inserts so
    a crash between commit and renderer ack does not lose deliveries — atomicity
    is the entire point of the outbox pattern. We deliberately do NOT swallow:
    a failure rolls back the message inserts too. Bus publish is best-effort
    post-commit (logged on failure) so SSE subscribers do not block durability.
    """
    from app.services.session_writes import TurnContext, stage_turn_messages

    new_messages = _filter_messages_to_persist(messages, from_index, pre_user_msg_id=pre_user_msg_id)
    logger.info(
        "persist_turn: session=%s from_index=%d total_msgs=%d new_msgs=%d roles=%s pre_user=%s",
        session_id, from_index, len(messages), len(new_messages),
        [m.get("role") for m in new_messages], pre_user_msg_id is not None,
    )

    now = datetime.now(timezone.utc)
    ctx = TurnContext(
        session_id=session_id,
        bot=bot,
        correlation_id=correlation_id,
        msg_metadata=msg_metadata,
        is_heartbeat=is_heartbeat,
        hide_messages=hide_messages,
        pre_user_msg_id=pre_user_msg_id,
        now=now,
    )
    staged = stage_turn_messages(db, ctx, new_messages)

    await db.execute(update(Session).where(Session.id == session_id).values(last_active=now))

    if channel_id and staged.records and not suppress_outbox:
        await _enqueue_outbox_for_channel(db, channel_id=channel_id, persisted_records=staged.records)
    elif channel_id is None and staged.records:
        # Thread sub-sessions live as channel_id IS NULL rows but mirror their parent channel's
        # integrations. `suppress_outbox` is independent here — bus-level session_id tagging is
        # gated separately in turn_worker; we still want the outbox fanout.
        await _enqueue_outbox_for_thread(db, session_id=session_id, persisted_records=staged.records)

    await db.commit()

    if channel_id:
        await _link_orphan_attachments(
            db,
            channel_id=channel_id,
            first_user_msg_id=staged.first_user_msg_id,
            last_assistant_msg_id=staged.last_assistant_msg_id,
        )

    # Publish each persisted row to the in-memory channel-events bus so SSE
    # subscribers (web UI tabs) receive the typed NEW_MESSAGE event without
    # waiting for the drainer. Sub-session runs (channel_id is None but the
    # Session walks up to a parent channel) resolve the parent channel and
    # publish there — this is how the run-view modal receives live events.
    bus_channel = channel_id
    if bus_channel is None and staged.records:
        from app.services.sub_session_bus import resolve_bus_channel_id
        bus_channel = await resolve_bus_channel_id(db, session_id)
    if bus_channel and staged.records:
        await _publish_persisted_messages_to_bus(db, bus_channel=bus_channel, persisted_records=staged.records)
    if staged.records:
        try:
            from app.services.unread import process_persisted_messages

            await process_persisted_messages(
                db,
                session_id=session_id,
                bus_channel_id=bus_channel,
                records=staged.records,
            )
        except Exception:
            logger.exception("persist_turn: unread processing failed for session %s", session_id)

    return staged.first_user_msg_id


async def store_dispatch_echo(
    session_id: uuid.UUID | None,
    client_id: str | None,
    posting_bot_id: str,
    text: str,
    extra_metadata: dict | None = None,
) -> None:
    """Mirror a bot-authored message into the channel session for the next agent load.

    Dispatchers (Slack, etc.) post messages that bypass the inbound message handler, so
    ``chat.postMessage`` results (e.g. delegated bots) never flow through
    ``store_passive_message``.  This writes the same shape of row as human passive traffic:
    ``metadata.passive`` so it appears in the channel-context system block on load.

    IMPORTANT: Skips echoing if the posting bot owns the session — the assistant
    message is already in the session via persist_turn.  Echoing it again as a
    passive user message causes the bot to see its own output 2-3x (active history
    + channel context + heartbeat preamble).
    """
    stripped = (text or "").strip()
    if session_id is None or not client_id or not stripped:
        return

    ch_label = client_id.split(":", 1)[-1] if ":" in client_id else client_id
    content = f"[channel:{ch_label} bot:{posting_bot_id}] {stripped}"

    source = client_id.split(":")[0] if ":" in client_id else "unknown"
    include_in_memory = True
    try:
        async with async_session() as db:
            # Skip echo if posting bot owns this session — avoids duplication.
            # The assistant response is already persisted via persist_turn.
            session = await db.get(Session, session_id)
            if session and session.bot_id == posting_bot_id:
                logger.debug(
                    "store_dispatch_echo: skipping self-echo for bot %s in session %s",
                    posting_bot_id, session_id,
                )
                return

            # Check channel passive_memory setting
            from app.db.models import Channel
            from app.services.channels import is_integration_client_id
            _channel_id = session.channel_id if session else None
            if is_integration_client_id(client_id):
                from sqlalchemy import select
                result = await db.execute(
                    select(Channel).where(Channel.client_id == client_id)
                )
                channel = result.scalar_one_or_none()
                if channel:
                    _channel_id = channel.id
                if channel is not None:
                    if not channel.passive_memory:
                        return
                    include_in_memory = channel.passive_memory
            # Resolve display name for UI attribution
            _sender_display_name = posting_bot_id
            try:
                _bot = get_bot(posting_bot_id)
                _sender_display_name = _bot.display_name or _bot.name or posting_bot_id
            except Exception:
                pass
            metadata = {
                "passive": True,
                "include_in_memory": include_in_memory,
                "trigger_rag": False,
                "source": source,
                "sender_type": "bot",
                "sender_id": f"bot:{posting_bot_id}",
                "sender_display_name": _sender_display_name,
            }
            if extra_metadata:
                metadata.update(extra_metadata)
            await store_passive_message(db, session_id, content, metadata, channel_id=_channel_id)
    except Exception:
        logger.exception(
            "store_dispatch_echo failed session=%s client_id=%s",
            session_id,
            client_id,
        )


async def store_passive_message(
    db: AsyncSession,
    session_id: uuid.UUID,
    content: str,
    metadata: dict,
    channel_id: uuid.UUID | None = None,
    role: str = "user",
) -> None:
    """Store a passive (non-agent-triggering) message in the session."""
    now = datetime.now(timezone.utc)
    clean_role = role if role in {"user", "assistant", "system", "tool"} else "user"
    record = Message(
        session_id=session_id,
        role=clean_role,
        content=content,
        metadata_=metadata,
        created_at=now,
    )
    db.add(record)
    await db.execute(
        update(Session)
        .where(Session.id == session_id)
        .values(last_active=now)
    )
    await db.commit()
    await db.refresh(record)

    # Notify channel event subscribers with the persisted row
    _notify_id = channel_id
    if not _notify_id:
        # Fallback: look up channel_id from session
        _sess = await db.get(Session, session_id)
        if _sess:
            _notify_id = _sess.channel_id
    if _notify_id:
        # NEW_MESSAGE is outbox-durable: enqueue for renderer delivery,
        # publish to bus for SSE subscribers.
        from app.domain.message import Message as DomainMessage
        from app.services.channel_events import publish_message as _publish_message
        from app.services.outbox_publish import enqueue_new_message_for_channel

        _domain_msg = DomainMessage.from_orm(record, channel_id=_notify_id)
        await enqueue_new_message_for_channel(_notify_id, _domain_msg)
        _publish_message(_notify_id, record)


def _sanitize_tool_messages(messages: list[dict]) -> list[dict]:
    """Fix tool message ordering and strip orphans.

    LLMs (especially Gemini via LiteLLM) require strict ordering:
    assistant(tool_calls) must come before its tool(results), and every
    tool result must have a matching tool_call.  DB round-trips can break
    ordering (same-timestamp inserts) and compaction can orphan messages.

    Strategy: extract tool call/result groups, reinsert them in the
    correct position, and strip anything that can't be matched.
    """
    # Pass 1: find where each tool_call ID is offered (assistant) and
    # answered (tool result), by position in the message list.
    call_positions: dict[str, int] = {}   # tc_id → index of assistant msg
    result_positions: dict[str, int] = {} # tc_id → index of tool msg

    for i, msg in enumerate(messages):
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tc_id = tc.get("id") or ""
                if tc_id:
                    call_positions[tc_id] = i
        elif msg.get("role") == "tool" and msg.get("tool_call_id"):
            result_positions[msg["tool_call_id"]] = i

    # Pass 2: identify problems
    all_call_ids = set(call_positions.keys())
    all_result_ids = set(result_positions.keys())
    orphan_results = all_result_ids - all_call_ids
    orphan_calls = all_call_ids - all_result_ids
    misordered = {
        tc_id for tc_id in (all_call_ids & all_result_ids)
        if call_positions[tc_id] >= result_positions[tc_id]
    }

    if not orphan_results and not orphan_calls and not misordered:
        return messages

    if orphan_results:
        logger.warning("Stripping %d orphaned tool result(s)", len(orphan_results))
    if orphan_calls:
        logger.warning("Stripping %d unanswered tool call(s)", len(orphan_calls))
    if misordered:
        logger.warning("Reordering %d misordered tool sequence(s)", len(misordered))

    # Pass 3: rebuild.  Pull out misordered tool results, strip orphans,
    # then reinsert tool results right after their tool_call source.
    displaced: dict[str, dict] = {}  # tc_id → tool result msg (pulled out)
    result_indices_to_skip: set[int] = set()

    for tc_id in misordered:
        idx = result_positions[tc_id]
        displaced[tc_id] = messages[idx]
        result_indices_to_skip.add(idx)

    cleaned: list[dict] = []
    for i, msg in enumerate(messages):
        if i in result_indices_to_skip:
            continue

        if msg.get("role") == "tool" and msg.get("tool_call_id") in orphan_results:
            continue

        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            kept = [tc for tc in msg["tool_calls"]
                    if (tc.get("id") or "") not in orphan_calls]
            if not kept:
                if msg.get("content"):
                    cleaned.append({"role": "assistant", "content": msg["content"]})
                continue
            if len(kept) != len(msg["tool_calls"]):
                msg = {**msg, "tool_calls": kept}

        cleaned.append(msg)

        # Reinsert any displaced tool results right after their source
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tc_id = tc.get("id") or ""
                if tc_id in displaced:
                    cleaned.append(displaced.pop(tc_id))

    return cleaned


def _attachment_hint(att: Attachment) -> str:
    """Build a compact redaction hint for an attachment in history.

    Uses an XML-style self-closing tag rather than natural-language
    instructions. LLMs are far less likely to echo an ``<attachment/>``
    tag into their own output than text like ``→ To fetch full file,
    call: get_attachment("…")`` — which the model was reproducing
    verbatim in assistant responses visible to users. The tool-usage
    docs for ``get_attachment`` live in the attachments skill and do
    not need to be restated in every enriched message.
    """
    desc = att.description or "pending summary"
    # Quote-escape the description so it can't break the attribute.
    safe_desc = desc.replace('"', "'")
    return (
        f'<attachment id="{att.id}" filename="{att.filename}" '
        f'description="{safe_desc}"/>'
    )


def _enrich_content_with_attachments(content: Any, attachments: list[Attachment]) -> Any:
    """Replace image placeholders in stored content with attachment hints.

    Only replaces the ``[image — not available in this session]`` /
    ``[image]`` placeholders that ``_redact_images_for_db`` writes to
    storage. Messages *without* a placeholder (assistant replies, tool
    results) are returned unchanged so the hint text cannot leak into
    what the bot renders back to the user — the LLM was happily copying
    the hint format into its own assistant turns after seeing it in
    enriched history.
    """
    if not attachments:
        return content

    hints = "\n".join(_attachment_hint(a) for a in attachments)

    if isinstance(content, str):
        if "[image — not available in this session]" in content:
            return content.replace(
                "[image — not available in this session]",
                hints,
                1,
            )
        if "[image]" in content:
            return content.replace("[image]", hints, 1)
        return content

    if isinstance(content, list):
        result: list = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text", "")
                if "[image — not available in this session]" in text:
                    text = text.replace(
                        "[image — not available in this session]",
                        hints,
                    )
                result.append({"type": "text", "text": text})
            else:
                result.append(part)
        return result

    return content


def _message_to_dict(msg: Message, enrich_attachments: bool = False) -> dict:
    d: dict = {"role": msg.role}
    if msg.content is not None:
        content = normalize_stored_content(msg.content)
        # Only user messages get attachment hints injected. Assistant /
        # tool messages are rendered as-is: if the LLM sees the hint
        # appended to its own prior assistant turns it will happily
        # reproduce the exact format in new responses, which then ships
        # to the user verbatim.
        if (
            enrich_attachments
            and msg.role == "user"
            and hasattr(msg, "attachments")
            and msg.attachments
        ):
            content = _enrich_content_with_attachments(content, msg.attachments)
        d["content"] = content
    elif msg.tool_calls is not None:
        # Some models (e.g. gpt-5.3-chat-latest) reject null/absent content
        # on assistant tool-call messages. Use empty string as safe default.
        d["content"] = ""
    else:
        # Catch-all: never let a message leave without a content field.
        d["content"] = ""
    if msg.tool_calls is not None:
        d["tool_calls"] = msg.tool_calls
    if msg.tool_call_id is not None:
        d["tool_call_id"] = msg.tool_call_id
    # Restore tool record ID for retrieval-pointer pruning across sessions
    if msg.metadata_ and msg.metadata_.get("tool_record_id"):
        d["_tool_record_id"] = msg.metadata_["tool_record_id"]
    # Restore sticky-tool flag so reference output (skills) survives reload
    if msg.metadata_ and msg.metadata_.get("no_prune"):
        d["_no_prune"] = True
    # Store metadata in a private key so _load_messages can split passive/active;
    # _strip_metadata_keys removes it before returning to the LLM.
    if msg.metadata_:
        d["_metadata"] = msg.metadata_
    return d


def _is_internal_history_message(msg: dict) -> bool:
    meta = msg.get("_metadata") or {}
    return bool(
        meta.get("hidden")
        or meta.get("pipeline_step")
        or meta.get("kind") == "compaction_run"
    )


def _is_background_context_message(msg: dict) -> bool:
    meta = msg.get("_metadata") or {}
    if meta.get("context_visibility") == "background":
        return True
    if meta.get("is_heartbeat"):
        return True
    if meta.get("trigger") in {"heartbeat", "scheduled_task"}:
        return True
    if meta.get("source_task_type") in {"heartbeat", "memory_hygiene", "skill_review"}:
        return True
    return False


def _compact_assistant_turn_body_text(msg: dict) -> str | None:
    """Render compact replay text from canonical assistant_turn_body metadata."""
    meta = msg.get("_metadata") or {}
    body = meta.get("assistant_turn_body") or {}
    items = body.get("items")
    if not isinstance(items, list) or not items:
        return None

    tool_name_by_id: dict[str, str] = {}
    for tc in msg.get("tool_calls") or []:
        if not isinstance(tc, dict):
            continue
        tc_id = tc.get("id")
        fn = tc.get("function") or {}
        if tc_id:
            tool_name_by_id[str(tc_id)] = str(fn.get("name") or "tool")

    parts: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        if kind == "text":
            text = str(item.get("text") or "").strip()
            if text:
                parts.append(text)
        elif kind == "tool_call":
            tool_call_id = str(item.get("toolCallId") or "")
            tool_name = tool_name_by_id.get(tool_call_id, "tool")
            parts.append(f"[Used tool: {tool_name}]")

    compact = " ".join(part for part in parts if part).strip()
    return compact or None


def _rewrite_active_history_for_model(active: list[dict]) -> list[dict]:
    """Drop UI-only rows and compact older assistant transcript-heavy history."""
    visible = [m for m in active if not _is_internal_history_message(m)]
    if not visible:
        return []

    latest_assistant_idx: int | None = None
    for idx, msg in enumerate(visible):
        if msg.get("role") == "assistant":
            latest_assistant_idx = idx

    rewritten: list[dict] = []
    for idx, msg in enumerate(visible):
        if msg.get("role") != "assistant" or idx == latest_assistant_idx:
            rewritten.append(msg)
            continue

        compact = _compact_assistant_turn_body_text(msg)
        content = msg.get("content")
        content_text = content if isinstance(content, str) else str(content or "")
        if not compact or len(content_text) < _ASSISTANT_HISTORY_COMPACT_THRESHOLD:
            rewritten.append(msg)
            continue

        updated = dict(msg)
        updated["content"] = compact
        rewritten.append(updated)

    return rewritten


def _filter_old_heartbeats(msgs: list[dict], *, keep_latest: int = 1) -> list[dict]:
    """Strip old heartbeat turns, keeping only the most recent ones.

    All heartbeat messages (user prompts, assistant responses, tool results)
    are dropped except for the *keep_latest* most recent heartbeat "turns".
    A turn is a contiguous run of heartbeat-tagged messages.

    This prevents stale heartbeat loops from flooding context and drowning
    out user messages.  The bot retains awareness of its most recent heartbeat
    output via the kept turn(s).
    """
    # Identify heartbeat turn boundaries.  A "turn" starts at each
    # user-role heartbeat message and includes all subsequent heartbeat
    # messages until the next non-heartbeat message or another user-role
    # heartbeat.
    hb_turn_starts: list[int] = []
    hb_indices: set[int] = set()
    for i, m in enumerate(msgs):
        meta = m.get("_metadata") or {}
        if meta.get("is_heartbeat"):
            hb_indices.add(i)
            if m.get("role") == "user":
                hb_turn_starts.append(i)

    if not hb_turn_starts:
        # No heartbeat turns at all — return as-is.
        return msgs

    # Map each heartbeat message index to its turn number.
    # Messages before the first heartbeat-user are assigned to turn 0.
    turn_for: dict[int, int] = {}
    current_turn = 0
    for i in sorted(hb_indices):
        if i in hb_turn_starts:
            current_turn = hb_turn_starts.index(i)
        turn_for[i] = current_turn

    total_turns = len(hb_turn_starts)
    keep_from_turn = max(0, total_turns - keep_latest)

    return [
        m for i, m in enumerate(msgs)
        if i not in hb_indices or turn_for.get(i, 0) >= keep_from_turn
    ]


def _strip_metadata_keys(messages: list[dict]) -> list[dict]:
    """Remove internal _metadata keys before passing messages to the LLM.

    Also applies the R1 Phase 2 history-replay wrap: a stored user message
    whose ``_metadata.source`` is in :data:`EXTERNAL_UNTRUSTED_SOURCES` gets
    its body wrapped in ``<untrusted-data>`` here — the LLM-bound boundary —
    so an attacker-controlled message that survived as raw history (e.g.
    ``inject_message``-stored bodies, or any future caller that stores raw)
    doesn't re-enter context unwrapped on turn N+1. The wrap is idempotent:
    chat-route turns whose stored form already carries the marker pass through
    unchanged.
    """
    from app.security.prompt_sanitize import (
        EXTERNAL_UNTRUSTED_SOURCES,
        wrap_untrusted_content,
        is_already_wrapped,
    )

    out = []
    for m in messages:
        meta = m.get("_metadata") or {}
        source = (meta.get("source") or "").strip().lower()
        needs_wrap = (
            m.get("role") == "user"
            and source
            and source in EXTERNAL_UNTRUSTED_SOURCES
        )
        if needs_wrap:
            content = m.get("content")
            if isinstance(content, str) and content and not is_already_wrapped(content):
                m = {**m, "content": wrap_untrusted_content(content, source=source)}
            elif isinstance(content, list):
                # Multimodal: wrap each text part; leave image_url / other parts intact.
                new_parts = []
                changed = False
                for part in content:
                    if (
                        isinstance(part, dict)
                        and part.get("type") == "text"
                        and isinstance(part.get("text"), str)
                        and part["text"]
                        and not is_already_wrapped(part["text"])
                    ):
                        new_parts.append({
                            **part,
                            "text": wrap_untrusted_content(part["text"], source=source),
                        })
                        changed = True
                    else:
                        new_parts.append(part)
                if changed:
                    m = {**m, "content": new_parts}

        if "_metadata" in m:
            m = {k: v for k, v in m.items() if k != "_metadata"}
        out.append(m)
    return out
