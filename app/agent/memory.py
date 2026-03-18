import logging
import uuid

from openai import AsyncOpenAI
from sqlalchemy import select

from app.config import settings
from app.db.engine import async_session
from app.db.models import Memory

logger = logging.getLogger(__name__)

_client = AsyncOpenAI(
    base_url=settings.LITELLM_BASE_URL,
    api_key=settings.LITELLM_API_KEY,
    timeout=30.0,
)


async def _embed(text: str) -> list[float]:
    response = await _client.embeddings.create(
        model=settings.EMBEDDING_MODEL,
        input=[text],
    )
    return response.data[0].embedding


def _date_prefix(range_start, range_end) -> str:
    """Build a human-readable date prefix from message timestamps."""
    if range_start is None:
        return ""
    start_str = range_start.strftime("%B %-d, %Y")
    if range_end is None or range_start.date() == range_end.date():
        return f"[{start_str}] "
    end_str = range_end.strftime("%B %-d, %Y")
    return f"[{start_str} – {end_str}] "


def _format_memory_for_context(content: str, created_at) -> str:
    """Prefix memory content with created_at when serving to the model."""
    if created_at is None:
        return content
    date_str = created_at.strftime("%B %-d, %Y")
    return f"[{date_str}] {content}"


async def write_memory(
    summary_text: str,
    client_id: str,
    session_id: uuid.UUID,
    bot_id: str,
    message_range_start=None,
    message_range_end=None,
    message_count: int | None = None,
) -> tuple[bool, str | None]:
    """Embed content and write it to the memories table.

    Returns (success, error_message). error_message is set only when success is False.
    """
    summary_text = _date_prefix(message_range_start, message_range_end) + summary_text

    try:
        embedding = await _embed(summary_text)
    except Exception as e:
        logger.exception("Failed to embed memory for session %s", session_id)
        return (False, str(e))

    memory = Memory(
        session_id=session_id,
        client_id=client_id,
        bot_id=bot_id,
        content=summary_text,
        embedding=embedding,
        message_range_start=message_range_start,
        message_range_end=message_range_end,
        message_count=message_count,
    )

    try:
        async with async_session() as db:
            db.add(memory)
            await db.commit()
        logger.info(
            "Wrote memory for session %s (%d chars)",
            session_id, len(summary_text),
        )
        return (True, None)
    except Exception as e:
        logger.exception("Failed to write memory for session %s", session_id)
        return (False, str(e))


async def retrieve_memories(
    query: str,
    session_id: uuid.UUID,
    client_id: str,
    bot_id: str,
    cross_session: bool = False,
    cross_client: bool = False,
    cross_bot: bool = False,
    similarity_threshold: float = settings.MEMORY_SIMILARITY_THRESHOLD,

) -> list[str]:
    """Search the memories table for relevant past summaries.

    By default, scoped to the current session. 
    If cross_session is True, widens to all sessions for this client_id.

    Note: setting MEMORY_SIMILARITY_THRESHOLD higher will make memory retrieval stricter 
    (only highly similar memories will be returned), while setting it lower will recall more loosely-related memories.

    """
    try:
        query_embedding = await _embed(query)
    except Exception:
        logger.exception("Failed to embed query for memory retrieval")
        return []

    max_distance = 1.0 - similarity_threshold
    distance_expr = Memory.embedding.cosine_distance(query_embedding)

    stmt = (
        select(Memory.content, Memory.created_at, distance_expr.label("distance"))
        .order_by(distance_expr)
        .limit(settings.MEMORY_RETRIEVAL_LIMIT)
    )

    # Determine filter conditions for memory retrieval
    if not cross_session and not cross_client and not cross_bot:
        # Only this session
        stmt = stmt.where(Memory.session_id == session_id)
    elif cross_session and not cross_client and not cross_bot:
        # All sessions for this client (same bot)
        stmt = stmt.where(
            (Memory.client_id == client_id) &
            (Memory.bot_id == bot_id)
        )
    elif cross_session and cross_client and not cross_bot:
        # All sessions for all clients (same bot)
        stmt = stmt.where(Memory.bot_id == bot_id)
    elif cross_session and not cross_client and cross_bot:
        # All sessions for this client, all bots
        stmt = stmt.where(Memory.client_id == client_id)
    elif cross_session and cross_client and cross_bot:
        # All memories (no restrictions)
        pass
    else:
        # Fallback to session only if conditions are not met
        stmt = stmt.where(Memory.session_id == session_id)

    try:
        async with async_session() as db:
            result = await db.execute(stmt)
            rows = result.all()
    except Exception:
        logger.exception("Failed to query memories")
        return []

    if not rows:
        return []

    best_similarity = 1.0 - rows[0][2]
    logger.info(
        "Memory retrieval: best_similarity=%.3f threshold=%.3f query=%s...",
        best_similarity, similarity_threshold, query[:60],
    )

    chunks = []
    for content, created_at, distance in rows:
        similarity = 1.0 - distance
        if similarity >= similarity_threshold:
            chunks.append(_format_memory_for_context(content, created_at))
        else:
            break

    if chunks:
        logger.info("Retrieved %d memory chunk(s)", len(chunks))

    return chunks
