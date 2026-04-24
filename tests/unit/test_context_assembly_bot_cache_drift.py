"""Phase N.7 — context_assembly bot-authored skill cache drift seams.

Companion to ``test_context_assembly_cache_ttl_drift.py`` (G.6), which pinned
the TTL asymmetry + cross-cache invalidation isolation seams. This file
widens coverage into seams G.6 deliberately skipped:

  1. ``_get_bot_authored_skill_ids`` DB filter shape — `source_type='tool'`
     + `archived_at IS NULL` + `bots/<bot_id>/` prefix scope. A refactor that
     relaxes any of the three filters silently widens/narrows the bot-authored
     skill set.
  2. Empty-result caching — a bot with zero bot-authored skills caches ``[]``
     so the next call within TTL does NOT re-query (thundering-herd pin).
  3. Multi-bot isolation — bot A's cache slot never leaks into bot B's
     lookup; ``invalidate_bot_skill_cache("bot-a")`` leaves bot-b untouched.
  4. ``invalidate_skill_auto_enroll_cache`` silent-swallow — if the nested
     ``invalidate_enrolled_cache`` call raises, core + integration caches are
     STILL cleared and the raise is logged-and-swallowed (try/except at
     context_assembly.py:240). Pins the contract that a broken downstream
     cache can't wedge file-sync invalidation.

Neighbor file: ``test_context_assembly_cache_ttl_drift.py`` (Phase G.6).
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

import pytest

import app.agent.context_assembly as ca
from tests.factories.skills import build_skill


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
# N.7.1 — Bot-authored DB filter shape
# ---------------------------------------------------------------------------


class TestBotAuthoredFilterShape:
    async def test_source_type_tool_filter_excludes_file_skills(
        self, db_session, patched_async_sessions
    ):
        """A skill at ``bots/<bot>/…`` with ``source_type='file'`` is NOT
        bot-authored — bot-authored means ``source_type='tool'``.

        Drift pin: if the filter drops to an ``in (...)`` or removes
        source_type entirely, file-sourced skills would sneak into the
        bot-authored list and inflate auto-enrollment.
        """
        bot_id = "drift-bot-n7"
        tool_skill = build_skill(
            id=f"bots/{bot_id}/{uuid.uuid4().hex[:8]}",
            source_type="tool",
        )
        file_skill = build_skill(
            id=f"bots/{bot_id}/{uuid.uuid4().hex[:8]}",
            source_type="file",
        )
        db_session.add_all([tool_skill, file_skill])
        await db_session.commit()

        result = await ca._get_bot_authored_skill_ids(bot_id)

        assert tool_skill.id in result
        assert file_skill.id not in result

    async def test_archived_skills_excluded(
        self, db_session, patched_async_sessions
    ):
        """``archived_at IS NULL`` filter — archived bot-authored skills
        must not show up in the discovery list even within the bot's prefix.
        """
        bot_id = "drift-bot-n7b"
        live = build_skill(
            id=f"bots/{bot_id}/{uuid.uuid4().hex[:8]}",
            source_type="tool",
        )
        archived = build_skill(
            id=f"bots/{bot_id}/{uuid.uuid4().hex[:8]}",
            source_type="tool",
            archived_at=datetime.now(timezone.utc),
        )
        db_session.add_all([live, archived])
        await db_session.commit()

        result = await ca._get_bot_authored_skill_ids(bot_id)

        assert live.id in result
        assert archived.id not in result

    async def test_prefix_isolates_bots(
        self, db_session, patched_async_sessions
    ):
        """``bots/<bot_id>/`` prefix scope — bot-A lookup never returns
        bot-B's skills even if both are ``source_type='tool'`` + non-archived.
        """
        skill_a = build_skill(
            id=f"bots/bot-alpha/{uuid.uuid4().hex[:8]}",
            source_type="tool",
        )
        skill_b = build_skill(
            id=f"bots/bot-beta/{uuid.uuid4().hex[:8]}",
            source_type="tool",
        )
        db_session.add_all([skill_a, skill_b])
        await db_session.commit()

        result = await ca._get_bot_authored_skill_ids("bot-alpha")

        assert skill_a.id in result
        assert skill_b.id not in result

    async def test_core_and_integration_prefixes_not_matched(
        self, db_session, patched_async_sessions
    ):
        """``bots/`` prefix lookup must not match ``skills/core/…`` or
        ``integrations/slack/…`` — these live in the core + integration
        caches, not the bot cache.
        """
        bot_id = "drift-bot-n7c"
        bot_skill = build_skill(
            id=f"bots/{bot_id}/{uuid.uuid4().hex[:8]}",
            source_type="tool",
        )
        core_skill = build_skill(
            id=f"skills/core/{uuid.uuid4().hex[:8]}",
            source_type="file",
        )
        integ_skill = build_skill(
            id=f"integrations/slack/{uuid.uuid4().hex[:8]}",
            source_type="integration",
        )
        db_session.add_all([bot_skill, core_skill, integ_skill])
        await db_session.commit()

        result = await ca._get_bot_authored_skill_ids(bot_id)

        assert result == [bot_skill.id]


# ---------------------------------------------------------------------------
# N.7.2 — Empty-result caching (thundering-herd pin)
# ---------------------------------------------------------------------------


class TestEmptyResultCaching:
    async def test_bot_with_no_skills_caches_empty_list(
        self, db_session, patched_async_sessions
    ):
        """A bot with zero bot-authored skills stores ``(ts, [])`` so the
        next call within TTL does NOT re-query.

        Drift pin: if the cache write is guarded by ``if result:`` instead of
        unconditional, every request for a no-skills bot re-hits the DB —
        thundering-herd under load.
        """
        bot_id = "drift-empty-bot"
        assert bot_id not in ca._bot_skill_cache

        result = await ca._get_bot_authored_skill_ids(bot_id)

        assert result == []
        assert bot_id in ca._bot_skill_cache
        _, cached = ca._bot_skill_cache[bot_id]
        assert cached == []

    async def test_empty_cache_hit_skips_db(self, patched_async_sessions):
        """Cached ``[]`` within TTL returns without a DB hit."""
        bot_id = "drift-empty-hit"
        ca._bot_skill_cache[bot_id] = (time.monotonic(), [])

        from unittest.mock import patch

        with patch(
            "app.db.engine.async_session",
            side_effect=RuntimeError("DB must not be called for cached empty result"),
        ):
            result = await ca._get_bot_authored_skill_ids(bot_id)

        assert result == []


# ---------------------------------------------------------------------------
# N.7.3 — Multi-bot isolation in the bot cache
# ---------------------------------------------------------------------------


class TestMultiBotIsolation:
    async def test_bot_cache_hit_returns_only_own_slot(
        self, patched_async_sessions
    ):
        """Two bots cached simultaneously → lookup for bot-A returns bot-A's
        list; bot-B's list never leaks in.
        """
        ca._bot_skill_cache["bot-alpha"] = (
            time.monotonic(),
            ["bots/bot-alpha/skill-1"],
        )
        ca._bot_skill_cache["bot-beta"] = (
            time.monotonic(),
            ["bots/bot-beta/skill-1"],
        )

        result_a = await ca._get_bot_authored_skill_ids("bot-alpha")
        result_b = await ca._get_bot_authored_skill_ids("bot-beta")

        assert result_a == ["bots/bot-alpha/skill-1"]
        assert result_b == ["bots/bot-beta/skill-1"]

    def test_invalidate_one_bot_leaves_siblings_intact(self):
        """``invalidate_bot_skill_cache("bot-a")`` pops only bot-a's slot —
        bot-b's still-valid cache is preserved so its next lookup is a hit.
        """
        ca._bot_skill_cache["bot-a"] = (time.monotonic(), ["bots/bot-a/s1"])
        ca._bot_skill_cache["bot-b"] = (time.monotonic(), ["bots/bot-b/s1"])
        ca._bot_skill_cache["bot-c"] = (time.monotonic(), ["bots/bot-c/s1"])

        ca.invalidate_bot_skill_cache("bot-a")

        assert "bot-a" not in ca._bot_skill_cache
        assert "bot-b" in ca._bot_skill_cache
        assert "bot-c" in ca._bot_skill_cache

    def test_invalidate_missing_bot_is_noop(self):
        """Invalidating a bot that was never cached must not raise — callers
        fire blindly after every mutation without pre-checking membership.
        """
        ca._bot_skill_cache["bot-real"] = (time.monotonic(), ["bots/bot-real/s"])

        ca.invalidate_bot_skill_cache("never-cached-bot")

        assert "bot-real" in ca._bot_skill_cache


# ---------------------------------------------------------------------------
# N.7.4 — invalidate_skill_auto_enroll_cache silent-swallow contract
# ---------------------------------------------------------------------------


class TestInvalidateEnrollCacheSilentSwallow:
    def test_core_and_integration_cleared_even_if_downstream_raises(
        self, monkeypatch
    ):
        """The nested ``invalidate_enrolled_cache()`` call is wrapped in a
        try/except (context_assembly.py:240). If it raises, core +
        integration caches MUST still be cleared — otherwise a broken
        downstream cache wedges file-sync invalidation.
        """
        ca._core_skill_cache = (time.monotonic(), ["skills/core/old"])
        ca._integration_skill_cache["slack"] = (
            time.monotonic(),
            ["integrations/slack/old"],
        )

        def _boom(*args, **kwargs):
            raise RuntimeError("downstream enrollment cache on fire")

        monkeypatch.setattr(
            "app.services.skill_enrollment.invalidate_enrolled_cache",
            _boom,
        )

        # Must not raise
        ca.invalidate_skill_auto_enroll_cache()

        assert ca._core_skill_cache is None
        assert ca._integration_skill_cache == {}

    def test_downstream_invalidator_is_invoked(self, monkeypatch):
        """Happy path — the downstream ``invalidate_enrolled_cache`` is
        called with no args (clears all bots) when the top-level invalidator
        fires.
        """
        calls: list[tuple] = []

        def _spy(*args, **kwargs):
            calls.append((args, kwargs))

        monkeypatch.setattr(
            "app.services.skill_enrollment.invalidate_enrolled_cache",
            _spy,
        )

        ca.invalidate_skill_auto_enroll_cache()

        assert len(calls) == 1
        args, kwargs = calls[0]
        assert args == () and kwargs == {}
