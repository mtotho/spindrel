import logging
import uuid
from datetime import datetime

from openai import AsyncOpenAI
from sqlalchemy import and_, delete, select

from app.config import settings
from app.db.engine import async_session
from app.db.models import Memory

logger = logging.getLogger(__name__)


class _MemoryMergeAborted(Exception):
    """Rollback merge transaction when delete count does not match."""


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


def format_memory_search_hit(memory_id: uuid.UUID, content: str, created_at) -> str:
    """One search result line block: includes id for purge_memory / merge_memory."""
    body = _format_memory_for_context(content, created_at)
    return f"id: {memory_id}\n{body}"


def memory_scope_where(
    session_id: uuid.UUID,
    client_id: str,
    bot_id: str,
    *,
    cross_channel: bool,
    cross_client: bool,
    cross_bot: bool,
    channel_id: uuid.UUID | None = None,
):
    """SQLAlchemy filter for memories visible under the same rules as retrieval.

    Returns None when no row filter is needed (widest / global scope).
    """
    if not cross_channel:
        # Narrowest scope: same channel + same bot
        if channel_id is not None:
            return and_(Memory.channel_id == channel_id, Memory.bot_id == bot_id)
        # Fallback when channel_id unknown: use session_id
        return and_(Memory.session_id == session_id, Memory.bot_id == bot_id)
    if cross_channel and not cross_client and not cross_bot:
        return and_(Memory.client_id == client_id, Memory.bot_id == bot_id)
    if cross_channel and cross_client and not cross_bot:
        return Memory.bot_id == bot_id
    if cross_channel and not cross_client and cross_bot:
        return Memory.client_id == client_id
    if cross_channel and cross_client and cross_bot:
        return None
    # Fallback
    if channel_id is not None:
        return and_(Memory.channel_id == channel_id, Memory.bot_id == bot_id)
    return and_(Memory.session_id == session_id, Memory.bot_id == bot_id)


def _apply_memory_scope(
    stmt,
    session_id: uuid.UUID,
    client_id: str,
    bot_id: str,
    *,
    cross_channel: bool,
    cross_client: bool,
    cross_bot: bool,
    channel_id: uuid.UUID | None = None,
):
    clause = memory_scope_where(
        session_id, client_id, bot_id,
        cross_channel=cross_channel,
        cross_client=cross_client,
        cross_bot=cross_bot,
        channel_id=channel_id,
    )
    if clause is not None:
        return stmt.where(clause)
    return stmt


async def retrieve_memory_matches(
    query: str,
    session_id: uuid.UUID,
    client_id: str,
    bot_id: str,
    cross_channel: bool = False,
    cross_client: bool = False,
    cross_bot: bool = False,
    similarity_threshold: float = settings.MEMORY_SIMILARITY_THRESHOLD,
    channel_id: uuid.UUID | None = None,
) -> tuple[list[tuple[uuid.UUID, str, datetime | None, float]], float]:
    """Vector search; returns (memory_id, raw_content, created_at, similarity) per hit, plus best similarity."""
    try:
        query_embedding = await _embed(query)
    except Exception:
        logger.exception("Failed to embed query for memory retrieval")
        return [], 0.0

    distance_expr = Memory.embedding.cosine_distance(query_embedding)
    stmt = (
        select(Memory.id, Memory.content, Memory.created_at, distance_expr.label("distance"))
        .order_by(distance_expr)
        .limit(settings.MEMORY_RETRIEVAL_LIMIT)
    )
    stmt = _apply_memory_scope(
        stmt, session_id, client_id, bot_id,
        cross_channel=cross_channel,
        cross_client=cross_client,
        cross_bot=cross_bot,
        channel_id=channel_id,
    )

    try:
        async with async_session() as db:
            result = await db.execute(stmt)
            rows = result.all()
    except Exception:
        logger.exception("Failed to query memories")
        return [], 0.0

    if not rows:
        return [], 0.0

    best_similarity = 1.0 - rows[0][3]
    logger.info(
        "Memory retrieval: best_similarity=%.3f threshold=%.3f query=%s...",
        best_similarity, similarity_threshold, query[:60],
    )

    out: list[tuple[uuid.UUID, str, datetime | None, float]] = []
    for mid, content, created_at, distance in rows:
        similarity = 1.0 - distance
        if similarity >= similarity_threshold:
            out.append((mid, content, created_at, similarity))
        else:
            break

    if out:
        logger.info("Retrieved %d memory chunk(s)", len(out))

    return out, best_similarity


async def write_memory(
    summary_text: str,
    client_id: str,
    session_id: uuid.UUID,
    bot_id: str,
    message_range_start=None,
    message_range_end=None,
    message_count: int | None = None,
    correlation_id: uuid.UUID | None = None,
    channel_id: uuid.UUID | None = None,
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
        channel_id=channel_id,
        client_id=client_id,
        bot_id=bot_id,
        content=summary_text,
        embedding=embedding,
        message_range_start=message_range_start,
        message_range_end=message_range_end,
        message_count=message_count,
        correlation_id=correlation_id,
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
    cross_channel: bool = False,
    cross_client: bool = False,
    cross_bot: bool = False,
    similarity_threshold: float = settings.MEMORY_SIMILARITY_THRESHOLD,
    channel_id: uuid.UUID | None = None,
) -> tuple[list[str], float]:
    """Search the memories table for relevant past summaries.

    By default, scoped to the current channel.
    If cross_channel is True, widens to all channels for this client_id.

    Note: setting MEMORY_SIMILARITY_THRESHOLD higher will make memory retrieval stricter
    (only highly similar memories will be returned), while setting it lower will recall more loosely-related memories.

    """
    matches, best_similarity = await retrieve_memory_matches(
        query=query,
        session_id=session_id,
        client_id=client_id,
        bot_id=bot_id,
        cross_channel=cross_channel,
        cross_client=cross_client,
        cross_bot=cross_bot,
        similarity_threshold=similarity_threshold,
        channel_id=channel_id,
    )
    chunks = [
        _format_memory_for_context(content, created_at)
        for _mid, content, created_at, _sim in matches
    ]
    return chunks, best_similarity


async def delete_memory_scoped(
    memory_id: uuid.UUID,
    session_id: uuid.UUID,
    client_id: str,
    bot_id: str,
    *,
    cross_channel: bool,
    cross_client: bool,
    cross_bot: bool,
    channel_id: uuid.UUID | None = None,
) -> tuple[bool, str | None]:
    """Delete one memory row if it exists and falls under the given scope."""
    stmt = delete(Memory).where(Memory.id == memory_id)
    clause = memory_scope_where(
        session_id, client_id, bot_id,
        cross_channel=cross_channel,
        cross_client=cross_client,
        cross_bot=cross_bot,
        channel_id=channel_id,
    )
    if clause is not None:
        stmt = stmt.where(clause)
    try:
        async with async_session() as db:
            result = await db.execute(stmt)
            await db.commit()
    except Exception as e:
        logger.exception("Failed to delete memory %s", memory_id)
        return False, str(e)
    if result.rowcount == 0:
        return False, "Memory not found or not accessible in the current scope."
    logger.info("Deleted memory %s", memory_id)
    return True, None


async def merge_memories_scoped(
    memory_ids: list[uuid.UUID],
    merged_content: str | None,
    session_id: uuid.UUID,
    client_id: str,
    bot_id: str,
    *,
    cross_channel: bool,
    cross_client: bool,
    cross_bot: bool,
    correlation_id: uuid.UUID | None = None,
    channel_id: uuid.UUID | None = None,
) -> tuple[bool, str | None, uuid.UUID | None]:
    """Replace several memories with one new row (re-embedded). Order follows memory_ids."""
    unique_ids = list(dict.fromkeys(memory_ids))
    if len(unique_ids) < 2:
        return False, "Provide at least two distinct memory ids to merge.", None

    scope_kw = dict(
        cross_channel=cross_channel,
        cross_client=cross_client,
        cross_bot=cross_bot,
        channel_id=channel_id,
    )
    stmt = select(Memory).where(Memory.id.in_(unique_ids))
    clause = memory_scope_where(session_id, client_id, bot_id, **scope_kw)
    if clause is not None:
        stmt = stmt.where(clause)

    try:
        async with async_session() as db:
            result = await db.execute(stmt)
            rows = result.scalars().all()
    except Exception as e:
        logger.exception("Failed to load memories for merge")
        return False, str(e), None

    by_id = {r.id: r for r in rows}
    ordered = [by_id[i] for i in unique_ids if i in by_id]
    if len(ordered) != len(unique_ids):
        return False, "One or more memories were not found or are not accessible in the current scope.", None

    if merged_content is not None and merged_content.strip():
        text = merged_content.strip()
    else:
        text = "\n\n".join(r.content for r in ordered).strip()
    if not text:
        return False, "Merged content would be empty.", None

    try:
        embedding = await _embed(text)
    except Exception as e:
        logger.exception("Failed to embed merged memory")
        return False, str(e), None

    new_id = uuid.uuid4()
    new_row = Memory(
        id=new_id,
        session_id=session_id,
        channel_id=channel_id,
        client_id=client_id,
        bot_id=bot_id,
        content=text,
        embedding=embedding,
        message_range_start=None,
        message_range_end=None,
        message_count=None,
        correlation_id=correlation_id,
    )

    try:
        async with async_session() as db:
            async with db.begin():
                del_stmt = delete(Memory).where(Memory.id.in_(unique_ids))
                if clause is not None:
                    del_stmt = del_stmt.where(clause)
                del_result = await db.execute(del_stmt)
                if del_result.rowcount != len(unique_ids):
                    raise _MemoryMergeAborted
                db.add(new_row)
    except _MemoryMergeAborted:
        return False, "Could not remove all source memories; merge aborted.", None
    except Exception as e:
        logger.exception("Failed to merge memories")
        return False, str(e), None

    logger.info("Merged %d memories into %s", len(unique_ids), new_id)
    return True, None, new_id
