import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import BotConfig, get_bot
from app.db.models import Message, Session
from app.services.compaction import maybe_compact

logger = logging.getLogger(__name__)


async def load_or_create(
    db: AsyncSession,
    session_id: uuid.UUID | None,
    client_id: str,
    bot_id: str,
) -> tuple[uuid.UUID, list[dict]]:
    if session_id is not None:
        existing = await db.get(Session, session_id)
        if existing is not None:
            messages = await _load_messages(db, existing)
            return session_id, messages

    if session_id is None:
        session_id = uuid.uuid4()

    bot = get_bot(bot_id)
    session = Session(id=session_id, client_id=client_id, bot_id=bot_id)
    db.add(session)

    system_msg = Message(
        session_id=session_id,
        role="system",
        content=bot.system_prompt,
    )
    db.add(system_msg)
    await db.commit()

    return session_id, [{"role": "system", "content": bot.system_prompt}]


async def _load_messages(db: AsyncSession, session: Session) -> list[dict]:
    """Load messages for a session, using compacted summary when available."""
    bot = get_bot(session.bot_id)

    if session.summary and session.summary_message_id and bot.context_compaction:
        watermark_msg = await db.get(Message, session.summary_message_id)
        if watermark_msg is not None:
            recent_result = await db.execute(
                select(Message)
                .where(Message.session_id == session.id)
                .where(Message.created_at > watermark_msg.created_at)
                .order_by(Message.created_at)
            )
            recent = [_message_to_dict(m) for m in recent_result.scalars().all()]

            messages = [
                {"role": "system", "content": bot.system_prompt},
                {
                    "role": "system",
                    "content": (
                        f"Summary of the conversation so far:\n\n{session.summary}"
                    ),
                },
            ]
            messages.extend(recent)
            return _sanitize_tool_messages(messages)

    result = await db.execute(
        select(Message)
        .where(Message.session_id == session.id)
        .order_by(Message.created_at)
    )
    return _sanitize_tool_messages(
        [_message_to_dict(m) for m in result.scalars().all()]
    )


async def persist_turn(
    db: AsyncSession,
    session_id: uuid.UUID,
    bot: BotConfig,
    messages: list[dict],
    from_index: int,
) -> None:
    new_messages = messages[from_index:]
    for msg in new_messages:
        record = Message(
            session_id=session_id,
            role=msg["role"],
            content=msg.get("content"),
            tool_calls=msg.get("tool_calls"),
            tool_call_id=msg.get("tool_call_id"),
        )
        db.add(record)

    await db.execute(
        update(Session)
        .where(Session.id == session_id)
        .values(last_active=datetime.now(timezone.utc))
    )
    await db.commit()

    await maybe_compact(session_id, bot, messages)


def _sanitize_tool_messages(messages: list[dict]) -> list[dict]:
    """Remove orphaned tool messages that would cause LLM API errors.

    Gemini (and others) require every tool result to have a matching
    tool_call in a preceding assistant message, and vice versa.  DB
    round-trips, compaction watermarks, or malformed tool_call IDs can
    break these pairs.  Strip any that don't match.
    """
    # Collect all tool_call IDs present in assistant tool_calls
    offered_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tc_id = tc.get("id") or ""
                if tc_id:
                    offered_ids.add(tc_id)

    # Collect all tool_call IDs referenced by tool result messages
    answered_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "tool" and msg.get("tool_call_id"):
            answered_ids.add(msg["tool_call_id"])

    orphan_tool_ids = answered_ids - offered_ids
    orphan_call_ids = offered_ids - answered_ids

    if not orphan_tool_ids and not orphan_call_ids:
        return messages

    if orphan_tool_ids:
        logger.warning("Stripping %d orphaned tool result(s)", len(orphan_tool_ids))
    if orphan_call_ids:
        logger.warning("Stripping %d unanswered tool call(s)", len(orphan_call_ids))

    cleaned: list[dict] = []
    for msg in messages:
        if msg.get("role") == "tool" and msg.get("tool_call_id") in orphan_tool_ids:
            continue

        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            kept = [tc for tc in msg["tool_calls"]
                    if (tc.get("id") or "") not in orphan_call_ids]
            if not kept:
                # Assistant message had only orphaned tool calls — keep as
                # plain text if it has content, otherwise drop entirely.
                if msg.get("content"):
                    cleaned.append({"role": "assistant", "content": msg["content"]})
                continue
            msg = {**msg, "tool_calls": kept}

        cleaned.append(msg)

    return cleaned


def _message_to_dict(msg: Message) -> dict:
    d: dict = {"role": msg.role}
    if msg.content is not None:
        d["content"] = msg.content
    if msg.tool_calls is not None:
        d["tool_calls"] = msg.tool_calls
    if msg.tool_call_id is not None:
        d["tool_call_id"] = msg.tool_call_id
    return d
