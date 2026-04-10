"""Per-bot skill enrollment service.

Phase 3 of the Skill Simplification track. The `bot_skill_enrollment` table
holds each bot's persistent working set of skills. This module is the single
source of truth for reading, writing, and caching enrollments.

Source values stored on each row:
  - 'starter'   — auto-added on bot creation from the curated default set
  - 'fetched'   — promoted from a successful get_skill() call
  - 'manual'    — added by a human via the bot UI
  - 'migration' — backfilled for an existing bot when Phase 3 first ran
  - 'authored'  — bot-authored skill discovered via file_sync
  - 'auto'      — conditional auto-enrollment (e.g. when a bot joins a shared workspace)
"""
from __future__ import annotations

import logging
import time
from typing import Iterable

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import async_session
from app.db.models import BotSkillEnrollment, Skill

logger = logging.getLogger(__name__)


def _upsert_ignore(values: list[dict] | dict):
    """Build an INSERT ... ON CONFLICT DO NOTHING that works on PG and SQLite.

    SQLAlchemy's `dialects.postgresql.insert` only compiles for Postgres; the
    sqlite dialect has its own `insert`. We can't pick one statically because
    unit tests run on aiosqlite while production runs on Postgres. The dialect
    is decided at execute time by checking the bound session's dialect name —
    this helper only builds the statement; the caller passes whichever bind it
    has.
    """
    # Returns a tuple of (pg_stmt, sqlite_stmt) — the caller picks based on
    # dialect. We build both so the helper stays pure (no DB lookup).
    pg_stmt = pg_insert(BotSkillEnrollment).values(values).on_conflict_do_nothing(
        index_elements=["bot_id", "skill_id"],
    )
    sqlite_stmt = sqlite_insert(BotSkillEnrollment).values(values).on_conflict_do_nothing(
        index_elements=["bot_id", "skill_id"],
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
    """Drop cached enrolled-skill lists. Called after enrollment changes."""
    if bot_id is None:
        _enrolled_cache.clear()
    else:
        _enrolled_cache.pop(bot_id, None)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

async def get_enrolled_skill_ids(bot_id: str) -> list[str]:
    """Return the list of enrolled skill IDs for a bot, cached for 5 min."""
    now = time.monotonic()
    cached = _enrolled_cache.get(bot_id)
    if cached and (now - cached[0]) < _ENROLLED_CACHE_TTL:
        return cached[1]

    async with async_session() as db:
        rows = (await db.execute(
            select(BotSkillEnrollment.skill_id).where(BotSkillEnrollment.bot_id == bot_id)
        )).scalars().all()

    result = list(rows)
    _enrolled_cache[bot_id] = (now, result)
    return result


async def get_enrollments(bot_id: str) -> list[BotSkillEnrollment]:
    """Return full enrollment rows for a bot (skill_id, source, enrolled_at)."""
    async with async_session() as db:
        rows = (await db.execute(
            select(BotSkillEnrollment)
            .where(BotSkillEnrollment.bot_id == bot_id)
            .order_by(BotSkillEnrollment.enrolled_at.desc())
        )).scalars().all()
    return list(rows)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

async def enroll(
    bot_id: str,
    skill_id: str,
    source: str = "manual",
    *,
    db: AsyncSession | None = None,
) -> bool:
    """Enroll a single skill for a bot. Idempotent (ON CONFLICT DO NOTHING).

    Returns True if a new row was inserted, False if it already existed.
    """
    pg_stmt, sqlite_stmt = _upsert_ignore({
        "bot_id": bot_id,
        "skill_id": skill_id,
        "source": source,
    })

    if db is not None:
        result = await db.execute(_pick_stmt(db, pg_stmt, sqlite_stmt))
        # caller commits
        invalidate_enrolled_cache(bot_id)
        return bool(result.rowcount)

    async with async_session() as own_db:
        result = await own_db.execute(_pick_stmt(own_db, pg_stmt, sqlite_stmt))
        await own_db.commit()
    invalidate_enrolled_cache(bot_id)
    return bool(result.rowcount)


async def enroll_many(
    bot_id: str,
    skill_ids: Iterable[str],
    source: str = "manual",
    *,
    db: AsyncSession | None = None,
) -> int:
    """Enroll a batch of skills for a bot. Idempotent.

    Returns the number of newly inserted rows.
    """
    skill_id_list = [sid for sid in skill_ids if sid]
    if not skill_id_list:
        return 0

    pg_stmt, sqlite_stmt = _upsert_ignore([
        {"bot_id": bot_id, "skill_id": sid, "source": source}
        for sid in skill_id_list
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
    skill_id: str,
    *,
    db: AsyncSession | None = None,
) -> bool:
    """Remove a single enrollment. Returns True if a row was deleted."""
    stmt = delete(BotSkillEnrollment).where(
        BotSkillEnrollment.bot_id == bot_id,
        BotSkillEnrollment.skill_id == skill_id,
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
    skill_ids: Iterable[str],
    *,
    db: AsyncSession | None = None,
) -> int:
    """Remove a batch of enrollments. Returns the number of rows deleted."""
    skill_id_list = [sid for sid in skill_ids if sid]
    if not skill_id_list:
        return 0
    stmt = delete(BotSkillEnrollment).where(
        BotSkillEnrollment.bot_id == bot_id,
        BotSkillEnrollment.skill_id.in_(skill_id_list),
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
# Starter pack + bot creation hook
# ---------------------------------------------------------------------------

async def enroll_starter_pack(
    bot_id: str,
    *,
    db: AsyncSession | None = None,
) -> int:
    """Enroll the starter pack for a freshly created bot.

    Skips IDs that don't exist in the skills table to avoid FK violations
    when a release ships with a starter ID that hasn't been seeded yet.
    """
    from app.config import STARTER_SKILL_IDS

    starter = list(STARTER_SKILL_IDS)
    if not starter:
        return 0

    # Filter to skills that actually exist in the catalog
    if db is not None:
        existing = (await db.execute(
            select(Skill.id).where(Skill.id.in_(starter))
        )).scalars().all()
    else:
        async with async_session() as own_db:
            existing = (await own_db.execute(
                select(Skill.id).where(Skill.id.in_(starter))
            )).scalars().all()

    valid = [sid for sid in starter if sid in set(existing)]
    if not valid:
        logger.warning(
            "Starter pack for bot %s: none of %d declared skills exist in catalog",
            bot_id, len(starter),
        )
        return 0

    inserted = await enroll_many(bot_id, valid, source="starter", db=db)
    logger.info("Enrolled %d/%d starter skills for bot %s", inserted, len(valid), bot_id)
    return inserted


async def migrate_existing_bot(
    bot_id: str,
    auto_enrolled_ids: Iterable[str],
    *,
    db: AsyncSession | None = None,
) -> int:
    """Backfill enrollments for an existing bot.

    Used by the data migration step. Inserts the union of:
      - the starter pack
      - whatever skills the bot was auto-enrolled in on migration day

    Skills are inserted with source='migration' so the hygiene loop and UI
    can distinguish them from intentional starter additions.
    """
    from app.config import STARTER_SKILL_IDS

    union = set(STARTER_SKILL_IDS) | set(auto_enrolled_ids)
    if not union:
        return 0

    # Filter to existing skills
    if db is not None:
        existing = (await db.execute(
            select(Skill.id).where(Skill.id.in_(list(union)))
        )).scalars().all()
    else:
        async with async_session() as own_db:
            existing = (await own_db.execute(
                select(Skill.id).where(Skill.id.in_(list(union)))
            )).scalars().all()

    valid = [sid for sid in union if sid in set(existing)]
    if not valid:
        return 0

    return await enroll_many(bot_id, valid, source="migration", db=db)
