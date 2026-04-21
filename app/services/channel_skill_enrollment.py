"""Per-channel skill enrollment service."""
from __future__ import annotations

import time
from typing import Iterable

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import async_session
from app.db.models import ChannelSkillEnrollment


def _upsert_ignore(values: list[dict] | dict):
    pg_stmt = pg_insert(ChannelSkillEnrollment).values(values).on_conflict_do_nothing(
        index_elements=["channel_id", "skill_id"],
    )
    sqlite_stmt = sqlite_insert(ChannelSkillEnrollment).values(values).on_conflict_do_nothing(
        index_elements=["channel_id", "skill_id"],
    )
    return pg_stmt, sqlite_stmt


def _pick_stmt(db: AsyncSession, pg_stmt, sqlite_stmt):
    name = db.bind.dialect.name if db.bind is not None else "postgresql"
    return sqlite_stmt if name == "sqlite" else pg_stmt


_enrolled_cache: dict[str, tuple[float, list[str]]] = {}
_ENROLLED_CACHE_TTL = 300.0


def invalidate_enrolled_cache(channel_id: str | None = None) -> None:
    if channel_id is None:
        _enrolled_cache.clear()
    else:
        _enrolled_cache.pop(channel_id, None)


async def get_enrolled_skill_ids(channel_id: str) -> list[str]:
    now = time.monotonic()
    cached = _enrolled_cache.get(channel_id)
    if cached and (now - cached[0]) < _ENROLLED_CACHE_TTL:
        return cached[1]

    async with async_session() as db:
        rows = (await db.execute(
            select(ChannelSkillEnrollment.skill_id).where(ChannelSkillEnrollment.channel_id == channel_id)
        )).scalars().all()

    result = list(rows)
    _enrolled_cache[channel_id] = (now, result)
    return result


async def get_enrollments(channel_id: str) -> list[ChannelSkillEnrollment]:
    async with async_session() as db:
        rows = (await db.execute(
            select(ChannelSkillEnrollment)
            .where(ChannelSkillEnrollment.channel_id == channel_id)
            .order_by(ChannelSkillEnrollment.enrolled_at.desc())
        )).scalars().all()
    return list(rows)


async def enroll(
    channel_id: str,
    skill_id: str,
    source: str = "manual",
    *,
    db: AsyncSession | None = None,
) -> bool:
    pg_stmt, sqlite_stmt = _upsert_ignore({
        "channel_id": channel_id,
        "skill_id": skill_id,
        "source": source,
    })
    if db is not None:
        result = await db.execute(_pick_stmt(db, pg_stmt, sqlite_stmt))
        invalidate_enrolled_cache(channel_id)
        return bool(result.rowcount)

    async with async_session() as own_db:
        result = await own_db.execute(_pick_stmt(own_db, pg_stmt, sqlite_stmt))
        await own_db.commit()
    invalidate_enrolled_cache(channel_id)
    return bool(result.rowcount)


async def enroll_many(
    channel_id: str,
    skill_ids: Iterable[str],
    source: str = "manual",
    *,
    db: AsyncSession | None = None,
) -> int:
    skill_id_list = [sid for sid in skill_ids if sid]
    if not skill_id_list:
        return 0

    pg_stmt, sqlite_stmt = _upsert_ignore([
        {"channel_id": channel_id, "skill_id": sid, "source": source}
        for sid in skill_id_list
    ])
    if db is not None:
        result = await db.execute(_pick_stmt(db, pg_stmt, sqlite_stmt))
        invalidate_enrolled_cache(channel_id)
        return result.rowcount or 0

    async with async_session() as own_db:
        result = await own_db.execute(_pick_stmt(own_db, pg_stmt, sqlite_stmt))
        await own_db.commit()
    invalidate_enrolled_cache(channel_id)
    return result.rowcount or 0


async def unenroll(
    channel_id: str,
    skill_id: str,
    *,
    db: AsyncSession | None = None,
) -> bool:
    stmt = delete(ChannelSkillEnrollment).where(
        ChannelSkillEnrollment.channel_id == channel_id,
        ChannelSkillEnrollment.skill_id == skill_id,
    )
    if db is not None:
        result = await db.execute(stmt)
        invalidate_enrolled_cache(channel_id)
        return bool(result.rowcount)

    async with async_session() as own_db:
        result = await own_db.execute(stmt)
        await own_db.commit()
    invalidate_enrolled_cache(channel_id)
    return bool(result.rowcount)
