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

class TestPruneTool:
    async def test_prune_removes_enrollments(self, patched_session, db_session):
        from app.agent.context import current_bot_id
        from app.services.tool_enrollment import enroll_many, get_enrolled_tool_names, invalidate_enrolled_cache
        from app.tools.local.discovery import prune_enrolled_tools

        await _create_bot(db_session, "prune-bot")
        await enroll_many("prune-bot", ["a", "b", "c"], source="fetched")
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
        assert "No tool names" in result


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
