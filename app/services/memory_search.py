"""Hybrid BM25+vector search over memory files in filesystem_chunks.

Uses Reciprocal Rank Fusion (RRF) to merge vector similarity and PostgreSQL
full-text search results.  Scoped to file_path LIKE 'memory/%' within the
bot's workspace root.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text

from app.agent.embeddings import embed_text
from app.db.engine import async_session

logger = logging.getLogger(__name__)

RRF_K = 60  # RRF constant (standard value)


@dataclass
class MemorySearchResult:
    file_path: str
    content: str
    score: float


async def hybrid_memory_search(
    query: str,
    bot_id: str,
    roots: list[str] | None = None,
    root: str | None = None,
    *,
    memory_prefix: str = "memory",
    embedding_model: str | None = None,
    top_k: int = 10,
    vector_candidates: int = 20,
    text_candidates: int = 20,
) -> list[MemorySearchResult]:
    """Run hybrid vector + full-text search over memory files.

    Returns results ranked by Reciprocal Rank Fusion score.

    Args:
        roots: List of workspace roots to search across (preferred).
        root: Single root (deprecated, kept for backward compat).
        embedding_model: Model to use for query embedding. If None, uses default.
        memory_prefix: Relative path prefix for memory files within
            the workspace root (e.g. ``"memory"`` or ``"bots/dev_bot/memory"``).
    """
    if not query.strip():
        return []

    # Normalize roots: prefer list, fall back to single root
    search_roots = roots or ([root] if root else [])
    if not search_roots:
        logger.warning("hybrid_memory_search called with no roots for bot_id=%s", bot_id)
        return []

    try:
        query_embedding = await embed_text(query, model=embedding_model)
    except Exception:
        logger.exception("Failed to embed query for memory search (model=%s)", embedding_model)
        return []

    # Convert embedding list to PostgreSQL vector literal
    vec_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"

    # SQL LIKE pattern — e.g. "memory/%" or "bots/dev_bot/memory/%"
    path_pattern = memory_prefix.rstrip("/") + "/%"

    logger.debug(
        "hybrid_memory_search: bot_id=%s, roots=%s, path_pattern=%s, embedding_model=%s",
        bot_id, search_roots, path_pattern, embedding_model,
    )

    # Build root filter: single root uses = for simplicity, multi uses IN
    if len(search_roots) == 1:
        root_clause = "root = :root_0"
        root_params = {"root_0": search_roots[0]}
    else:
        root_placeholders = ", ".join(f":root_{i}" for i in range(len(search_roots)))
        root_clause = f"root IN ({root_placeholders})"
        root_params = {f"root_{i}": r for i, r in enumerate(search_roots)}

    sql = text(f"""
        WITH vector_hits AS (
            SELECT id, file_path, content,
                   1 - (embedding <=> :vec::vector) AS sim,
                   ROW_NUMBER() OVER (ORDER BY embedding <=> :vec::vector) AS rn
            FROM filesystem_chunks
            WHERE bot_id = :bot_id AND {root_clause}
              AND file_path LIKE :path_pattern
              AND embedding IS NOT NULL
            ORDER BY embedding <=> :vec::vector
            LIMIT :v_limit
        ),
        text_hits AS (
            SELECT id, file_path, content,
                   ts_rank_cd(tsv, websearch_to_tsquery('english', :query)) AS rank,
                   ROW_NUMBER() OVER (
                       ORDER BY ts_rank_cd(tsv, websearch_to_tsquery('english', :query)) DESC
                   ) AS rn
            FROM filesystem_chunks
            WHERE bot_id = :bot_id AND {root_clause}
              AND file_path LIKE :path_pattern
              AND tsv @@ websearch_to_tsquery('english', :query)
            ORDER BY rank DESC
            LIMIT :t_limit
        ),
        combined AS (
            SELECT COALESCE(v.id, t.id) AS id,
                   COALESCE(v.file_path, t.file_path) AS file_path,
                   COALESCE(v.content, t.content) AS content,
                   COALESCE(1.0 / (:rrf_k + v.rn), 0) + COALESCE(1.0 / (:rrf_k + t.rn), 0) AS rrf_score
            FROM vector_hits v
            FULL OUTER JOIN text_hits t ON v.id = t.id
        )
        SELECT file_path, content, rrf_score
        FROM combined
        ORDER BY rrf_score DESC
        LIMIT :top_k
    """)

    params = {
        "vec": vec_literal,
        "bot_id": bot_id,
        "path_pattern": path_pattern,
        "query": query,
        "v_limit": vector_candidates,
        "t_limit": text_candidates,
        "rrf_k": RRF_K,
        "top_k": top_k,
        **root_params,
    }

    try:
        async with async_session() as db:
            rows = (await db.execute(sql, params)).all()
    except Exception:
        logger.exception("Hybrid memory search query failed")
        return []

    if not rows:
        logger.debug(
            "hybrid_memory_search returned 0 results: bot_id=%s, roots=%s, path_pattern=%s",
            bot_id, search_roots, path_pattern,
        )

    return [
        MemorySearchResult(file_path=r.file_path, content=r.content, score=r.rrf_score)
        for r in rows
    ]
