import logging

from sqlalchemy import select, text as sa_text

from app.agent.embeddings import embed_text
from app.config import settings
from app.db.engine import async_session
from app.db.models import Document

logger = logging.getLogger(__name__)


async def _bm25_search(
    query: str,
    sources: list[str] | None = None,
    top_k: int | None = None,
) -> list[tuple[str, str, float]]:
    """Run BM25 full-text search on the documents table.

    Returns list of (content, source, ts_rank) sorted by rank descending.
    Gracefully returns [] on SQLite or any error.
    """
    top_k = top_k or settings.RAG_TOP_K
    try:
        async with async_session() as db:
            # Check if we're on PostgreSQL (tsv column is real TSVECTOR)
            dialect = db.bind.dialect.name if db.bind else ""
            if dialect != "postgresql":
                return []

            # Build source filter
            if sources:
                source_filter = "source = ANY(:sources)"
                params = {"q": query, "sources": sources}
            else:
                source_filter = "source LIKE 'skill:%'"
                params = {"q": query}

            sql = sa_text(f"""
                SELECT content, source,
                       ts_rank(tsv, plainto_tsquery('english', :q)) AS rank
                FROM documents
                WHERE tsv IS NOT NULL
                  AND {source_filter}
                  AND tsv @@ plainto_tsquery('english', :q)
                ORDER BY rank DESC
                LIMIT :lim
            """).bindparams(**params, lim=top_k * 2)

            result = await db.execute(sql)
            return [(row[0], row[1], float(row[2])) for row in result.all()]
    except Exception:
        logger.debug("BM25 search failed (expected on SQLite), falling back to vector-only", exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Skill index retrieval — semantic selection of on-demand skills
# ---------------------------------------------------------------------------
_skill_index_cache: dict[str, tuple[float, list[dict]]] = {}
_SKILL_INDEX_CACHE_TTL = 300  # 5 minutes


def invalidate_skill_index_cache() -> None:
    """Clear the skill index retrieval cache (call after skill re-embed)."""
    _skill_index_cache.clear()


async def retrieve_skill_index(
    query: str,
    skill_ids: list[str],
    *,
    top_k: int | None = None,
    threshold: float | None = None,
) -> list[dict]:
    """Retrieve the most relevant skill IDs for a user query via semantic search.

    Searches skill chunk embeddings in the documents table, groups by skill_id,
    and returns top-K distinct skills sorted by best similarity.

    Returns list of dicts: [{"skill_id": str, "similarity": float}, ...]
    """
    import hashlib
    import time

    if not query or not skill_ids:
        return []

    top_k = top_k or settings.SKILL_INDEX_RETRIEVAL_TOP_K
    threshold = threshold if threshold is not None else settings.SKILL_INDEX_RETRIEVAL_THRESHOLD

    # Cache check
    _q_hash = hashlib.md5(query.encode(), usedforsecurity=False).hexdigest()[:12]
    _ids_hash = hashlib.md5(",".join(sorted(skill_ids)).encode(), usedforsecurity=False).hexdigest()[:12]
    cache_key = f"{_q_hash}:{_ids_hash}:{top_k}:{threshold}"
    cached = _skill_index_cache.get(cache_key)
    if cached and (time.time() - cached[0]) < _SKILL_INDEX_CACHE_TTL:
        return cached[1]

    try:
        query_embedding = await embed_text(query)
    except Exception:
        logger.exception("Failed to embed query for skill index retrieval")
        return []

    from app.agent.vector_ops import halfvec_cosine_distance
    distance_expr = halfvec_cosine_distance(Document.embedding, query_embedding)

    skill_sources = [f"skill:{sid}" for sid in skill_ids]
    vector_limit = top_k * 3  # fetch extra to allow grouping by skill

    stmt = (
        select(Document.source, distance_expr.label("distance"))
        .where(Document.source.in_(skill_sources))
        .order_by(distance_expr)
        .limit(vector_limit)
    )

    try:
        async with async_session() as db:
            result = await db.execute(stmt)
            vector_rows = result.all()
    except Exception:
        logger.exception("Failed to query skill index embeddings")
        return []

    # Group by skill_id, keep best similarity per skill
    best_by_skill: dict[str, float] = {}
    for source, distance in vector_rows:
        sid = source.removeprefix("skill:")
        sim = 1.0 - distance
        if sid not in best_by_skill or sim > best_by_skill[sid]:
            best_by_skill[sid] = sim

    # BM25 fusion: boost skills that match keywords
    if settings.HYBRID_SEARCH_ENABLED:
        bm25_rows = await _bm25_search(query, sources=skill_sources, top_k=vector_limit)
        for _content, source, _rank in bm25_rows:
            sid = source.removeprefix("skill:")
            if sid not in best_by_skill:
                # BM25-only match — include with a synthetic similarity above threshold
                best_by_skill[sid] = threshold

    # Filter by threshold and sort
    results = [
        {"skill_id": sid, "similarity": sim}
        for sid, sim in best_by_skill.items()
        if sim >= threshold
    ]
    results.sort(key=lambda x: x["similarity"], reverse=True)
    results = results[:top_k]

    logger.info(
        "Skill index retrieval: %d/%d skills above threshold=%.3f (query=%s...)",
        len(results), len(skill_ids), threshold, query[:60],
    )

    _skill_index_cache[cache_key] = (time.time(), results)
    return results


async def rank_enrolled_skills(
    query: str,
    enrolled_ids: list[str],
    *,
    relevance_threshold: float | None = None,
) -> list[dict]:
    """Rank enrolled skills by relevance to the user query.

    Unlike retrieve_skill_index (which filters below threshold), this returns
    ALL enrolled skills sorted by similarity. Skills above relevance_threshold
    are flagged as relevant for the two-tier injection format.

    Returns: [{"skill_id": str, "similarity": float, "relevant": bool}, ...]
    sorted by similarity descending, with unscored skills appended at the end.
    """
    if relevance_threshold is None:
        relevance_threshold = settings.SKILL_ENROLLED_RELEVANCE_THRESHOLD

    if not query or not enrolled_ids:
        return [{"skill_id": sid, "similarity": 0.0, "relevant": False} for sid in enrolled_ids]

    # Use a very low threshold so we get scores for (nearly) all enrolled skills
    scored = await retrieve_skill_index(
        query, enrolled_ids, top_k=len(enrolled_ids), threshold=0.05,
    )
    scored_map = {r["skill_id"]: r["similarity"] for r in scored}

    results = []
    for sid in enrolled_ids:
        sim = scored_map.get(sid, 0.0)
        results.append({"skill_id": sid, "similarity": sim, "relevant": sim >= relevance_threshold})

    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results


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
