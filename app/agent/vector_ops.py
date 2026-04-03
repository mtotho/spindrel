"""Utility for halfvec-accelerated cosine distance queries.

pgvector 0.7+ supports halfvec (16-bit float) indexes.  By casting both the
column and query vector to ``HALFVEC(dims)`` in the ORDER BY expression,
PostgreSQL uses the smaller halfvec index for the scan while keeping full
float32 precision in the stored data.

On SQLite (used in tests) we fall back to the regular ``cosine_distance()``
method provided by pgvector's SQLAlchemy integration.
"""

import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# Cache the availability check so we only do it once.
_halfvec_available: bool | None = None


def _check_halfvec() -> bool:
    global _halfvec_available
    if _halfvec_available is not None:
        return _halfvec_available
    try:
        from pgvector.sqlalchemy import HALFVEC  # noqa: F401
        # Also verify we're on PostgreSQL — SQLite can't handle halfvec casts
        if "sqlite" in settings.DATABASE_URL.lower():
            _halfvec_available = False
            logger.debug("SQLite detected — using float32 cosine_distance (halfvec requires PostgreSQL)")
            return _halfvec_available
        _halfvec_available = True
    except ImportError:
        _halfvec_available = False
        logger.debug("pgvector HALFVEC type not available — using float32 cosine_distance")
    return _halfvec_available


def halfvec_cosine_distance(column: Any, query_vector: list[float], dims: int | None = None) -> Any:
    """Build a cosine-distance expression that uses halfvec casting for index acceleration.

    Produces SQL like::

        (embedding::halfvec(1536)) <=> (query::halfvec(1536))

    which lets PostgreSQL use a halfvec HNSW/IVFFlat index for the scan.

    Falls back to ``column.cosine_distance(query_vector)`` when HALFVEC
    is not importable (e.g. SQLite tests).

    Parameters
    ----------
    column : mapped column
        SQLAlchemy ORM column with a ``Vector`` type (e.g. ``Document.embedding``).
    query_vector : list[float]
        The query embedding.
    dims : int, optional
        Vector dimensions.  Defaults to ``settings.EMBEDDING_DIMENSIONS``.
    """
    if dims is None:
        dims = settings.EMBEDDING_DIMENSIONS

    if not _check_halfvec():
        return column.cosine_distance(query_vector)

    from pgvector.sqlalchemy import HALFVEC
    from sqlalchemy import type_coerce

    return column.cast(HALFVEC(dims)).cosine_distance(
        type_coerce(query_vector, HALFVEC(dims))
    )
