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


async def _diagnose_empty_results(
    bot_id: str,
    roots: list[str],
    path_pattern: str,
    embedding_model: str | None,
) -> None:
    """Log diagnostic counts to identify why memory search returned empty.

    Called only when hybrid search returns 0 results — helps debug indexing/query mismatches.
    """
    try:
        root_placeholders = ", ".join(f":root_{i}" for i in range(len(roots)))
        root_params = {f"root_{i}": r for i, r in enumerate(roots)}

        diag_sql = text(f"""
            SELECT
                count(*) AS total_chunks,
                count(*) FILTER (WHERE bot_id = :bot_id) AS matching_bot,
                count(*) FILTER (WHERE bot_id = :bot_id AND root IN ({root_placeholders})) AS matching_root,
                count(*) FILTER (WHERE bot_id = :bot_id AND root IN ({root_placeholders}) AND file_path LIKE :path_pattern) AS matching_path,
                count(*) FILTER (WHERE bot_id = :bot_id AND root IN ({root_placeholders}) AND file_path LIKE :path_pattern AND embedding IS NOT NULL) AS with_embedding,
                count(*) FILTER (WHERE bot_id = :bot_id AND root IN ({root_placeholders}) AND file_path LIKE :path_pattern AND tsv IS NOT NULL) AS with_tsv,
                (SELECT array_agg(DISTINCT embedding_model) FROM filesystem_chunks WHERE bot_id = :bot_id AND root IN ({root_placeholders}) AND file_path LIKE :path_pattern) AS models,
                (SELECT array_agg(DISTINCT file_path) FROM filesystem_chunks WHERE bot_id = :bot_id AND root IN ({root_placeholders}) AND file_path LIKE :path_pattern LIMIT 10) AS sample_paths,
                (SELECT array_agg(DISTINCT root) FROM filesystem_chunks WHERE bot_id = :bot_id LIMIT 5) AS bot_roots
            FROM filesystem_chunks
        """)

        async with async_session() as db:
            row = (await db.execute(diag_sql, {
                "bot_id": bot_id,
                "path_pattern": path_pattern,
                **root_params,
            })).one()

        logger.warning(
            "MEMORY SEARCH DIAGNOSTIC: "
            "total_chunks=%s, matching_bot=%s, matching_root=%s, matching_path=%s, "
            "with_embedding=%s, with_tsv=%s, models=%s, sample_paths=%s, bot_roots=%s, "
            "query_roots=%s, query_path_pattern=%s, query_model=%s",
            row.total_chunks, row.matching_bot, row.matching_root, row.matching_path,
            row.with_embedding, row.with_tsv, row.models, row.sample_paths, row.bot_roots,
            roots, path_pattern, embedding_model,
        )
    except Exception:
        logger.exception("Failed to run memory search diagnostics")


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
                   1 - (embedding <=> CAST(:vec AS vector)) AS sim,
                   ROW_NUMBER() OVER (ORDER BY embedding <=> CAST(:vec AS vector)) AS rn
            FROM filesystem_chunks
            WHERE bot_id = :bot_id AND {root_clause}
              AND file_path LIKE :path_pattern
              AND embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:vec AS vector)
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
    except Exception as exc:
        logger.exception(
            "Hybrid memory search query FAILED: bot_id=%s, roots=%s, path_pattern=%s, "
            "embedding_model=%s, vec_dims=%d",
            bot_id, search_roots, path_pattern, embedding_model,
            len(query_embedding) if query_embedding else 0,
        )
        # Run diagnostics to understand the state
        await _diagnose_empty_results(bot_id, search_roots, path_pattern, embedding_model)
        # Re-raise so callers can report the error instead of silent empty results
        raise RuntimeError(f"Memory search SQL failed: {exc}") from exc

    if not rows:
        logger.warning(
            "hybrid_memory_search returned 0 results: bot_id=%s, roots=%s, path_pattern=%s, model=%s",
            bot_id, search_roots, path_pattern, embedding_model,
        )
        # Run diagnostic count queries to identify the failure point
        await _diagnose_empty_results(bot_id, search_roots, path_pattern, embedding_model)

    return [
        MemorySearchResult(file_path=r.file_path, content=r.content, score=r.rrf_score)
        for r in rows
    ]
