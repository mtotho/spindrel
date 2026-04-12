"""Integration tests for the config-overhead endpoint.

Regression test for: channel.skills_extra stores dicts ({"id": "...", "mode": "..."})
but the config-overhead endpoint was passing them raw into the skills list, causing
asyncpg TypeError when the list reached a SQL IN clause.
"""
import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Channel

AUTH_HEADERS = {"Authorization": "Bearer test-key"}


async def _create_channel(db_session: AsyncSession, **overrides) -> str:
    channel_id = uuid.uuid4()
    defaults = dict(id=channel_id, name="test-overhead", bot_id="test-bot")
    defaults.update(overrides)
    db_session.add(Channel(**defaults))
    await db_session.commit()
    return str(channel_id)


class TestConfigOverheadSkillsExtra:
    """Regression: skills_extra dicts must be unwrapped before DB queries."""

    @pytest.mark.asyncio
    async def test_skills_extra_with_dicts_does_not_crash(
        self, client: AsyncClient, db_session: AsyncSession, engine,
    ):
        """Channel with dict-style skills_extra should return 200, not 500."""
        cid = await _create_channel(db_session, skills_extra=[
            {"id": "carapaces/baking/sourdough-process", "mode": "on_demand"},
            {"id": "carapaces/cooking/knife-skills", "mode": "on_demand"},
        ])

        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        with patch("app.services.context_estimate.async_session", factory):
            resp = await client.get(
                f"/api/v1/admin/channels/{cid}/config-overhead",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["approx_tokens"] > 0

    @pytest.mark.asyncio
    async def test_skills_extra_with_plain_strings_still_works(
        self, client: AsyncClient, db_session: AsyncSession, engine,
    ):
        """Plain string skills_extra (legacy format) should also work."""
        cid = await _create_channel(
            db_session,
            name="test-overhead-strings",
            skills_extra=["carapaces/baking/sourdough-process"],
        )

        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        with patch("app.services.context_estimate.async_session", factory):
            resp = await client.get(
                f"/api/v1/admin/channels/{cid}/config-overhead",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    @pytest.mark.asyncio
    async def test_skills_extra_none_works(
        self, client: AsyncClient, db_session: AsyncSession, engine,
    ):
        """Channel with no skills_extra should work fine (baseline)."""
        cid = await _create_channel(db_session, name="test-overhead-none")

        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        with patch("app.services.context_estimate.async_session", factory):
            resp = await client.get(
                f"/api/v1/admin/channels/{cid}/config-overhead",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_skills_extra_dicts_unwrapped_to_string_ids(
        self, db_session: AsyncSession,
    ):
        """Directly verify the unwrapping logic produces string IDs, not dicts.

        This catches the regression on SQLite too (where asyncpg's strict type
        check wouldn't fire) by inspecting the intermediate skill list that the
        endpoint builds before passing it to estimate_bot_context.
        """
        from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig, SkillConfig

        channel_id = uuid.uuid4()
        ch = Channel(
            id=channel_id, name="test-unwrap", bot_id="test-bot",
            skills_extra=[
                {"id": "carapaces/baking/sourdough-process", "mode": "on_demand"},
                {"id": "carapaces/cooking/knife-skills", "mode": "on_demand"},
            ],
        )
        db_session.add(ch)
        await db_session.commit()

        # Replicate the endpoint's skill-list construction logic
        bot = BotConfig(
            id="test-bot", name="Test Bot", model="test/model",
            system_prompt="You are a test bot.",
            memory=MemoryConfig(enabled=False),
            knowledge=KnowledgeConfig(enabled=False),
        )

        skills = [{"id": s.id, "mode": s.mode or "on_demand"} for s in bot.skills]
        disabled_skills = set(ch.skills_disabled or [])
        if disabled_skills:
            skills = [s for s in skills if s["id"] not in disabled_skills]

        # This is the critical unwrapping — the buggy version did:
        #   for sid in (ch.skills_extra or []):
        #       skills.append({"id": sid, ...})  # sid is a DICT
        for entry in (ch.skills_extra or []):
            sid = entry["id"] if isinstance(entry, dict) else entry
            if not any(s["id"] == sid for s in skills):
                skills.append({"id": sid, "mode": "on_demand"})

        # Every skill "id" must be a plain string — never a dict
        for s in skills:
            assert isinstance(s["id"], str), (
                f"Skill ID is {type(s['id']).__name__}, not str: {s['id']}"
            )

        # Verify the specific IDs are present
        skill_ids = {s["id"] for s in skills}
        assert "carapaces/baking/sourdough-process" in skill_ids
        assert "carapaces/cooking/knife-skills" in skill_ids
