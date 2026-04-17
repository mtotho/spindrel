"""Agent tool for searching historical messages in a channel."""
import json
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.agent.context import current_bot_id, current_channel_id
from app.db.engine import async_session
from app.db.models import Message, Session
from app.tools.registry import register

PREVIEW_LENGTH = 300


def _get_scope():
    """Return (bot_id, channel_id) from context, raising on missing values."""
    bot_id = current_bot_id.get()
    channel_id = current_channel_id.get()
    if not bot_id:
        return None, None, "Error: no bot_id in context."
    if not channel_id:
        return None, None, "Error: no channel_id in context."
    return bot_id, channel_id, None


def _build_query(channel_id, bot_id, query=None, start_date=None, end_date=None, role="all", limit=20, offset=0):
    """Build the SQLAlchemy select statement for message search."""
    stmt = (
        select(Message)
        .join(Session, Message.session_id == Session.id)
        .where(Session.channel_id == channel_id, Session.bot_id == bot_id)
    )

    if query:
        escaped = re.sub(r"([%_])", r"\\\1", query)
        stmt = stmt.where(Message.content.ilike(f"%{escaped}%"))

    if start_date:
        dt = datetime.fromisoformat(start_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        stmt = stmt.where(Message.created_at >= dt)

    if end_date:
        dt = datetime.fromisoformat(end_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        # If date-only (no time component), include the whole day
        if "T" not in end_date:
            dt = dt + timedelta(days=1)
        stmt = stmt.where(Message.created_at < dt)

    if role and role != "all":
        stmt = stmt.where(Message.role == role)
    else:
        # Exclude tool/system noise when showing "all"
        stmt = stmt.where(Message.role.in_(["user", "assistant"]))

    stmt = stmt.order_by(Message.created_at.desc())

    if offset:
        stmt = stmt.offset(offset)

    stmt = stmt.limit(limit)
    return stmt


def _serialize_messages(messages):
    """Serialize messages to JSON-friendly dicts."""
    results = []
    for msg in messages:
        content = msg.content or ""
        results.append({
            "id": str(msg.id),
            "session_id": str(msg.session_id),
            "role": msg.role,
            "content_preview": content[:PREVIEW_LENGTH],
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        })
    return results


@register({
    "type": "function",
    "function": {
        "name": "search_history",
        "description": (
            "Search historical messages in this channel by keyword and/or date range. "
            "Uses keyword matching (not semantic search). "
            "For workspace files use search_workspace; for memory use search_memory."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword or phrase to search for in message content. Case-insensitive."
                },
                "start_date": {
                    "type": "string",
                    "description": "ISO 8601 start date (inclusive). E.g. '2026-03-01' or '2026-03-01T00:00:00Z'."
                },
                "end_date": {
                    "type": "string",
                    "description": "ISO 8601 end date (inclusive). E.g. '2026-03-22'."
                },
                "role": {
                    "type": "string",
                    "description": "Filter by message role.",
                    "enum": ["user", "assistant", "all"]
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return. Defaults to 20, max 100."
                }
            },
            "required": []
        }
    }
})
async def search_history(
    query: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    role: str = "all",
    limit: int = 20,
) -> str:
    bot_id, channel_id, err = _get_scope()
    if err:
        return err

    limit = max(1, min(limit, 100))

    stmt = _build_query(
        channel_id=channel_id,
        bot_id=bot_id,
        query=query,
        start_date=start_date,
        end_date=end_date,
        role=role,
        limit=limit,
    )

    async with async_session() as db:
        messages = (await db.execute(stmt)).scalars().all()

    if not messages:
        return "No messages found."

    return json.dumps(_serialize_messages(messages), ensure_ascii=False)
