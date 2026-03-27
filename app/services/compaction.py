import asyncio
import json
import logging
import os
import re as _re_mod
import shutil
import uuid
from collections.abc import AsyncGenerator
from dataclasses import replace as _dc_replace
from datetime import datetime
from typing import Any

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import BotConfig
from app.agent.context import set_agent_context
from app.agent.loop import run_agent_tool_loop
from app.agent.recording import _record_trace_event
from app.config import settings
from app.db.engine import async_session
from app.db.models import Channel, ConversationSection, Message, Session
from app.services.sessions import normalize_stored_content

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Filesystem transcript helpers
# ---------------------------------------------------------------------------

def _get_history_dir(bot: BotConfig, channel: Channel | None = None) -> str | None:
    """Return host-side .history dir path, creating if needed. None if no workspace.

    Path: bots/<bot_id>/.history/<channel_slug>/  (always under bot's own dir)
    For orchestrators this means writing into bots/<bot_id>/ even though their
    ws_root is the shared workspace root — the relative path stored in DB will
    be bots/<bot_id>/.history/<channel_slug>/001_foo.md which resolves correctly
    from the orchestrator's ws_root.
    """
    from app.services.workspace import workspace_service
    try:
        root = workspace_service.get_workspace_root(bot.id, bot)
        # Orchestrators see the full shared workspace root — always nest under
        # bots/<bot_id>/ so history doesn't pollute the top level and avoids
        # collisions between multiple orchestrators.
        if bot.shared_workspace_id and bot.shared_workspace_role == "orchestrator":
            bot_dir = os.path.join(root, "bots", bot.id)
        else:
            bot_dir = root

        if channel:
            ch_slug = _re_mod.sub(r'[^a-z0-9]+', '_', channel.name.lower())[:40].strip('_') or str(channel.id)[:8]
            history_dir = os.path.join(bot_dir, ".history", ch_slug)
        else:
            history_dir = os.path.join(bot_dir, ".history")
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
    """Resolve the effective history mode: channel override → bot → default 'summary'."""
    if channel and channel.history_mode:
        return channel.history_mode
    return bot.history_mode or "file"


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


async def _get_compaction_prompt(bot: BotConfig, channel: Channel | None = None) -> str:
    from app.services.prompt_resolution import resolve_prompt_template, resolve_workspace_file_prompt

    # 0. Channel-level workspace file link (highest priority)
    if channel and getattr(channel, "compaction_workspace_file_path", None):
        resolved = resolve_workspace_file_prompt(
            str(channel.compaction_workspace_id) if getattr(channel, "compaction_workspace_id", None) else None,
            channel.compaction_workspace_file_path,
            "",
        )
        if resolved:
            return resolved

    has_template = (
        (channel and getattr(channel, "compaction_prompt_template_id", None))
        or bot.compaction_prompt_template_id
    )

    if has_template:
        async with async_session() as db:
            # 1. Channel-level template link
            if channel and getattr(channel, "compaction_prompt_template_id", None):
                resolved = await resolve_prompt_template(
                    str(channel.compaction_prompt_template_id), "", db,
                )
                if resolved:
                    return resolved

            # 2. Channel inline prompt
            if channel and channel.memory_knowledge_compaction_prompt:
                return channel.memory_knowledge_compaction_prompt

            # 3. Bot-level template link
            if bot.compaction_prompt_template_id:
                resolved = await resolve_prompt_template(
                    bot.compaction_prompt_template_id, "", db,
                )
                if resolved:
                    return resolved

    # 2 (no template path). Channel inline prompt
    if channel and channel.memory_knowledge_compaction_prompt:
        return channel.memory_knowledge_compaction_prompt

    # 4. Bot inline prompt → global setting
    return (bot.memory_knowledge_compaction_prompt or settings.MEMORY_KNOWLEDGE_COMPACTION_PROMPT).strip()


def _is_compaction_enabled(bot: BotConfig, channel: Channel | None = None) -> bool:
    if channel is not None:
        return channel.context_compaction
    return bot.context_compaction


def _messages_for_memory_phase(messages: list[dict]) -> list[dict]:
    """Build message list for memory phase: user, assistant, and tool (content truncated to 500 chars).
    Lets the model see tool results when deciding what to store, without blowing context on huge payloads.
    Passive messages are included with a [passive] prefix so the LLM can decide what to memorize.
    """
    filtered = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if content is None:
            continue
        is_passive = (m.get("_metadata") or {}).get("passive", False)
        if role in ("user", "assistant"):
            text = _stringify_message_content(content)
            if is_passive:
                filtered.append({"role": role, "content": f"[passive] {text}"})
            else:
                filtered.append({"role": role, "content": text})
        elif role == "tool":
            text = _stringify_message_content(content)
            truncated = text[:500] + "..." if len(text) > 500 else text
            filtered.append({"role": "tool", "content": truncated})
    return filtered


async def _run_compaction_memory_phase(
    session_id: uuid.UUID,
    client_id: str,
    bot: BotConfig,
    memory_phase_messages: list[dict],
    correlation_id: uuid.UUID | None = None,
    channel: Channel | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Run the shared agent tool loop with the 'last chance to save' prompt only.
    Model decides what to store in memory/knowledge/persona and uses tools; _generate_summary does the actual summary separately.
    Yields events with compaction=True.
    """
    system_content = await _get_compaction_prompt(bot, channel)
    transcript = "\n".join(
        f"[{m['role'].upper()}]: {m['content']}" for m in memory_phase_messages
    )
    user_content = f"Conversation so far (about to be summarized):\n\n{transcript}"

    set_agent_context(
        session_id=session_id,
        client_id=client_id,
        bot_id=bot.id,
        correlation_id=correlation_id,
        channel_id=channel.id if channel else None,
        memory_cross_channel=bot.memory.cross_channel if bot.memory.enabled else None,
        memory_cross_client=bot.memory.cross_client if bot.memory.enabled else None,
        memory_cross_bot=bot.memory.cross_bot if bot.memory.enabled else None,
        memory_similarity_threshold=bot.memory.similarity_threshold if bot.memory.enabled else None,
    )

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]

    # If the compaction prompt contains @tool: or @tool-pack: tags, inject those tools
    # into the memory phase even if they aren't in the bot's configured local_tools.
    # Same pattern as run_stream() pinning for user-message @tool: tags.
    import re as _re
    _tool_tag_re = _re.compile(r"@tool:([A-Za-z_][\w\-\.]*)")
    _pack_tag_re = _re.compile(r"@tool-pack:([A-Za-z_][\w\-\.]*)")
    _tagged: list[str] = list(_tool_tag_re.findall(system_content))
    _pack_names = _pack_tag_re.findall(system_content)
    if _pack_names:
        from app.tools.packs import get_tool_packs
        _packs = get_tool_packs()
        for _pack in _pack_names:
            _tagged.extend(_packs.get(_pack, []))
    _tagged_tool_names = list(dict.fromkeys(_tagged))
    if _tagged_tool_names:
        run_bot = _dc_replace(
            bot,
            local_tools=list(dict.fromkeys((bot.local_tools or []) + _tagged_tool_names)),
            pinned_tools=list(dict.fromkeys((bot.pinned_tools or []) + _tagged_tool_names)),
        )
    else:
        run_bot = bot

    model = _get_compaction_model(bot, channel)
    async for event in run_agent_tool_loop(
        messages,
        run_bot,
        session_id=session_id,
        client_id=client_id,
        model_override=model,
        compaction=True,
        correlation_id=correlation_id,
        channel_id=channel.id if channel else None,
    ):
        yield event


def _messages_for_summary(messages: list[dict]) -> list[dict]:
    """Build the message list to send to the summarization LLM.
    Passive messages are excluded from the alternating user/assistant turns.
    If there are any passive messages, prepend a 'Channel context' system block.
    """
    passive_lines: list[str] = []
    active: list[dict] = []

    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if not content:
            continue
        is_passive = (m.get("_metadata") or {}).get("passive", False)
        if role == "user" and is_passive:
            meta = m.get("_metadata") or {}
            sender = meta.get("sender_id") or "user"
            passive_lines.append(f"  {sender}: {_stringify_message_content(content)}")
        elif role in ("user", "assistant") and not is_passive:
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
) -> tuple[str, str]:
    """Call the LLM to produce a title and summary."""
    prompt_messages: list[dict] = [{"role": "system", "content": settings.BASE_COMPACTION_PROMPT}]

    if existing_summary:
        prompt_messages.append({
            "role": "user",
            "content": f"Previous summary of earlier conversation:\n\n{existing_summary}",
        })

    transcript = "\n".join(
        f"[{m['role'].upper()}]: {m['content']}" for m in conversation
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

    raw = response.choices[0].message.content or "{}"
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        raw = raw.rsplit("```", 1)[0]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Compaction LLM returned non-JSON: %s", raw[:200])
        return ("Conversation", raw)

    title = data.get("title", "Conversation")
    summary = data.get("summary", raw)
    return (title, summary)


async def _generate_section(
    conversation: list[dict],
    model: str,
    provider_id: str | None = None,
) -> tuple[str, str, str, list[str]]:
    """Call the LLM to produce a section title, summary, formatted transcript, and tags."""
    prompt_messages: list[dict] = [{"role": "system", "content": settings.SECTION_COMPACTION_PROMPT}]

    transcript = "\n".join(
        f"[{m['role'].upper()}]: {m['content']}" for m in conversation
    )
    prompt_messages.append({
        "role": "user",
        "content": f"Conversation segment to archive:\n\n{transcript}",
    })

    from app.services.providers import get_llm_client
    response = await get_llm_client(provider_id).chat.completions.create(
        model=model,
        messages=prompt_messages,
        temperature=0.3,
    )

    raw = response.choices[0].message.content or "{}"
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        raw = raw.rsplit("```", 1)[0]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Section LLM returned non-JSON: %s", raw[:200])
        return ("Conversation", raw[:200], raw, [])

    title = data.get("title", "Conversation")
    summary = data.get("summary", "")
    section_transcript = data.get("transcript", raw)
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    return (title, summary, section_transcript, tags)


async def _regenerate_executive_summary(
    channel_id: uuid.UUID,
    model: str,
    provider_id: str | None = None,
) -> str:
    """Query all sections for a channel and produce a compact executive summary."""
    async with async_session() as db:
        result = await db.execute(
            select(ConversationSection)
            .where(ConversationSection.channel_id == channel_id)
            .order_by(ConversationSection.sequence)
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
    )

    return (response.choices[0].message.content or "").strip()


async def run_compaction_stream(
    session_id: uuid.UUID, bot: BotConfig, messages: list[dict],
    *,
    correlation_id: uuid.UUID | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """If compaction is due, run memory/knowledge phase (yielding tool events) then summarize.
    Yields compaction_start, then tool_start/tool_result (with compaction=True), then compaction_done.
    If compaction is not due, yields nothing.
    """
    # Load channel (if any) for channel-level compaction settings
    channel: Channel | None = None
    async with async_session() as db:
        session = await db.get(Session, session_id)
        if session is None:
            return
        if session.channel_id:
            channel = await db.get(Channel, session.channel_id)

    if not _is_compaction_enabled(bot, channel):
        return

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

    if user_msg_count < interval:
        logger.info(
            "Compaction not needed for %s (%d/%d turns)",
            session_id, user_msg_count, interval,
        )
        return

    logger.info("Starting compaction for session %s", session_id)

    client_id: str
    existing_summary: str | None
    async with async_session() as db:
        session = await db.get(Session, session_id)
        if session is None:
            return
        client_id = session.client_id
        existing_summary = session.summary

    asyncio.create_task(_record_trace_event(
        correlation_id=correlation_id,
        session_id=session_id,
        bot_id=bot.id,
        client_id=client_id,
        event_type="compaction_start",
        data={"interval": _get_compaction_interval(bot, channel), "keep_turns": _get_compaction_keep_turns(bot, channel)},
    ))

    keep_turns = _get_compaction_keep_turns(bot, channel)
    turns_to_summarize = interval - keep_turns
    conversation = _messages_for_summary(messages)
    user_count = 0
    to_summarize: list[dict] = []
    for m in conversation:
        if m.get("role") == "user":
            user_count += 1
            if user_count > turns_to_summarize:
                break
        to_summarize.append(m)

    if not to_summarize:
        logger.debug("No turns to summarize for %s", session_id)
        return

    run_memory_phase = (
        bot.memory.enabled or bot.knowledge.enabled or bot.persona
    )
    if channel and channel.compaction_skip_memory_phase:
        run_memory_phase = False

    if run_memory_phase:
        memory_conversation = _messages_for_memory_phase(messages)
        user_count_m = 0
        memory_phase_messages: list[dict] = []
        for m in memory_conversation:
            if m.get("role") == "user":
                user_count_m += 1
                if user_count_m > turns_to_summarize:
                    break
            memory_phase_messages.append(m)
        yield {"type": "compaction_start", "phase": "memory"}
        async for event in _run_compaction_memory_phase(session_id, client_id, bot, memory_phase_messages, correlation_id=correlation_id, channel=channel):
            yield event

    try:
        model = _get_compaction_model(bot, channel)
        history_mode = _get_history_mode(bot, channel)

        # --- Compute watermark (shared across all modes) ---
        async with async_session() as db:
            recent_user_msgs = await db.execute(
                select(Message.id)
                .where(Message.session_id == session_id)
                .where(Message.role == "user")
                .order_by(Message.created_at.desc())
                .limit(keep_turns)
            )
            user_msg_ids = recent_user_msgs.scalars().all()

            if not user_msg_ids:
                logger.debug("No user messages to compact for %s", session_id)
                return

            oldest_kept_id = user_msg_ids[-1]
            oldest_kept = await db.get(Message, oldest_kept_id)
            preceding = await db.execute(
                select(Message.id)
                .where(Message.session_id == session_id)
                .where(Message.created_at < oldest_kept.created_at)
                .order_by(Message.created_at.desc())
                .limit(1)
            )
            watermark_id = preceding.scalar()
            if watermark_id is None:
                logger.debug("All messages within keep window for %s, skipping", session_id)
                return

        if history_mode in ("structured", "file"):
            # --- Section-based compaction ---
            sec_title, sec_summary, sec_transcript, sec_tags = await _generate_section(
                to_summarize, model, provider_id=bot.model_provider_id,
            )

            # Compute message count and period
            msg_count = sum(1 for m in to_summarize if m.get("role") in ("user", "assistant"))

            # Embed for structured mode only
            sec_embedding = None
            if history_mode == "structured":
                from app.agent.embeddings import embed_text
                sec_embedding = await embed_text(f"{sec_title}\n{sec_summary}")

            # Write transcript to filesystem
            transcript_path = None
            history_dir = _get_history_dir(bot, channel)
            ws_root = _get_workspace_root(bot)
            channel_id = channel.id if channel else None

            # Get next sequence number
            async with async_session() as db:
                if channel_id:
                    max_seq_result = await db.execute(
                        select(func.max(ConversationSection.sequence))
                        .where(ConversationSection.channel_id == channel_id)
                    )
                    max_seq = max_seq_result.scalar() or 0
                else:
                    max_seq = 0

            if history_dir and ws_root:
                try:
                    transcript_path = _write_section_file(
                        history_dir, max_seq + 1, sec_title, sec_summary,
                        sec_transcript, None, None, msg_count,
                        sec_tags or [], ws_root,
                    )
                except Exception:
                    logger.warning("Failed to write section file for session %s", session_id, exc_info=True)
            elif not history_dir:
                logger.warning("No workspace configured for bot %s — section file not written", bot.id)

            async with async_session() as db:
                section = ConversationSection(
                    channel_id=channel_id,
                    session_id=session_id,
                    sequence=max_seq + 1,
                    title=sec_title,
                    summary=sec_summary,
                    transcript_path=transcript_path,
                    message_count=msg_count,
                    chunk_size=msg_count,
                    embedding=sec_embedding,
                    tags=sec_tags or None,
                )
                db.add(section)
                await db.commit()

            # Append new section summary to existing executive summary
            if existing_summary and channel_id:
                exec_summary = f"{existing_summary}\n\n[Section {max_seq + 1}] {sec_title}: {sec_summary}"
            else:
                exec_summary = f"[Section {max_seq + 1}] {sec_title}: {sec_summary}"

            # Update session with executive summary + watermark
            async with async_session() as db:
                await db.execute(
                    update(Session)
                    .where(Session.id == session_id)
                    .values(
                        title=sec_title,
                        summary=exec_summary,
                        summary_message_id=watermark_id,
                    )
                )
                await db.commit()

            title = sec_title
            summary = exec_summary
        else:
            # --- Default summary mode ---
            title, summary = await _generate_summary(
                to_summarize, model, existing_summary, provider_id=bot.model_provider_id,
            )

            async with async_session() as db:
                await db.execute(
                    update(Session)
                    .where(Session.id == session_id)
                    .values(
                        title=title,
                        summary=summary,
                        summary_message_id=watermark_id,
                    )
                )
                await db.commit()

        logger.info(
            "Compaction complete for %s: mode=%s, title=%r, summary_len=%d",
            session_id, history_mode, title, len(summary),
        )
        asyncio.create_task(_record_trace_event(
            correlation_id=correlation_id,
            session_id=session_id,
            bot_id=bot.id,
            client_id=client_id,
            event_type="compaction_done",
            data={"title": title, "summary_len": len(summary), "history_mode": history_mode},
        ))
        yield {"type": "compaction_done", "title": title}
    except Exception:
        logger.exception("Compaction failed for session %s", session_id)


async def _drain_compaction(
    session_id: uuid.UUID, bot: BotConfig, messages: list[dict],
    correlation_id: uuid.UUID | None = None,
    dispatch_type: str | None = None,
    dispatch_config: dict | None = None,
) -> None:
    """Drain run_compaction_stream (memory phase if any + summary). Used by fire-and-forget path."""
    compacted = False
    try:
        async for event in run_compaction_stream(session_id, bot, messages, correlation_id=correlation_id):
            if isinstance(event, dict) and event.get("type") == "compaction_done":
                compacted = True
    except Exception:
        logger.exception("Background compaction failed for session %s", session_id)

    if compacted and dispatch_type and dispatch_config:
        try:
            from app.agent.dispatchers import get as get_dispatcher
            from app.db.models import Task
            notif = Task(
                bot_id=bot.id,
                session_id=session_id,
                dispatch_type=dispatch_type,
                dispatch_config=dispatch_config,
            )
            dispatcher = get_dispatcher(dispatch_type)
            await dispatcher.deliver(notif, "🧠 _Context compacted._")
        except Exception:
            logger.warning("Failed to post compaction notification for session %s", session_id)


def maybe_compact(
    session_id: uuid.UUID, bot: BotConfig, messages: list[dict],
    correlation_id: uuid.UUID | None = None,
    dispatch_type: str | None = None,
    dispatch_config: dict | None = None,
) -> None:
    """If compaction is due, run it in the background (memory phase + summary). Non-blocking."""
    asyncio.create_task(_drain_compaction(
        session_id, bot, messages,
        correlation_id=correlation_id,
        dispatch_type=dispatch_type,
        dispatch_config=dispatch_config,
    ))


async def run_compaction_forced(
    session_id: uuid.UUID, bot: BotConfig, db: AsyncSession
) -> tuple[str, str]:
    """Run full compaction (memory phase if enabled + summary) on the entire session.
    Used by POST /sessions/{id}/summarize. Returns (title, summary). Caller must commit db.
    """
    session = await db.get(Session, session_id)
    if session is None:
        raise ValueError("Session not found")

    # Load channel for channel-level compaction settings
    channel: Channel | None = None
    if session.channel_id:
        channel = await db.get(Channel, session.channel_id)

    client_id = session.client_id
    existing_summary = session.summary
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

    run_memory_phase = bot.memory.enabled or bot.knowledge.enabled or bot.persona
    if channel and channel.compaction_skip_memory_phase:
        run_memory_phase = False
    if run_memory_phase:
        memory_phase_messages = _messages_for_memory_phase(messages)
        async for _ in _run_compaction_memory_phase(
            session_id, client_id, bot, memory_phase_messages, correlation_id=correlation_id, channel=channel
        ):
            pass

    model = _get_compaction_model(bot, channel)
    history_mode = _get_history_mode(bot, channel)

    keep_turns = _get_compaction_keep_turns(bot, channel)
    recent_user_msgs = await db.execute(
        select(Message.id)
        .where(Message.session_id == session_id)
        .where(Message.role == "user")
        .order_by(Message.created_at.desc())
        .limit(keep_turns)
    )
    user_msg_ids = recent_user_msgs.scalars().all()
    if not user_msg_ids:
        raise ValueError("No user messages found in session")
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
        raise ValueError("All messages within keep window, nothing to compact")

    if history_mode in ("structured", "file"):
        sec_title, sec_summary, sec_transcript, sec_tags = await _generate_section(
            conversation, model, provider_id=bot.model_provider_id,
        )
        msg_count = sum(1 for m in conversation if m.get("role") in ("user", "assistant"))

        sec_embedding = None
        if history_mode == "structured":
            from app.agent.embeddings import embed_text
            sec_embedding = await embed_text(f"{sec_title}\n{sec_summary}")

        channel_id = session.channel_id
        if channel_id:
            max_seq_result = await db.execute(
                select(func.max(ConversationSection.sequence))
                .where(ConversationSection.channel_id == channel_id)
            )
            max_seq = max_seq_result.scalar() or 0
        else:
            max_seq = 0

        # Write transcript to filesystem
        transcript_path = None
        history_dir = _get_history_dir(bot, channel)
        ws_root = _get_workspace_root(bot)
        if history_dir and ws_root:
            try:
                transcript_path = _write_section_file(
                    history_dir, max_seq + 1, sec_title, sec_summary,
                    sec_transcript, None, None, msg_count,
                    sec_tags or [], ws_root,
                )
            except Exception:
                logger.warning("Failed to write section file for session %s", session_id, exc_info=True)
        elif not history_dir:
            logger.warning("No workspace configured for bot %s — section file not written", bot.id)

        section = ConversationSection(
            channel_id=channel_id,
            session_id=session_id,
            sequence=max_seq + 1,
            title=sec_title,
            summary=sec_summary,
            transcript_path=transcript_path,
            message_count=msg_count,
            chunk_size=msg_count,
            embedding=sec_embedding,
            tags=sec_tags or None,
        )
        db.add(section)
        await db.flush()

        if existing_summary and channel_id:
            exec_summary = f"{existing_summary}\n\n[Section {max_seq + 1}] {sec_title}: {sec_summary}"
        else:
            exec_summary = f"[Section {max_seq + 1}] {sec_title}: {sec_summary}"

        title, summary = sec_title, exec_summary
    else:
        title, summary = await _generate_summary(
            conversation, model, existing_summary, provider_id=bot.model_provider_id,
        )

    await db.execute(
        update(Session)
        .where(Session.id == session_id)
        .values(title=title, summary=summary, summary_message_id=last_msg_id)
    )

    asyncio.create_task(_record_trace_event(
        correlation_id=correlation_id,
        session_id=session_id,
        bot_id=bot.id,
        client_id=client_id,
        event_type="compaction_done",
        data={"forced": True, "title": title, "summary_len": len(summary), "history_mode": history_mode},
    ))
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
    """Retroactively chunk historical messages into ConversationSection rows.

    Yields progress dicts as JSON-line events. Only processes messages at or
    before the active session's watermark (summary_message_id).

    If clear_existing=True, deletes all existing sections for the channel first.
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
        effective_provider = provider_id or bot.model_provider_id

        # 2. Load ALL messages across all sessions for this channel
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

    active_timestamps: list[datetime] = []
    for orig_msg in all_msgs:
        if orig_msg.role == "system":
            continue
        is_passive = (orig_msg.metadata_ or {}).get("passive", False)
        if orig_msg.role in ("user", "assistant") and not (orig_msg.role == "user" and is_passive):
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
                .where(ConversationSection.channel_id == channel_id)
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
                .where(ConversationSection.channel_id == channel_id)
                .order_by(ConversationSection.sequence)
            )).scalars().all()

        if existing:
            covered_ua = sum(s.message_count for s in existing)
            start_seq = existing[-1].sequence + 1

            # Skip covered_ua user+assistant messages in the conversation
            skipped = 0
            skip_idx = 0
            for idx, m in enumerate(conversation):
                if m.get("role") in ("user", "assistant"):
                    skipped += 1
                if skipped >= covered_ua:
                    skip_idx = idx + 1
                    break
            conversation = conversation[skip_idx:]
            active_timestamps = active_timestamps[covered_ua:]
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
        title, summary, transcript, tags = await _generate_section(
            chunk, effective_model, provider_id=effective_provider,
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

        embedding = None
        if effective_mode == "structured":
            from app.agent.embeddings import embed_text
            embedding = await embed_text(f"{title}\n{summary}")

        # Write transcript to filesystem
        transcript_path = None
        history_dir = _get_history_dir(bot, channel)
        ws_root = _get_workspace_root(bot)
        if history_dir and ws_root:
            try:
                transcript_path = _write_section_file(
                    history_dir, seq, title, summary, transcript,
                    period_start, period_end, msg_count,
                    tags or [], ws_root,
                )
            except Exception:
                logger.warning("Failed to write section file for backfill chunk %d", seq, exc_info=True)
        elif not history_dir:
            logger.warning("No workspace configured for bot %s — section file not written", bot.id)

        async with async_session() as db:
            section = ConversationSection(
                channel_id=channel_id,
                session_id=session.id,
                sequence=seq,
                title=title,
                summary=summary,
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
        channel_id, effective_model, provider_id=effective_provider,
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
