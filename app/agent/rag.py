import logging

from sqlalchemy import func, select, text as sa_text

from app.agent.embeddings import embed_text
from app.config import settings
from app.db.engine import async_session
from app.db.models import Document

logger = logging.getLogger(__name__)


async def _bm25_search(
    query: str,
    skill_ids: list[str] | None = None,
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
            elif skill_ids:
                skill_sources = [f"skill:{sid}" for sid in skill_ids]
                source_filter = "source = ANY(:sources)"
                params = {"q": query, "sources": skill_sources}
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


async def retrieve_context(
    query: str,
    skill_ids: list[str] | None = None,
    similarity_threshold: float | None = None,
    sources: list[str] | None = None,
) -> tuple[list[tuple[str, str]], float]:
    """Retrieve relevant skill chunks via pgvector cosine similarity search,
    optionally fused with BM25 results via Reciprocal Rank Fusion.

    Returns (chunks, best_similarity) where each chunk is (content, source).

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

    from app.agent.vector_ops import halfvec_cosine_distance
    distance_expr = halfvec_cosine_distance(Document.embedding, query_embedding)

    # Fetch more results when hybrid search will fuse them
    vector_limit = settings.RAG_TOP_K
    if settings.HYBRID_SEARCH_ENABLED:
        vector_limit = settings.RAG_TOP_K * 2

    if sources:
        # Use explicit source list (for workspace skills, etc.)
        stmt = (
            select(Document.content, Document.source, distance_expr.label("distance"))
            .where(Document.source.in_(sources))
            .order_by(distance_expr)
            .limit(vector_limit)
        )
    else:
        stmt = (
            select(Document.content, Document.source, distance_expr.label("distance"))
            .where(Document.source.like("skill:%"))
            .order_by(distance_expr)
            .limit(vector_limit)
        )

        if skill_ids:
            skill_sources = [f"skill:{sid}" for sid in skill_ids]
            stmt = stmt.where(Document.source.in_(skill_sources))

    try:
        async with async_session() as db:
            result = await db.execute(stmt)
            vector_rows = result.all()
    except Exception:
        logger.exception("Failed to query vector store")
        return [], 0.0

    if not vector_rows:
        logger.info("Skill retrieval: no documents found for query: %s...", query[:80])
        return [], 0.0

    # Try hybrid search (BM25 + RRF fusion)
    if settings.HYBRID_SEARCH_ENABLED:
        bm25_rows = await _bm25_search(query, skill_ids=skill_ids, sources=sources, top_k=settings.RAG_TOP_K)
        if bm25_rows:
            return _fuse_results(vector_rows, bm25_rows, threshold, query)

    # Vector-only path
    best_distance = vector_rows[0][2]
    best_similarity = 1.0 - best_distance
    logger.info(
        "Skill retrieval: best_similarity=%.3f threshold=%.3f query=%s...",
        best_similarity, threshold, query[:60],
    )

    chunks = []
    for content, source, distance in vector_rows:
        similarity = 1.0 - distance
        if similarity >= threshold:
            chunks.append((content, source))
            logger.debug("  chunk (sim=%.3f, src=%s): %s...", similarity, source, content[:80])
        else:
            break

    chunks = chunks[:settings.RAG_TOP_K]

    if chunks:
        logger.info("Retrieved %d skill chunk(s)", len(chunks))
    else:
        logger.info("No chunks above threshold (best was %.3f, need %.3f)",
                     best_similarity, threshold)

    return chunks, best_similarity


def _fuse_results(
    vector_rows: list,
    bm25_rows: list[tuple[str, str, float]],
    threshold: float,
    query: str,
) -> tuple[list[tuple[str, str]], float]:
    """Fuse vector and BM25 results using Reciprocal Rank Fusion."""
    from app.agent.hybrid_search import reciprocal_rank_fusion

    k = settings.HYBRID_SEARCH_RRF_K

    # Build ranked lists as (content, source) tuples
    vector_list = [(content, source) for content, source, distance in vector_rows]
    bm25_list = [(content, source) for content, source, rank in bm25_rows]

    # RRF fusion
    fused = reciprocal_rank_fusion(vector_list, bm25_list, k=k)

    # Build a lookup of vector similarities for threshold checking
    vector_sims = {(content, source): 1.0 - distance for content, source, distance in vector_rows}
    bm25_set = {(content, source) for content, source, _ in bm25_rows}

    best_similarity = max(vector_sims.values()) if vector_sims else 0.0

    chunks = []
    bm25_only_count = 0
    _max_bm25_only = settings.RAG_TOP_K // 2  # cap keyword-only results
    for (item, rrf_score) in fused:
        content, source = item
        vec_sim = vector_sims.get((content, source))

        if vec_sim is not None and vec_sim >= threshold:
            # Has a vector match above threshold — include
            chunks.append((content, source))
        elif vec_sim is None and (content, source) in bm25_set:
            # BM25-only match (no vector match) — include as keyword hit, capped
            if bm25_only_count < _max_bm25_only:
                chunks.append((content, source))
                bm25_only_count += 1
        elif vec_sim is not None and vec_sim < threshold and (content, source) in bm25_set:
            # Below vector threshold but matched keywords — include
            chunks.append((content, source))
        # else: below threshold and no BM25 match — skip

        if len(chunks) >= settings.RAG_TOP_K:
            break

    logger.info(
        "Hybrid retrieval: %d vector + %d BM25 → %d fused chunks (threshold=%.3f, query=%s...)",
        len(vector_rows), len(bm25_rows), len(chunks), threshold, query[:60],
    )

    return chunks, best_similarity


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
