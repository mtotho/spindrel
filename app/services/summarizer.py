"""Channel message summarizer — on-demand and auto-trigger after idle."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.config import settings
from app.db.engine import async_session
from app.db.models import Channel, Message, Session

logger = logging.getLogger(__name__)

_DEFAULT_PROMPT = """\
Summarize the following conversation in approximately {target_size} characters.
Preserve key decisions, specific values (numbers, file paths, IDs, URLs), and outstanding action items.
Structure as: Key Context, Recent Actions, Open Items.
{custom_prompt_suffix}"""


def _resolve_model(channel: Channel | None) -> str:
    """Resolve model: channel.summarizer_model > channel.compression_model > global."""
    if channel:
        if channel.summarizer_model:
            return channel.summarizer_model
        if channel.compression_model:
            return channel.compression_model
    if settings.SUMMARIZER_MODEL:
        return settings.SUMMARIZER_MODEL
    if settings.CONTEXT_COMPRESSION_MODEL:
        return settings.CONTEXT_COMPRESSION_MODEL
    return settings.COMPACTION_MODEL


async def summarize_messages(
    channel_id: UUID,
    skip: int = 0,
    take: int | None = None,
    target_size: int | None = None,
    prompt: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    provider_id: str | None = None,
) -> str:
    """Summarize historical messages in a channel.

    Returns the summary string, or an error message on failure.
    """
    # Load channel for defaults
    channel: Channel | None = None
    async with async_session() as db:
        channel = (await db.execute(
            select(Channel).where(Channel.id == channel_id)
        )).scalar_one_or_none()

    if not channel:
        return "Error: channel not found."

    # Resolve parameters: param > channel > global
    take = take or channel.summarizer_message_count or settings.SUMMARIZER_MESSAGE_COUNT
    target_size = target_size or channel.summarizer_target_size or settings.SUMMARIZER_TARGET_SIZE
    model = _resolve_model(channel)

    custom_suffix = prompt or ""
    if channel.summarizer_prompt and not prompt:
        custom_suffix = channel.summarizer_prompt

    effective_prompt = _DEFAULT_PROMPT.format(
        target_size=target_size,
        custom_prompt_suffix=custom_suffix,
    )

    # Fetch messages
    stmt = (
        select(Message)
        .join(Session, Message.session_id == Session.id)
        .where(
            Session.channel_id == channel_id,
            Message.role.in_(["user", "assistant"]),
        )
    )

    # Date filters
    if start_date:
        dt = datetime.fromisoformat(start_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        stmt = stmt.where(Message.created_at >= dt)

    if end_date:
        dt = datetime.fromisoformat(end_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if "T" not in end_date:
            dt = dt + timedelta(days=1)
        stmt = stmt.where(Message.created_at < dt)

    # Ordering and pagination
    if start_date or end_date:
        # Date-filtered: oldest first, apply take as limit
        stmt = stmt.order_by(Message.created_at.asc()).limit(take)
    else:
        # No date filter: use skip/take pagination, oldest first
        stmt = stmt.order_by(Message.created_at.asc()).offset(skip).limit(take)

    async with async_session() as db:
        msgs = (await db.execute(stmt)).scalars().all()

    if not msgs:
        return "No messages found in the specified range."

    # Format as transcript
    lines = []
    for msg in msgs:
        ts = msg.created_at.strftime("%Y-%m-%d %H:%M") if msg.created_at else "?"
        content = (msg.content or "")[:2000]
        lines.append(f"[{ts}] {msg.role}: {content}")

    transcript = "\n".join(lines)

    # Call LLM
    prompt_messages = [
        {"role": "system", "content": effective_prompt},
        {"role": "user", "content": f"Conversation ({len(msgs)} messages):\n\n{transcript}"},
    ]

    try:
        from app.services.providers import get_llm_client
        response = await get_llm_client(provider_id).chat.completions.create(
            model=model,
            messages=prompt_messages,
            temperature=0.2,
            max_tokens=settings.CONTEXT_COMPRESSION_MAX_SUMMARY_TOKENS,
        )
        return response.choices[0].message.content or "Summary generation returned empty."
    except Exception:
        logger.warning("Summarizer LLM call failed", exc_info=True)
        return "Error: summarizer LLM call failed."


async def get_last_user_message_time(channel_id: UUID) -> datetime | None:
    """Return the timestamp of the most recent user message in the channel."""
    stmt = (
        select(Message.created_at)
        .join(Session, Message.session_id == Session.id)
        .where(
            Session.channel_id == channel_id,
            Message.role == "user",
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    async with async_session() as db:
        result = (await db.execute(stmt)).scalar_one_or_none()
    return result
