import logging

from openai import AsyncOpenAI
from sqlalchemy import func, select

from app.config import settings
from app.db.engine import async_session
from app.db.models import Document

logger = logging.getLogger(__name__)

_client = AsyncOpenAI(
    base_url=settings.LITELLM_BASE_URL,
    api_key=settings.LITELLM_API_KEY,
    timeout=30.0,
)


async def retrieve_context(query: str, skill_ids: list[str] | None = None) -> tuple[list[str], float]:
    """Retrieve relevant skill chunks via pgvector cosine similarity search.

    If skill_ids is provided, only search those skills.
    If skill_ids is None, search all skill documents.
    """
    try:
        response = await _client.embeddings.create(
            model=settings.EMBEDDING_MODEL,
            input=[query],
        )
        query_embedding = response.data[0].embedding
    except Exception:
        logger.exception("Failed to embed query for retrieval")
        return [], 0.0

    max_distance = 1.0 - settings.RAG_SIMILARITY_THRESHOLD
    distance_expr = Document.embedding.cosine_distance(query_embedding)

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
        best_similarity, settings.RAG_SIMILARITY_THRESHOLD, query[:60],
    )

    chunks = []
    for content, distance in rows:
        similarity = 1.0 - distance
        if similarity >= settings.RAG_SIMILARITY_THRESHOLD:
            chunks.append(content)
            logger.debug("  chunk (sim=%.3f): %s...", similarity, content[:80])
        else:
            break

    if chunks:
        logger.info("Retrieved %d skill chunk(s)", len(chunks))
    else:
        logger.info("No chunks above threshold (best was %.3f, need %.3f)",
                     best_similarity, settings.RAG_SIMILARITY_THRESHOLD)

    return chunks, best_similarity
