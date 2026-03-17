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


async def write_memory(
    summary_text: str,
    client_id: str,
    session_id: uuid.UUID,
    message_range_start=None,
    message_range_end=None,
    message_count: int | None = None,
) -> None:
    """Embed content and write it to the memories table."""
    summary_text = _date_prefix(message_range_start, message_range_end) + summary_text

    try:
        embedding = await _embed(summary_text)
    except Exception:
        logger.exception("Failed to embed memory for session %s", session_id)
        return

    memory = Memory(
        session_id=session_id,
        client_id=client_id,
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
    except Exception:
        logger.exception("Failed to write memory for session %s", session_id)


async def retrieve_memories(
    query: str,
    session_id: uuid.UUID,
    client_id: str,
    cross_session: bool = False,
) -> list[str]:
    """Search the memories table for relevant past summaries.

    By default, scoped to the current session. If cross_session is True,
    widens to all sessions for this client_id.
    """
    try:
        query_embedding = await _embed(query)
    except Exception:
        logger.exception("Failed to embed query for memory retrieval")
        return []

    max_distance = 1.0 - settings.MEMORY_SIMILARITY_THRESHOLD
    distance_expr = Memory.embedding.cosine_distance(query_embedding)

    stmt = (
        select(Memory.content, distance_expr.label("distance"))
        .order_by(distance_expr)
        .limit(settings.MEMORY_RETRIEVAL_LIMIT)
    )

    if cross_session:
        stmt = stmt.where(Memory.client_id == client_id)
    else:
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

    best_similarity = 1.0 - rows[0][1]
    logger.info(
        "Memory retrieval: best_similarity=%.3f threshold=%.3f query=%s...",
        best_similarity, settings.MEMORY_SIMILARITY_THRESHOLD, query[:60],
    )

    chunks = []
    for content, distance in rows:
        similarity = 1.0 - distance
        if similarity >= settings.MEMORY_SIMILARITY_THRESHOLD:
            chunks.append(content)
        else:
            break

    if chunks:
        logger.info("Retrieved %d memory chunk(s)", len(chunks))

    return chunks
