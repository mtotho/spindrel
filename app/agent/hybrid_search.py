"""Hybrid search utilities: BM25 full-text search + Reciprocal Rank Fusion.

Combines vector cosine similarity results with PostgreSQL ts_rank BM25 results
using RRF to improve retrieval precision.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def reciprocal_rank_fusion(
    *ranked_lists: list[tuple[str, ...]],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Fuse multiple ranked lists using Reciprocal Rank Fusion (RRF).

    Each ranked list is a sequence of items (tuples). Items are identified
    by their full tuple value for deduplication.

    Formula: score(d) = Σ 1/(k + rank_i(d))

    Args:
        *ranked_lists: Variable number of ranked lists (best-first order).
        k: RRF constant (default 60). Higher values weight top results more.

    Returns:
        List of (item_key, rrf_score) sorted by score descending.
        item_key is a string identifier built from the first element of each tuple.
    """
    if k <= 0:
        raise ValueError(f"RRF k must be positive, got {k}")

    scores: dict[tuple, float] = {}  # item tuple -> score

    for ranked_list in ranked_lists:
        for rank, item in enumerate(ranked_list):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank + 1)

    # Sort by score descending
    sorted_items = sorted(scores.keys(), key=lambda t: scores[t], reverse=True)
    return [(item, scores[item]) for item in sorted_items]


def is_postgres_dialect(bind) -> bool:
    """Check if the SQLAlchemy bind is using PostgreSQL."""
    try:
        return bind.dialect.name == "postgresql"
    except Exception:
        return False
