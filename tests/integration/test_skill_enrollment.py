"""Integration tests for the Phase 3 per-bot skill working set.

Covers app/services/skill_enrollment.py + the enrolled-skills endpoints +
the cascade-on-bot-delete behavior. Runs against the in-memory SQLite test
schema, which exercises the dialect-branched insert helper.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.conftest import AUTH_HEADERS

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


async def _create_skill(db: AsyncSession, skill_id: str, *, name: str | None = None) -> None:
    from app.db.models import Skill as SkillRow
    db.add(SkillRow(
        id=skill_id,
        name=name or skill_id,
        description=f"desc for {skill_id}",
        content=f"# {skill_id}\n\nbody",
        source_type="file",
        triggers=[],
    ))
    await db.commit()


@pytest_asyncio.fixture
async def patched_session(engine):
    """Patch async_session in skill_enrollment + skills tool to use the test engine."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with (
        patch("app.services.skill_enrollment.async_session", factory),
        patch("app.tools.local.skills.async_session", factory),
    ):
        yield factory


# ---------------------------------------------------------------------------
# Service-level tests
# ---------------------------------------------------------------------------

class TestEnrollService:
    async def test_enroll_idempotent(self, patched_session, db_session):
        from app.services.skill_enrollment import enroll, get_enrolled_skill_ids, invalidate_enrolled_cache

        await _create_bot(db_session, "bot1")
        await _create_skill(db_session, "skill1")
        invalidate_enrolled_cache()  # in case prior test polluted the cache

        first = await enroll("bot1", "skill1", source="manual")
        assert first is True

        # Re-enroll same row → no insert
        second = await enroll("bot1", "skill1", source="fetched")
        assert second is False

        invalidate_enrolled_cache()
        ids = await get_enrolled_skill_ids("bot1")
        assert ids == ["skill1"]

    async def test_enroll_many_idempotent(self, patched_session, db_session):
        from app.services.skill_enrollment import enroll_many, get_enrolled_skill_ids, invalidate_enrolled_cache

        await _create_bot(db_session, "bot2")
        for sid in ("a", "b", "c"):
            await _create_skill(db_session, sid)
        invalidate_enrolled_cache()

        n1 = await enroll_many("bot2", ["a", "b", "c"], source="starter")
        assert n1 == 3

        # Re-enroll partially overlapping batch
        n2 = await enroll_many("bot2", ["a", "b"], source="manual")
        assert n2 == 0

        invalidate_enrolled_cache()
        ids = await get_enrolled_skill_ids("bot2")
        assert sorted(ids) == ["a", "b", "c"]

    async def test_unenroll_round_trip(self, patched_session, db_session):
        from app.services.skill_enrollment import (
            enroll_many, unenroll, unenroll_many, get_enrolled_skill_ids, invalidate_enrolled_cache,
        )

        await _create_bot(db_session, "bot3")
        for sid in ("x", "y", "z"):
            await _create_skill(db_session, sid)

        await enroll_many("bot3", ["x", "y", "z"], source="manual")
        invalidate_enrolled_cache()

        removed = await unenroll("bot3", "y")
        assert removed is True
        invalidate_enrolled_cache()
        assert sorted(await get_enrolled_skill_ids("bot3")) == ["x", "z"]

        removed_batch = await unenroll_many("bot3", ["x", "y", "missing"])
        # y was already gone, missing never existed → only x deleted
        assert removed_batch == 1
        invalidate_enrolled_cache()
        assert await get_enrolled_skill_ids("bot3") == ["z"]

    async def test_enroll_starter_pack_skips_missing(self, patched_session, db_session):
        from app.services.skill_enrollment import enroll_starter_pack, get_enrolled_skill_ids, invalidate_enrolled_cache
        from app.config import STARTER_SKILL_IDS

        await _create_bot(db_session, "bot4")
        # Seed only 2 of the 5 starter skills — the rest should be silently skipped
        await _create_skill(db_session, STARTER_SKILL_IDS[0])
        await _create_skill(db_session, STARTER_SKILL_IDS[1])
        invalidate_enrolled_cache()

        n = await enroll_starter_pack("bot4")
        assert n == 2

        invalidate_enrolled_cache()
        ids = await get_enrolled_skill_ids("bot4")
        assert sorted(ids) == sorted([STARTER_SKILL_IDS[0], STARTER_SKILL_IDS[1]])


# ---------------------------------------------------------------------------
# Tool: prune_enrolled_skills
# ---------------------------------------------------------------------------

class TestPruneTool:
    async def test_prune_removes_enrollments(self, patched_session, db_session):
        from datetime import timedelta
        from sqlalchemy import update as sa_update
        from app.agent.context import current_bot_id
        from app.db.models import BotSkillEnrollment
        from app.services.skill_enrollment import enroll_many, get_enrolled_skill_ids, invalidate_enrolled_cache
        from app.tools.local.skills import prune_enrolled_skills

        await _create_bot(db_session, "bot5")
        for sid in ("k1", "k2", "k3"):
            await _create_skill(db_session, sid)
        await enroll_many("bot5", ["k1", "k2", "k3"], source="manual")

        # Age enrollments past the 7-day protection window
        async with patched_session() as db:
            from datetime import datetime, timezone
            await db.execute(
                sa_update(BotSkillEnrollment)
                .where(BotSkillEnrollment.bot_id == "bot5")
                .values(enrolled_at=datetime.now(timezone.utc) - timedelta(days=30))
            )
            await db.commit()

        tok = current_bot_id.set("bot5")
        try:
            invalidate_enrolled_cache()
            result = await prune_enrolled_skills(["k1", "k2"])
        finally:
            current_bot_id.reset(tok)

        assert "Pruned 2" in result
        invalidate_enrolled_cache()
        assert await get_enrolled_skill_ids("bot5") == ["k3"]

    async def test_prune_no_bot_context(self, patched_session, db_session):
        from app.agent.context import current_bot_id
        from app.tools.local.skills import prune_enrolled_skills

        # Clear any leaked ContextVar from prior tests in the suite
        tok = current_bot_id.set(None)
        try:
            result = await prune_enrolled_skills(["whatever"])
        finally:
            current_bot_id.reset(tok)
        assert "no bot context" in result.lower()

    async def test_prune_rejects_authored_without_override(self, patched_session, db_session):
        """Authored skills require an explicit override reason to prune."""
        from app.agent.context import current_bot_id
        from app.services.skill_enrollment import enroll, get_enrolled_skill_ids, invalidate_enrolled_cache
        from app.tools.local.skills import prune_enrolled_skills

        await _create_bot(db_session, "bot5a")
        await _create_skill(db_session, "bots/bot5a/my-authored")
        await enroll("bot5a", "bots/bot5a/my-authored", source="authored")

        tok = current_bot_id.set("bot5a")
        try:
            invalidate_enrolled_cache()
            result = await prune_enrolled_skills(["bots/bot5a/my-authored"])
        finally:
            current_bot_id.reset(tok)

        assert "protected" in result.lower() or "override" in result.lower()
        invalidate_enrolled_cache()
        assert await get_enrolled_skill_ids("bot5a") == ["bots/bot5a/my-authored"]

    async def test_prune_rejects_recent_without_override(self, patched_session, db_session):
        """Recently enrolled skills (< 7 days) require an override."""
        from app.agent.context import current_bot_id
        from app.services.skill_enrollment import enroll, get_enrolled_skill_ids, invalidate_enrolled_cache
        from app.tools.local.skills import prune_enrolled_skills

        await _create_bot(db_session, "bot5b")
        await _create_skill(db_session, "recent-skill")
        await enroll("bot5b", "recent-skill", source="fetched")

        tok = current_bot_id.set("bot5b")
        try:
            invalidate_enrolled_cache()
            result = await prune_enrolled_skills(["recent-skill"])
        finally:
            current_bot_id.reset(tok)

        assert "protected" in result.lower() or "override" in result.lower()
        invalidate_enrolled_cache()
        assert await get_enrolled_skill_ids("bot5b") == ["recent-skill"]

    async def test_prune_authored_with_override_archives(self, patched_session, db_session):
        """Authored skills with override should be archived and unenrolled."""
        from app.agent.context import current_bot_id, current_correlation_id
        from app.db.models import Skill as SkillRow
        from app.services.skill_enrollment import enroll, get_enrolled_skill_ids, invalidate_enrolled_cache
        from app.tools.local.skills import prune_enrolled_skills

        await _create_bot(db_session, "bot5c")
        await _create_skill(db_session, "bots/bot5c/to-archive")
        await enroll("bot5c", "bots/bot5c/to-archive", source="authored")

        tok_bot = current_bot_id.set("bot5c")
        tok_corr = current_correlation_id.set(None)
        try:
            invalidate_enrolled_cache()
            result = await prune_enrolled_skills(
                ["bots/bot5c/to-archive"],
                overrides={"bots/bot5c/to-archive": "should be memory not skill"},
            )
        finally:
            current_bot_id.reset(tok_bot)
            current_correlation_id.reset(tok_corr)

        assert "archived" in result.lower()
        invalidate_enrolled_cache()
        assert await get_enrolled_skill_ids("bot5c") == []

        # Verify the skill itself is archived (not deleted)
        async with patched_session() as db:
            row = await db.get(SkillRow, "bots/bot5c/to-archive")
            assert row is not None
            assert row.archived_at is not None

    async def test_prune_mixed_protected_and_unprotected(self, patched_session, db_session):
        """Unprotected skills are pruned even when some protected skills are rejected."""
        from datetime import timedelta
        from app.agent.context import current_bot_id
        from app.db.models import BotSkillEnrollment
        from app.services.skill_enrollment import enroll, get_enrolled_skill_ids, invalidate_enrolled_cache
        from app.tools.local.skills import prune_enrolled_skills

        await _create_bot(db_session, "bot5d")
        await _create_skill(db_session, "bots/bot5d/authored-one")
        await _create_skill(db_session, "old-catalog")
        await enroll("bot5d", "bots/bot5d/authored-one", source="authored")
        await enroll("bot5d", "old-catalog", source="fetched")

        # Age the catalog enrollment past the protection window
        async with patched_session() as db:
            from sqlalchemy import update
            await db.execute(
                update(BotSkillEnrollment)
                .where(
                    BotSkillEnrollment.bot_id == "bot5d",
                    BotSkillEnrollment.skill_id == "old-catalog",
                )
                .values(enrolled_at=datetime.now(timezone.utc) - timedelta(days=30))
            )
            await db.commit()

        tok = current_bot_id.set("bot5d")
        try:
            invalidate_enrolled_cache()
            result = await prune_enrolled_skills(["bots/bot5d/authored-one", "old-catalog"])
        finally:
            current_bot_id.reset(tok)

        # old-catalog should be pruned, authored should be blocked
        assert "blocked" in result.lower() or "protected" in result.lower()
        invalidate_enrolled_cache()
        remaining = await get_enrolled_skill_ids("bot5d")
        assert "bots/bot5d/authored-one" in remaining
        assert "old-catalog" not in remaining


# ---------------------------------------------------------------------------
# get_skill promotes on success
# ---------------------------------------------------------------------------

class TestGetSkillPromotion:
    async def test_get_skill_promotes(self, patched_session, db_session):
        from app.agent.context import current_bot_id
        from app.services.skill_enrollment import get_enrolled_skill_ids, invalidate_enrolled_cache
        from app.tools.local.skills import get_skill

        await _create_bot(db_session, "bot6")
        await _create_skill(db_session, "promoteme", name="Promote Me")

        tok = current_bot_id.set("bot6")
        try:
            invalidate_enrolled_cache()
            content = await get_skill(skill_id="promoteme")
        finally:
            current_bot_id.reset(tok)

        assert "Promote Me" in content
        invalidate_enrolled_cache()
        assert await get_enrolled_skill_ids("bot6") == ["promoteme"]

    async def test_get_skill_blocked_by_channel_disable(self, patched_session, db_session):
        from app.agent.context import current_bot_id, current_channel_id
        from app.db.models import Channel
        from app.services.skill_enrollment import get_enrolled_skill_ids, invalidate_enrolled_cache
        from app.tools.local.skills import get_skill

        await _create_bot(db_session, "bot7")
        await _create_skill(db_session, "blockedhere")

        ch_id = uuid.uuid4()
        db_session.add(Channel(
            id=ch_id, name="ch", bot_id="bot7", skills_disabled=["blockedhere"],
        ))
        await db_session.commit()

        tok_b = current_bot_id.set("bot7")
        tok_c = current_channel_id.set(ch_id)
        try:
            invalidate_enrolled_cache()
            content = await get_skill(skill_id="blockedhere")
        finally:
            current_channel_id.reset(tok_c)
            current_bot_id.reset(tok_b)

        assert "disabled on this channel" in content
        # Critical: must NOT have been enrolled
        invalidate_enrolled_cache()
        assert await get_enrolled_skill_ids("bot7") == []


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

class TestEnrolledSkillsEndpoints:
    async def test_list_returns_metadata(self, client, patched_session, db_session):
        from app.services.skill_enrollment import enroll_many, invalidate_enrolled_cache

        await _create_bot(db_session, "bot8")
        await _create_skill(db_session, "ep1", name="Endpoint One")
        await _create_skill(db_session, "ep2", name="Endpoint Two")
        await enroll_many("bot8", ["ep1", "ep2"], source="starter")
        invalidate_enrolled_cache()

        resp = await client.get(
            "/api/v1/admin/bots/bot8/enrolled-skills",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body) == 2
        names = {item["name"] for item in body}
        assert names == {"Endpoint One", "Endpoint Two"}
        for item in body:
            assert item["source"] == "starter"

    async def test_post_invalid_source_rejected(self, client, patched_session, db_session):
        await _create_bot(db_session, "bot9")
        await _create_skill(db_session, "ep3")

        resp = await client.post(
            "/api/v1/admin/bots/bot9/enrolled-skills",
            headers={**AUTH_HEADERS, "Content-Type": "application/json"},
            json={"skill_id": "ep3", "source": "garbage"},
        )
        assert resp.status_code == 422

    async def test_post_valid_then_delete(self, client, patched_session, db_session):
        from app.services.skill_enrollment import get_enrolled_skill_ids, invalidate_enrolled_cache

        await _create_bot(db_session, "bot10")
        await _create_skill(db_session, "ep4")

        resp = await client.post(
            "/api/v1/admin/bots/bot10/enrolled-skills",
            headers={**AUTH_HEADERS, "Content-Type": "application/json"},
            json={"skill_id": "ep4", "source": "manual"},
        )
        assert resp.status_code == 201
        invalidate_enrolled_cache()
        assert await get_enrolled_skill_ids("bot10") == ["ep4"]

        resp = await client.delete(
            "/api/v1/admin/bots/bot10/enrolled-skills/ep4",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 204
        invalidate_enrolled_cache()
        assert await get_enrolled_skill_ids("bot10") == []

    async def test_delete_skill_id_with_slashes(self, client, patched_session, db_session):
        """Skill IDs like ``carapaces/orchestrator/foo`` contain slashes.

        Regression: the DELETE route used ``{skill_id}`` instead of
        ``{skill_id:path}``, so removing any slashed enrollment 404'd.
        """
        from app.services.skill_enrollment import enroll, get_enrolled_skill_ids, invalidate_enrolled_cache

        slashed_id = "carapaces/orchestrator/workspace-delegation"
        await _create_bot(db_session, "bot11")
        await _create_skill(db_session, slashed_id)
        await enroll("bot11", slashed_id, source="manual")
        invalidate_enrolled_cache()

        resp = await client.delete(
            f"/api/v1/admin/bots/bot11/enrolled-skills/{slashed_id}",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 204, resp.text
        invalidate_enrolled_cache()
        assert await get_enrolled_skill_ids("bot11") == []


# ---------------------------------------------------------------------------
# Cascade on bot delete
# ---------------------------------------------------------------------------

class TestBotDeleteCascade:
    """Verify the bot_skill_enrollment table is set up to cascade on bot delete.

    SQLite doesn't enforce foreign keys by default (would need PRAGMA per-conn),
    so we verify the cascade *at the schema level* by introspecting the model
    metadata. Production Postgres always enforces FKs, so this is sufficient.
    """

    async def test_fk_cascade_declared_on_bot_id(self):
        from app.db.models import BotSkillEnrollment
        col = BotSkillEnrollment.__table__.c.bot_id
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        fk = fks[0]
        assert fk.column.table.name == "bots"
        assert fk.ondelete == "CASCADE"

    async def test_fk_cascade_declared_on_skill_id(self):
        from app.db.models import BotSkillEnrollment
        col = BotSkillEnrollment.__table__.c.skill_id
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        fk = fks[0]
        assert fk.column.table.name == "skills"
        assert fk.ondelete == "CASCADE"


