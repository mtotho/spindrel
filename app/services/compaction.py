import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from dataclasses import replace as _dc_replace
from typing import Any

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import BotConfig
from app.agent.context import set_agent_context
from app.agent.loop import run_agent_tool_loop
from app.agent.recording import _record_trace_event
from app.config import settings
from app.db.engine import async_session
from app.db.models import Channel, Message, Session
from app.services.sessions import normalize_stored_content

logger = logging.getLogger(__name__)


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


def _get_compaction_prompt(bot: BotConfig, channel: Channel | None = None) -> str:
    if channel and channel.memory_knowledge_compaction_prompt:
        return channel.memory_knowledge_compaction_prompt
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
    system_content = _get_compaction_prompt(bot, channel)
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
        title, summary = await _generate_summary(to_summarize, model, existing_summary, provider_id=bot.model_provider_id)

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
            "Compaction complete for %s: title=%r, summary_len=%d",
            session_id, title, len(summary),
        )
        asyncio.create_task(_record_trace_event(
            correlation_id=correlation_id,
            session_id=session_id,
            bot_id=bot.id,
            client_id=client_id,
            event_type="compaction_done",
            data={"title": title, "summary_len": len(summary)},
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

    def _msg_to_dict(m: Message) -> dict:
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

    messages = [_msg_to_dict(m) for m in all_msgs]
    messages = [m for m in messages if m.get("role") != "system"]

    conversation = _messages_for_summary(messages)
    if not conversation:
        raise ValueError("No conversation content to summarize")

    run_memory_phase = bot.memory.enabled or bot.knowledge.enabled or bot.persona
    if run_memory_phase:
        memory_phase_messages = _messages_for_memory_phase(messages)
        async for _ in _run_compaction_memory_phase(
            session_id, client_id, bot, memory_phase_messages, correlation_id=correlation_id, channel=channel
        ):
            pass

    model = _get_compaction_model(bot, channel)
    title, summary = await _generate_summary(conversation, model, existing_summary, provider_id=bot.model_provider_id)

    keep_turns = _get_compaction_keep_turns(bot, channel)
    recent_user_msgs = await db.execute(
        select(Message.id)
        .where(Message.session_id == session_id)
        .where(Message.role == "user")
        .order_by(Message.created_at.desc())
        .limit(keep_turns)
    )
    user_msg_ids = recent_user_msgs.scalars().all()
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
        data={"forced": True, "title": title, "summary_len": len(summary)},
    ))
    return (title, summary)
