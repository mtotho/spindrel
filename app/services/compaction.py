import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from dataclasses import replace as _dc_replace
from typing import Any

from openai import AsyncOpenAI
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import BotConfig
from app.agent.context import set_agent_context
from app.agent.loop import run_agent_tool_loop
from app.agent.recording import _record_trace_event
from app.config import settings
from app.db.engine import async_session
from app.db.models import Message, Session
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

_client = AsyncOpenAI(
    base_url=settings.LITELLM_BASE_URL,
    api_key=settings.LITELLM_API_KEY,
    timeout=60.0,
)


def _get_compaction_model(bot: BotConfig) -> str:
    if bot.compaction_model:
        return bot.compaction_model
    if settings.COMPACTION_MODEL:
        return settings.COMPACTION_MODEL
    return bot.model


def _get_compaction_interval(bot: BotConfig) -> int:
    if bot.compaction_interval is not None:
        return bot.compaction_interval
    return settings.COMPACTION_INTERVAL


def _get_compaction_keep_turns(bot: BotConfig) -> int:
    if bot.compaction_keep_turns is not None:
        return bot.compaction_keep_turns
    return settings.COMPACTION_KEEP_TURNS


def _messages_for_memory_phase(messages: list[dict]) -> list[dict]:
    """Build message list for memory phase: user, assistant, and tool (content truncated to 500 chars).
    Lets the model see tool results when deciding what to store, without blowing context on huge payloads.
    """
    filtered = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if content is None:
            continue
        if role in ("user", "assistant"):
            filtered.append({"role": role, "content": _stringify_message_content(content)})
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
) -> AsyncGenerator[dict[str, Any], None]:
    """Run the shared agent tool loop with the 'last chance to save' prompt only.
    Model decides what to store in memory/knowledge/persona and uses tools; _generate_summary does the actual summary separately.
    Yields events with compaction=True.
    """
    system_content = (
        (bot.memory_knowledge_compaction_prompt or settings.MEMORY_KNOWLEDGE_COMPACTION_PROMPT).strip()
    )
    transcript = "\n".join(
        f"[{m['role'].upper()}]: {m['content']}" for m in memory_phase_messages
    )
    user_content = f"Conversation so far (about to be summarized):\n\n{transcript}"

    set_agent_context(
        session_id=session_id,
        client_id=client_id,
        bot_id=bot.id,
        correlation_id=correlation_id,
        memory_cross_session=bot.memory.cross_session if bot.memory.enabled else None,
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

    model = _get_compaction_model(bot)
    async for event in run_agent_tool_loop(
        messages,
        run_bot,
        session_id=session_id,
        client_id=client_id,
        model_override=model,
        compaction=True,
        correlation_id=correlation_id,
    ):
        yield event


def _messages_for_summary(messages: list[dict]) -> list[dict]:
    """Build the message list to send to the summarization LLM."""
    filtered = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role in ("user", "assistant") and content:
            filtered.append({"role": role, "content": _stringify_message_content(content)})
    return filtered


async def _generate_summary(
    conversation: list[dict],
    model: str,
    existing_summary: str | None,
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

    response = await _client.chat.completions.create(
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
    if not bot.context_compaction:
        return

    interval = _get_compaction_interval(bot)
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
        data={"interval": _get_compaction_interval(bot), "keep_turns": _get_compaction_keep_turns(bot)},
    ))

    keep_turns = _get_compaction_keep_turns(bot)
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
        async for event in _run_compaction_memory_phase(session_id, client_id, bot, memory_phase_messages, correlation_id=correlation_id):
            yield event

    try:
        model = _get_compaction_model(bot)
        title, summary = await _generate_summary(to_summarize, model, existing_summary)

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
) -> None:
    """Drain run_compaction_stream (memory phase if any + summary). Used by fire-and-forget path."""
    try:
        async for _ in run_compaction_stream(session_id, bot, messages, correlation_id=correlation_id):
            pass
    except Exception:
        logger.exception("Background compaction failed for session %s", session_id)


def maybe_compact(
    session_id: uuid.UUID, bot: BotConfig, messages: list[dict],
    correlation_id: uuid.UUID | None = None,
) -> None:
    """If compaction is due, run it in the background (memory phase + summary). Non-blocking."""
    asyncio.create_task(_drain_compaction(session_id, bot, messages, correlation_id=correlation_id))


async def run_compaction_forced(
    session_id: uuid.UUID, bot: BotConfig, db: AsyncSession
) -> tuple[str, str]:
    """Run full compaction (memory phase if enabled + summary) on the entire session.
    Used by POST /sessions/{id}/summarize. Returns (title, summary). Caller must commit db.
    """
    session = await db.get(Session, session_id)
    if session is None:
        raise ValueError("Session not found")

    client_id = session.client_id
    existing_summary = session.summary
    correlation_id = uuid.uuid4()

    asyncio.create_task(_record_trace_event(
        correlation_id=correlation_id,
        session_id=session_id,
        bot_id=bot.id,
        client_id=client_id,
        event_type="compaction_start",
        data={"forced": True, "interval": _get_compaction_interval(bot), "keep_turns": _get_compaction_keep_turns(bot)},
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
            session_id, client_id, bot, memory_phase_messages, correlation_id=correlation_id
        ):
            pass

    model = _get_compaction_model(bot)
    title, summary = await _generate_summary(conversation, model, existing_summary)


    keep_turns = _get_compaction_keep_turns(bot)
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
