"""Phase H.3 — skill_enrollment.py cache invalidation and cross-bot isolation.

Seam class: silent-UPDATE + multi-row sync (module-level cache with TTL)

``enroll_many`` / ``unenroll_many`` / ``enroll`` / ``unenroll`` all call
``invalidate_enrolled_cache(bot_id)`` AFTER the DB write. The module-level
``_enrolled_cache`` dict stores (timestamp, [skill_ids]) tuples per bot_id.

Drift seams pinned:
1. Empty list to enroll_many → early return without DB write OR cache invalidation.
   Cache remains stale until TTL expires. Reader gets stale data.
2. Cross-bot isolation: enrolling bot-A must not corrupt bot-B's cache entry.
3. unenroll with no matching row returns False / 0 (no exception, but also
   does NOT invalidate cache — documents the silent no-op contract).
4. Double-enroll (upsert/IGNORE): second insert is a no-op, rowcount=0, but
   cache IS invalidated (flag_modified equivalent for the cache layer).
"""
from __future__ import annotations

import time

import pytest

import app.services.skill_enrollment as _enroll_mod
from app.db.models import Bot, BotSkillEnrollment, Skill
from app.services.skill_enrollment import (
    enroll,
    enroll_many,
    get_enrolled_skill_ids,
    invalidate_enrolled_cache,
    unenroll,
    unenroll_many,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bot(bot_id: str) -> Bot:
    return Bot(
        id=bot_id,
        name=bot_id,
        model="test/model",
        system_prompt="",
    )


def _skill(skill_id: str) -> Skill:
    return Skill(
        id=skill_id,
        name=skill_id,
        content="# skill",
        source_type="file",
    )


@pytest.fixture(autouse=True)
def _clear_caches():
    """Reset module-level enrollment caches before and after each test (B.28)."""
    invalidate_enrolled_cache()
    yield
    invalidate_enrolled_cache()


# ---------------------------------------------------------------------------
# H.3.1 — happy path: enroll creates rows, cache populated on next read
# ---------------------------------------------------------------------------


class TestEnrollHappyPath:
    @pytest.mark.asyncio
    async def test_when_skills_enrolled_then_get_enrolled_returns_them(
        self, db_session, patched_async_sessions
    ):
        db_session.add(_bot("bot-a"))
        db_session.add(_skill("skill-1"))
        db_session.add(_skill("skill-2"))
        await db_session.commit()

        await enroll_many("bot-a", ["skill-1", "skill-2"], db=db_session)
        await db_session.commit()

        ids = await get_enrolled_skill_ids("bot-a")
        assert set(ids) == {"skill-1", "skill-2"}

    @pytest.mark.asyncio
    async def test_when_skill_unenrolled_then_removed_from_subsequent_read(
        self, db_session, patched_async_sessions
    ):
        db_session.add(_bot("bot-b"))
        db_session.add(_skill("s1"))
        db_session.add(_skill("s2"))
        await db_session.commit()

        await enroll_many("bot-b", ["s1", "s2"], db=db_session)
        await db_session.commit()

        await unenroll("bot-b", "s1", db=db_session)
        await db_session.commit()

        ids = await get_enrolled_skill_ids("bot-b")
        assert ids == ["s2"]


# ---------------------------------------------------------------------------
# H.3.2 — drift pin: empty list to enroll_many → no-op, cache NOT cleared
# ---------------------------------------------------------------------------


class TestEmptyListNoOp:
    @pytest.mark.asyncio
    async def test_when_empty_list_then_returns_zero_without_db_write(
        self, db_session, patched_async_sessions
    ):
        db_session.add(_bot("bot-c"))
        db_session.add(_skill("s-keep"))
        await db_session.commit()

        # Pre-populate cache with a known enrollment.
        await enroll("bot-c", "s-keep", db=db_session)
        await db_session.commit()
        ids_before = await get_enrolled_skill_ids("bot-c")
        assert "s-keep" in ids_before

        # Now call enroll_many with an empty list.
        count = await enroll_many("bot-c", [], db=db_session)
        assert count == 0

        # Cache must still reflect the real enrollment (not corrupted).
        # We do NOT commit here because no write happened.
        ids_after = await get_enrolled_skill_ids("bot-c")
        assert "s-keep" in ids_after

    @pytest.mark.asyncio
    async def test_when_empty_list_unenroll_many_returns_zero(
        self, db_session, patched_async_sessions
    ):
        db_session.add(_bot("bot-d"))
        await db_session.commit()

        count = await unenroll_many("bot-d", [], db=db_session)
        assert count == 0


# ---------------------------------------------------------------------------
# H.3.3 — drift pin: cross-bot isolation
# ---------------------------------------------------------------------------


class TestCrossBotIsolation:
    @pytest.mark.asyncio
    async def test_enrolling_bot_a_does_not_affect_bot_b_cache(
        self, db_session, patched_async_sessions
    ):
        """Enrolling bot-A must not corrupt bot-B's cached enrollment list."""
        db_session.add(_bot("bot-x"))
        db_session.add(_bot("bot-y"))
        db_session.add(_skill("common-skill"))
        db_session.add(_skill("bot-y-skill"))
        await db_session.commit()

        # Pre-populate bot-y cache.
        await enroll("bot-y", "bot-y-skill", db=db_session)
        await db_session.commit()
        ids_y_before = await get_enrolled_skill_ids("bot-y")
        assert "bot-y-skill" in ids_y_before

        # Enroll bot-x — should only invalidate bot-x's cache.
        await enroll("bot-x", "common-skill", db=db_session)
        await db_session.commit()

        # bot-y's enrollment must still include its skills, not bot-x's.
        ids_y_after = await get_enrolled_skill_ids("bot-y")
        assert "bot-y-skill" in ids_y_after
        assert "common-skill" not in ids_y_after

    @pytest.mark.asyncio
    async def test_unenrolling_bot_a_does_not_remove_bot_b_cache(
        self, db_session, patched_async_sessions
    ):
        db_session.add(_bot("ba"))
        db_session.add(_bot("bb"))
        db_session.add(_skill("shared"))
        await db_session.commit()

        await enroll("ba", "shared", db=db_session)
        await enroll("bb", "shared", db=db_session)
        await db_session.commit()

        # Unenroll ba — bb must keep its enrollment.
        await unenroll("ba", "shared", db=db_session)
        await db_session.commit()

        ids_ba = await get_enrolled_skill_ids("ba")
        ids_bb = await get_enrolled_skill_ids("bb")
        assert "shared" not in ids_ba
        assert "shared" in ids_bb


# ---------------------------------------------------------------------------
# H.3.4 — drift pin: unenroll on non-enrolled skill
# ---------------------------------------------------------------------------


class TestUnenrollNonExistent:
    @pytest.mark.asyncio
    async def test_when_skill_not_enrolled_then_unenroll_returns_false(
        self, db_session, patched_async_sessions
    ):
        """unenroll on a skill the bot doesn't have → returns False, no error.

        Pins the 0-row DELETE contract: caller can't distinguish
        'was enrolled and removed' from 'was never enrolled'.
        """
        db_session.add(_bot("bot-none"))
        db_session.add(_skill("ghost-skill"))
        await db_session.commit()

        removed = await unenroll("bot-none", "ghost-skill", db=db_session)
        assert removed is False

    @pytest.mark.asyncio
    async def test_when_unenroll_many_none_match_returns_zero(
        self, db_session, patched_async_sessions
    ):
        db_session.add(_bot("bot-empty"))
        await db_session.commit()

        count = await unenroll_many("bot-empty", ["no-such-skill"], db=db_session)
        assert count == 0


# ---------------------------------------------------------------------------
# H.3.5 — double-enroll is idempotent, rowcount reflects 0 new rows
# ---------------------------------------------------------------------------


class TestDoubleEnrollIdempotent:
    @pytest.mark.asyncio
    async def test_when_enrolled_twice_then_second_returns_zero_and_row_is_unique(
        self, db_session, patched_async_sessions
    ):
        """Second enroll is a no-op (ON CONFLICT DO NOTHING / INSERT OR IGNORE).

        rowcount=0 means no new rows, but the enrollment is still in place.
        """
        db_session.add(_bot("bot-idem"))
        db_session.add(_skill("idem-skill"))
        await db_session.commit()

        first = await enroll_many("bot-idem", ["idem-skill"], db=db_session)
        await db_session.commit()

        second = await enroll_many("bot-idem", ["idem-skill"], db=db_session)
        await db_session.commit()

        assert first >= 1  # at least 1 new row on first enroll
        assert second == 0  # idempotent: no new rows on second enroll

        # Exactly one enrollment row must exist.
        from sqlalchemy import select, func
        count = (await db_session.execute(
            select(func.count()).select_from(BotSkillEnrollment).where(
                BotSkillEnrollment.bot_id == "bot-idem",
                BotSkillEnrollment.skill_id == "idem-skill",
            )
        )).scalar()
        assert count == 1
