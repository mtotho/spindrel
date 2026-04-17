import json
import logging
import re
import uuid
from typing import Any
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import BotConfig, get_bot
from app.agent.persona import get_persona
from app.db.engine import async_session
from sqlalchemy.orm import selectinload

from app.db.models import Attachment, Channel, Message, Session, SharedWorkspace, SharedWorkspaceBot


logger = logging.getLogger(__name__)


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
) -> str:
    """Base prompt + bot system prompt + optional memory guidelines.

    If workspace_base_prompt_enabled and the bot belongs to a shared workspace,
    reads common/prompts/base.md (+ bots/{bot_id}/prompts/base.md) from the
    workspace filesystem and uses that instead of the global base prompt.
    """
    from app.agent.base_prompt import render_base_prompt, resolve_workspace_base_prompt
    from app.config import settings as _settings
    parts = []

    # Global base prompt: org-wide instructions prepended before everything
    if _settings.GLOBAL_BASE_PROMPT:
        parts.append(_settings.GLOBAL_BASE_PROMPT.rstrip())

    ws_base = None
    if workspace_base_prompt_enabled:
        ws_base = resolve_workspace_base_prompt(bot.shared_workspace_id, bot.id)

    if ws_base:
        parts.append(ws_base.rstrip())
    else:
        base = render_base_prompt(bot)
        if base:
            parts.append(base.rstrip())

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
    parts.append(_sys_prompt.rstrip())
    if getattr(bot, "memory_scheme", None) == "workspace-files":
        from app.config import settings as _cfg
        from app.services.memory_scheme import get_memory_rel_path
        _mem_rel = get_memory_rel_path(bot)
        from app.config import DEFAULT_MEMORY_SCHEME_PROMPT
        _tmpl = _cfg.MEMORY_SCHEME_PROMPT.strip() if _cfg.MEMORY_SCHEME_PROMPT else ""
        _prompt = (_tmpl or DEFAULT_MEMORY_SCHEME_PROMPT).format(memory_rel=_mem_rel).strip()
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
            messages = await _load_messages(db, existing, preserve_metadata=preserve_metadata)
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
    system_content = _effective_system_prompt(bot, workspace_base_prompt_enabled=ws_base_enabled)
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



async def _load_messages(db: AsyncSession, session: Session, *, preserve_metadata: bool = False) -> list[dict]:
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
        msgs = [{"role": "system", "content": _effective_system_prompt(bot, workspace_base_prompt_enabled=ws_base_enabled)}]
        if persona_layer:
            msgs.append({"role": "system", "content": f"[PERSONA]\n{persona_layer}"})
        return msgs

    def _split_passive_active(msgs: list[dict]) -> tuple[list[dict], list[dict]]:
        passive = [m for m in msgs if (m.get("_metadata") or {}).get("passive")]
        active = [m for m in msgs if not (m.get("_metadata") or {}).get("passive")]
        return passive, active

    def _inject_channel_context(messages: list[dict], passive: list[dict]) -> list[dict]:
        if passive:
            messages.append({"role": "system", "content": _format_passive_context(passive)})
        return messages

    # Load channel once for history mode
    _channel: Channel | None = None
    if session.channel_id:
        _channel = await db.get(Channel, session.channel_id)

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
            active = _filter_old_heartbeats(active)
            messages = _base_messages()

            if _history_mode == "file" and session.channel_id:
                # File mode: section index is injected by context_assembly.py
                # with proper count/verbosity — skip executive summary here to
                # avoid duplicating section titles+summaries in context.
                pass
            elif _history_mode == "structured":
                # Structured mode: inject compact executive summary (section retrieval happens in context_assembly)
                messages.append({"role": "system", "content": f"Executive summary of conversation history:\n\n{session.summary}"})
            else:
                # Default summary mode
                messages.append({"role": "system", "content": f"Summary of the conversation so far:\n\n{session.summary}"})

            _inject_channel_context(messages, passive)
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
            active = _filter_old_heartbeats(active)
            messages = _base_messages()
            if _history_mode != "file" or not session.channel_id:
                # In file mode, section index is injected by context_assembly.py —
                # skip executive summary here to avoid duplication.
                messages.append({"role": "system", "content": f"Summary of the conversation so far:\n\n{session.summary}"})
            _inject_channel_context(messages, passive)
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
    active = _filter_old_heartbeats(active)
    messages = _base_messages()
    _inject_channel_context(messages, passive)
    messages.extend(active)
    return _sanitize_tool_messages(messages if preserve_metadata else _strip_metadata_keys(messages))


def strip_metadata_keys(messages: list[dict]) -> list[dict]:
    """Public wrapper for stripping internal ``_metadata`` keys.

    Call after history rewriting when messages were loaded with
    ``preserve_metadata=True``.
    """
    return _strip_metadata_keys(messages)


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
) -> uuid.UUID | None:
    """Persist new messages from a turn. Returns the first user message ID (for attachment linking).

    If pre_user_msg_id is set, the first user message was already persisted
    before the agent loop and should be skipped here. The pre-persisted ID
    is used for attachment linking.
    """
    # Ephemeral system messages (datetime, memory, skills, fs_context, tool_index, etc.) are
    # re-injected fresh on every turn — persisting them causes unbounded context growth.
    new_messages = [m for m in messages[from_index:] if m.get("role") != "system"]

    # If user message was pre-persisted, skip the first user message from the list
    if pre_user_msg_id:
        _skipped = False
        filtered = []
        for m in new_messages:
            if not _skipped and m.get("role") == "user":
                _skipped = True
                continue
            filtered.append(m)
        new_messages = filtered

    roles = [m.get("role") for m in new_messages]
    logger.info(
        "persist_turn: session=%s from_index=%d total_msgs=%d new_msgs=%d roles=%s pre_user=%s",
        session_id, from_index, len(messages), len(new_messages), roles,
        pre_user_msg_id is not None,
    )
    now = datetime.now(timezone.utc)
    first_user = pre_user_msg_id is None  # only track first user if not pre-persisted
    first_user_msg_id: uuid.UUID | None = pre_user_msg_id
    last_assistant_msg_id: uuid.UUID | None = None
    # Track records for per-row SSE publish after commit + attachment linking
    persisted_records: list[Message] = []
    for i, msg in enumerate(new_messages):
        # Attach msg_metadata to the first user message in the turn
        meta = {}
        if msg_metadata and msg.get("role") == "user" and first_user:
            meta = msg_metadata
            first_user = False
        # Auto-inject bot metadata on assistant messages
        if msg.get("role") == "assistant" and not meta:
            meta = {"sender_type": "bot", "sender_id": f"bot:{bot.id}", "sender_display_name": bot.name}
        # Carry forward tools_used from the agent loop into message metadata
        if msg.get("_tools_used"):
            meta = {**meta, "tools_used": msg["_tools_used"]}
        # Carry forward per-tool envelopes (rendered output keyed by mimetype)
        # so the web UI can show rich tool result rendering on persisted
        # messages — not just during streaming. The list is in invocation
        # order, matching message.tool_calls[].
        if msg.get("_tool_envelopes"):
            meta = {**meta, "tool_results": msg["_tool_envelopes"]}
        # Carry forward tool record ID for retrieval-pointer pruning
        if msg.get("_tool_record_id"):
            meta = {**meta, "tool_record_id": msg["_tool_record_id"]}
        # Carry forward sticky-tool flag (skill/runbook output never pruned)
        if msg.get("_no_prune"):
            meta = {**meta, "no_prune": True}
        # Carry forward auto-injected skills for UI display on persisted messages
        if msg.get("_auto_injected_skills"):
            meta = {**meta, "auto_injected_skills": msg["_auto_injected_skills"]}
        # Carry forward skills still in context (from prior get_skill calls)
        # for the UI skill orb on persisted messages.
        if msg.get("_active_skills"):
            meta = {**meta, "active_skills": msg["_active_skills"]}
        # Carry forward LLM retry/fallback info for UI display on persisted messages
        if msg.get("_llm_status"):
            meta = {**meta, "llm_status": msg["_llm_status"]}
        # Extract delegation info from delegate_to_agent tool calls
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            _delegations = []
            for tc in msg["tool_calls"]:
                fn = tc.get("function") or {}
                if fn.get("name") == "delegate_to_agent":
                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                        _delegations.append({
                            "bot_id": args.get("bot_id"),
                            "prompt_preview": (args.get("prompt") or "")[:200],
                            "notify_parent": args.get("notify_parent", True),
                        })
                    except (json.JSONDecodeError, TypeError):
                        pass
            if _delegations:
                meta = {**meta, "delegations": _delegations}
        # Tag all messages in heartbeat turns so _load_messages can filter old ones
        if is_heartbeat:
            meta = {**meta, "is_heartbeat": True}
        record = Message(
            session_id=session_id,
            role=msg["role"],
            content=_content_for_db(msg),
            tool_calls=msg.get("tool_calls"),
            tool_call_id=msg.get("tool_call_id"),
            correlation_id=correlation_id,
            metadata_=meta,
            created_at=now + timedelta(microseconds=i),
        )
        db.add(record)
        persisted_records.append(record)
        if first_user_msg_id is None and msg.get("role") == "user":
            first_user_msg_id = record.id
        if msg.get("role") == "assistant":
            last_assistant_msg_id = record.id

    await db.execute(
        update(Session)
        .where(Session.id == session_id)
        .values(last_active=now)
    )

    # Outbox enqueue (durable channel-event delivery). Resolve every
    # dispatch target bound to the channel and insert one outbox row per
    # (record, target) pair INSIDE the same transaction as the message
    # inserts. The drainer (`outbox_drainer.py`) picks them up and routes
    # them through the renderer registry. A crash between this commit and
    # the renderer ack does not lose deliveries — the rows survive.
    #
    # An enqueue failure here propagates: the in-progress transaction
    # rolls back (taking the message inserts with it) and the caller
    # surfaces the error. We deliberately do NOT swallow — the legacy
    # try/except let one row's outbox insert silently fail while the
    # commit proceeded, leaving the bus subscribers with a NEW_MESSAGE
    # for which no integration delivery was ever attempted. Atomicity
    # is the entire point of the outbox pattern.
    if channel_id and persisted_records:
        from app.domain.channel_events import ChannelEvent, ChannelEventKind
        from app.domain.message import Message as DomainMessage
        from app.domain.payloads import MessagePayload
        from app.services import outbox as _outbox
        from app.services.dispatch_resolution import resolve_targets

        channel_row = await db.get(Channel, channel_id)
        if channel_row is not None:
            targets = await resolve_targets(channel_row)
            for record in persisted_records:
                domain_msg = DomainMessage.from_orm(
                    record, channel_id=channel_id
                )
                event = ChannelEvent(
                    channel_id=channel_id,
                    kind=ChannelEventKind.NEW_MESSAGE,
                    payload=MessagePayload(message=domain_msg),
                )
                await _outbox.enqueue(db, channel_id, event, targets)

    await db.commit()

    # Link orphaned attachments to the correct message in this turn.
    # User-uploaded attachments (posted_by IS NULL) → first user message.
    # Bot/tool-created attachments (posted_by IS NOT NULL, e.g. send_file) → last assistant message.
    if channel_id:
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

    # Publish each persisted row to the in-memory channel-events bus so
    # SSE subscribers (web UI tabs) receive the typed NEW_MESSAGE event
    # without waiting for the drainer. Attachments are eagerly loaded so
    # the payload is complete. Outbox delivery to integrations runs in
    # parallel via the drainer (rows enqueued above).
    if channel_id and persisted_records:
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
                    domain_msg = DomainMessage.from_orm(row, channel_id=channel_id)
                    event = ChannelEvent(
                        channel_id=channel_id,
                        kind=ChannelEventKind.NEW_MESSAGE,
                        payload=MessagePayload(message=domain_msg),
                    )
                    publish_to_bus(channel_id, event)
                except Exception:
                    logger.warning(
                        "Failed to publish persisted message %s for channel %s",
                        row.id, channel_id, exc_info=True,
                    )
        except Exception:
            logger.exception(
                "Failed publish loop for channel %s", channel_id,
            )

    return first_user_msg_id


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
) -> None:
    """Store a passive (non-agent-triggering) message in the session."""
    now = datetime.now(timezone.utc)
    record = Message(
        session_id=session_id,
        role="user",
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
    """Remove internal _metadata keys before passing messages to the LLM."""
    out = []
    for m in messages:
        if "_metadata" in m:
            m = {k: v for k, v in m.items() if k != "_metadata"}
        out.append(m)
    return out
