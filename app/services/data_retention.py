"""Data retention sweep — deletes old rows from operational tables."""

import asyncio
import logging
import re

from sqlalchemy import text

from app.config import settings
from app.db.engine import async_session

logger = logging.getLogger(__name__)

# Table registry: (table_name, date_column, status_filter_sql or None)
# Status filters ensure running/pending/active rows are never deleted.
RETENTION_TABLES: list[tuple[str, str, str | None]] = [
    ("trace_events", "created_at", None),
    ("tool_calls", "created_at", None),
    ("model_fallback_events", "created_at", None),
    ("tool_approvals", "created_at", None),
    ("compaction_logs", "created_at", None),
    ("heartbeat_runs", "run_at", "status != 'running'"),
    ("workflow_runs", "created_at", "status IN ('completed', 'failed', 'cancelled')"),
    ("tasks", "created_at", "status IN ('complete', 'failed', 'cancelled')"),
    ("webhook_deliveries", "created_at", None),
]

# Defense-in-depth: validate that all table/column names in RETENTION_TABLES
# are safe SQL identifiers. Prevents injection if someone adds a configurable name.
_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
for _t, _dc, _sf in RETENTION_TABLES:
    assert _IDENT_RE.match(_t), f"Invalid table name in RETENTION_TABLES: {_t}"
    assert _IDENT_RE.match(_dc), f"Invalid column name in RETENTION_TABLES: {_dc}"


def _build_where(date_col: str, days: int, status_filter: str | None) -> str:
    """Build WHERE clause for a retention query."""
    clauses = [f"{date_col} < now() - ('{days} days')::interval"]
    if status_filter:
        clauses.append(status_filter)
    return " AND ".join(clauses)


async def run_data_retention_sweep(retention_days: int | None = None) -> dict[str, int]:
    """DELETE old rows from operational tables. Returns per-table deleted counts.

    Each table is purged in its own session/transaction so that a failure
    in one table does not abort the rest.

    Args:
        retention_days: Override; if None, reads from settings.DATA_RETENTION_DAYS.
                        If that is also None, returns empty (retention disabled).
    """
    days = retention_days if retention_days is not None else settings.DATA_RETENTION_DAYS
    if days is None:
        logger.debug("Data retention disabled (DATA_RETENTION_DAYS not set)")
        return {}

    deleted: dict[str, int] = {}

    for table, date_col, status_filter in RETENTION_TABLES:
        where = _build_where(date_col, days, status_filter)
        sql = f"DELETE FROM {table} WHERE {where}"
        try:
            async with async_session() as db:
                result = await db.execute(text(sql))
                count = result.rowcount
                await db.commit()
            if count:
                logger.info("Data retention: deleted %d rows from %s", count, table)
            deleted[table] = count
        except Exception:
            logger.exception("Data retention: failed to purge %s", table)
            deleted[table] = 0

    total = sum(deleted.values())
    if total:
        logger.info("Data retention sweep complete: %d total rows deleted", total)
    else:
        logger.debug("Data retention sweep complete: nothing to purge")

    return deleted


async def get_purgeable_counts(retention_days: int | None = None) -> dict[str, int]:
    """SELECT COUNT of rows that would be purged per table."""
    days = retention_days if retention_days is not None else settings.DATA_RETENTION_DAYS
    if days is None:
        return {table: 0 for table, _, _ in RETENTION_TABLES}

    counts: dict[str, int] = {}

    async with async_session() as db:
        for table, date_col, status_filter in RETENTION_TABLES:
            where = _build_where(date_col, days, status_filter)
            sql = f"SELECT COUNT(*) FROM {table} WHERE {where}"
            try:
                result = await db.execute(text(sql))
                counts[table] = result.scalar() or 0
            except Exception:
                logger.exception("Data retention: failed to count %s", table)
                counts[table] = 0

    return counts


async def data_retention_worker():
    """Background loop: runs purge sweep on a configurable interval."""
    logger.info("Data retention worker started")
    while True:
        # Re-read interval each iteration so admin UI changes take effect
        interval = settings.DATA_RETENTION_SWEEP_INTERVAL_S
        await asyncio.sleep(interval)
        try:
            await run_data_retention_sweep()
        except Exception:
            logger.exception("Data retention sweep failed")
