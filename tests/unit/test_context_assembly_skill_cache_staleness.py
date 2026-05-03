"""F.7 — context_assembly skill-description cache stale-read under invalidation.

Seam class: silent-UPDATE + multi-actor
Suspected drift: Phase B.7 pinned the invalidator (writes to cache are cleared).
The read path is untested for the race: turn A reads cache at t=0, turn B
invalidates at t=1 after a skill edit, turn A continues using stale-pulled
skills. Single-worker, not a DB-level race, but real under concurrent request
handlers. 30s TTL means staleness can persist regardless of invalidation across
workers (already a known Loose End — `_bot_skill_cache is process-local`).

Loose Ends: stale-read window is a known constraint; process-local cache means
multi-worker deployments cannot share invalidations. Pinned as accepted
limitation. No new bugs confirmed — drift contracts documented.

Reference: tests/unit/test_context_assembly_core_gaps.py (Phase B.7 — covers
the invalidator path; this file covers the read path and drift contracts).
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import app.agent.tool_surface.enrollment as ca
from app.db.models import Skill
from tests.factories.skills import build_skill


# ---------------------------------------------------------------------------
# Cache reset — B.28 compliance: prevent cache state leaking across tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_caches():
    ca._bot_skill_cache.clear()
    ca._core_skill_cache = None
    ca._integration_skill_cache.clear()
    yield
    ca._bot_skill_cache.clear()
    ca._core_skill_cache = None
    ca._integration_skill_cache.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bot_skill(bot_id: str, suffix: str | None = None) -> Skill:
    """Build a bot-authored Skill row matching _get_bot_authored_skill_ids query."""
    sfx = suffix or uuid.uuid4().hex[:8]
    return build_skill(
        id=f"bots/{bot_id}/{sfx}",
        source_type="tool",
        archived_at=None,
    )


# ===========================================================================
# Cache hit / miss
# ===========================================================================

class TestCacheHitPath:
    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_list_without_db_query(self):
        """Second call within TTL returns cached list; DB is never touched.

        Drift pin: if the TTL check were removed or inverted, the function would
        query DB on every call — this test catches that regression.
        """
        expected = ["bots/bot-a/skill-1"]
        ca._bot_skill_cache["bot-a"] = (time.monotonic(), expected)

        # Patch DB to raise so any accidental DB query surfaces immediately.
        with patch("app.db.engine.async_session", side_effect=RuntimeError("DB must not be called")):
            result = await ca._get_bot_authored_skill_ids("bot-a")

        assert result == expected

    @pytest.mark.asyncio
    async def test_ttl_expiry_causes_db_requery(self, db_session, patched_async_sessions):
        """Cache entry older than 30s is evicted; function re-queries the DB."""
        # Seed a stale cache entry
        ca._bot_skill_cache["bot-b"] = (time.monotonic() - 31.0, ["bots/bot-b/stale"])

        # Seed a fresh skill in the DB
        skill = _bot_skill("bot-b", "fresh")
        db_session.add(skill)
        await db_session.commit()

        result = await ca._get_bot_authored_skill_ids("bot-b")

        assert result == [skill.id]
        # Cache is now refreshed
        assert ca._bot_skill_cache.get("bot-b") is not None
        _, cached_ids = ca._bot_skill_cache["bot-b"]
        assert cached_ids == [skill.id]

    @pytest.mark.asyncio
    async def test_first_call_queries_db_and_populates_cache(self, db_session, patched_async_sessions):
        """Cold-cache first call fetches from DB and stores result."""
        skill = _bot_skill("bot-c")
        db_session.add(skill)
        await db_session.commit()

        assert "bot-c" not in ca._bot_skill_cache

        result = await ca._get_bot_authored_skill_ids("bot-c")

        assert result == [skill.id]
        assert "bot-c" in ca._bot_skill_cache
        _, cached_ids = ca._bot_skill_cache["bot-c"]
        assert cached_ids == [skill.id]

    @pytest.mark.asyncio
    async def test_second_call_within_ttl_returns_same_list_object(self, db_session, patched_async_sessions):
        """Two calls within TTL return the same list object (no defensive copy)."""
        skill = _bot_skill("bot-d")
        db_session.add(skill)
        await db_session.commit()

        first = await ca._get_bot_authored_skill_ids("bot-d")
        second = await ca._get_bot_authored_skill_ids("bot-d")

        # Same list object — cache returns the reference, not a copy
        assert first is second


# ===========================================================================
# DB filter correctness
# ===========================================================================

class TestDbFilterContracts:
    @pytest.mark.asyncio
    async def test_archived_skill_excluded(self, db_session, patched_async_sessions):
        """Skills with archived_at set are excluded from results."""
        skill = _bot_skill("bot-e")
        skill.archived_at = datetime.now(timezone.utc)
        db_session.add(skill)
        await db_session.commit()

        result = await ca._get_bot_authored_skill_ids("bot-e")

        assert result == []

    @pytest.mark.asyncio
    async def test_non_tool_source_type_excluded(self, db_session, patched_async_sessions):
        """Skills with source_type != 'tool' are excluded."""
        skill = build_skill(
            id=f"bots/bot-f/{uuid.uuid4().hex[:8]}",
            source_type="file",
        )
        db_session.add(skill)
        await db_session.commit()

        result = await ca._get_bot_authored_skill_ids("bot-f")

        assert result == []

    @pytest.mark.asyncio
    async def test_skills_from_other_bots_excluded(self, db_session, patched_async_sessions):
        """Only skills matching the queried bot_id prefix are returned."""
        skill_a = _bot_skill("bot-g")
        skill_other = _bot_skill("bot-other")
        db_session.add(skill_a)
        db_session.add(skill_other)
        await db_session.commit()

        result = await ca._get_bot_authored_skill_ids("bot-g")

        assert result == [skill_a.id]
        assert skill_other.id not in result


# ===========================================================================
# Stale-read drift pins
# ===========================================================================

class TestStaleReadDriftPins:
    @pytest.mark.asyncio
    async def test_stale_local_variable_persists_after_invalidation(self, db_session, patched_async_sessions):
        """Drift pin: once captured in a local variable, a list is not retroactively
        updated when the cache is invalidated.

        Turn A reads at t=0 → captures a reference to the list.
        Turn B invalidates the cache at t=1.
        Turn A's local variable still holds the old list (no post-hoc propagation).

        This is expected Python semantics, but confirms that callers who captured
        `skills = await _get_bot_authored_skill_ids(bot_id)` at turn-start and
        use it throughout the turn will see stale skill IDs if a skill is edited
        mid-turn and invalidated by a concurrent request.
        """
        skill = _bot_skill("bot-h")
        db_session.add(skill)
        await db_session.commit()

        # Turn A: capture the list
        turn_a_skills = await ca._get_bot_authored_skill_ids("bot-h")
        assert turn_a_skills == [skill.id]

        # Concurrent event: invalidate
        ca.invalidate_bot_skill_cache("bot-h")
        assert "bot-h" not in ca._bot_skill_cache

        # Turn A's local variable is unchanged — no magic propagation
        assert turn_a_skills == [skill.id]

    @pytest.mark.asyncio
    async def test_invalidate_all_clears_every_slot_then_next_read_rehits_db(self, db_session, patched_async_sessions):
        """Drift pin: invalidate_bot_skill_cache(None) clears all slots;
        next call re-queries DB for each bot independently.
        """
        skill = _bot_skill("bot-i")
        db_session.add(skill)
        await db_session.commit()

        # Pre-populate cache for two bots
        ca._bot_skill_cache["bot-i"] = (time.monotonic(), [skill.id])
        ca._bot_skill_cache["bot-j"] = (time.monotonic(), ["bots/bot-j/old"])

        ca.invalidate_bot_skill_cache(None)

        assert ca._bot_skill_cache == {}

        # Next read for bot-i hits DB and re-caches
        result = await ca._get_bot_authored_skill_ids("bot-i")
        assert result == [skill.id]
        assert "bot-i" in ca._bot_skill_cache

    @pytest.mark.asyncio
    async def test_concurrent_reads_no_exception(self, db_session, patched_async_sessions):
        """Two concurrent reads via asyncio.gather raise no exception.

        The cache dict is mutated by both coroutines; the last writer wins the
        slot. Both return a valid (possibly different) list — no KeyError,
        RuntimeError, or corruption.
        """
        skill1 = _bot_skill("bot-k", "sk1")
        skill2 = _bot_skill("bot-k", "sk2")
        db_session.add(skill1)
        db_session.add(skill2)
        await db_session.commit()

        results = await asyncio.gather(
            ca._get_bot_authored_skill_ids("bot-k"),
            ca._get_bot_authored_skill_ids("bot-k"),
        )

        # Both results are valid lists; no exception was raised
        assert all(isinstance(r, list) for r in results)
        expected_ids = {skill1.id, skill2.id}
        for r in results:
            assert set(r) == expected_ids
