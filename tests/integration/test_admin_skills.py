"""Integration tests for /api/v1/admin/skills."""
from datetime import datetime, timezone

import pytest

from app.db.models import Skill as SkillRow
from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


class TestAdminSkillsList:
    async def test_list_skills_empty(self, client, db_session):
        resp = await client.get("/api/v1/admin/skills", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_includes_regular_skill(self, client, db_session):
        now = datetime.now(timezone.utc)
        row = SkillRow(
            id="test-skill", name="Test Skill", content="hello",
            content_hash="abc", source_type="manual",
            created_at=now, updated_at=now,
        )
        db_session.add(row)
        await db_session.commit()
        resp = await client.get("/api/v1/admin/skills", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        skills = resp.json()
        assert len(skills) == 1
        assert skills[0]["id"] == "test-skill"
        assert skills[0]["source_type"] == "manual"
