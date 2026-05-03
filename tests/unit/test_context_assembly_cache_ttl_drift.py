"""Phase G.6 — context_assembly multi-cache TTL drift seams.

Seam class: multi-actor + silent-UPDATE

context_assembly.py has THREE module-level caches with TWO different TTLs:

  _bot_skill_cache          dict[bot_id → (ts, [ids])]   TTL = 30s
  _core_skill_cache         (ts, [ids]) | None            TTL = 60s
  _integration_skill_cache  dict[type → (ts, [ids])]      TTL = 60s

Two separate invalidators:
  invalidate_bot_skill_cache(bot_id)  — clears ONLY _bot_skill_cache
  invalidate_skill_auto_enroll_cache()— clears ONLY _core + _integration

Drift seams:
- Calling invalidate_bot_skill_cache after a bot-authored skill update does NOT
  clear _core_skill_cache or _integration_skill_cache. If a skill was recently
  moved from bot-authored to file-based (e.g. promoted to a core skill), the
  core cache can serve a stale empty result for up to 60s even after the bot
  cache was correctly invalidated.
- Calling invalidate_skill_auto_enroll_cache after a file sync does NOT clear
  _bot_skill_cache. A bot's per-authored-skill list can remain stale for up
  to 30s after file-sync invalidation.
- The bot cache expires at 30s but the core/integration caches don't expire
  until 60s — in the 30-60s window after a bulk change, the bot cache will
  re-read fresh data while the core cache still serves the old snapshot.
"""
from __future__ import annotations

import time
import uuid
from unittest.mock import patch

import pytest

import app.agent.tool_surface.enrollment as ca
from tests.factories.skills import build_skill


# ---------------------------------------------------------------------------
# Cache reset — prevent state leaking across tests
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
# G.6.1 — TTL asymmetry (structural)
# ---------------------------------------------------------------------------


class TestTtlAsymmetry:
    def test_bot_cache_ttl_shorter_than_core_and_integration(self):
        """Structural: bot cache (30s) expires before core/integration (60s).

        Drift pin: in the 30-60s window after a change, the bot cache re-reads
        fresh DB data while core/integration still serve the pre-change snapshot.
        """
        assert ca._BOT_SKILL_CACHE_TTL == 30.0
        assert ca._SKILL_CACHE_TTL == 60.0
        assert ca._BOT_SKILL_CACHE_TTL < ca._SKILL_CACHE_TTL


# ---------------------------------------------------------------------------
# G.6.2 — Cross-cache invalidation isolation
# ---------------------------------------------------------------------------


class TestCrossCacheInvalidationIsolation:
    def test_invalidate_bot_cache_leaves_core_cache_intact(self):
        """invalidate_bot_skill_cache does NOT clear _core_skill_cache.

        Drift pin: after a bot-authored skill update, the bot invalidator fires
        but the core cache retains its snapshot — a skill promoted to core
        remains invisible via _get_core_skill_ids for up to 60s.
        """
        ca._core_skill_cache = (time.monotonic(), ["core/skill-1"])
        ca._bot_skill_cache["bot-x"] = (time.monotonic(), ["bots/bot-x/skill-a"])

        ca.invalidate_bot_skill_cache("bot-x")

        # Bot cache cleared for bot-x
        assert "bot-x" not in ca._bot_skill_cache
        # Core cache untouched
        assert ca._core_skill_cache is not None
        _, ids = ca._core_skill_cache
        assert ids == ["core/skill-1"]

    def test_invalidate_bot_cache_leaves_integration_cache_intact(self):
        """invalidate_bot_skill_cache does NOT clear _integration_skill_cache."""
        ca._integration_skill_cache["homeassistant"] = (
            time.monotonic(), ["integrations/homeassistant/skill-1"]
        )
        ca._bot_skill_cache["bot-y"] = (time.monotonic(), ["bots/bot-y/skill-b"])

        ca.invalidate_bot_skill_cache("bot-y")

        assert "bot-y" not in ca._bot_skill_cache
        assert "homeassistant" in ca._integration_skill_cache

    def test_invalidate_enroll_cache_leaves_bot_cache_intact(self):
        """invalidate_skill_auto_enroll_cache does NOT clear _bot_skill_cache.

        Drift pin: file-sync fires invalidate_skill_auto_enroll_cache but
        _bot_skill_cache still holds stale bot-authored skill IDs for up to 30s.
        """
        ca._bot_skill_cache["bot-z"] = (time.monotonic(), ["bots/bot-z/old"])
        ca._core_skill_cache = (time.monotonic(), ["core/old"])
        ca._integration_skill_cache["slack"] = (time.monotonic(), ["integrations/slack/s"])

        ca.invalidate_skill_auto_enroll_cache()

        # Core and integration cleared
        assert ca._core_skill_cache is None
        assert ca._integration_skill_cache == {}
        # Bot cache untouched
        assert "bot-z" in ca._bot_skill_cache
        _, ids = ca._bot_skill_cache["bot-z"]
        assert ids == ["bots/bot-z/old"]

    def test_invalidate_all_bot_cache_leaves_core_intact(self):
        """invalidate_bot_skill_cache(None) clears all bot slots but not core."""
        ca._core_skill_cache = (time.monotonic(), ["core/keep-me"])
        ca._bot_skill_cache["bot-1"] = (time.monotonic(), ["bots/bot-1/s"])
        ca._bot_skill_cache["bot-2"] = (time.monotonic(), ["bots/bot-2/s"])

        ca.invalidate_bot_skill_cache(None)

        assert ca._bot_skill_cache == {}
        assert ca._core_skill_cache is not None


# ---------------------------------------------------------------------------
# G.6.3 — Core cache DB behaviour
# ---------------------------------------------------------------------------


class TestCoreCacheDb:
    @pytest.mark.asyncio
    async def test_core_cache_cold_queries_db_and_populates(
        self, db_session, patched_async_sessions
    ):
        """Cold _core_skill_cache queries DB and stores result.

        Core skills: source_type='file', id not prefixed with integrations/ or bots/.
        """
        core_skill = build_skill(
            id=f"skills/core/{uuid.uuid4().hex[:8]}",
            source_type="file",
        )
        db_session.add(core_skill)
        await db_session.commit()

        assert ca._core_skill_cache is None

        result = await ca._get_core_skill_ids()

        assert core_skill.id in result
        assert ca._core_skill_cache is not None
        _, cached = ca._core_skill_cache
        assert core_skill.id in cached

    @pytest.mark.asyncio
    async def test_core_cache_excludes_integration_skills(
        self, db_session, patched_async_sessions
    ):
        """Skills prefixed 'integrations/' are excluded from the core cache query."""
        integration_skill = build_skill(
            id=f"integrations/slack/{uuid.uuid4().hex[:8]}",
            source_type="integration",
        )
        core_skill = build_skill(
            id=f"skills/core/{uuid.uuid4().hex[:8]}",
            source_type="file",
        )
        db_session.add_all([integration_skill, core_skill])
        await db_session.commit()

        result = await ca._get_core_skill_ids()

        assert core_skill.id in result
        assert integration_skill.id not in result

    @pytest.mark.asyncio
    async def test_core_cache_hit_skips_db(self, db_session, patched_async_sessions):
        """Core cache hit within TTL returns stored list without DB query."""
        cached_ids = ["skills/core/fake-id"]
        ca._core_skill_cache = (time.monotonic(), cached_ids)

        with patch("app.db.engine.async_session", side_effect=RuntimeError("DB must not be called")):
            result = await ca._get_core_skill_ids()

        assert result == cached_ids

    @pytest.mark.asyncio
    async def test_core_cache_ttl_expiry_forces_requery(
        self, db_session, patched_async_sessions
    ):
        """Core cache entry older than 60s triggers a fresh DB read."""
        ca._core_skill_cache = (time.monotonic() - 61.0, ["skills/core/stale"])

        fresh_skill = build_skill(
            id=f"skills/core/{uuid.uuid4().hex[:8]}",
            source_type="file",
        )
        db_session.add(fresh_skill)
        await db_session.commit()

        result = await ca._get_core_skill_ids()

        assert fresh_skill.id in result
        assert "skills/core/stale" not in result


# ---------------------------------------------------------------------------
# G.6.4 — Integration cache DB behaviour
# ---------------------------------------------------------------------------


class TestIntegrationCacheDb:
    @pytest.mark.asyncio
    async def test_integration_cache_cold_queries_db_and_populates(
        self, db_session, patched_async_sessions
    ):
        """Cold _integration_skill_cache queries DB for the given integration_type."""
        skill = build_skill(
            id=f"integrations/homeassistant/{uuid.uuid4().hex[:8]}",
            source_type="integration",
        )
        db_session.add(skill)
        await db_session.commit()

        assert "homeassistant" not in ca._integration_skill_cache

        result = await ca._get_integration_skill_ids("homeassistant")

        assert skill.id in result
        assert "homeassistant" in ca._integration_skill_cache
        _, cached = ca._integration_skill_cache["homeassistant"]
        assert skill.id in cached

    @pytest.mark.asyncio
    async def test_integration_cache_scoped_by_type(
        self, db_session, patched_async_sessions
    ):
        """Querying 'slack' returns only slack skills; 'homeassistant' skills excluded."""
        slack_skill = build_skill(
            id=f"integrations/slack/{uuid.uuid4().hex[:8]}",
            source_type="integration",
        )
        ha_skill = build_skill(
            id=f"integrations/homeassistant/{uuid.uuid4().hex[:8]}",
            source_type="integration",
        )
        db_session.add_all([slack_skill, ha_skill])
        await db_session.commit()

        result = await ca._get_integration_skill_ids("slack")

        assert slack_skill.id in result
        assert ha_skill.id not in result

    @pytest.mark.asyncio
    async def test_integration_cache_hit_skips_db(self):
        """Integration cache hit within TTL never touches the DB."""
        cached_ids = ["integrations/slack/fake-skill"]
        ca._integration_skill_cache["slack"] = (time.monotonic(), cached_ids)

        with patch("app.db.engine.async_session", side_effect=RuntimeError("DB must not be called")):
            result = await ca._get_integration_skill_ids("slack")

        assert result == cached_ids

    @pytest.mark.asyncio
    async def test_two_integration_types_cached_independently(
        self, db_session, patched_async_sessions
    ):
        """Each integration_type occupies its own cache slot."""
        slack_skill = build_skill(
            id=f"integrations/slack/{uuid.uuid4().hex[:8]}",
            source_type="integration",
        )
        ha_skill = build_skill(
            id=f"integrations/homeassistant/{uuid.uuid4().hex[:8]}",
            source_type="integration",
        )
        db_session.add_all([slack_skill, ha_skill])
        await db_session.commit()

        slack_result = await ca._get_integration_skill_ids("slack")
        ha_result = await ca._get_integration_skill_ids("homeassistant")

        assert slack_skill.id in slack_result
        assert ha_skill.id not in slack_result
        assert ha_skill.id in ha_result
        assert slack_skill.id not in ha_result
        assert "slack" in ca._integration_skill_cache
        assert "homeassistant" in ca._integration_skill_cache
