import json
import logging
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


def _content_for_db(msg: dict) -> str | dict | list | None:
    raw = msg.get("content")
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
    if workspace_base_prompt_enabled and bot.shared_workspace_id:
        ws_base = resolve_workspace_base_prompt(bot.shared_workspace_id, bot.id)

    if ws_base:
        parts.append(ws_base.rstrip())
    else:
        base = render_base_prompt(bot)
        if base:
            parts.append(base.rstrip())

    parts.append(bot.system_prompt.rstrip())
    if getattr(bot, "memory_scheme", None) == "workspace-files":
        from app.config import settings as _cfg
        from app.services.memory_scheme import get_memory_rel_path
        _mem_rel = get_memory_rel_path(bot)
        _tmpl = _cfg.MEMORY_SCHEME_PROMPT.strip() if _cfg.MEMORY_SCHEME_PROMPT else ""
        _prompt = (_tmpl or _MEMORY_SCHEME_PROMPT).format(memory_rel=_mem_rel).strip()
        parts.append(_prompt)
    elif bot.memory.enabled and bot.memory.prompt:
        parts.append(bot.memory.prompt.strip())
    return "\n\n".join(parts)


_MEMORY_SCHEME_PROMPT = """\
## Memory

Your persistent memory lives in `{memory_rel}/` relative to your workspace directory.
MEMORY.md and recent daily logs are in your context — do not re-read them.

### MEMORY.md — Curated Knowledge
Stable facts: user preferences, key decisions, system configs, learned patterns.
Keep under ~100 lines. Promote important learnings from daily logs here.
Format: ## sections with _Updated: YYYY-MM-DD_ headers. Edit in place.

### logs/YYYY-MM-DD.md — Daily Logs
Session notes, events, decisions, task progress. Today's log and yesterday's
are in your context. Append to today's log during the session.

### reference/ — Reference Documents
Longer guides, runbooks, architecture notes. Not in your context.
Use get_memory_file("name") or search_memory("query") to access.

### Tools
- search_memory(query) — hybrid semantic+keyword search across all memory files
- get_memory_file(name) — read a specific memory file
- Writing: use exec_command (sed, echo, heredoc, etc.) to write/edit memory files

### Memory Protocol
- Before answering about past work or context: search_memory first
- Before starting any new task: check today's memory log (already in context)
- When you learn something important: write it to the daily log immediately, don't wait
- When corrected on a mistake or preference: add it as a rule to MEMORY.md
- When context is getting large: summarize key points to today's daily log before they're lost
- When a fact is confirmed across multiple sessions: promote it from daily log to MEMORY.md
- Promote stable facts to MEMORY.md — keep it curated and under ~100 lines
- Format MEMORY.md sections with _Updated: YYYY-MM-DD_ headers; edit in place"""


async def load_or_create(
    db: AsyncSession,
    session_id: uuid.UUID | None,
    client_id: str,
    bot_id: str,
    locked: bool = False,
    channel_id: uuid.UUID | None = None,
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
            messages = await _load_messages(db, existing)
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



async def _load_messages(db: AsyncSession, session: Session) -> list[dict]:
    """Load messages for a session, using compacted summary when available."""
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
            return _sanitize_tool_messages(_strip_metadata_keys(messages))
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
            return _sanitize_tool_messages(_strip_metadata_keys(messages))

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
    return _sanitize_tool_messages(_strip_metadata_keys(messages))

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
) -> uuid.UUID | None:
    """Persist new messages from a turn. Returns the first user message ID (for attachment linking)."""
    # Ephemeral system messages (datetime, memory, skills, fs_context, tool_index, etc.) are
    # re-injected fresh on every turn — persisting them causes unbounded context growth.
    new_messages = [m for m in messages[from_index:] if m.get("role") != "system"]
    roles = [m.get("role") for m in new_messages]
    logger.info(
        "persist_turn: session=%s from_index=%d total_msgs=%d new_msgs=%d roles=%s",
        session_id, from_index, len(messages), len(new_messages), roles,
    )
    now = datetime.now(timezone.utc)
    first_user = True
    first_user_msg_id: uuid.UUID | None = None
    for i, msg in enumerate(new_messages):
        # Attach msg_metadata to the first user message in the turn
        meta = {}
        if msg_metadata and msg.get("role") == "user" and first_user:
            meta = msg_metadata
            first_user = False
        # Auto-inject bot metadata on assistant messages
        if msg.get("role") == "assistant" and not meta:
            meta = {"sender_type": "bot", "sender_id": f"bot:{bot.id}", "sender_display_name": bot.name}
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
        if first_user_msg_id is None and msg.get("role") == "user":
            first_user_msg_id = record.id

    await db.execute(
        update(Session)
        .where(Session.id == session_id)
        .values(last_active=now)
    )
    await db.commit()

    return first_user_msg_id


async def store_dispatch_echo(
    session_id: uuid.UUID | None,
    client_id: str | None,
    posting_bot_id: str,
    text: str,
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
            if is_integration_client_id(client_id):
                from sqlalchemy import select
                result = await db.execute(
                    select(Channel).where(Channel.client_id == client_id)
                )
                channel = result.scalar_one_or_none()
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
            await store_passive_message(db, session_id, content, metadata)
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
    """Build a compact redaction hint for an attachment in history."""
    desc = att.description or "pending summary"
    return (
        f'[attached: {att.filename} — "{desc}"]\n'
        f'→ To fetch full file, call: get_attachment("{att.id}")'
    )


def _enrich_content_with_attachments(content: Any, attachments: list[Attachment]) -> Any:
    """Replace image/file placeholders in stored content with attachment summaries.

    Only applies to older turns where images were redacted to placeholders by
    _redact_images_for_db.  Returns enriched content.
    """
    if not attachments:
        return content

    hints = "\n".join(_attachment_hint(a) for a in attachments)
    tool_hint = (
        "\n(Use get_attachment tool to fetch full file/image if needed.)"
        if any(a.description for a in attachments)
        else ""
    )

    if isinstance(content, str):
        # Replace generic image placeholders with attachment summaries
        if "[image — not available in this session]" in content:
            content = content.replace(
                "[image — not available in this session]",
                hints + tool_hint,
                1,  # replace first occurrence; remaining will be replaced by subsequent calls
            )
        elif "[image]" in content:
            content = content.replace("[image]", hints + tool_hint, 1)
        else:
            # No placeholder — append hints
            content = content + "\n" + hints + tool_hint
        return content

    if isinstance(content, list):
        # Replace image_url placeholder parts with text attachment hints
        result: list = []
        hint_injected = False
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text", "")
                if "[image — not available in this session]" in text:
                    text = text.replace(
                        "[image — not available in this session]",
                        hints + tool_hint,
                    )
                    hint_injected = True
                result.append({"type": "text", "text": text})
            else:
                result.append(part)
        if not hint_injected:
            result.append({"type": "text", "text": hints + tool_hint})
        return result

    return content


def _message_to_dict(msg: Message, enrich_attachments: bool = False) -> dict:
    d: dict = {"role": msg.role}
    if msg.content is not None:
        content = normalize_stored_content(msg.content)
        if enrich_attachments and hasattr(msg, "attachments") and msg.attachments:
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
    # Store metadata in a private key so _load_messages can split passive/active;
    # _strip_metadata_keys removes it before returning to the LLM.
    if msg.metadata_:
        d["_metadata"] = msg.metadata_
    return d


def _filter_old_heartbeats(msgs: list[dict]) -> list[dict]:
    """Strip ALL heartbeat messages from the active conversation history.

    Heartbeat messages are tagged with is_heartbeat=True in metadata.
    They're dropped entirely because:
    - For heartbeat turns: the preamble already includes "Previous heartbeat
      conclusion" — keeping old exchanges is redundant.
    - For user turns: heartbeat prompts look like user instructions and confuse
      the LLM into continuing from the heartbeat context instead of the user's
      actual message.
    - The bot's memory files provide long-term heartbeat continuity.
    """
    return [m for m in msgs if not (m.get("_metadata") or {}).get("is_heartbeat")]


def _strip_metadata_keys(messages: list[dict]) -> list[dict]:
    """Remove internal _metadata keys before passing messages to the LLM."""
    out = []
    for m in messages:
        if "_metadata" in m:
            m = {k: v for k, v in m.items() if k != "_metadata"}
        out.append(m)
    return out
