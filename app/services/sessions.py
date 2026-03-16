import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import get_bot
from app.db.models import Message, Session


async def load_or_create(
    db: AsyncSession,
    session_id: uuid.UUID | None,
    client_id: str,
    bot_id: str,
) -> tuple[uuid.UUID, list[dict]]:
    if session_id is not None:
        existing = await db.get(Session, session_id)
        if existing is not None:
            result = await db.execute(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.created_at)
            )
            messages = [_message_to_dict(m) for m in result.scalars().all()]
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


async def persist_turn(
    db: AsyncSession,
    session_id: uuid.UUID,
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


def _message_to_dict(msg: Message) -> dict:
    d: dict = {"role": msg.role}
    if msg.content is not None:
        d["content"] = msg.content
    if msg.tool_calls is not None:
        d["tool_calls"] = msg.tool_calls
    if msg.tool_call_id is not None:
        d["tool_call_id"] = msg.tool_call_id
    return d
