"""History RAG — summarize recent channel history for context injection."""
import logging

from app.config import settings
from app.db.engine import async_session
from app.db.models import Channel, Message, Session

from sqlalchemy import select

logger = logging.getLogger(__name__)

_DEFAULT_PROMPT = """\
Given the user's current message and their recent conversation history, extract and summarize ONLY the information directly relevant to what the user is asking about.

User's message:
{query}

Recent conversation history:
{history}

Provide a concise summary of relevant context. If nothing is relevant, say "No relevant history."
"""

_DEFAULT_TURNS = 50
_DEFAULT_MAX_TOKENS = 16000  # ~64k chars / 4
_CHARS_PER_TOKEN = 4


def _resolve_model(channel: Channel) -> str:
    """Resolve summarizer model: channel > compaction chain."""
    if channel.history_rag_model:
        return channel.history_rag_model
    if settings.CONTEXT_COMPRESSION_MODEL:
        return settings.CONTEXT_COMPRESSION_MODEL
    return settings.COMPACTION_MODEL


async def summarize_history_context(
    user_query: str,
    channel: Channel,
    provider_id: str | None = None,
) -> tuple[str | None, int]:
    """Load recent messages from the channel and summarize relevant context.

    Returns (summary_text, message_count). Returns (None, 0) if no history
    or on error.
    """
    turns = channel.history_rag_turns or _DEFAULT_TURNS
    max_tokens = channel.history_rag_max_tokens or _DEFAULT_MAX_TOKENS
    max_chars = max_tokens * _CHARS_PER_TOKEN

    # Load recent messages across all sessions in this channel
    async with async_session() as db:
        rows = (await db.execute(
            select(Message.role, Message.content)
            .join(Session, Message.session_id == Session.id)
            .where(
                Session.channel_id == channel.id,
                Message.role.in_(["user", "assistant"]),
                Message.content.is_not(None),
            )
            .order_by(Message.created_at.desc())
            .limit(turns)
        )).all()

    if not rows:
        return None, 0

    # Build conversation text (chronological order)
    lines: list[str] = []
    total_chars = 0
    for role, content in reversed(rows):
        line = f"[{role}]: {content}"
        if total_chars + len(line) > max_chars:
            # Truncate this line to fit
            remaining = max_chars - total_chars
            if remaining > 20:
                lines.append(line[:remaining] + "...")
            break
        lines.append(line)
        total_chars += len(line)

    if not lines:
        return None, 0

    history_text = "\n\n".join(lines)
    msg_count = len(lines)

    # Build prompt
    prompt_template = channel.history_rag_prompt or _DEFAULT_PROMPT
    prompt = prompt_template.replace("{query}", user_query).replace("{history}", history_text)

    model = _resolve_model(channel)

    try:
        from app.services.providers import get_llm_client
        response = await get_llm_client(provider_id).chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1024,
        )
        summary = response.choices[0].message.content or ""
        if not summary.strip() or "no relevant history" in summary.lower():
            return None, msg_count

        logger.info(
            "History RAG for channel %s: %d messages → %d char summary",
            channel.id, msg_count, len(summary),
        )
        return summary, msg_count
    except Exception:
        logger.warning("History RAG failed for channel %s", channel.id, exc_info=True)
        return None, 0
