"""Phase N.3 — channel_skill_enrollment.py drift seams.

Seam class: silent-UPDATE + multi-row sync + orphan pointer + cross-actor.

``enroll`` / ``enroll_many`` / ``unenroll`` all call
``invalidate_enrolled_cache(channel_id)`` AFTER the DB write. The module-level
``_enrolled_cache`` dict stores (timestamp, [skill_ids]) tuples keyed by
channel_id, with a 300s TTL.

Drift seams pinned:
1. Empty list to enroll_many → early return without DB write OR cache touch.
2. Cross-channel isolation: enrolling channel-A must not corrupt channel-B's
   cached list.
3. unenroll on a non-enrolled skill returns False, no error, cache still
   invalidated (silent no-op contract).
4. Double-enroll (ON CONFLICT DO NOTHING) is idempotent — second call
   returns 0, row count stays at 1.
5. Orphan pointer: channel row cascaded away leaves stale cache behind
   (cascade FK on DB side; module cache is manual).
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

import app.services.channel_skill_enrollment as _enroll_mod
from app.db.models import Channel, ChannelSkillEnrollment
from app.services.channel_skill_enrollment import (
    enroll,
    enroll_many,
    get_enrolled_skill_ids,
    invalidate_enrolled_cache,
    unenroll,
)
from tests.factories import build_channel, build_skill


@pytest.fixture(autouse=True)
def _clear_cache():
    invalidate_enrolled_cache()
    yield
    invalidate_enrolled_cache()


async def _seed_channel_and_skills(
    db_session, *, skill_ids: list[str]
) -> str:
    channel = build_channel()
    db_session.add(channel)
    for sid in skill_ids:
        db_session.add(build_skill(id=sid))
    await db_session.commit()
    return str(channel.id)


class TestEnrollHappyPath:
    @pytest.mark.asyncio
    async def test_enroll_many_then_get_enrolled_returns_all(
        self, db_session, patched_async_sessions
    ):
        channel_id = await _seed_channel_and_skills(
            db_session, skill_ids=["skills/alpha", "skills/beta"]
        )

        inserted = await enroll_many(
            channel_id, ["skills/alpha", "skills/beta"], db=db_session
        )
        await db_session.commit()

        assert inserted >= 1
        ids = await get_enrolled_skill_ids(channel_id)
        assert set(ids) == {"skills/alpha", "skills/beta"}

    @pytest.mark.asyncio
    async def test_unenroll_removes_from_subsequent_read(
        self, db_session, patched_async_sessions
    ):
        channel_id = await _seed_channel_and_skills(
            db_session, skill_ids=["skills/a", "skills/b"]
        )

        await enroll_many(channel_id, ["skills/a", "skills/b"], db=db_session)
        await db_session.commit()

        removed = await unenroll(channel_id, "skills/a", db=db_session)
        await db_session.commit()

        assert removed is True
        ids = await get_enrolled_skill_ids(channel_id)
        assert ids == ["skills/b"]


class TestEmptyListNoOp:
    @pytest.mark.asyncio
    async def test_enroll_many_with_empty_list_is_no_op(
        self, db_session, patched_async_sessions
    ):
        """enroll_many([]) short-circuits before touching DB or cache."""
        channel_id = await _seed_channel_and_skills(
            db_session, skill_ids=["skills/keep"]
        )
        await enroll(channel_id, "skills/keep", db=db_session)
        await db_session.commit()

        ids_before = await get_enrolled_skill_ids(channel_id)
        assert "skills/keep" in ids_before

        count = await enroll_many(channel_id, [], db=db_session)
        assert count == 0

        ids_after = await get_enrolled_skill_ids(channel_id)
        assert "skills/keep" in ids_after

    @pytest.mark.asyncio
    async def test_enroll_many_with_falsy_ids_filtered_before_insert(
        self, db_session, patched_async_sessions
    ):
        """Empty-string skill_ids are stripped and don't reach INSERT."""
        channel_id = await _seed_channel_and_skills(
            db_session, skill_ids=["skills/real"]
        )

        count = await enroll_many(channel_id, ["", None, "skills/real"], db=db_session)  # type: ignore[list-item]
        await db_session.commit()

        assert count == 1
        ids = await get_enrolled_skill_ids(channel_id)
        assert ids == ["skills/real"]


class TestCrossChannelIsolation:
    @pytest.mark.asyncio
    async def test_enrolling_channel_a_does_not_affect_channel_b_cache(
        self, db_session, patched_async_sessions
    ):
        """Mutating channel-A's enrollments must not corrupt channel-B's cache."""
        channel_a = build_channel()
        channel_b = build_channel()
        db_session.add_all([channel_a, channel_b])
        db_session.add(build_skill(id="skills/shared"))
        db_session.add(build_skill(id="skills/only-b"))
        await db_session.commit()

        a_id = str(channel_a.id)
        b_id = str(channel_b.id)

        # Warm channel-B cache first.
        await enroll(b_id, "skills/only-b", db=db_session)
        await db_session.commit()
        ids_b_before = await get_enrolled_skill_ids(b_id)
        assert "skills/only-b" in ids_b_before

        # Enroll channel-A. Should only invalidate A's cache.
        await enroll(a_id, "skills/shared", db=db_session)
        await db_session.commit()

        ids_b_after = await get_enrolled_skill_ids(b_id)
        assert "skills/only-b" in ids_b_after
        assert "skills/shared" not in ids_b_after

    @pytest.mark.asyncio
    async def test_unenrolling_channel_a_does_not_remove_channel_b_row(
        self, db_session, patched_async_sessions
    ):
        channel_a = build_channel()
        channel_b = build_channel()
        db_session.add_all([channel_a, channel_b])
        db_session.add(build_skill(id="skills/shared"))
        await db_session.commit()

        a_id = str(channel_a.id)
        b_id = str(channel_b.id)

        await enroll(a_id, "skills/shared", db=db_session)
        await enroll(b_id, "skills/shared", db=db_session)
        await db_session.commit()

        await unenroll(a_id, "skills/shared", db=db_session)
        await db_session.commit()

        ids_a = await get_enrolled_skill_ids(a_id)
        ids_b = await get_enrolled_skill_ids(b_id)
        assert "skills/shared" not in ids_a
        assert "skills/shared" in ids_b


class TestUnenrollNonExistent:
    @pytest.mark.asyncio
    async def test_unenroll_non_enrolled_skill_returns_false(
        self, db_session, patched_async_sessions
    ):
        """unenroll on a skill the channel doesn't have → False, no error."""
        channel_id = await _seed_channel_and_skills(
            db_session, skill_ids=["skills/ghost"]
        )

        removed = await unenroll(channel_id, "skills/ghost", db=db_session)
        assert removed is False


class TestDoubleEnrollIdempotent:
    @pytest.mark.asyncio
    async def test_double_enroll_keeps_one_row(
        self, db_session, patched_async_sessions
    ):
        """Second enroll is ON CONFLICT DO NOTHING; row count stays at 1."""
        channel_id = await _seed_channel_and_skills(
            db_session, skill_ids=["skills/idem"]
        )

        first = await enroll_many(channel_id, ["skills/idem"], db=db_session)
        await db_session.commit()
        second = await enroll_many(channel_id, ["skills/idem"], db=db_session)
        await db_session.commit()

        assert first >= 1
        assert second == 0

        count = (
            await db_session.execute(
                select(func.count())
                .select_from(ChannelSkillEnrollment)
                .where(
                    ChannelSkillEnrollment.channel_id == channel_id,
                    ChannelSkillEnrollment.skill_id == "skills/idem",
                )
            )
        ).scalar()
        assert count == 1


class TestOrphanPointerCacheStaleness:
    @pytest.mark.asyncio
    async def test_out_of_band_row_delete_leaves_stale_cache_entry(
        self, db_session, patched_async_sessions
    ):
        """DB rows removed out-of-band don't invalidate the module cache.

        Pins the silent-UPDATE seam: FK cascades (or any direct DELETE that
        does not go through ``unenroll``) remove enrollment rows, but the
        module-level ``_enrolled_cache`` still serves the pre-delete list
        for up to ``_ENROLLED_CACHE_TTL`` seconds. The mitigation is either a
        channel-delete hook that calls ``invalidate_enrolled_cache(channel_id)``
        or shrinking the TTL. Pinning the current behavior as bug-shaped so a
        future fix flips the assertion.
        """
        channel_id = await _seed_channel_and_skills(
            db_session, skill_ids=["skills/x"]
        )
        await enroll(channel_id, "skills/x", db=db_session)
        await db_session.commit()

        # Warm the cache.
        ids_before = await get_enrolled_skill_ids(channel_id)
        assert "skills/x" in ids_before
        assert channel_id in _enroll_mod._enrolled_cache

        # Simulate an out-of-band delete (FK cascade, migration, admin SQL)
        # that bypasses the service layer.
        from sqlalchemy import delete as sa_delete

        await db_session.execute(
            sa_delete(ChannelSkillEnrollment).where(
                ChannelSkillEnrollment.channel_id == channel_id
            )
        )
        await db_session.commit()

        # DB truth: enrollment row is gone.
        remaining = (
            await db_session.execute(
                select(func.count())
                .select_from(ChannelSkillEnrollment)
                .where(ChannelSkillEnrollment.channel_id == channel_id)
            )
        ).scalar()
        assert remaining == 0

        # Cache truth (BUG-SHAPED BEHAVIOR): still lists the old skill.
        # If we later add a cache-invalidation hook on channel deletion,
        # flip this to ``assert "skills/x" not in ids_after``.
        ids_after = await get_enrolled_skill_ids(channel_id)
        assert "skills/x" in ids_after, (
            "regression guard: out-of-band row delete does not auto-invalidate "
            "the channel_skill_enrollment module cache"
        )
