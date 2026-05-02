import asyncio
import json
import logging
import os
import re as _re_mod
import shutil
import time as _time
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.agent.bots import BotConfig
from app.agent.tool_dispatch import ToolResultEnvelope
from app.agent.recording import _record_trace_event
from app.config import settings
from app.db.engine import async_session
from app.db.models import Channel, CompactionLog, ConversationSection, Message, Session
from app.services.sessions import normalize_stored_content

logger = logging.getLogger(__name__)

from app.config import DEFAULT_MEMORY_SCHEME_FLUSH_PROMPT

COMPACTION_RUN_KIND = "compaction_run"
_ACTIVE_MANUAL_COMPACTION_STATUSES = {"queued", "running"}
_MANUAL_COMPACTION_TASKS: dict[str, asyncio.Task] = {}
_COMPACTION_NOOP_ERRORS = (
    "All messages within keep window",
    "No conversation content to summarize",
    "No user messages found in session",
)


# ---------------------------------------------------------------------------
# Depth-aware section prompts (Phase 1)
# ---------------------------------------------------------------------------

_SECTION_PROMPT_TIER0 = """\
You are a conversation archiver. You will receive a segment of conversation between \
a user and an AI assistant that is being archived. The raw transcript is stored separately — \
you only need to produce metadata.

Produce a JSON object with the following fields:
- "title": A concise heading for this conversation segment (5-12 words). Do NOT include dates or times \
in the title — timestamps are added automatically from message metadata.
- "summary": A detailed 3-sentence summary preserving exact errors, commands, file paths, \
config values, and timestamps. Include what was tried and why. Preserve operational detail — \
this is early history that may be referenced later.
- "tags": An array of 3-5 short topic tags (1-3 words each) that categorize this segment.

Respond ONLY with the JSON object, no markdown fences or extra text."""

_SECTION_PROMPT_TIER1 = """\
You are a conversation archiver. You will receive a segment of conversation between \
a user and an AI assistant that is being archived. The raw transcript is stored separately — \
you only need to produce metadata.

Produce a JSON object with the following fields:
- "title": A concise heading for this conversation segment (5-12 words). Do NOT include dates or times \
in the title — timestamps are added automatically from message metadata.
- "summary": A 2-sentence summary capturing decisions, rationale, and outcomes. \
Drop dead-end exploration and intermediate debugging steps when the conclusion is known.
- "tags": An array of 3-5 short topic tags (1-3 words each) that categorize this segment.

Respond ONLY with the JSON object, no markdown fences or extra text."""

_SECTION_PROMPT_TIER2 = """\
You are a conversation archiver. You will receive a segment of conversation between \
a user and an AI assistant that is being archived. The raw transcript is stored separately — \
you only need to produce metadata.

Produce a JSON object with the following fields:
- "title": A concise heading for this conversation segment (5-12 words). Do NOT include dates or times \
in the title — timestamps are added automatically from message metadata.
- "summary": A 1-2 sentence high-level summary — narrative arc only. What was the goal, \
what happened, what carries forward. Only durable facts.
- "tags": An array of 3-5 short topic tags (1-3 words each) that categorize this segment.

Respond ONLY with the JSON object, no markdown fences or extra text."""

_SECTION_PROMPT_AGGRESSIVE = """\
Summarize this conversation segment in exactly one sentence. Only durable facts and decisions. \
No filler. Respond with JSON: {"title": "...", "summary": "...", "tags": [...]}"""


def _select_section_prompt(section_count: int) -> str:
    """Select a depth-aware compaction prompt based on how many sections already exist."""
    if section_count < 5:
        return _SECTION_PROMPT_TIER0
    elif section_count < 15:
        return _SECTION_PROMPT_TIER1
    else:
        return _SECTION_PROMPT_TIER2


def _truncate_at_sentence(text: str, max_chars: int) -> str:
    """Truncate *text* to at most *max_chars*, breaking at the last sentence
    boundary (. ! ? followed by whitespace or end-of-string) so we never cut
    mid-sentence.  Falls back to the full slice if no boundary is found.
    """
    if len(text) <= max_chars:
        return text
    window = text[:max_chars]
    for i in range(len(window) - 1, -1, -1):
        if window[i] in ".!?" and (i + 1 >= len(window) or window[i + 1] in " \n\t\r"):
            return window[: i + 1]
    return window.rstrip() + "…"


# ---------------------------------------------------------------------------
# Filesystem transcript helpers
# ---------------------------------------------------------------------------

def _get_history_dir(bot: BotConfig, channel: Channel | None = None) -> str | None:
    """Return host-side .history dir path, creating if needed. None if no workspace.

    When a channel is provided, history lives inside the channel workspace:
      {channel_ws_root}/.history/   (i.e. channels/{channel_id}/.history/)
    Without a channel, falls back to bot-level:
      {bot_ws_root}/.history/
    """
    try:
        if channel:
            from app.services.channel_workspace import get_channel_workspace_root
            channel_root = get_channel_workspace_root(str(channel.id), bot)
            history_dir = os.path.join(channel_root, ".history")
        else:
            from app.services.workspace import workspace_service
            root = workspace_service.get_workspace_root(bot.id, bot)
            history_dir = os.path.join(root, ".history")
        os.makedirs(history_dir, exist_ok=True)
        return history_dir
    except Exception:
        logger.exception("Failed to get/create .history dir for bot %s", bot.id)
        return None


def _get_workspace_root(bot: BotConfig) -> str | None:
    """Return workspace root path for a bot, or None."""
    from app.services.workspace import workspace_service
    try:
        return workspace_service.get_workspace_root(bot.id, bot)
    except Exception:
        logger.exception("Failed to get workspace root for bot %s", bot.id)
        return None


def _get_channel_ws_root(bot: BotConfig) -> str | None:
    """Return the channel-workspace root (parent of channels/) for a bot, or None.

    This is the root against which `channels/{id}/.history/...` paths are relative.
    """
    from app.services.channel_workspace import _get_ws_root
    try:
        return _get_ws_root(bot)
    except Exception:
        logger.exception("Failed to get channel ws root for bot %s", bot.id)
        return None


def _write_section_file(
    history_dir: str,
    sequence: int,
    title: str,
    summary: str,
    transcript: str,
    period_start: datetime | None,
    period_end: datetime | None,
    message_count: int,
    tags: list[str],
    workspace_root: str,
) -> str:
    """Write a section markdown file. Returns relative path from workspace root."""
    slug = _re_mod.sub(r'[^a-z0-9]+', '_', title.lower())[:50].strip('_')
    filename = f"{sequence:03d}_{slug}.md"
    filepath = os.path.join(history_dir, filename)

    period = ""
    if period_start:
        period += f"From: {period_start.strftime('%Y-%m-%d %H:%M')}"
    if period_end:
        period += f"  To: {period_end.strftime('%Y-%m-%d %H:%M')}"
    tag_line = f"Tags: {', '.join(tags)}\n" if tags else ""

    content = (
        f"# {title}\n"
        f"{period}\n"
        f"Messages: {message_count}\n"
        f"{tag_line}\n"
        f"Summary: {summary}\n\n"
        f"---\n\n"
        f"{transcript}"
    )

    with open(filepath, "w") as f:
        f.write(content)

    return os.path.relpath(filepath, workspace_root)


def _msg_to_dict(m: Message) -> dict:
    """Convert a Message ORM instance to a plain dict for compaction."""
    d: dict = {"role": m.role}
    if m.content is not None:
        d["content"] = normalize_stored_content(m.content)
    if m.tool_calls is not None:
        d["tool_calls"] = m.tool_calls
    if m.tool_call_id is not None:
        d["tool_call_id"] = m.tool_call_id
    if m.metadata_:
        d["_metadata"] = m.metadata_
    return d


def _get_history_mode(bot: BotConfig, channel: Channel | None = None) -> str:
    """Resolve the effective history mode: channel override → bot → global default."""
    if channel and channel.history_mode:
        return channel.history_mode
    return bot.history_mode or settings.DEFAULT_HISTORY_MODE


def _resolve_trigger_heartbeat(channel: Channel | None = None) -> bool:
    """Resolve whether to trigger a heartbeat before compaction: channel → global.
    Deprecated — kept for backward compat when memory_flush_enabled is not set.
    """
    if channel and channel.trigger_heartbeat_before_compaction is not None:
        return channel.trigger_heartbeat_before_compaction
    return settings.TRIGGER_HEARTBEAT_BEFORE_COMPACTION


def _resolve_memory_flush_enabled(bot: BotConfig, channel: Channel | None = None) -> bool:
    """Resolve whether to run a dedicated memory flush before compaction.

    Priority: channel.memory_flush_enabled → global MEMORY_FLUSH_ENABLED
    → auto-enable for workspace-files bots → False.
    """
    if channel and channel.memory_flush_enabled is not None:
        return channel.memory_flush_enabled
    if settings.MEMORY_FLUSH_ENABLED:
        return True
    # Auto-enable for workspace-files bots: this is the primary mechanism
    # for cross-session learning, so it should be on by default
    if bot.memory_scheme == "workspace-files":
        return True
    # Legacy fallback: if TRIGGER_HEARTBEAT_BEFORE_COMPACTION is set but
    # MEMORY_FLUSH_ENABLED is not, the old heartbeat path still fires
    return False


def _get_memory_flush_model(bot: BotConfig, channel: Channel | None = None) -> str:
    """Resolve the model for memory flush: channel → global → bot model."""
    if channel and channel.memory_flush_model:
        return channel.memory_flush_model
    if settings.MEMORY_FLUSH_MODEL:
        return settings.MEMORY_FLUSH_MODEL
    return bot.model


def _resolve_provider_for_selected_model(
    *,
    model: str,
    bot: BotConfig,
    explicit_provider_id: str | None = None,
) -> str | None:
    """Resolve provider for an auxiliary model without inheriting blindly.

    Compaction/memory-flush models often differ from the bot's chat model. If
    the selected model differs, prefer the provider registry for that model and
    only fall back to the bot provider for the bot's own model or unknown rows.
    """
    if explicit_provider_id:
        return explicit_provider_id
    from app.services.providers import resolve_provider_for_model

    resolved = resolve_provider_for_model(model)
    if resolved:
        return resolved
    return bot.model_provider_id


def _compaction_bus_key(session: Session) -> uuid.UUID:
    return session.channel_id or session.id


def _compact_bot_name(bot: BotConfig) -> str:
    return getattr(bot, "display_name", None) or getattr(bot, "name", None) or bot.id


def _is_noop_compaction_error(exc: Exception) -> bool:
    text = str(exc)
    return any(marker in text for marker in _COMPACTION_NOOP_ERRORS)


def _compaction_envelope(
    *,
    origin: str,
    status: str,
    title: str | None = None,
    detail: str | None = None,
    summary_text: str | None = None,
    summary_len: int | None = None,
    error: str | None = None,
    trigger_reason: str | None = None,
    result_kind: str | None = None,
) -> dict[str, Any]:
    origin_label = "Manual" if origin == "manual" else "Auto"
    if status == "queued":
        heading = "Compaction queued"
        body_detail = detail or "A response is still running. Compaction will start after it finishes."
    elif status == "running":
        heading = "Compaction running"
        body_detail = detail or "Older conversation history is being summarized."
    elif status == "warning":
        heading = "Context pressure rising"
        body_detail = detail or "The conversation is approaching the automatic compaction threshold."
    elif status == "failed":
        heading = "Compaction failed"
        body_detail = error or detail or "Compaction did not complete."
    elif result_kind == "noop":
        heading = "Nothing to compact"
        body_detail = detail or "The live keep window already contains the available conversation."
    else:
        heading = "Context compacted"
        body_detail = detail or "Older conversation history was summarized."

    lines = [f"**{heading}**", "", body_detail, "", f"Source: {origin_label} compaction."]
    if title:
        lines.append(f"Title: {title}.")
    if summary_text:
        lines.extend(["", "Summary:", "", summary_text])
    if summary_len is not None:
        lines.append(f"Summary length: {summary_len:,} characters.")
    if trigger_reason:
        lines.append(f"Trigger: {trigger_reason}.")
    body = "\n".join(lines)
    plain_body = f"{heading}: {body_detail}"
    return ToolResultEnvelope(
        content_type="text/markdown",
        body=body,
        plain_body=plain_body,
        display="panel",
        display_label="Compaction",
        byte_size=len(body.encode("utf-8")),
        view_key="compaction_run",
        data={
            "origin": origin,
            "status": status,
            "title": title,
            "detail": body_detail,
            "summary_text": summary_text,
            "summary_len": summary_len,
            "trigger_reason": trigger_reason,
            "result_kind": result_kind or status,
            "error": error,
        },
    ).compact_dict()


def _compaction_metadata(
    *,
    bot: BotConfig,
    origin: str,
    status: str,
    title: str | None = None,
    detail: str | None = None,
    summary_text: str | None = None,
    summary_len: int | None = None,
    error: str | None = None,
    trigger_reason: str | None = None,
    result_kind: str | None = None,
) -> dict[str, Any]:
    metadata = {
        "kind": COMPACTION_RUN_KIND,
        "source": "compaction",
        "sender_type": "bot",
        "sender_id": f"bot:{bot.id}",
        "sender_display_name": _compact_bot_name(bot),
        "compaction_origin": origin,
        "compaction_status": status,
        "assistant_turn_body": {"version": 1, "items": []},
        "envelope": _compaction_envelope(
            origin=origin,
            status=status,
            title=title,
            detail=detail,
            summary_text=summary_text,
            summary_len=summary_len,
            error=error,
            trigger_reason=trigger_reason,
            result_kind=result_kind,
        ),
    }
    if title:
        metadata["compaction_title"] = title
    if summary_len is not None:
        metadata["compaction_summary_len"] = summary_len
    if summary_text:
        metadata["compaction_summary_text"] = summary_text
    if trigger_reason:
        metadata["compaction_trigger_reason"] = trigger_reason
    if result_kind:
        metadata["compaction_result"] = result_kind
    if error:
        metadata["compaction_error"] = error[:500]
    return metadata


async def _find_latest_compaction_run(
    db: AsyncSession,
    session_id: uuid.UUID,
    *,
    origin: str | None = None,
    statuses: set[str] | None = None,
) -> Message | None:
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.desc())
        .limit(100)
    )
    for msg in result.scalars().all():
        meta = msg.metadata_ or {}
        if meta.get("kind") != COMPACTION_RUN_KIND:
            continue
        if origin is not None and meta.get("compaction_origin") != origin:
            continue
        if statuses is not None and meta.get("compaction_status") not in statuses:
            continue
        return msg
    return None


async def _insert_compaction_run_message(
    session_id: uuid.UUID,
    bot: BotConfig,
    *,
    origin: str,
    status: str,
    detail: str | None = None,
    trigger_reason: str | None = None,
) -> uuid.UUID | None:
    async with async_session() as db:
        session = await db.get(Session, session_id)
        if session is None:
            return None
        msg = Message(
            session_id=session_id,
            role="assistant",
            content="",
            metadata_=_compaction_metadata(
                bot=bot,
                origin=origin,
                status=status,
                detail=detail,
                trigger_reason=trigger_reason,
            ),
            created_at=datetime.now(timezone.utc),
        )
        db.add(msg)
        await db.commit()
        await db.refresh(msg)

        from app.services.channel_events import publish_message

        publish_message(_compaction_bus_key(session), msg)
        return msg.id


async def _update_compaction_run_message(
    message_id: uuid.UUID,
    bot: BotConfig,
    *,
    status: str,
    title: str | None = None,
    detail: str | None = None,
    summary_text: str | None = None,
    summary_len: int | None = None,
    error: str | None = None,
    trigger_reason: str | None = None,
    result_kind: str | None = None,
) -> None:
    async with async_session() as db:
        msg = await db.get(Message, message_id)
        if msg is None:
            return
        session = await db.get(Session, msg.session_id)
        if session is None:
            return
        meta = dict(msg.metadata_ or {})
        origin = str(meta.get("compaction_origin") or "manual")
        merged_trigger = trigger_reason or meta.get("compaction_trigger_reason")
        meta.update(
            _compaction_metadata(
                bot=bot,
                origin=origin,
                status=status,
                title=title,
                detail=detail,
                summary_text=summary_text,
                summary_len=summary_len,
                error=error,
                trigger_reason=merged_trigger,
                result_kind=result_kind,
            )
        )
        msg.metadata_ = meta
        flag_modified(msg, "metadata_")
        await db.commit()
        await db.refresh(msg)

        from app.services.channel_events import publish_message_updated

        publish_message_updated(_compaction_bus_key(session), msg)


def _manual_task_active(session_id: uuid.UUID | str) -> bool:
    task = _MANUAL_COMPACTION_TASKS.get(str(session_id))
    return task is not None and not task.done()


def _track_manual_task(session_id: uuid.UUID | str, task: asyncio.Task) -> None:
    key = str(session_id)
    _MANUAL_COMPACTION_TASKS[key] = task

    def _drop_done(_task: asyncio.Task) -> None:
        if _MANUAL_COMPACTION_TASKS.get(key) is _task:
            _MANUAL_COMPACTION_TASKS.pop(key, None)

    task.add_done_callback(_drop_done)


async def _run_memory_flush(
    channel: Channel,
    bot: BotConfig,
    session_id: uuid.UUID,
    messages: list[dict],
    correlation_id: uuid.UUID | None = None,
) -> str | None:
    """Run a dedicated memory flush — gives the bot a chance to save memories,
    knowledge, and persona before compaction archives older messages.

    Uses the agent loop with the bot's normal tools so save_memory,
    update_knowledge, update_persona, etc. are all available.
    """
    from app.agent.loop import run
    from app.services.prompt_resolution import resolve_prompt

    async with async_session() as db:
        # Memory scheme override: use file-based flush prompt
        if bot.memory_scheme == "workspace-files":
            prompt = settings.MEMORY_SCHEME_FLUSH_PROMPT or DEFAULT_MEMORY_SCHEME_FLUSH_PROMPT
        else:
            prompt = await resolve_prompt(
                workspace_id=str(channel.memory_flush_workspace_id) if channel.memory_flush_workspace_id else None,
                workspace_file_path=channel.memory_flush_workspace_file_path,
                template_id=str(channel.memory_flush_prompt_template_id) if channel.memory_flush_prompt_template_id else None,
                inline_prompt=channel.memory_flush_prompt or settings.MEMORY_FLUSH_DEFAULT_PROMPT,
                db=db,
            )

        # Grab existing summary so the flush knows what's already been captured
        session_row = await db.get(Session, session_id)
        existing_summary = session_row.summary if session_row else None

    # Build metadata header
    now = datetime.now()
    msg_count = sum(1 for m in messages if m.get("role") in ("user", "assistant"))
    header_lines = [
        "[MEMORY FLUSH — PRE-COMPACTION]",
        "This is an automated pre-compaction memory flush — not a user message.",
        f"Current time: {now.strftime('%Y-%m-%d %H:%M UTC')}",
        f"Channel: {channel.name}",
        f"Messages about to be archived: ~{msg_count}",
    ]

    # Inject existing summary so the bot knows what's already been captured
    if existing_summary:
        max_chars = settings.PREVIOUS_SUMMARY_INJECT_CHARS
        if len(existing_summary) > max_chars:
            truncated = _truncate_at_sentence(existing_summary, max_chars)
            header_lines.append(f"\nExisting conversation summary (may be truncated):\n{truncated}")
        else:
            header_lines.append(f"\nExisting conversation summary:\n{existing_summary}")

    header_lines.append("")
    full_prompt = "\n".join(header_lines) + prompt

    model = _get_memory_flush_model(bot, channel)
    provider_id = (
        channel.memory_flush_model_provider_id
        or settings.MEMORY_FLUSH_MODEL_PROVIDER_ID
    )
    provider_id = _resolve_provider_for_selected_model(
        model=model,
        bot=bot,
        explicit_provider_id=provider_id,
    )

    logger.info("Running memory flush for channel %s (session %s, model=%s)", channel.id, session_id, model)

    try:
        result = await run(
            messages=messages,
            bot=bot,
            user_message=full_prompt,
            session_id=session_id,
            client_id=channel.client_id,
            correlation_id=correlation_id,
            channel_id=channel.id,
            model_override=model,
            provider_id_override=provider_id,
            task_mode=True,
        )
        logger.info("Memory flush complete for channel %s", channel.id)
        return result.response
    except Exception:
        logger.warning("Memory flush failed for channel %s", channel.id, exc_info=True)
        return None


async def _flush_member_bots(
    channel: Channel,
    session_id: uuid.UUID,
    messages: list[dict],
) -> None:
    """Trigger memory flush for each member bot in a multi-bot channel.

    Each member bot with memory_scheme='workspace-files' gets flushed
    independently — they share the conversation history but write to their
    own workspace memory paths.
    """
    from app.agent.bots import get_bot as _get_bot
    from app.db.models import ChannelBotMember

    try:
        async with async_session() as db:
            from sqlalchemy import select
            rows = (await db.execute(
                select(ChannelBotMember.bot_id).where(ChannelBotMember.channel_id == channel.id)
            )).scalars().all()
    except Exception:
        logger.debug("Failed to load member bots for flush in channel %s", channel.id, exc_info=True)
        return

    if not rows:
        return

    for bot_id in rows:
        try:
            member_bot = _get_bot(bot_id)
        except Exception:
            continue
        if member_bot.memory_scheme != "workspace-files":
            continue
        try:
            await _run_memory_flush(channel, member_bot, session_id, messages, correlation_id=uuid.uuid4())
            logger.info("Member bot %s memory flush complete for channel %s", bot_id, channel.id)
        except Exception:
            logger.warning("Member bot %s memory flush failed for channel %s", bot_id, channel.id, exc_info=True)


def _stringify_message_content(content: Any) -> str:
    """Compaction prompts must be plain text; multimodal turns become short summaries."""
    if content is None:
        return ""
    if isinstance(content, list):
        parts: list[str] = []
        for p in content:
            if isinstance(p, dict) and p.get("type") == "text":
                parts.append(str(p.get("text", "")))
            elif isinstance(p, dict) and p.get("type") == "image_url":
                parts.append("[image]")
            elif isinstance(p, dict) and p.get("type") == "input_audio":
                parts.append("[audio]")
            elif isinstance(p, dict):
                parts.append(str(p)[:120])
        return " ".join(parts).strip() or "[multimodal message]"
    if isinstance(content, str):
        normalized = normalize_stored_content(content)
        if normalized is not content and isinstance(normalized, list):
            return _stringify_message_content(normalized)
        return content
    return str(content)

def _get_compaction_model(bot: BotConfig, channel: Channel | None = None) -> str:
    if channel and channel.compaction_model:
        return channel.compaction_model
    if bot.compaction_model:
        return bot.compaction_model
    if settings.COMPACTION_MODEL:
        return settings.COMPACTION_MODEL
    return bot.model


def _get_compaction_provider(bot: BotConfig, channel: Channel | None = None) -> str | None:
    """Read the stored provider_id for the compaction model.

    Cascade: explicit channel/bot/global provider → provider that owns the
    selected compaction model → bot's own provider.
    """
    model = _get_compaction_model(bot, channel)
    if channel and channel.compaction_model_provider_id:
        return channel.compaction_model_provider_id
    if bot.compaction_model_provider_id:
        return bot.compaction_model_provider_id
    if settings.COMPACTION_MODEL_PROVIDER_ID:
        return settings.COMPACTION_MODEL_PROVIDER_ID
    return _resolve_provider_for_selected_model(model=model, bot=bot)


def _get_compaction_interval(bot: BotConfig, channel: Channel | None = None) -> int:
    if channel and channel.compaction_interval is not None:
        return channel.compaction_interval
    if bot.compaction_interval is not None:
        return bot.compaction_interval
    return settings.COMPACTION_INTERVAL


def _get_compaction_keep_turns(bot: BotConfig, channel: Channel | None = None) -> int:
    if channel and channel.compaction_keep_turns is not None:
        return channel.compaction_keep_turns
    if bot.compaction_keep_turns is not None:
        return bot.compaction_keep_turns
    return settings.COMPACTION_KEEP_TURNS


def _is_compaction_enabled(bot: BotConfig, channel: Channel | None = None) -> bool:
    if channel is not None:
        return channel.context_compaction
    return bot.context_compaction


def _get_compaction_trigger_utilization_soft() -> float:
    return float(getattr(settings, "COMPACTION_TRIGGER_UTILIZATION_SOFT", 0.70) or 0.70)


def _get_compaction_live_history_max_ratio() -> float:
    return float(getattr(settings, "COMPACTION_LIVE_HISTORY_MAX_RATIO", 0.20) or 0.20)


def _get_compaction_live_history_max_tokens() -> int:
    return int(getattr(settings, "COMPACTION_LIVE_HISTORY_MAX_TOKENS", 60_000) or 60_000)


def _messages_for_summary(messages: list[dict]) -> list[dict]:
    """Build the message list to send to the summarization LLM.

    Passive messages are excluded from the alternating user/assistant turns.
    If there are any passive messages, prepend a 'Channel context' system block.

    Heartbeat-tagged messages are excluded entirely — they're internal automated
    checks that shouldn't pollute conversation summaries or section transcripts.

    Tool call messages are included as compact representations so the summarizer
    knows what the bot actually did, not just what it said.
    """
    passive_lines: list[str] = []
    active: list[dict] = []

    for m in messages:
        # Skip heartbeat messages — they're automated internal checks
        meta = m.get("_metadata") or {}
        if (
            meta.get("is_heartbeat")
            or meta.get("hidden")
            or meta.get("pipeline_step")
            or meta.get("kind") == COMPACTION_RUN_KIND
        ):
            continue
        role = m.get("role")
        content = m.get("content")
        tool_calls = m.get("tool_calls")
        is_passive = meta.get("passive", False)

        if role == "user" and is_passive:
            meta = m.get("_metadata") or {}
            sender = meta.get("sender_id") or "user"
            if content:
                passive_lines.append(f"  {sender}: {_stringify_message_content(content)}")
            continue

        if role == "assistant":
            parts: list[str] = []
            if content:
                parts.append(_stringify_message_content(content))
            if tool_calls:
                names = []
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    names.append(fn.get("name", "unknown"))
                parts.append(f"[Used tools: {', '.join(names)}]")
            if parts:
                active.append({"role": "assistant", "content": " ".join(parts)})
            continue

        if role == "tool":
            name = m.get("name") or m.get("_metadata", {}).get("tool_name", "tool")
            result_text = _stringify_message_content(content) if content else ""
            truncated = result_text[:200] + ("..." if len(result_text) > 200 else "")
            active.append({"role": "assistant", "content": f"[Tool result from {name}: {truncated}]"})
            continue

        if role == "user" and content and not is_passive:
            active.append({"role": role, "content": _stringify_message_content(content)})

    if passive_lines:
        ctx = "Channel context since last compaction:\n" + "\n".join(passive_lines)
        return [{"role": "system", "content": ctx}] + active
    return active


async def _generate_summary(
    conversation: list[dict],
    model: str,
    existing_summary: str | None,
    provider_id: str | None = None,
) -> tuple[str, str, dict]:
    """Call the LLM to produce a title and summary. Returns (title, summary, usage_info)."""
    prompt_messages: list[dict] = [{"role": "system", "content": settings.BASE_COMPACTION_PROMPT}]

    if existing_summary:
        prompt_messages.append({
            "role": "user",
            "content": f"Previous summary of earlier conversation:\n\n{existing_summary}",
        })

    from app.services.secret_registry import redact as _redact_secrets
    transcript = "\n".join(
        f"[{m['role'].upper()}]: {_redact_secrets(m['content'] or '')}" for m in conversation
    )
    prompt_messages.append({
        "role": "user",
        "content": f"Conversation to summarize:\n\n{transcript}",
    })

    from app.services.providers import get_llm_client
    response = await get_llm_client(provider_id).chat.completions.create(
        model=model,
        messages=prompt_messages,
        temperature=0.3,
    )

    usage = getattr(response, "usage", None)
    usage_info = {
        "tier": "normal",
        "prompt_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
        "completion_tokens": getattr(usage, "completion_tokens", None) if usage else None,
    }

    raw = response.choices[0].message.content or "{}"
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        raw = raw.rsplit("```", 1)[0]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Compaction LLM returned non-JSON: %s", raw[:200])
        return ("Conversation", raw, usage_info)

    title = data.get("title", "Conversation")
    summary = data.get("summary", raw)
    return (title, summary, usage_info)


def _build_transcript(conversation: list[dict]) -> str:
    """Build a plain-text transcript from raw messages. Deterministic, no LLM needed."""
    from app.services.secret_registry import redact as _redact_secrets
    lines = []
    for m in conversation:
        role = (m.get("role") or "unknown").upper()
        content = m.get("content") or ""
        if isinstance(content, list):
            # Multi-part content (e.g. vision messages) — extract text parts
            content = "\n".join(
                p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
            )
        lines.append(f"[{role}]: {_redact_secrets(content)}")
    return "\n".join(lines)


def _parse_section_response(raw: str) -> dict | None:
    """Parse LLM section response JSON, stripping markdown fences and surrounding text."""
    raw = raw.strip()
    # Try direct parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Strip markdown fences (```json ... ``` or ``` ... ```)
    if "```" in raw:
        # Find content between first ``` and last ```
        first = raw.find("```")
        # Skip the opening fence line
        fence_end = raw.find("\n", first)
        if fence_end == -1:
            fence_end = first + 3
        last = raw.rfind("```")
        if last > first:
            inner = raw[fence_end + 1:last].strip()
            try:
                return json.loads(inner)
            except json.JSONDecodeError:
                pass
    # Extract first JSON object by finding outermost { ... }
    start = raw.find("{")
    if start != -1:
        # Find matching closing brace
        depth = 0
        for i in range(start, len(raw)):
            if raw[i] == "{":
                depth += 1
            elif raw[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(raw[start:i + 1])
                    except json.JSONDecodeError:
                        pass
                    break
    return None


async def _generate_section(
    conversation: list[dict],
    model: str,
    provider_id: str | None = None,
    *,
    channel_id: uuid.UUID | None = None,
    correlation_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    bot_id: str | None = None,
    client_id: str | None = None,
) -> tuple[str, str, str, list[str], dict]:
    """LLM generates title/summary/tags; transcript is built deterministically.

    Three-tier escalation:
    1. Normal — depth-aware prompt with previous-context injection
    2. Aggressive — tighter prompt, lower max_tokens, temperature 0.1
    3. Deterministic — no LLM call, mechanical title/summary from first user message

    Returns (title, summary, transcript, tags, usage_info).
    usage_info contains: tier, prompt_tokens, completion_tokens.
    """
    transcript = _build_transcript(conversation)
    compaction_tier = "normal"

    # --- Query section count + previous section for this session ---
    section_count = 0
    prev_title: str | None = None
    prev_summary: str | None = None
    section_scope = None
    if session_id:
        section_scope = ConversationSection.session_id == session_id
    elif channel_id:
        section_scope = ConversationSection.channel_id == channel_id

    if section_scope is not None:
        async with async_session() as db:
            count_result = await db.execute(
                select(func.count())
                .select_from(ConversationSection)
                .where(section_scope)
            )
            section_count = count_result.scalar() or 0

            if section_count > 0:
                from sqlalchemy.orm import defer as _defer_col
                prev_result = await db.execute(
                    select(ConversationSection)
                    .where(section_scope)
                    .order_by(ConversationSection.sequence.desc())
                    .limit(1)
                    .options(_defer_col(ConversationSection.transcript), _defer_col(ConversationSection.embedding))
                )
                prev_section = prev_result.scalar_one_or_none()
                if prev_section:
                    prev_title = prev_section.title
                    prev_summary = prev_section.summary

    # --- Phase 1: Depth-aware prompt selection ---
    system_prompt = _select_section_prompt(section_count)

    # --- Phase 2: Previous-context continuity ---
    user_content = f"Conversation segment to archive:\n\n{transcript}"
    if prev_title and prev_summary:
        user_content = (
            f"Previous section covered: '{prev_title}' — {prev_summary}. "
            f"Do NOT repeat this. Focus on what is new, changed, or resolved since then.\n\n"
            f"{user_content}"
        )

    # --- Phase 3: Three-tier fallback escalation ---
    from app.services.providers import get_llm_client
    last_error: str | None = None

    # Tier 1: Normal
    try:
        response = await get_llm_client(provider_id).chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=1024,
            timeout=180.0,
        )
        raw = response.choices[0].message.content or "{}"
        usage = getattr(response, "usage", None)
        usage_info = {
            "tier": compaction_tier,
            "prompt_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
            "completion_tokens": getattr(usage, "completion_tokens", None) if usage else None,
        }
        data = _parse_section_response(raw)
        if data is not None:
            title = data.get("title", "Conversation")
            summary = data.get("summary", "")
            tags = data.get("tags", [])
            if not isinstance(tags, list):
                tags = []
            _log_compaction_tier(compaction_tier, correlation_id, session_id, bot_id, client_id)
            return (title, summary, transcript, tags, usage_info)
        # Non-JSON response — fall through to aggressive
        last_error = f"normal tier returned non-JSON: {raw[:200]}"
        logger.error(
            "Section LLM returned non-JSON (tier normal) model=%s provider=%s raw=%s",
            model, provider_id, raw[:500],
        )
    except Exception as exc:
        last_error = f"normal tier failed: {exc}"
        logger.error(
            "Section LLM failed (tier normal) model=%s provider=%s, escalating to aggressive",
            model, provider_id, exc_info=True,
        )

    # Tier 2: Aggressive
    compaction_tier = "aggressive"
    try:
        response = await get_llm_client(provider_id).chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SECTION_PROMPT_AGGRESSIVE},
                {"role": "user", "content": user_content},
            ],
            temperature=0.1,
            max_tokens=256,
            timeout=120.0,
        )
        raw = response.choices[0].message.content or "{}"
        usage = getattr(response, "usage", None)
        usage_info = {
            "tier": compaction_tier,
            "prompt_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
            "completion_tokens": getattr(usage, "completion_tokens", None) if usage else None,
        }
        data = _parse_section_response(raw)
        if data is not None:
            title = data.get("title", "Conversation")
            summary = data.get("summary", "")
            tags = data.get("tags", [])
            if not isinstance(tags, list):
                tags = []
            _log_compaction_tier(compaction_tier, correlation_id, session_id, bot_id, client_id)
            return (title, summary, transcript, tags, usage_info)
        last_error = f"aggressive tier returned non-JSON: {raw[:200]}"
        logger.error(
            "Section LLM returned non-JSON (tier aggressive) model=%s provider=%s raw=%s",
            model, provider_id, raw[:500],
        )
    except Exception as exc:
        last_error = f"aggressive tier failed: {exc}"
        logger.error(
            "Section LLM failed (tier aggressive) model=%s provider=%s, escalating to deterministic",
            model, provider_id, exc_info=True,
        )

    # Tier 3: Deterministic — no LLM call
    compaction_tier = "deterministic"
    first_user_msg = ""
    for m in conversation:
        if m.get("role") == "user":
            content = m.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
                )
            first_user_msg = content.strip()
            break
    det_title = (first_user_msg[:80] + "…") if len(first_user_msg) > 80 else (first_user_msg or "Conversation")
    _log_compaction_tier(compaction_tier, correlation_id, session_id, bot_id, client_id)
    usage_info = {
        "tier": compaction_tier,
        "prompt_tokens": None,
        "completion_tokens": None,
        "error": last_error or "Section LLM did not produce usable JSON.",
    }
    return (det_title, "Auto-archived conversation segment.", transcript, ["auto-truncated"], usage_info)


def _log_compaction_tier(
    tier: str,
    correlation_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    bot_id: str | None,
    client_id: str | None,
) -> None:
    """Fire-and-forget trace event recording which compaction tier was used."""
    if tier != "normal":
        logger.info("Compaction used tier '%s'", tier)
    if correlation_id:
        asyncio.create_task(_record_trace_event(
            correlation_id=correlation_id,
            session_id=session_id,
            bot_id=bot_id,
            client_id=client_id,
            event_type="compaction_tier",
            data={"compaction_tier": tier},
        ))


async def _regenerate_executive_summary(
    session_id: uuid.UUID,
    model: str,
    provider_id: str | None = None,
) -> str:
    """Query all sections for a session and produce a compact executive summary."""
    from sqlalchemy.orm import defer
    async with async_session() as db:
        result = await db.execute(
            select(ConversationSection)
            .where(ConversationSection.session_id == session_id)
            .order_by(ConversationSection.sequence)
            .options(defer(ConversationSection.transcript), defer(ConversationSection.embedding))
        )
        sections = result.scalars().all()

    if not sections:
        return ""

    section_lines = []
    for s in sections:
        section_lines.append(f"Section {s.sequence}: {s.title}\n  {s.summary}")

    prompt_messages = [
        {"role": "system", "content": settings.SECTION_EXECUTIVE_SUMMARY_PROMPT},
        {"role": "user", "content": "Section summaries:\n\n" + "\n\n".join(section_lines)},
    ]

    from app.services.providers import get_llm_client
    response = await get_llm_client(provider_id).chat.completions.create(
        model=model,
        messages=prompt_messages,
        temperature=0.3,
        max_tokens=2048,
        timeout=300.0,
    )

    return (response.choices[0].message.content or "").strip()


def _append_section_to_executive_summary(
    existing_summary: str | None,
    *,
    section_sequence: int,
    section_title: str,
    section_summary: str,
    section_tier: str,
) -> str:
    """Append only signal-bearing sections to the rolling executive summary."""
    existing = existing_summary or ""
    if section_tier == "deterministic" or section_summary == "Auto-archived conversation segment.":
        return existing
    section_line = f"[Section {section_sequence}] {section_title}: {section_summary}"
    if existing:
        return f"{existing}\n\n{section_line}"
    return section_line


async def _record_compaction_log(
    *,
    channel_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    bot_id: str,
    model: str,
    history_mode: str,
    tier: str,
    forced: bool = False,
    memory_flush: bool = False,
    messages_archived: int | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    duration_ms: int | None = None,
    section_id: uuid.UUID | None = None,
    error: str | None = None,
    correlation_id: uuid.UUID | None = None,
    flush_result: str | None = None,
) -> None:
    """Persist a compaction log row. Fire-and-forget safe."""
    try:
        async with async_session() as db:
            db.add(CompactionLog(
                channel_id=channel_id,
                session_id=session_id,
                bot_id=bot_id,
                model=model,
                history_mode=history_mode,
                tier=tier,
                forced=forced,
                memory_flush=memory_flush,
                messages_archived=messages_archived,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                duration_ms=duration_ms,
                section_id=section_id,
                error=error,
                correlation_id=correlation_id,
                flush_result=flush_result,
            ))
            await db.commit()
    except Exception:
        logger.warning("Failed to record compaction log", exc_info=True)


# ===== Cluster 8 compaction stage helpers =====

@dataclass(frozen=True)
class WatermarkPlan:
    oldest_kept_id: uuid.UUID
    oldest_kept_dt: datetime
    last_msg_id: uuid.UUID
    prev_watermark_dt: datetime | None


@dataclass(frozen=True)
class SectionPersistOutcome:
    section_id: uuid.UUID
    title: str
    summary: str
    msg_count: int
    usage: dict
    exec_summary: str


async def _run_memory_flush_phase(
    *,
    channel: Channel | None,
    bot: BotConfig,
    session_id: uuid.UUID,
    messages: list[dict],
    correlation_id: uuid.UUID | None,
) -> tuple[bool, str | None]:
    """Run pre-compaction memory flush (or heartbeat fallback). Errors are log-and-swallowed."""
    memory_flush_ran = False
    flush_result: str | None = None
    if channel and _resolve_memory_flush_enabled(bot, channel):
        try:
            flush_result = await _run_memory_flush(
                channel, bot, session_id, messages, correlation_id=correlation_id,
            )
            memory_flush_ran = True
        except Exception:
            logger.warning(
                "Memory flush failed before compaction for channel %s",
                channel.id, exc_info=True,
            )
        if channel:
            await _flush_member_bots(channel, session_id, messages)
    elif _resolve_trigger_heartbeat(channel) and channel:
        from app.services.heartbeat import trigger_channel_heartbeat
        try:
            await trigger_channel_heartbeat(channel.id, bot, correlation_id=correlation_id)
            logger.info("Triggered heartbeat before compaction for channel %s", channel.id)
        except Exception:
            logger.warning(
                "Failed to trigger heartbeat before compaction for channel %s",
                channel.id, exc_info=True,
            )
    return memory_flush_ran, flush_result


async def _compute_compaction_watermark(
    *,
    db: AsyncSession,
    session_id: uuid.UUID,
    keep_turns: int,
    prev_watermark_id: uuid.UUID | None,
) -> WatermarkPlan | None:
    """Compute oldest-kept message + watermark id. Returns None when nothing is compactable."""
    recent_user_msgs = await db.execute(
        select(Message.id)
        .where(Message.session_id == session_id)
        .where(Message.role == "user")
        .order_by(Message.created_at.desc())
        .limit(keep_turns)
    )
    user_msg_ids = recent_user_msgs.scalars().all()
    if not user_msg_ids:
        return None
    oldest_kept = await db.get(Message, user_msg_ids[-1])
    preceding = await db.execute(
        select(Message.id)
        .where(Message.session_id == session_id)
        .where(Message.created_at < oldest_kept.created_at)
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    last_msg_id = preceding.scalar()
    if last_msg_id is None:
        return None
    prev_watermark_dt: datetime | None = None
    if prev_watermark_id:
        prev_wm_msg = await db.get(Message, prev_watermark_id)
        if prev_wm_msg:
            prev_watermark_dt = prev_wm_msg.created_at
    return WatermarkPlan(
        oldest_kept_id=oldest_kept.id,
        oldest_kept_dt=oldest_kept.created_at,
        last_msg_id=last_msg_id,
        prev_watermark_dt=prev_watermark_dt,
    )


async def _persist_section_and_summary(
    *,
    db: AsyncSession,
    session_id: uuid.UUID,
    channel: Channel | None,
    bot: BotConfig,
    messages: list[dict],
    watermark: WatermarkPlan,
    correlation_id: uuid.UUID | None,
    client_id: str,
    model: str,
    existing_summary: str | None,
    autoflush_only: bool,
) -> SectionPersistOutcome:
    """Generate section, embed, write transcript, insert ConversationSection, prune, build exec summary.

    `autoflush_only=True` (forced path): caller owns the txn; helper calls `db.flush()` only.
    `autoflush_only=False` (stream path): helper opens its own internal commit and uses
    a separate session for `prune_sections`, matching pre-refactor stream behavior.
    """
    sec_title, sec_summary, sec_transcript, sec_tags, sec_usage = await _generate_section(
        messages, model, provider_id=_get_compaction_provider(bot, channel),
        channel_id=channel.id if channel else None,
        correlation_id=correlation_id,
        session_id=session_id,
        bot_id=bot.id,
        client_id=client_id,
    )
    msg_count = sum(1 for m in messages if m.get("role") in ("user", "assistant"))

    period_query = (
        select(func.min(Message.created_at), func.max(Message.created_at))
        .where(Message.session_id == session_id)
        .where(Message.created_at < watermark.oldest_kept_dt)
        .where(Message.role.in_(["user", "assistant"]))
    )
    if watermark.prev_watermark_dt is not None:
        period_query = period_query.where(Message.created_at > watermark.prev_watermark_dt)
    period_result = await db.execute(period_query)
    row = period_result.one_or_none()
    period_start, period_end = (row[0], row[1]) if row else (None, None)

    sec_embedding = None
    try:
        from app.agent.embeddings import embed_text
        sec_embedding = await embed_text(f"{sec_title}\n{sec_summary}")
    except Exception:
        logger.warning("Failed to embed section for session %s", session_id, exc_info=True)

    if session_id:
        max_seq_result = await db.execute(
            select(func.max(ConversationSection.sequence))
            .where(ConversationSection.session_id == session_id)
        )
        max_seq = max_seq_result.scalar() or 0
    else:
        max_seq = 0

    transcript_path = None
    history_dir = _get_history_dir(bot, channel)
    ws_root = _get_channel_ws_root(bot) if channel else _get_workspace_root(bot)
    channel_id = channel.id if channel else None
    if settings.HISTORY_WRITE_FILES and history_dir and ws_root:
        try:
            transcript_path = _write_section_file(
                history_dir, max_seq + 1, sec_title, sec_summary,
                sec_transcript, period_start, period_end, msg_count,
                sec_tags or [], ws_root,
            )
        except Exception:
            logger.warning("Failed to write section file for session %s", session_id, exc_info=True)

    section = ConversationSection(
        channel_id=channel_id,
        session_id=session_id,
        sequence=max_seq + 1,
        title=sec_title,
        summary=sec_summary,
        transcript=sec_transcript,
        transcript_path=transcript_path,
        message_count=msg_count,
        chunk_size=msg_count,
        period_start=period_start,
        period_end=period_end,
        embedding=sec_embedding,
        tags=sec_tags or None,
    )
    db.add(section)
    if autoflush_only:
        await db.flush()
    else:
        await db.commit()

    if channel_id:
        try:
            if autoflush_only:
                pruned = await prune_sections(channel_id, db=db)
            else:
                pruned = await prune_sections(channel_id)
            if pruned:
                logger.info("Pruned %d old sections from channel %s", pruned, channel_id)
        except Exception:
            logger.warning("Section retention pruning failed for channel %s", channel_id, exc_info=True)

    exec_summary = _append_section_to_executive_summary(
        existing_summary,
        section_sequence=max_seq + 1,
        section_title=sec_title,
        section_summary=sec_summary,
        section_tier=str(sec_usage.get("tier") or "normal"),
    )

    _EXEC_SUMMARY_REGEN_CHARS = 2000
    _EXEC_SUMMARY_REGEN_SECTIONS = 15
    section_count = exec_summary.count("[Section ")
    if len(exec_summary) > _EXEC_SUMMARY_REGEN_CHARS or section_count >= _EXEC_SUMMARY_REGEN_SECTIONS:
        logger.info(
            "Executive summary exceeded threshold (%d chars, %d sections) — regenerating for session %s",
            len(exec_summary), section_count, session_id,
        )
        try:
            exec_summary = await _regenerate_executive_summary(
                session_id, model, provider_id=_get_compaction_provider(bot, channel),
            )
        except Exception:
            logger.warning("Failed to regenerate executive summary for session %s", session_id, exc_info=True)

    return SectionPersistOutcome(
        section_id=section.id,
        title=sec_title,
        summary=sec_summary,
        msg_count=msg_count,
        usage=sec_usage,
        exec_summary=exec_summary,
    )


async def _persist_session_compaction_state(
    *,
    db: AsyncSession,
    session_id: uuid.UUID,
    title: str,
    summary: str,
    watermark_id: uuid.UUID,
) -> None:
    """Update Session.title/summary/summary_message_id. Does not commit."""
    await db.execute(
        update(Session)
        .where(Session.id == session_id)
        .values(title=title, summary=summary, summary_message_id=watermark_id)
    )


def _record_compaction_completion(
    *,
    correlation_id: uuid.UUID | None,
    session_id: uuid.UUID,
    bot_id: str,
    client_id: str,
    channel_id: uuid.UUID | None,
    title: str,
    summary: str,
    history_mode: str,
    model: str,
    tier: str,
    forced: bool,
    memory_flush: bool,
    messages_archived: int,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    duration_ms: int,
    section_id: uuid.UUID | None,
    flush_result: str | None,
    error: str | None = None,
) -> None:
    """Fire-and-forget compaction_done trace + compaction log row insert."""
    trace_data: dict[str, Any] = {
        "title": title,
        "summary_len": len(summary),
        "history_mode": history_mode,
    }
    if forced:
        trace_data = {"forced": True, **trace_data}
    asyncio.create_task(_record_trace_event(
        correlation_id=correlation_id,
        session_id=session_id,
        bot_id=bot_id,
        client_id=client_id,
        event_type="compaction_done",
        data=trace_data,
    ))
    asyncio.create_task(_record_compaction_log(
        channel_id=channel_id,
        session_id=session_id,
        bot_id=bot_id,
        model=model,
        history_mode=history_mode,
        tier=tier,
        forced=forced,
        memory_flush=memory_flush,
        messages_archived=messages_archived,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        duration_ms=duration_ms,
        section_id=section_id,
        error=error,
        correlation_id=correlation_id,
        flush_result=flush_result,
    ))


# ===== End Cluster 8 helpers =====


async def run_compaction_stream(
    session_id: uuid.UUID, bot: BotConfig, messages: list[dict],
    *,
    correlation_id: uuid.UUID | None = None,
    budget_triggered: bool = False,
    trigger_reason: str | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """If compaction is due, run memory/knowledge phase (yielding tool events) then summarize.
    Yields compaction_start, then tool_start/tool_result (with compaction=True), then compaction_done.
    If compaction is not due, yields nothing.
    """
    # Pre-flight: load session/channel + check enabled.
    channel: Channel | None = None
    async with async_session() as db:
        session = await db.get(Session, session_id)
        if session is None:
            return
        if session.channel_id:
            channel = await db.get(Channel, session.channel_id)

    if not _is_compaction_enabled(bot, channel):
        return

    # Eligibility check (interval vs unread user-message count).
    interval = _get_compaction_interval(bot, channel)
    async with async_session() as db:
        session = await db.get(Session, session_id)
        if session is None:
            return
        watermark_filter = (
            Message.created_at > (
                select(Message.created_at)
                .where(Message.id == session.summary_message_id)
                .scalar_subquery()
            )
            if session.summary_message_id
            else True
        )
        user_count_result = await db.execute(
            select(func.count())
            .where(Message.session_id == session_id)
            .where(Message.role == "user")
            .where(watermark_filter)
        )
        user_msg_count = user_count_result.scalar() or 0

    if user_msg_count < interval and not budget_triggered:
        logger.info(
            "Compaction not needed for %s (%d/%d turns)",
            session_id, user_msg_count, interval,
        )
        return
    if budget_triggered:
        logger.info(
            "Budget-triggered early compaction for session %s (%s)",
            session_id,
            trigger_reason or "budget",
        )

    # Reload session for client_id / existing summary / prev watermark.
    client_id: str
    existing_summary: str | None
    prev_watermark_id: uuid.UUID | None = None
    async with async_session() as db:
        session = await db.get(Session, session_id)
        if session is None:
            return
        client_id = session.client_id
        existing_summary = session.summary
        prev_watermark_id = session.summary_message_id

    keep_turns = _get_compaction_keep_turns(bot, channel)
    model = _get_compaction_model(bot, channel)
    history_mode = _get_history_mode(bot, channel)

    # Compute watermark + load summary window before emitting compaction_start
    # so no-op budget triggers do not render transient compaction cards.
    async with async_session() as db:
        watermark = await _compute_compaction_watermark(
            db=db, session_id=session_id, keep_turns=keep_turns,
            prev_watermark_id=prev_watermark_id,
        )
        if watermark is None:
            logger.debug("Nothing to compact for %s", session_id)
            return
        summary_stmt = (
            select(Message)
            .where(Message.session_id == session_id)
            .where(Message.created_at < watermark.oldest_kept_dt)
            .order_by(Message.created_at)
        )
        if watermark.prev_watermark_dt is not None:
            summary_stmt = summary_stmt.where(Message.created_at > watermark.prev_watermark_dt)
        summary_result = await db.execute(summary_stmt)
        summary_window = [_msg_to_dict(m) for m in summary_result.scalars().all()]

    to_summarize = _messages_for_summary(summary_window)
    if not to_summarize:
        logger.debug("No turns to summarize for %s", session_id)
        return

    logger.info("Starting compaction for session %s", session_id)
    yield {
        "type": "compaction_start",
        "trigger_reason": trigger_reason,
        "budget_triggered": budget_triggered,
    }

    asyncio.create_task(_record_trace_event(
        correlation_id=correlation_id,
        session_id=session_id,
        bot_id=bot.id,
        client_id=client_id,
        event_type="compaction_start",
        data={
            "interval": _get_compaction_interval(bot, channel),
            "keep_turns": _get_compaction_keep_turns(bot, channel),
            "trigger_reason": trigger_reason,
        },
    ))

    memory_flush_ran, flush_result = await _run_memory_flush_phase(
        channel=channel, bot=bot, session_id=session_id,
        messages=messages, correlation_id=correlation_id,
    )

    _t0 = _time.monotonic()
    try:
        section_id: uuid.UUID | None = None
        if history_mode in ("structured", "file"):
            async with async_session() as db:
                outcome = await _persist_section_and_summary(
                    db=db, session_id=session_id, channel=channel, bot=bot,
                    messages=to_summarize, watermark=watermark,
                    correlation_id=correlation_id, client_id=client_id,
                    model=model, existing_summary=existing_summary,
                    autoflush_only=False,
                )
            title = outcome.title
            summary = outcome.exec_summary
            messages_archived = outcome.msg_count
            usage = outcome.usage
            section_id = outcome.section_id
        else:
            title, summary, sum_usage = await _generate_summary(
                to_summarize, model, existing_summary, provider_id=_get_compaction_provider(bot, channel),
            )
            messages_archived = len(to_summarize)
            usage = sum_usage

        async with async_session() as db:
            await _persist_session_compaction_state(
                db=db, session_id=session_id,
                title=title, summary=summary,
                watermark_id=watermark.last_msg_id,
            )
            await db.commit()

        _duration_ms = int((_time.monotonic() - _t0) * 1000)
        logger.info(
            "Compaction complete for %s: mode=%s, title=%r, summary_len=%d",
            session_id, history_mode, title, len(summary),
        )
        _record_compaction_completion(
            correlation_id=correlation_id, session_id=session_id, bot_id=bot.id,
            client_id=client_id, channel_id=channel.id if channel else None,
            title=title, summary=summary, history_mode=history_mode, model=model,
            tier=usage.get("tier", "normal"), forced=False,
            memory_flush=memory_flush_ran, messages_archived=messages_archived,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            duration_ms=_duration_ms, section_id=section_id,
            flush_result=flush_result,
            error=usage.get("error"),
        )
        yield {"type": "compaction_done", "title": title, "summary": summary}
    except Exception as exc:
        logger.exception("Compaction failed for session %s", session_id)
        yield {"type": "compaction_failed", "error": str(exc)}


async def _drain_compaction(
    session_id: uuid.UUID, bot: BotConfig, messages: list[dict],
    correlation_id: uuid.UUID | None = None,
    budget_triggered: bool = False,
    trigger_reason: str | None = None,
) -> None:
    """Drain run_compaction_stream (memory phase if any + summary). Used by fire-and-forget path."""
    compacted = False
    started = False
    terminal = False
    run_message_id: uuid.UUID | None = None
    try:
        async with async_session() as db:
            manual = await _find_latest_compaction_run(
                db,
                session_id,
                origin="manual",
                statuses=_ACTIVE_MANUAL_COMPACTION_STATUSES,
            )
            if manual is not None:
                logger.info(
                    "Skipping auto compaction for %s because manual compaction is %s",
                    session_id,
                    (manual.metadata_ or {}).get("compaction_status"),
                )
                return
        async for event in run_compaction_stream(
            session_id,
            bot,
            messages,
            correlation_id=correlation_id,
            budget_triggered=budget_triggered,
            trigger_reason=trigger_reason,
        ):
            if not isinstance(event, dict):
                continue
            event_type = event.get("type")
            if event_type == "compaction_start":
                started = True
                run_message_id = await _insert_compaction_run_message(
                    session_id,
                    bot,
                    origin="auto",
                    status="running",
                    detail="Automatic compaction started after the latest response.",
                    trigger_reason=trigger_reason,
                )
            elif event_type == "compaction_done":
                compacted = True
                terminal = True
                if run_message_id:
                    title = str(event.get("title") or "Compacted conversation")
                    summary_text = str(event.get("summary") or "") or None
                    await _update_compaction_run_message(
                        run_message_id,
                        bot,
                        status="completed",
                        title=title,
                        summary_text=summary_text,
                        summary_len=len(summary_text) if summary_text else None,
                        detail="Older conversation history was summarized automatically.",
                        result_kind="compacted",
                        trigger_reason=trigger_reason,
                    )
            elif event_type == "compaction_failed" and run_message_id:
                terminal = True
                await _update_compaction_run_message(
                    run_message_id,
                    bot,
                    status="failed",
                    error=str(event.get("error") or "Compaction failed."),
                    trigger_reason=trigger_reason,
                    result_kind="failed",
                )
    except Exception:
        logger.exception("Background compaction failed for session %s", session_id)
        terminal = True
        if run_message_id:
            await _update_compaction_run_message(
                run_message_id,
                bot,
                status="failed",
                error="Background compaction failed.",
                trigger_reason=trigger_reason,
                result_kind="failed",
            )

    if started and run_message_id and not compacted and not terminal:
        await _update_compaction_run_message(
            run_message_id,
            bot,
            status="completed",
            detail="Nothing was eligible for compaction.",
            trigger_reason=trigger_reason,
            result_kind="noop",
        )


def _should_trigger_budget_compaction(
    budget_utilization: float | None,
    budget_snapshot: dict[str, Any] | None,
    *,
    trigger_utilization_soft: float | None = None,
    live_history_max_ratio: float | None = None,
) -> tuple[bool, str | None]:
    """Return whether early compaction should fire, plus the reason."""
    trigger_utilization_soft = trigger_utilization_soft if trigger_utilization_soft is not None else _get_compaction_trigger_utilization_soft()
    live_history_max_ratio = live_history_max_ratio if live_history_max_ratio is not None else _get_compaction_live_history_max_ratio()
    live_tokens = int((budget_snapshot or {}).get("live_history_tokens") or 0)
    live_util = (budget_snapshot or {}).get("live_history_utilization")
    try:
        live_util_f = float(live_util) if live_util is not None else None
    except (TypeError, ValueError):
        live_util_f = None

    if live_tokens >= _get_compaction_live_history_max_tokens():
        return True, "live_history_tokens"
    if live_util_f is not None and live_util_f >= live_history_max_ratio:
        return True, "live_history_ratio"
    if budget_utilization is not None and budget_utilization > trigger_utilization_soft:
        return True, "total_utilization"
    return False, None


async def _resolve_context_pressure_thresholds(session_id: uuid.UUID) -> tuple[float, float]:
    trigger_util = _get_compaction_trigger_utilization_soft()
    live_ratio = _get_compaction_live_history_max_ratio()
    try:
        async with async_session() as db:
            session = await db.get(Session, session_id)
            channel = await db.get(Channel, session.channel_id) if session and session.channel_id else None
            cfg = (channel.config or {}) if channel is not None else {}
        if cfg.get("native_context_compaction_utilization") is not None:
            trigger_util = float(cfg.get("native_context_compaction_utilization"))
    except Exception:
        logger.debug("Failed to resolve context pressure thresholds", exc_info=True)
    return trigger_util, live_ratio


async def _maybe_insert_context_pressure_warning(
    session_id: uuid.UUID,
    bot: BotConfig,
    *,
    budget_utilization: float | None,
    budget_snapshot: dict[str, Any] | None,
) -> None:
    session: Session | None = None
    trigger_util, live_ratio = await _resolve_context_pressure_thresholds(session_id)
    warning_util = trigger_util * 0.85
    warning_live_ratio = live_ratio * 0.85
    async with async_session() as db:
        session = await db.get(Session, session_id)
        if session is None:
            return
        channel = await db.get(Channel, session.channel_id) if session.channel_id else None
        cfg = (channel.config or {}) if channel is not None else {}
        try:
            warning_util = float(cfg.get("native_context_warning_utilization") or warning_util)
        except (TypeError, ValueError):
            pass

    live_util = (budget_snapshot or {}).get("live_history_utilization")
    try:
        live_util_f = float(live_util) if live_util is not None else None
    except (TypeError, ValueError):
        live_util_f = None
    pressure = (
        (budget_utilization is not None and budget_utilization >= warning_util)
        or (live_util_f is not None and live_util_f >= warning_live_ratio)
    )
    if not pressure:
        return

    async with async_session() as db:
        existing = await _find_active_compaction_message(
            db,
            session_id,
            origin="auto",
            statuses={"warning", "running", "queued"},
        )
    if existing is not None:
        return
    await _insert_compaction_run_message(
        session_id,
        bot,
        origin="auto",
        status="warning",
        detail=(
            "This chat is approaching the automatic compaction threshold. "
            "Recent conversation will stay live; older turns may be archived into sections after a future turn."
        ),
        trigger_reason="context_pressure_warning",
    )


def maybe_compact(
    session_id: uuid.UUID, bot: BotConfig, messages: list[dict],
    correlation_id: uuid.UUID | None = None,
    budget_utilization: float | None = None,
    budget_snapshot: dict[str, Any] | None = None,
) -> None:
    """If compaction is due, run it in the background (memory phase + summary). Non-blocking.

    Early compaction fires when replayable live history grows too large, or as a
    fallback when overall prompt utilization breaches the soft threshold.
    """
    _budget_triggered, _trigger_reason = _should_trigger_budget_compaction(
        budget_utilization,
        budget_snapshot,
    )
    live_util = (budget_snapshot or {}).get("live_history_utilization")
    try:
        live_util_f = float(live_util) if live_util is not None else None
    except (TypeError, ValueError):
        live_util_f = None
    warn_pressure = (
        (
            budget_utilization is not None
            and _get_compaction_trigger_utilization_soft() * 0.85 <= budget_utilization < _get_compaction_trigger_utilization_soft()
        )
        or (
            live_util_f is not None
            and _get_compaction_live_history_max_ratio() * 0.85 <= live_util_f < _get_compaction_live_history_max_ratio()
        )
    )
    if not _budget_triggered and warn_pressure:
        asyncio.create_task(_maybe_insert_context_pressure_warning(
            session_id,
            bot,
            budget_utilization=budget_utilization,
            budget_snapshot=budget_snapshot,
        ))
    asyncio.create_task(_drain_compaction(
        session_id, bot, messages,
        correlation_id=correlation_id,
        budget_triggered=_budget_triggered,
        trigger_reason=_trigger_reason,
    ))


async def _run_manual_compaction_operation(
    session_id: uuid.UUID,
    bot: BotConfig,
    message_id: uuid.UUID,
) -> None:
    try:
        async with async_session() as db:
            title, summary = await run_compaction_forced(session_id, bot, db)
            await db.commit()
        await _update_compaction_run_message(
            message_id,
            bot,
            status="completed",
            title=title,
            detail="Manual compaction completed.",
            summary_text=summary,
            summary_len=len(summary),
            result_kind="compacted",
        )
    except Exception as exc:
        if _is_noop_compaction_error(exc):
            await _update_compaction_run_message(
                message_id,
                bot,
                status="completed",
                detail=str(exc),
                result_kind="noop",
            )
            return
        logger.exception("Manual compaction failed for session %s", session_id)
        await _update_compaction_run_message(
            message_id,
            bot,
            status="failed",
            error=str(exc) or "Manual compaction failed.",
            result_kind="failed",
        )


def _start_manual_compaction_task(
    session_id: uuid.UUID,
    bot: BotConfig,
    message_id: uuid.UUID,
) -> None:
    if _manual_task_active(session_id):
        return
    task = asyncio.create_task(_run_manual_compaction_operation(session_id, bot, message_id))
    _track_manual_task(session_id, task)


async def request_manual_compaction(
    session_id: uuid.UUID,
    bot: BotConfig,
    db: AsyncSession,
) -> dict[str, str]:
    """Persist a manual compaction request and run it when the session is idle."""
    from app.services import session_locks

    session = await db.get(Session, session_id)
    if session is None:
        raise ValueError("Session not found")

    active = await _find_latest_compaction_run(
        db,
        session_id,
        origin="manual",
        statuses=_ACTIVE_MANUAL_COMPACTION_STATUSES,
    )
    if active is not None:
        active_status = str((active.metadata_ or {}).get("compaction_status") or "running")
        if active_status == "running" and not _manual_task_active(session_id):
            _start_manual_compaction_task(session_id, bot, active.id)
        if active_status == "queued" and not session_locks.is_active(session_id):
            await _update_compaction_run_message(
                active.id,
                bot,
                status="running",
                detail="Manual compaction started.",
            )
            _start_manual_compaction_task(session_id, bot, active.id)
            return {"status": "started", "message_id": str(active.id)}
        return {
            "status": "queued" if active_status == "queued" else "started",
            "message_id": str(active.id),
        }

    if session_locks.is_active(session_id):
        message_id = await _insert_compaction_run_message(
            session_id,
            bot,
            origin="manual",
            status="queued",
            detail="A response is still running. Compaction will start after it finishes.",
        )
        return {"status": "queued", "message_id": str(message_id or "")}

    message_id = await _insert_compaction_run_message(
        session_id,
        bot,
        origin="manual",
        status="running",
        detail="Manual compaction started.",
    )
    if message_id:
        _start_manual_compaction_task(session_id, bot, message_id)
    return {"status": "started", "message_id": str(message_id or "")}


def drain_queued_manual_compaction(session_id: uuid.UUID | str) -> None:
    """Schedule queued manual compaction after the active turn releases its lock."""
    try:
        key = str(session_id)
        if _manual_task_active(key):
            return
        loop = asyncio.get_running_loop()
        task = loop.create_task(_drain_queued_manual_compaction(uuid.UUID(key)))
        _track_manual_task(key, task)
    except RuntimeError:
        logger.debug("No running loop to drain queued compaction for %s", session_id)
    except Exception:
        logger.warning("Failed to schedule queued compaction drain for %s", session_id, exc_info=True)


async def _drain_queued_manual_compaction(session_id: uuid.UUID) -> None:
    from app.agent.bots import get_bot
    from app.services import session_locks

    if session_locks.is_active(session_id):
        return
    async with async_session() as db:
        session = await db.get(Session, session_id)
        if session is None:
            return
        bot = get_bot(session.bot_id)
        queued = await _find_latest_compaction_run(
            db,
            session_id,
            origin="manual",
            statuses={"queued"},
        )
        if queued is None:
            return
        message_id = queued.id

    await _update_compaction_run_message(
        message_id,
        bot,
        status="running",
        detail="Manual compaction started after the active response finished.",
    )
    await _run_manual_compaction_operation(session_id, bot, message_id)


async def run_compaction_forced(
    session_id: uuid.UUID, bot: BotConfig, db: AsyncSession
) -> tuple[str, str]:
    """Run full compaction (memory phase if enabled + summary) on the entire session.
    Used by POST /sessions/{id}/summarize. Returns (title, summary). Caller must commit db.
    """
    session = await db.get(Session, session_id)
    if session is None:
        raise ValueError("Session not found")

    channel: Channel | None = None
    if session.channel_id:
        channel = await db.get(Channel, session.channel_id)

    client_id = session.client_id
    existing_summary = session.summary
    prev_watermark_id = session.summary_message_id
    correlation_id = uuid.uuid4()

    asyncio.create_task(_record_trace_event(
        correlation_id=correlation_id,
        session_id=session_id,
        bot_id=bot.id,
        client_id=client_id,
        event_type="compaction_start",
        data={"forced": True, "interval": _get_compaction_interval(bot, channel), "keep_turns": _get_compaction_keep_turns(bot, channel)},
    ))

    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at)
    )
    all_msgs = result.scalars().all()
    messages = [_msg_to_dict(m) for m in all_msgs]
    messages = [m for m in messages if m.get("role") != "system"]
    conversation = _messages_for_summary(messages)
    if not conversation:
        raise ValueError("No conversation content to summarize")

    memory_flush_ran, flush_result = await _run_memory_flush_phase(
        channel=channel, bot=bot, session_id=session_id,
        messages=messages, correlation_id=correlation_id,
    )

    _t0 = _time.monotonic()
    model = _get_compaction_model(bot, channel)
    history_mode = _get_history_mode(bot, channel)
    keep_turns = _get_compaction_keep_turns(bot, channel)

    watermark = await _compute_compaction_watermark(
        db=db, session_id=session_id, keep_turns=keep_turns,
        prev_watermark_id=prev_watermark_id,
    )
    if watermark is None:
        # Distinguish "no user messages" from "all in keep window" to preserve
        # the legacy ValueError messages (matched by _is_noop_compaction_error).
        any_user = await db.execute(
            select(func.count())
            .where(Message.session_id == session_id)
            .where(Message.role == "user")
        )
        if (any_user.scalar() or 0) == 0:
            raise ValueError("No user messages found in session")
        raise ValueError("All messages within keep window, nothing to compact")

    section_id: uuid.UUID | None = None
    if history_mode in ("structured", "file"):
        outcome = await _persist_section_and_summary(
            db=db, session_id=session_id, channel=channel, bot=bot,
            messages=conversation, watermark=watermark,
            correlation_id=correlation_id, client_id=client_id,
            model=model, existing_summary=existing_summary,
            autoflush_only=True,
        )
        title = outcome.title
        summary = outcome.exec_summary
        messages_archived = outcome.msg_count
        usage = outcome.usage
        section_id = outcome.section_id
    else:
        title, summary, sum_usage = await _generate_summary(
            conversation, model, existing_summary, provider_id=_get_compaction_provider(bot, channel),
        )
        messages_archived = len(conversation)
        usage = sum_usage

    await _persist_session_compaction_state(
        db=db, session_id=session_id,
        title=title, summary=summary,
        watermark_id=watermark.last_msg_id,
    )

    _duration_ms = int((_time.monotonic() - _t0) * 1000)
    _record_compaction_completion(
        correlation_id=correlation_id, session_id=session_id, bot_id=bot.id,
        client_id=client_id, channel_id=session.channel_id,
        title=title, summary=summary, history_mode=history_mode, model=model,
        tier=usage.get("tier", "normal"), forced=True,
        memory_flush=memory_flush_ran, messages_archived=messages_archived,
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        duration_ms=_duration_ms, section_id=section_id,
        flush_result=flush_result,
        error=usage.get("error"),
    )
    return (title, summary)


# ---------------------------------------------------------------------------
# Eligible message counting (used by backfill + admin API)
# ---------------------------------------------------------------------------

async def count_eligible_messages(channel_id: uuid.UUID) -> int:
    """Count user+assistant messages eligible for sectioning (up to watermark).

    This mirrors the message loading logic in backfill_sections — loads all
    non-system messages across all sessions up to the active session's watermark,
    then counts only user+assistant (non-passive) messages.
    """
    async with async_session() as db:
        channel = await db.get(Channel, channel_id)
        if not channel or not channel.active_session_id:
            return 0

        session = await db.get(Session, channel.active_session_id)
        if not session:
            return 0

        watermark_filter = True  # type: ignore[assignment]
        if session.summary_message_id:
            watermark_msg = await db.get(Message, session.summary_message_id)
            if watermark_msg:
                watermark_filter = Message.created_at <= watermark_msg.created_at

        result = await db.execute(
            select(Message)
            .join(Session, Message.session_id == Session.id)
            .where(Session.channel_id == channel_id)
            .where(watermark_filter)
            .where(Message.role.in_(["user", "assistant"]))
            .order_by(Message.created_at)
        )
        all_msgs = result.scalars().all()

    count = 0
    for m in all_msgs:
        is_passive = (m.metadata_ or {}).get("passive", False)
        if m.role == "user" and is_passive:
            continue
        # Match _messages_for_summary: skip messages with no content
        if not m.content:
            continue
        count += 1
    return count


# ---------------------------------------------------------------------------
# Fire-and-forget backfill (survives browser refresh)
# ---------------------------------------------------------------------------
_BACKFILL_JOBS: dict[str, dict] = {}


async def _drain_backfill(
    channel_id: uuid.UUID,
    task_id: str,
    chunk_size: int,
    model: str | None,
    provider_id: str | None,
    history_mode: str | None,
    clear_existing: bool = False,
) -> None:
    """Run backfill_sections in the background, tracking progress in _BACKFILL_JOBS."""
    state: dict = {"status": "running", "sections_created": 0, "total_chunks": 0, "error": None}
    _BACKFILL_JOBS[task_id] = state
    try:
        async for event in backfill_sections(
            channel_id, chunk_size=chunk_size, model=model,
            provider_id=provider_id, history_mode=history_mode,
            clear_existing=clear_existing,
        ):
            if event["type"] == "backfill_progress":
                state.update(
                    sections_created=event["section"],
                    total_chunks=event["total_chunks"],
                    current_title=event.get("title"),
                )
            elif event["type"] == "backfill_done":
                state.update(
                    status="complete",
                    sections_created=event["sections_created"],
                    executive_summary=event.get("executive_summary"),
                )
    except Exception as e:
        state.update(status="failed", error=str(e))
        logger.exception("Backfill failed for channel %s", channel_id)


async def backfill_sections(
    channel_id: uuid.UUID,
    chunk_size: int = 50,
    model: str | None = None,
    provider_id: str | None = None,
    history_mode: str | None = None,
    clear_existing: bool = False,
) -> AsyncGenerator[dict, None]:
    """Retroactively chunk the channel's active session into ConversationSection rows.

    Yields progress dicts as JSON-line events. Only processes messages on the
    active session at or before that session's watermark (summary_message_id).

    If clear_existing=True, deletes existing sections for the active session first.
    """
    from app.agent.bots import get_bot

    # 1. Load channel + active session, resolve history_mode
    async with async_session() as db:
        channel = await db.get(Channel, channel_id)
        if not channel:
            raise ValueError("Channel not found")

        if not channel.active_session_id:
            raise ValueError("Channel has no active session")

        session = await db.get(Session, channel.active_session_id)
        if not session:
            raise ValueError("Active session not found")

        bot = get_bot(channel.bot_id)
        effective_mode = history_mode or _get_history_mode(bot, channel)
        if effective_mode not in ("file", "structured"):
            raise ValueError(f"Channel must be in file or structured mode (got '{effective_mode}')")

        effective_model = model or _get_compaction_model(bot, channel)
        effective_provider = provider_id or _get_compaction_provider(bot, channel)

        # 2. Load messages from the active session only.
        watermark_filter = True  # type: ignore[assignment]
        if session.summary_message_id:
            watermark_msg = await db.get(Message, session.summary_message_id)
            if watermark_msg:
                watermark_filter = Message.created_at <= watermark_msg.created_at

        result = await db.execute(
            select(Message)
            .where(Message.session_id == session.id)
            .where(watermark_filter)
            .order_by(Message.created_at)
        )
        all_msgs = result.scalars().all()

    if not all_msgs:
        raise ValueError("No messages to backfill")

    # 3. Convert to dicts, filter, and build conversation for summarization.
    # Also build a parallel timestamp list from user/assistant messages only
    # (matching what _messages_for_summary keeps as "active" messages).
    messages = [_msg_to_dict(m) for m in all_msgs]
    messages = [m for m in messages if m.get("role") != "system"]

    # Build active_timestamps aligned with what _messages_for_summary keeps
    # as countable messages (user/assistant/tool — excluding passive users and
    # heartbeats).  Tool messages become "assistant" in the conversation, so
    # they must be counted here too for period index alignment.
    active_timestamps: list[datetime] = []
    for orig_msg in all_msgs:
        if orig_msg.role == "system":
            continue
        meta = orig_msg.metadata_ or {}
        if meta.get("is_heartbeat"):
            continue
        is_passive = meta.get("passive", False)
        if orig_msg.role == "user" and is_passive:
            continue
        if orig_msg.role in ("user", "assistant", "tool"):
            active_timestamps.append(orig_msg.created_at)

    conversation = _messages_for_summary(messages)

    if not conversation:
        raise ValueError("No conversation content to backfill")

    # 4. Clear existing sections or skip already-covered messages for resume
    if clear_existing:
        async with async_session() as db:
            from sqlalchemy import delete as sa_delete
            deleted = await db.execute(
                sa_delete(ConversationSection)
                .where(ConversationSection.session_id == session.id)
            )
            await db.commit()
            logger.info("Cleared %d existing sections for channel %s", deleted.rowcount, channel_id)
        # Also clear history files on disk
        history_dir = _get_history_dir(bot, channel)
        if history_dir and os.path.isdir(history_dir):
            shutil.rmtree(history_dir)
            os.makedirs(history_dir, exist_ok=True)
        start_seq = 1
    else:
        # Resume: query existing sections to find how many messages are already covered
        async with async_session() as db:
            existing = (await db.execute(
                select(ConversationSection)
                .where(ConversationSection.session_id == session.id)
                .order_by(ConversationSection.sequence)
            )).scalars().all()

        if existing:
            covered_ua = sum(s.message_count for s in existing)
            start_seq = existing[-1].sequence + 1

            # Count actual user+assistant messages in conversation (post-filter)
            total_ua_in_conversation = sum(
                1 for m in conversation if m.get("role") in ("user", "assistant")
            )
            logger.info(
                "Backfill resume: %d existing sections covering %d msgs, "
                "conversation has %d user+assistant msgs (post-filter), "
                "skipping %d, start_seq=%d",
                len(existing), covered_ua, total_ua_in_conversation,
                min(covered_ua, total_ua_in_conversation), start_seq,
            )

            # Skip covered_ua user+assistant messages in the conversation
            skipped = 0
            skip_idx = len(conversation)  # default: skip everything if covered_ua >= total
            for idx, m in enumerate(conversation):
                if m.get("role") in ("user", "assistant"):
                    skipped += 1
                if skipped >= covered_ua:
                    skip_idx = idx + 1
                    break
            conversation = conversation[skip_idx:]
            active_timestamps = active_timestamps[min(covered_ua, len(active_timestamps)):]
        else:
            start_seq = 1

    # 5. Chunk into groups of chunk_size user+assistant messages
    chunks: list[list[dict]] = []
    current_chunk: list[dict] = []
    msg_count_in_chunk = 0
    for m in conversation:
        current_chunk.append(m)
        if m.get("role") in ("user", "assistant"):
            msg_count_in_chunk += 1
        if msg_count_in_chunk >= chunk_size:
            chunks.append(current_chunk)
            current_chunk = []
            msg_count_in_chunk = 0
    if current_chunk:
        chunks.append(current_chunk)

    total_chunks = len(chunks)

    # 6. Process each chunk
    sections_created = 0
    for i, chunk in enumerate(chunks):
        seq = start_seq + i
        title, summary, transcript, tags, _usage = await _generate_section(
            chunk, effective_model, provider_id=effective_provider,
            channel_id=channel_id,
            session_id=session.id,
            bot_id=session.bot_id,
        )

        msg_count = sum(1 for m in chunk if m.get("role") in ("user", "assistant"))

        # Compute period from active_timestamps (aligned with conversation's user/assistant msgs)
        ua_before = sum(
            sum(1 for m in chunks[j] if m.get("role") in ("user", "assistant"))
            for j in range(i)
        )
        period_start = active_timestamps[ua_before] if ua_before < len(active_timestamps) else None
        ts_end_idx = ua_before + msg_count - 1
        period_end = active_timestamps[ts_end_idx] if 0 <= ts_end_idx < len(active_timestamps) else None

        # Always embed section for semantic search
        embedding = None
        try:
            from app.agent.embeddings import embed_text
            embedding = await embed_text(f"{title}\n{summary}")
        except Exception:
            logger.warning("Failed to embed section for backfill chunk %d", seq, exc_info=True)

        # Write transcript to filesystem (optional) and DB (always)
        transcript_path = None
        history_dir = _get_history_dir(bot, channel)
        ws_root = _get_channel_ws_root(bot) if channel else _get_workspace_root(bot)
        if settings.HISTORY_WRITE_FILES and history_dir and ws_root:
            try:
                transcript_path = _write_section_file(
                    history_dir, seq, title, summary, transcript,
                    period_start, period_end, msg_count,
                    tags or [], ws_root,
                )
            except Exception:
                logger.warning("Failed to write section file for backfill chunk %d", seq, exc_info=True)

        async with async_session() as db:
            section = ConversationSection(
                channel_id=channel_id,
                session_id=session.id,
                sequence=seq,
                title=title,
                summary=summary,
                transcript=transcript,
                transcript_path=transcript_path,
                message_count=msg_count,
                chunk_size=chunk_size,
                period_start=period_start,
                period_end=period_end,
                embedding=embedding,
                tags=tags or None,
            )
            db.add(section)
            await db.commit()

        sections_created += 1
        yield {
            "type": "backfill_progress",
            "section": sections_created,
            "total_chunks": total_chunks,
            "title": title,
        }

    # 7. Regenerate executive summary
    exec_summary = await _regenerate_executive_summary(
        session.id, effective_model, provider_id=effective_provider,
    )

    # Update session summary
    async with async_session() as db:
        await db.execute(
            update(Session)
            .where(Session.id == session.id)
            .values(summary=exec_summary)
        )
        await db.commit()

    yield {
        "type": "backfill_done",
        "sections_created": sections_created,
        "executive_summary": exec_summary,
    }


# ---------------------------------------------------------------------------
# Repair missing section periods
# ---------------------------------------------------------------------------

async def repair_section_periods(channel_id: uuid.UUID | None = None) -> int:
    """Backfill period_start/period_end for sections that are missing them.

    Uses the section's session_id + sequence to find the corresponding messages.
    Returns the number of sections repaired.
    """
    async with async_session() as db:
        query = (
            select(ConversationSection)
            .where(ConversationSection.period_start.is_(None))
        )
        if channel_id:
            query = query.where(ConversationSection.channel_id == channel_id)
        result = await db.execute(query)
        sections = result.scalars().all()

        repaired = 0
        for section in sections:
            if not section.session_id:
                continue
            # Determine message boundaries from the section's own session stream.
            all_sections = await db.execute(
                select(ConversationSection)
                .where(ConversationSection.session_id == section.session_id)
                .order_by(ConversationSection.sequence)
            )
            ordered = all_sections.scalars().all()

            # Find this section's position and compute message range
            # Each section covers message_count user+assistant messages
            msgs_before = sum(
                s.message_count or 0
                for s in ordered
                if s.sequence < section.sequence
            )
            msg_count = section.message_count or 0

            if msg_count == 0:
                continue

            # Query the actual messages by offset
            period_result = await db.execute(
                select(Message.created_at)
                .where(Message.session_id == section.session_id)
                .where(Message.role.in_(["user", "assistant"]))
                .order_by(Message.created_at)
                .offset(msgs_before)
                .limit(msg_count)
            )
            timestamps = period_result.scalars().all()
            if timestamps:
                section.period_start = timestamps[0]
                section.period_end = timestamps[-1]
                repaired += 1

        if repaired:
            await db.commit()
        return repaired


# ---------------------------------------------------------------------------
# Section index formatter (for context injection in file mode)
# ---------------------------------------------------------------------------

def _format_section_period(period_start, period_end, detailed: bool = False) -> str:
    """Smart date range: same-day shows times, multi-day shows date range."""
    if not period_start:
        return "?"
    if not period_end or period_start == period_end:
        return period_start.strftime("%b %-d, %-I:%M%p").lower().replace("am", "am").replace("pm", "pm") if detailed else period_start.strftime("%b %-d")
    same_day = period_start.date() == period_end.date()
    if same_day:
        return f"{period_start.strftime('%b %-d, %-I:%M%p').lower()} — {period_end.strftime('%-I:%M%p').lower()}"
    if detailed:
        return f"{period_start.strftime('%b %-d %-I:%M%p').lower()} — {period_end.strftime('%b %-d %-I:%M%p').lower()}"
    return f"{period_start.strftime('%b %-d')} — {period_end.strftime('%b %-d')}"


def format_section_index(
    sections: list,
    verbosity: str = "standard",
    total_sections: int | None = None,
    all_tags: list[str] | None = None,
) -> str:
    """Format a section index for injection into the system prompt.

    Sections are expected in **most-recent-first** order; output preserves that.

    Args:
        all_tags: Flat list of tags from *all* sections (not just displayed ones).
            When provided and total_sections > displayed, a topic frequency summary
            is appended so the bot has visibility into older history topics.

    Verbosity levels:
      compact  — title + date + tags only
      standard — adds one-line summary
      detailed — adds message count + full period
    """
    header = (
        "Archived conversation history — use read_conversation_history with:\n"
        "  - A section number (e.g. '3') to read a full transcript\n"
        "  - 'search:<query>' to find sections by topic, content, or semantic similarity\n"
        "  - 'tool:<id>' to retrieve full output of a summarized tool call"
    )
    if total_sections and total_sections > len(sections):
        header += (
            f"\n\nShowing {len(sections)} most recent of {total_sections} total sections. "
            "Use 'search:<query>' to find older sections by topic."
        )
        # Append topic frequency map when all_tags are provided
        if all_tags:
            from collections import Counter
            _tag_counts = Counter(all_tags)
            if _tag_counts:
                _sorted = sorted(_tag_counts.items(), key=lambda x: (-x[1], x[0]))
                _tag_summary = ", ".join(f"{tag} ({cnt})" for tag, cnt in _sorted[:30])
                if len(_sorted) > 30:
                    _tag_summary += f", +{len(_sorted) - 30} more"
                header += f"\n\nTopic coverage (all {total_sections} sections): {_tag_summary}"

    if verbosity == "compact":
        lines = [header]
        for s in sections:
            date_str = _format_section_period(s.period_start, s.period_end)
            tag_str = f" [{', '.join(s.tags)}]" if s.tags else ""
            lines.append(f"- #{s.sequence}: {s.title} ({date_str}){tag_str}")
        return "\n".join(lines)

    if verbosity == "detailed":
        lines = [header, ""]
        for s in sections:
            date_str = _format_section_period(s.period_start, s.period_end, detailed=True)
            tag_str = f" [{', '.join(s.tags)}]" if s.tags else ""
            lines.append(
                f"#{s.sequence}: {s.title} ({s.message_count} msgs, {date_str}){tag_str}"
            )
            lines.append(f"  {s.summary}")
            lines.append("")
        return "\n".join(lines).rstrip()

    # standard (default)
    lines = [header, ""]
    for s in sections:
        date_str = _format_section_period(s.period_start, s.period_end)
        tag_str = f" [{', '.join(s.tags)}]" if s.tags else ""
        lines.append(f"#{s.sequence}: {s.title} ({date_str}){tag_str}")
        lines.append(f"  {s.summary}")
        lines.append("")
    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# Section retention pruning
# ---------------------------------------------------------------------------


def _delete_section_file(sec: ConversationSection, bot: BotConfig | None = None) -> None:
    """Best-effort delete the transcript file for a section."""
    if not sec.transcript_path:
        return
    try:
        # transcript_path is relative to workspace root
        ws_root = _get_workspace_root(bot) if bot else None
        if ws_root:
            full_path = os.path.join(ws_root, sec.transcript_path)
        else:
            full_path = sec.transcript_path
        if os.path.isfile(full_path):
            os.remove(full_path)
    except Exception:
        logger.debug("Could not delete section file %s", sec.transcript_path, exc_info=True)


async def prune_sections(channel_id: uuid.UUID, db: AsyncSession | None = None) -> int:
    """Delete old sections per the global retention policy.

    When *db* is provided the caller owns the transaction (no commit here).
    When *db* is None a fresh session is opened and committed.

    Returns the number of sections deleted.
    """
    mode = settings.SECTION_RETENTION_MODE
    if mode == "forever":
        return 0

    value = settings.SECTION_RETENTION_VALUE

    owns_session = db is None
    if owns_session:
        _ctx = async_session()
        db = await _ctx.__aenter__()

    try:
        from sqlalchemy.orm import defer as _prune_defer
        _prune_opts = [_prune_defer(ConversationSection.transcript), _prune_defer(ConversationSection.embedding)]

        if mode == "count":
            # Keep the N most recent sections by sequence
            keep_q = (
                select(ConversationSection.id)
                .where(ConversationSection.channel_id == channel_id)
                .order_by(ConversationSection.sequence.desc())
                .limit(value)
            )
            keep_ids = set((await db.execute(keep_q)).scalars().all())
            all_q = (
                select(ConversationSection)
                .where(ConversationSection.channel_id == channel_id)
                .options(*_prune_opts)
            )
            all_sections = (await db.execute(all_q)).scalars().all()
            to_delete = [s for s in all_sections if s.id not in keep_ids]
        elif mode == "days":
            from datetime import timedelta, timezone
            cutoff = datetime.now(timezone.utc) - timedelta(days=value)
            old_q = (
                select(ConversationSection)
                .where(
                    ConversationSection.channel_id == channel_id,
                    ConversationSection.created_at < cutoff,
                )
                .options(*_prune_opts)
            )
            to_delete = list((await db.execute(old_q)).scalars().all())
        else:
            return 0

        if not to_delete:
            return 0

        for sec in to_delete:
            _delete_section_file(sec)
            await db.delete(sec)

        if owns_session:
            await db.commit()
        return len(to_delete)
    finally:
        if owns_session:
            await _ctx.__aexit__(None, None, None)
