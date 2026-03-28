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
    root: str,
    *,
    top_k: int = 10,
    vector_candidates: int = 20,
    text_candidates: int = 20,
) -> list[MemorySearchResult]:
    """Run hybrid vector + full-text search over memory files.

    Returns results ranked by Reciprocal Rank Fusion score.
    """
    if not query.strip():
        return []

    try:
        query_embedding = await embed_text(query)
    except Exception:
        logger.exception("Failed to embed query for memory search")
        return []

    # Convert embedding list to PostgreSQL vector literal
    vec_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"

    sql = text("""
        WITH vector_hits AS (
            SELECT id, file_path, content,
                   1 - (embedding <=> :vec::vector) AS sim,
                   ROW_NUMBER() OVER (ORDER BY embedding <=> :vec::vector) AS rn
            FROM filesystem_chunks
            WHERE bot_id = :bot_id AND root = :root
              AND file_path LIKE 'memory/%%'
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
            WHERE bot_id = :bot_id AND root = :root
              AND file_path LIKE 'memory/%%'
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

    try:
        async with async_session() as db:
            rows = (await db.execute(sql, {
                "vec": vec_literal,
                "bot_id": bot_id,
                "root": root,
                "query": query,
                "v_limit": vector_candidates,
                "t_limit": text_candidates,
                "rrf_k": RRF_K,
                "top_k": top_k,
            })).all()
    except Exception:
        logger.exception("Hybrid memory search query failed")
        return []

    return [
        MemorySearchResult(file_path=r.file_path, content=r.content, score=r.rrf_score)
        for r in rows
    ]
