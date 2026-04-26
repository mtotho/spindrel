"""Integration tests for the per-bot tool enrollment working set.

Covers app/services/tool_enrollment.py + the prune_enrolled_tools tool +
cascade-on-bot-delete behavior. Runs against the in-memory SQLite test
schema, which exercises the dialect-branched insert helper.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

async def _create_bot(db: AsyncSession, bot_id: str) -> None:
    from app.db.models import Bot as BotRow
    db.add(BotRow(
        id=bot_id, name=bot_id, model="test/m", system_prompt="t", source_type="manual",
    ))
    await db.commit()


@pytest_asyncio.fixture
async def patched_session(engine):
    """Patch async_session in tool_enrollment + discovery tool to use the test engine."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with (
        patch("app.services.tool_enrollment.async_session", factory),
        patch("app.db.engine.async_session", factory),
    ):
        yield factory


# ---------------------------------------------------------------------------
# Service-level tests
# ---------------------------------------------------------------------------

class TestToolEnrollService:
    async def test_enroll_idempotent(self, patched_session, db_session):
        from app.services.tool_enrollment import enroll, get_enrolled_tool_names, invalidate_enrolled_cache

        await _create_bot(db_session, "bot1")
        invalidate_enrolled_cache()

        first = await enroll("bot1", "get_weather", source="fetched")
        assert first is True

        # Re-enroll same row -> no insert
        second = await enroll("bot1", "get_weather", source="manual")
        assert second is False

        invalidate_enrolled_cache()
        names = await get_enrolled_tool_names("bot1")
        assert names == ["get_weather"]

    async def test_enroll_many_idempotent(self, patched_session, db_session):
        from app.services.tool_enrollment import enroll_many, get_enrolled_tool_names, invalidate_enrolled_cache

        await _create_bot(db_session, "bot2")
        invalidate_enrolled_cache()

        n1 = await enroll_many("bot2", ["read", "write", "edit"], source="starter")
        assert n1 == 3

        # Re-enroll partially overlapping batch
        n2 = await enroll_many("bot2", ["read", "write"], source="manual")
        assert n2 == 0

        invalidate_enrolled_cache()
        names = await get_enrolled_tool_names("bot2")
        assert sorted(names) == ["edit", "read", "write"]

    async def test_unenroll_round_trip(self, patched_session, db_session):
        from app.services.tool_enrollment import (
            enroll_many, unenroll, unenroll_many, get_enrolled_tool_names, invalidate_enrolled_cache,
        )

        await _create_bot(db_session, "bot3")
        await enroll_many("bot3", ["x", "y", "z"], source="manual")
        invalidate_enrolled_cache()

        removed = await unenroll("bot3", "y")
        assert removed is True
        invalidate_enrolled_cache()
        assert sorted(await get_enrolled_tool_names("bot3")) == ["x", "z"]

        removed_batch = await unenroll_many("bot3", ["x", "y", "missing"])
        # y was already gone, missing never existed -> only x deleted
        assert removed_batch == 1
        invalidate_enrolled_cache()
        assert await get_enrolled_tool_names("bot3") == ["z"]

    async def test_enroll_starter_tools(self, patched_session, db_session):
        from app.services.tool_enrollment import enroll_starter_tools, get_enrolled_tool_names, invalidate_enrolled_cache

        await _create_bot(db_session, "bot4")
        invalidate_enrolled_cache()

        n = await enroll_starter_tools("bot4", ["read", "write", "search_workspace"])
        assert n == 3

        invalidate_enrolled_cache()
        names = await get_enrolled_tool_names("bot4")
        assert sorted(names) == ["read", "search_workspace", "write"]

    async def test_enroll_starter_tools_empty(self, patched_session, db_session):
        from app.services.tool_enrollment import enroll_starter_tools

        await _create_bot(db_session, "bot5")
        n = await enroll_starter_tools("bot5", [])
        assert n == 0

    async def test_cache_ttl(self, patched_session, db_session):
        """Cache returns stale data until invalidated."""
        from app.services.tool_enrollment import enroll, get_enrolled_tool_names, invalidate_enrolled_cache

        await _create_bot(db_session, "bot6")
        invalidate_enrolled_cache()

        await enroll("bot6", "tool_a", source="fetched")
        names1 = await get_enrolled_tool_names("bot6")
        assert names1 == ["tool_a"]

        # enroll() invalidates the cache, so a second call should see the new tool
        await enroll("bot6", "tool_b", source="fetched")
        names2 = await get_enrolled_tool_names("bot6")
        assert sorted(names2) == ["tool_a", "tool_b"]

    async def test_get_enrollments_returns_full_rows(self, patched_session, db_session):
        from app.services.tool_enrollment import enroll_many, get_enrollments, invalidate_enrolled_cache

        await _create_bot(db_session, "bot7")
        invalidate_enrolled_cache()
        await enroll_many("bot7", ["alpha", "beta"], source="starter")

        rows = await get_enrollments("bot7")
        assert len(rows) == 2
        assert all(r.source == "starter" for r in rows)
        assert {r.tool_name for r in rows} == {"alpha", "beta"}


# ---------------------------------------------------------------------------
# Tool: prune_enrolled_tools
# ---------------------------------------------------------------------------

async def _age_enrollments(db: AsyncSession, bot_id: str, days: int) -> None:
    """Push enrolled_at back by N days so protection rule doesn't fire."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import update

    from app.db.models import BotToolEnrollment

    backdated = datetime.now(timezone.utc) - timedelta(days=days)
    await db.execute(
        update(BotToolEnrollment)
        .where(BotToolEnrollment.bot_id == bot_id)
        .values(enrolled_at=backdated)
    )
    await db.commit()


class TestPruneTool:
    async def test_prune_removes_enrollments(self, patched_session, db_session):
        from app.agent.context import current_bot_id
        from app.services.tool_enrollment import enroll_many, get_enrolled_tool_names, invalidate_enrolled_cache
        from app.tools.local.discovery import prune_enrolled_tools

        await _create_bot(db_session, "prune-bot")
        await enroll_many("prune-bot", ["a", "b", "c"], source="fetched")
        # Bypass the <7d recency protection so the rows are freely prunable.
        await _age_enrollments(db_session, "prune-bot", days=30)
        invalidate_enrolled_cache()

        tok = current_bot_id.set("prune-bot")
        try:
            result = await prune_enrolled_tools(["a", "c"])
        finally:
            current_bot_id.reset(tok)

        import json as _json
        payload = _json.loads(result)
        assert payload["removed"] == 2
        assert payload["blocked"] == 0
        assert "Pruned 2" in payload["message"]

        invalidate_enrolled_cache()
        assert await get_enrolled_tool_names("prune-bot") == ["b"]

    async def test_prune_no_bot_context(self):
        from app.tools.local.discovery import prune_enrolled_tools
        result = await prune_enrolled_tools(["x"])
        assert "no bot context" in result.lower()

    async def test_prune_empty_list(self, patched_session, db_session):
        from app.agent.context import current_bot_id
        from app.tools.local.discovery import prune_enrolled_tools

        await _create_bot(db_session, "prune-bot2")
        tok = current_bot_id.set("prune-bot2")
        try:
            result = await prune_enrolled_tools([])
        finally:
            current_bot_id.reset(tok)
        assert "no tool names provided" in result.lower()

    async def test_prune_blocks_recent_enrollment(self, patched_session, db_session):
        """Tools enrolled <7 days ago are protected without an override."""
        import json as _json

        from app.agent.context import current_bot_id
        from app.services.tool_enrollment import enroll_many, invalidate_enrolled_cache
        from app.tools.local.discovery import prune_enrolled_tools

        await _create_bot(db_session, "prune-recent")
        await enroll_many("prune-recent", ["x"], source="fetched")
        invalidate_enrolled_cache()

        tok = current_bot_id.set("prune-recent")
        try:
            result = await prune_enrolled_tools(["x"])
        finally:
            current_bot_id.reset(tok)

        payload = _json.loads(result)
        assert payload["removed"] == 0
        assert payload["blocked"] == 1
        assert "blocked" in payload["message"].lower()

    async def test_prune_accepts_override_for_recent(self, patched_session, db_session):
        """Recent enrollment can be pruned with an override reason."""
        import json as _json

        from app.agent.context import current_bot_id
        from app.services.tool_enrollment import enroll_many, get_enrolled_tool_names, invalidate_enrolled_cache
        from app.tools.local.discovery import prune_enrolled_tools

        await _create_bot(db_session, "prune-recent2")
        await enroll_many("prune-recent2", ["y"], source="fetched")
        invalidate_enrolled_cache()

        tok = current_bot_id.set("prune-recent2")
        try:
            result = await prune_enrolled_tools(["y"], overrides={"y": "stale"})
        finally:
            current_bot_id.reset(tok)

        payload = _json.loads(result)
        assert payload["removed"] == 1
        assert payload["blocked"] == 0
        invalidate_enrolled_cache()
        assert await get_enrolled_tool_names("prune-recent2") == []

    async def test_prune_blocks_pinned_tool_without_override(
        self, patched_session, db_session,
    ):
        """A tool listed in Bot.pinned_tools is protected even if old."""
        import json as _json

        from app.agent.context import current_bot_id
        from app.db.models import Bot as BotRow
        from app.services.tool_enrollment import enroll_many, invalidate_enrolled_cache
        from app.tools.local.discovery import prune_enrolled_tools

        await _create_bot(db_session, "prune-pinned")
        bot = await db_session.get(BotRow, "prune-pinned")
        bot.pinned_tools = ["pinned_one"]
        await db_session.commit()
        await enroll_many("prune-pinned", ["pinned_one"], source="fetched")
        await _age_enrollments(db_session, "prune-pinned", days=30)
        invalidate_enrolled_cache()

        tok = current_bot_id.set("prune-pinned")
        try:
            result = await prune_enrolled_tools(["pinned_one"])
        finally:
            current_bot_id.reset(tok)

        payload = _json.loads(result)
        assert payload["removed"] == 0
        assert payload["blocked"] == 1
        assert "pinned" in payload["message"].lower()

    async def test_prune_partial_blocked_with_allowed(
        self, patched_session, db_session,
    ):
        """Atomic batch: when some are protected, allowed names still prune."""
        import json as _json

        from app.agent.context import current_bot_id
        from app.services.tool_enrollment import enroll_many, get_enrolled_tool_names, invalidate_enrolled_cache
        from app.tools.local.discovery import prune_enrolled_tools

        await _create_bot(db_session, "prune-mix")
        await enroll_many("prune-mix", ["old_one", "new_one"], source="fetched")
        # Backdate only old_one (we'll fake-age all then re-fresh new_one).
        await _age_enrollments(db_session, "prune-mix", days=30)
        # Now overwrite new_one's enrolled_at back to "now" so it's protected.
        from datetime import datetime, timezone
        from sqlalchemy import update

        from app.db.models import BotToolEnrollment as BTE
        await db_session.execute(
            update(BTE)
            .where(BTE.bot_id == "prune-mix", BTE.tool_name == "new_one")
            .values(enrolled_at=datetime.now(timezone.utc))
        )
        await db_session.commit()
        invalidate_enrolled_cache()

        tok = current_bot_id.set("prune-mix")
        try:
            result = await prune_enrolled_tools(["old_one", "new_one"])
        finally:
            current_bot_id.reset(tok)

        payload = _json.loads(result)
        assert payload["removed"] == 1
        assert payload["blocked"] == 1
        invalidate_enrolled_cache()
        assert await get_enrolled_tool_names("prune-mix") == ["new_one"]


class TestRecordUse:
    """Usage telemetry — fetch_count + last_used_at on every successful call."""

    async def test_record_use_creates_enrollment_if_missing(
        self, patched_session, db_session,
    ):
        from app.db.models import BotToolEnrollment
        from app.services.tool_enrollment import invalidate_enrolled_cache, record_use
        from sqlalchemy import select

        await _create_bot(db_session, "ru-bot")
        invalidate_enrolled_cache()

        await record_use("ru-bot", "fresh_tool")

        rows = (await db_session.execute(
            select(BotToolEnrollment).where(BotToolEnrollment.bot_id == "ru-bot")
        )).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.tool_name == "fresh_tool"
        assert row.source == "fetched"
        assert row.fetch_count == 1
        assert row.last_used_at is not None

    async def test_record_use_increments_fetch_count(
        self, patched_session, db_session,
    ):
        from app.db.models import BotToolEnrollment
        from app.services.tool_enrollment import invalidate_enrolled_cache, record_use
        from sqlalchemy import select

        await _create_bot(db_session, "ru-bot2")
        invalidate_enrolled_cache()

        await record_use("ru-bot2", "tool_a")
        await record_use("ru-bot2", "tool_a")
        await record_use("ru-bot2", "tool_a")

        row = (await db_session.execute(
            select(BotToolEnrollment).where(
                BotToolEnrollment.bot_id == "ru-bot2",
                BotToolEnrollment.tool_name == "tool_a",
            )
        )).scalar_one()
        assert row.fetch_count == 3

    async def test_record_use_preserves_existing_source(
        self, patched_session, db_session,
    ):
        """Calling record_use on a 'starter' tool must not overwrite source='fetched'."""
        from app.db.models import BotToolEnrollment
        from app.services.tool_enrollment import (
            enroll_starter_tools, invalidate_enrolled_cache, record_use,
        )
        from sqlalchemy import select

        await _create_bot(db_session, "ru-starter")
        await enroll_starter_tools("ru-starter", ["starter_tool"])
        invalidate_enrolled_cache()

        await record_use("ru-starter", "starter_tool")

        row = (await db_session.execute(
            select(BotToolEnrollment).where(
                BotToolEnrollment.bot_id == "ru-starter",
                BotToolEnrollment.tool_name == "starter_tool",
            )
        )).scalar_one()
        assert row.source == "starter"
        assert row.fetch_count == 1

    async def test_record_use_many_counts_duplicates(
        self, patched_session, db_session,
    ):
        from app.db.models import BotToolEnrollment
        from app.services.tool_enrollment import invalidate_enrolled_cache, record_use_many
        from sqlalchemy import select

        await _create_bot(db_session, "ru-many")
        invalidate_enrolled_cache()

        await record_use_many("ru-many", ["alpha", "beta", "alpha", "alpha"])

        rows = {
            r.tool_name: r for r in (await db_session.execute(
                select(BotToolEnrollment).where(BotToolEnrollment.bot_id == "ru-many")
            )).scalars().all()
        }
        assert rows["alpha"].fetch_count == 3
        assert rows["beta"].fetch_count == 1

    async def test_record_use_empty_inputs_noop(self, patched_session, db_session):
        from app.services.tool_enrollment import record_use, record_use_many

        # No exception on empty/None inputs
        await record_use("", "tool")
        await record_use("bot", "")
        await record_use_many("bot", [])
        await record_use_many("", ["x"])


# ---------------------------------------------------------------------------
# Tool: get_tool_info enrollment
# ---------------------------------------------------------------------------

class TestGetToolInfoEnrollment:
    """get_tool_info should enroll the looked-up tool into the working set.

    This is the ``get_skill``-parity behavior: asking for the schema is a
    strong signal the bot intends to use the tool, so it persists in
    ``bot_tool_enrollment`` without needing the follow-up call to succeed.
    Prevents the "call get_tool_info every turn" spiral.
    """

    async def test_get_tool_info_enrolls_local_tool(
        self, patched_session, db_session,
    ):
        from app.agent.context import current_bot_id, current_activated_tools
        from app.services.tool_enrollment import (
            get_enrolled_tool_names, invalidate_enrolled_cache,
        )
        from app.tools.local.discovery import get_tool_info

        await _create_bot(db_session, "gti-bot")
        invalidate_enrolled_cache()

        tok_bot = current_bot_id.set("gti-bot")
        tok_active = current_activated_tools.set([])
        try:
            # get_current_local_time is a canonical always-registered local tool
            result = await get_tool_info("get_current_local_time")
        finally:
            current_activated_tools.reset(tok_active)
            current_bot_id.reset(tok_bot)

        # Schema returned (not an error payload)
        assert '"error"' not in result or '"error": ' not in result
        invalidate_enrolled_cache()
        names = await get_enrolled_tool_names("gti-bot")
        assert "get_current_local_time" in names, (
            f"get_tool_info should enroll the tool; got working set {names!r}"
        )

    async def test_get_tool_info_without_bot_context_does_not_error(
        self, patched_session, db_session,
    ):
        """No bot context (e.g. sandbox/dev-panel invocation) must not raise."""
        from app.agent.context import current_activated_tools
        from app.tools.local.discovery import get_tool_info

        tok_active = current_activated_tools.set([])
        try:
            # Should still return the schema even if enrollment is skipped
            result = await get_tool_info("get_current_local_time")
        finally:
            current_activated_tools.reset(tok_active)

        assert "get_current_local_time" in result


# ---------------------------------------------------------------------------
# Cascade on bot delete (schema-level verification)
# ---------------------------------------------------------------------------

class TestBotDeleteCascade:
    """Verify bot_tool_enrollment cascades on bot delete.

    SQLite doesn't enforce FKs by default, so we verify at the schema level.
    Production Postgres always enforces FKs.
    """

    async def test_fk_cascade_declared_on_bot_id(self):
        from app.db.models import BotToolEnrollment
        col = BotToolEnrollment.__table__.c.bot_id
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        fk = fks[0]
        assert fk.column.table.name == "bots"
        assert fk.ondelete == "CASCADE"
