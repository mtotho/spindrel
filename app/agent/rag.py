import logging

from sqlalchemy import func, select

from app.agent.embeddings import embed_text
from app.config import settings
from app.db.engine import async_session
from app.db.models import Document

logger = logging.getLogger(__name__)


async def retrieve_context(
    query: str,
    skill_ids: list[str] | None = None,
    similarity_threshold: float | None = None,
    sources: list[str] | None = None,
) -> tuple[list[str], float]:
    """Retrieve relevant skill chunks via pgvector cosine similarity search.

    If skill_ids is provided, only search those skills (source = "skill:{id}").
    If sources is provided, filter by exact source values (overrides skill_ids).
    If neither, search all skill documents.
    If similarity_threshold is provided, use it instead of RAG_SIMILARITY_THRESHOLD.
    """
    threshold = similarity_threshold if similarity_threshold is not None else settings.RAG_SIMILARITY_THRESHOLD

    try:
        query_embedding = await embed_text(query)
    except Exception:
        logger.exception("Failed to embed query for retrieval")
        return [], 0.0

    distance_expr = Document.embedding.cosine_distance(query_embedding)

    if sources:
        # Use explicit source list (for workspace skills, etc.)
        stmt = (
            select(Document.content, distance_expr.label("distance"))
            .where(Document.source.in_(sources))
            .order_by(distance_expr)
            .limit(settings.RAG_TOP_K)
        )
    else:
        stmt = (
            select(Document.content, distance_expr.label("distance"))
            .where(Document.source.like("skill:%"))
            .order_by(distance_expr)
            .limit(settings.RAG_TOP_K)
        )

        if skill_ids:
            skill_sources = [f"skill:{sid}" for sid in skill_ids]
            stmt = stmt.where(Document.source.in_(skill_sources))

    try:
        async with async_session() as db:
            result = await db.execute(stmt)
            rows = result.all()
    except Exception:
        logger.exception("Failed to query vector store")
        return [], 0.0

    if not rows:
        logger.info("Skill retrieval: no documents found for query: %s...", query[:80])
        return [], 0.0

    best_distance = rows[0][1]
    best_similarity = 1.0 - best_distance
    logger.info(
        "Skill retrieval: best_similarity=%.3f threshold=%.3f query=%s...",
        best_similarity, threshold, query[:60],
    )

    chunks = []
    for content, distance in rows:
        similarity = 1.0 - distance
        if similarity >= threshold:
            chunks.append(content)
            logger.debug("  chunk (sim=%.3f): %s...", similarity, content[:80])
        else:
            break

    if chunks:
        logger.info("Retrieved %d skill chunk(s)", len(chunks))
    else:
        logger.info("No chunks above threshold (best was %.3f, need %.3f)",
                     best_similarity, threshold)

    return chunks, best_similarity


async def fetch_skill_chunks_by_id(skill_id: str) -> list[str]:
    """Fetch all chunks for a skill by ID, ordered by chunk index.

    Bypasses similarity threshold — used for @skill:name tag injection.
    """
    stmt = (
        select(Document.content)
        .where(Document.source == f"skill:{skill_id}")
        .order_by(Document.metadata_["chunk_index"].as_integer())
    )
    try:
        async with async_session() as db:
            result = await db.execute(stmt)
            return list(result.scalars().all())
    except Exception:
        logger.exception("Failed to fetch skill chunks for %r", skill_id)
        return []
