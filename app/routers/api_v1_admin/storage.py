"""Storage breakdown and manual purge — /admin/storage/."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.db.engine import async_session
from app.services.data_retention import (
    RETENTION_TABLES,
    get_purgeable_counts,
    run_data_retention_sweep,
)
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/storage", tags=["Storage"])


class TableStats(BaseModel):
    table: str
    row_count: int
    size_bytes: int | None  # None when pg_total_relation_size unavailable (e.g. SQLite)
    size_display: str | None
    oldest_row: str | None  # ISO timestamp
    purgeable: int


class StorageBreakdown(BaseModel):
    tables: list[TableStats]
    retention_days: int | None
    sweep_interval_s: int


class PurgeResult(BaseModel):
    deleted: dict[str, int]
    total: int


def _fmt_bytes(b: int) -> str:
    if b >= 1_073_741_824:
        return f"{b / 1_073_741_824:.1f} GB"
    if b >= 1_048_576:
        return f"{b / 1_048_576:.1f} MB"
    if b >= 1024:
        return f"{b / 1024:.1f} KB"
    return f"{b} B"


@router.get("/breakdown", response_model=StorageBreakdown)
async def storage_breakdown():
    """Row counts, sizes, oldest row, and purgeable counts per operational table."""
    purgeable = await get_purgeable_counts()
    tables: list[TableStats] = []

    async with async_session() as db:
        for table, date_col, _ in RETENTION_TABLES:
            # Row count
            row = await db.execute(text(f"SELECT COUNT(*) FROM {table}"))
            row_count = row.scalar() or 0

            # Table size (PostgreSQL only)
            size_bytes: int | None = None
            size_display: str | None = None
            try:
                row = await db.execute(
                    text("SELECT pg_total_relation_size(:tbl)"),
                    {"tbl": table},
                )
                size_bytes = row.scalar()
                if size_bytes is not None:
                    size_display = _fmt_bytes(size_bytes)
            except Exception:
                pass  # SQLite or insufficient permissions

            # Oldest row
            oldest: str | None = None
            try:
                row = await db.execute(text(f"SELECT MIN({date_col}) FROM {table}"))
                val = row.scalar()
                if val is not None:
                    oldest = val.isoformat() if hasattr(val, "isoformat") else str(val)
            except Exception:
                pass

            tables.append(TableStats(
                table=table,
                row_count=row_count,
                size_bytes=size_bytes,
                size_display=size_display,
                oldest_row=oldest,
                purgeable=purgeable.get(table, 0),
            ))

    return StorageBreakdown(
        tables=tables,
        retention_days=settings.DATA_RETENTION_DAYS,
        sweep_interval_s=settings.DATA_RETENTION_SWEEP_INTERVAL_S,
    )


@router.post("/purge", response_model=PurgeResult)
async def purge_storage():
    """Manual trigger: purge old rows now using current DATA_RETENTION_DAYS setting."""
    if settings.DATA_RETENTION_DAYS is None:
        return PurgeResult(deleted={}, total=0)

    deleted = await run_data_retention_sweep()
    return PurgeResult(deleted=deleted, total=sum(deleted.values()))
