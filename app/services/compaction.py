import asyncio
import json
import logging
import uuid

from openai import AsyncOpenAI
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import BotConfig
from app.config import settings
from app.db.engine import async_session
from app.db.models import Message, Session

logger = logging.getLogger(__name__)

_client = AsyncOpenAI(
    base_url=settings.LITELLM_BASE_URL,
    api_key=settings.LITELLM_API_KEY,
    timeout=60.0,
)

_SUMMARIZE_PROMPT = """\
You are a conversation summarizer. You will receive the message history of a \
conversation between a user and an AI assistant.

Produce a JSON object with the following fields:
- "title": A concise title for this conversation (3-8 words, like a chat tab name).
- "summary": A detailed summary of everything discussed so far. Include key facts, \
decisions, code snippets or file paths mentioned, user preferences expressed, and \
any ongoing tasks. This summary will replace the full history, so capture everything \
the assistant would need to continue the conversation seamlessly.

IMPORTANT: Include human-readable time references in the summary text itself \
(e.g. "On March 5, 2025: ..." or "During the week of March 1-7: ..."). \
These summaries may be stored as long-term memories and retrieved weeks later, \
so temporal context is essential for the model to reason about when things happened.

Respond ONLY with the JSON object, no markdown fences or extra text."""


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


def _messages_for_summary(messages: list[dict]) -> list[dict]:
    """Build the message list to send to the summarization LLM."""
    filtered = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role in ("user", "assistant") and content:
            filtered.append({"role": role, "content": content})
    return filtered


async def _generate_summary(
    conversation: list[dict],
    model: str,
    existing_summary: str | None,
) -> tuple[str, str]:
    """Call the LLM to produce a title and summary."""
    prompt_messages: list[dict] = [{"role": "system", "content": _SUMMARIZE_PROMPT}]

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


async def maybe_compact(
    session_id: uuid.UUID, bot: BotConfig, messages: list[dict]
) -> None:
    """Check if compaction is due and run it as a background task if so."""
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
            logger.debug(
                "Compaction not needed for %s (%d/%d turns)",
                session_id, user_msg_count, interval,
            )
            return

    asyncio.create_task(_run_compaction(session_id, bot, messages))


async def _run_compaction(
    session_id: uuid.UUID, bot: BotConfig, messages: list[dict]
) -> None:
    """Perform the actual compaction: summarize and update the session."""
    try:
        logger.info("Starting compaction for session %s", session_id)
        model = _get_compaction_model(bot)

        async with async_session() as db:
            session = await db.get(Session, session_id)
            if session is None:
                return
            existing_summary = session.summary

        conversation = _messages_for_summary(messages)
        if not conversation:
            logger.debug("No conversation content to compact for %s", session_id)
            return

        title, summary = await _generate_summary(
            conversation, model, existing_summary,
        )

        keep_turns = settings.COMPACTION_KEEP_TURNS

        async with async_session() as db:
            recent_user_msgs = await db.execute(
                select(Message.id)
                .where(Message.session_id == session_id)
                .where(Message.role == "user")
                .order_by(Message.created_at.desc())
                .limit(keep_turns)
            )
            user_msg_ids = recent_user_msgs.scalars().all()

            if user_msg_ids:
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
            else:
                logger.debug("No user messages to compact for %s", session_id)
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
    except Exception:
        logger.exception("Compaction failed for session %s", session_id)
