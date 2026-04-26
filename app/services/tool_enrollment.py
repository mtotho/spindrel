"""Per-bot tool enrollment service.

Mirrors skill_enrollment.py for tools. The `bot_tool_enrollment` table
holds each bot's persistent working set of tools. This module is the single
source of truth for reading, writing, and caching tool enrollments.

Source values stored on each row:
  - 'starter'  — auto-added on bot creation from the bot's local_tools
  - 'fetched'  — promoted from a successful tool call
  - 'manual'   — added by a human via the bot UI
"""
from __future__ import annotations

import logging
import time
from typing import Iterable

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import async_session
from app.db.models import BotToolEnrollment

logger = logging.getLogger(__name__)


def _upsert_ignore(values: list[dict] | dict):
    """Build INSERT ... ON CONFLICT DO NOTHING for PG and SQLite."""
    pg_stmt = pg_insert(BotToolEnrollment).values(values).on_conflict_do_nothing(
        index_elements=["bot_id", "tool_name"],
    )
    sqlite_stmt = sqlite_insert(BotToolEnrollment).values(values).on_conflict_do_nothing(
        index_elements=["bot_id", "tool_name"],
    )
    return pg_stmt, sqlite_stmt


def _pick_stmt(db: AsyncSession, pg_stmt, sqlite_stmt):
    """Return the statement matching the session's dialect."""
    name = db.bind.dialect.name if db.bind is not None else "postgresql"
    return sqlite_stmt if name == "sqlite" else pg_stmt


# ---------------------------------------------------------------------------
# Per-bot enrolled-list cache
# ---------------------------------------------------------------------------
_enrolled_cache: dict[str, tuple[float, list[str]]] = {}
_ENROLLED_CACHE_TTL = 300.0  # 5 minutes


def invalidate_enrolled_cache(bot_id: str | None = None) -> None:
    """Drop cached enrolled-tool lists. Called after enrollment changes."""
    if bot_id is None:
        _enrolled_cache.clear()
    else:
        _enrolled_cache.pop(bot_id, None)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

async def get_enrolled_tool_names(bot_id: str) -> list[str]:
    """Return the list of enrolled tool names for a bot, cached for 5 min."""
    now = time.monotonic()
    cached = _enrolled_cache.get(bot_id)
    if cached and (now - cached[0]) < _ENROLLED_CACHE_TTL:
        return cached[1]

    async with async_session() as db:
        rows = (await db.execute(
            select(BotToolEnrollment.tool_name).where(BotToolEnrollment.bot_id == bot_id)
        )).scalars().all()

    result = list(rows)
    _enrolled_cache[bot_id] = (now, result)
    return result


async def get_enrollments(bot_id: str) -> list[BotToolEnrollment]:
    """Return full enrollment rows for a bot (tool_name, source, enrolled_at)."""
    async with async_session() as db:
        rows = (await db.execute(
            select(BotToolEnrollment)
            .where(BotToolEnrollment.bot_id == bot_id)
            .order_by(BotToolEnrollment.enrolled_at.desc())
        )).scalars().all()
    return list(rows)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

async def enroll(
    bot_id: str,
    tool_name: str,
    source: str = "manual",
    *,
    db: AsyncSession | None = None,
) -> bool:
    """Enroll a single tool for a bot. Idempotent (ON CONFLICT DO NOTHING).

    Returns True if a new row was inserted, False if it already existed.
    """
    pg_stmt, sqlite_stmt = _upsert_ignore({
        "bot_id": bot_id,
        "tool_name": tool_name,
        "source": source,
    })

    if db is not None:
        result = await db.execute(_pick_stmt(db, pg_stmt, sqlite_stmt))
        invalidate_enrolled_cache(bot_id)
        return bool(result.rowcount)

    async with async_session() as own_db:
        result = await own_db.execute(_pick_stmt(own_db, pg_stmt, sqlite_stmt))
        await own_db.commit()
    invalidate_enrolled_cache(bot_id)
    return bool(result.rowcount)


async def enroll_many(
    bot_id: str,
    tool_names: Iterable[str],
    source: str = "manual",
    *,
    db: AsyncSession | None = None,
) -> int:
    """Enroll a batch of tools for a bot. Idempotent.

    Returns the number of newly inserted rows.
    """
    name_list = [n for n in tool_names if n]
    if not name_list:
        return 0

    pg_stmt, sqlite_stmt = _upsert_ignore([
        {"bot_id": bot_id, "tool_name": n, "source": source}
        for n in name_list
    ])

    if db is not None:
        result = await db.execute(_pick_stmt(db, pg_stmt, sqlite_stmt))
        invalidate_enrolled_cache(bot_id)
        return result.rowcount or 0

    async with async_session() as own_db:
        result = await own_db.execute(_pick_stmt(own_db, pg_stmt, sqlite_stmt))
        await own_db.commit()
    invalidate_enrolled_cache(bot_id)
    return result.rowcount or 0


async def unenroll(
    bot_id: str,
    tool_name: str,
    *,
    db: AsyncSession | None = None,
) -> bool:
    """Remove a single enrollment. Returns True if a row was deleted."""
    stmt = delete(BotToolEnrollment).where(
        BotToolEnrollment.bot_id == bot_id,
        BotToolEnrollment.tool_name == tool_name,
    )
    if db is not None:
        result = await db.execute(stmt)
        invalidate_enrolled_cache(bot_id)
        return bool(result.rowcount)

    async with async_session() as own_db:
        result = await own_db.execute(stmt)
        await own_db.commit()
    invalidate_enrolled_cache(bot_id)
    return bool(result.rowcount)


async def unenroll_many(
    bot_id: str,
    tool_names: Iterable[str],
    *,
    db: AsyncSession | None = None,
) -> int:
    """Remove a batch of enrollments. Returns the number of rows deleted."""
    name_list = [n for n in tool_names if n]
    if not name_list:
        return 0
    stmt = delete(BotToolEnrollment).where(
        BotToolEnrollment.bot_id == bot_id,
        BotToolEnrollment.tool_name.in_(name_list),
    )
    if db is not None:
        result = await db.execute(stmt)
        invalidate_enrolled_cache(bot_id)
        return result.rowcount or 0

    async with async_session() as own_db:
        result = await own_db.execute(stmt)
        await own_db.commit()
    invalidate_enrolled_cache(bot_id)
    return result.rowcount or 0


# ---------------------------------------------------------------------------
# Usage telemetry
# ---------------------------------------------------------------------------

def _record_use_stmts(bot_id: str, tool_name: str):
    """Build dialect-specific INSERT ... ON CONFLICT DO UPDATE for usage."""
    base_values = {
        "bot_id": bot_id,
        "tool_name": tool_name,
        "source": "fetched",
        "fetch_count": 1,
        "last_used_at": func.now(),
    }
    pg_stmt = pg_insert(BotToolEnrollment).values(**base_values)
    pg_stmt = pg_stmt.on_conflict_do_update(
        index_elements=["bot_id", "tool_name"],
        set_={
            "fetch_count": BotToolEnrollment.fetch_count + 1,
            "last_used_at": func.now(),
        },
    )

    sqlite_stmt = sqlite_insert(BotToolEnrollment).values(**base_values)
    sqlite_stmt = sqlite_stmt.on_conflict_do_update(
        index_elements=["bot_id", "tool_name"],
        set_={
            "fetch_count": BotToolEnrollment.fetch_count + 1,
            "last_used_at": func.now(),
        },
    )
    return pg_stmt, sqlite_stmt


async def record_use(
    bot_id: str,
    tool_name: str,
    *,
    db: AsyncSession | None = None,
) -> None:
    """Record a successful tool invocation.

    Upserts the enrollment row: increments ``fetch_count`` and stamps
    ``last_used_at = now()``. Creates a ``source='fetched'`` row if one does
    not exist (matches the previous post-call enroll behavior).

    Strict superset of ``enroll(source='fetched')`` — call this from the
    dispatcher's success path instead of ``enroll`` so that usage telemetry
    accumulates on every successful call (incl. pinned tools that were
    never enrolled through semantic discovery).
    """
    if not bot_id or not tool_name:
        return

    pg_stmt, sqlite_stmt = _record_use_stmts(bot_id, tool_name)

    if db is not None:
        await db.execute(_pick_stmt(db, pg_stmt, sqlite_stmt))
        invalidate_enrolled_cache(bot_id)
        return

    async with async_session() as own_db:
        await own_db.execute(_pick_stmt(own_db, pg_stmt, sqlite_stmt))
        await own_db.commit()
    invalidate_enrolled_cache(bot_id)


async def record_use_many(
    bot_id: str,
    tool_names: Iterable[str],
    *,
    db: AsyncSession | None = None,
) -> None:
    """Batch ``record_use`` for multiple tool invocations.

    Counts duplicates so a tool called N times in one turn bumps
    ``fetch_count`` by N. One DB round-trip per unique tool.
    """
    from collections import Counter

    counts = Counter(n for n in tool_names if n)
    if not bot_id or not counts:
        return

    async def _apply(session: AsyncSession) -> None:
        for name, n in counts.items():
            base_values = {
                "bot_id": bot_id,
                "tool_name": name,
                "source": "fetched",
                "fetch_count": n,
                "last_used_at": func.now(),
            }
            pg_stmt = pg_insert(BotToolEnrollment).values(**base_values)
            pg_stmt = pg_stmt.on_conflict_do_update(
                index_elements=["bot_id", "tool_name"],
                set_={
                    "fetch_count": BotToolEnrollment.fetch_count + pg_stmt.excluded.fetch_count,
                    "last_used_at": pg_stmt.excluded.last_used_at,
                },
            )
            sqlite_stmt = sqlite_insert(BotToolEnrollment).values(**base_values)
            sqlite_stmt = sqlite_stmt.on_conflict_do_update(
                index_elements=["bot_id", "tool_name"],
                set_={
                    "fetch_count": BotToolEnrollment.fetch_count + sqlite_stmt.excluded.fetch_count,
                    "last_used_at": sqlite_stmt.excluded.last_used_at,
                },
            )
            await session.execute(_pick_stmt(session, pg_stmt, sqlite_stmt))

    if db is not None:
        await _apply(db)
        invalidate_enrolled_cache(bot_id)
        return

    async with async_session() as own_db:
        await _apply(own_db)
        await own_db.commit()
    invalidate_enrolled_cache(bot_id)


# ---------------------------------------------------------------------------
# Starter enrollment (bot creation hook)
# ---------------------------------------------------------------------------

async def enroll_starter_tools(
    bot_id: str,
    local_tools: list[str],
    *,
    db: AsyncSession | None = None,
) -> int:
    """Enroll a bot's declared local_tools as 'starter' enrollments.

    Called at bot creation so that declared tools are in the working set
    from turn 1 without needing semantic discovery.
    """
    if not local_tools:
        return 0
    return await enroll_many(bot_id, local_tools, source="starter", db=db)
