"""Integration tests for /api/v1/admin/skills — workspace skills visibility."""
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.db.models import Document, SharedWorkspace, Skill as SkillRow
from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


async def _insert_workspace_skill(db_session, workspace_id: str, **overrides):
    """Insert a Document row mimicking an embedded workspace skill."""
    defaults = {
        "skill_id": f"ws:test:{uuid.uuid4().hex[:12]}",
        "skill_name": "Test Skill",
        "workspace_id": workspace_id,
        "mode": "pinned",
        "bot_id": None,
        "source_path": "common/skills/test.md",
    }
    meta = {**defaults, **overrides}
    source = f"workspace_skill:{workspace_id}:{meta['source_path']}"
    doc = Document(
        content="test chunk content",
        source=source,
        metadata_=meta,
    )
    db_session.add(doc)
    await db_session.commit()
    return meta


async def _create_ws(db_session, name="Test WS"):
    """Create a SharedWorkspace row, return (uuid, str_id)."""
    ws_id = uuid.uuid4()
    ws = SharedWorkspace(
        id=ws_id, name=name, image="img:latest",
        status="stopped", created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(ws)
    await db_session.commit()
    return ws_id, str(ws_id)


# ---------------------------------------------------------------------------
# GET /api/v1/admin/skills — includes workspace skills
# ---------------------------------------------------------------------------

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
        assert skills[0]["workspace_id"] is None

    async def test_list_includes_workspace_skills(self, client, db_session):
        _, ws_str = await _create_ws(db_session)
        await _insert_workspace_skill(
            db_session, ws_str,
            skill_id="ws:test:abc123",
            skill_name="Coding Guide",
            mode="pinned",
            source_path="common/skills/pinned/coding.md",
        )

        resp = await client.get("/api/v1/admin/skills", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        ws_skills = [s for s in resp.json() if s["source_type"] == "workspace"]
        assert len(ws_skills) == 1
        assert ws_skills[0]["name"] == "Coding Guide"
        assert ws_skills[0]["workspace_id"] == ws_str
        assert ws_skills[0]["workspace_name"] == "Test WS"
        assert ws_skills[0]["mode"] == "pinned"
        assert ws_skills[0]["chunk_count"] == 1

    async def test_workspace_skills_multiple_chunks_counted(self, client, db_session):
        _, ws_str = await _create_ws(db_session, "WS2")
        meta = {
            "skill_id": "ws:test:multi",
            "skill_name": "Multi Chunk",
            "workspace_id": ws_str,
            "mode": "rag",
            "bot_id": None,
            "source_path": "common/skills/rag/big.md",
        }
        source = f"workspace_skill:{ws_str}:{meta['source_path']}"
        for i in range(3):
            db_session.add(Document(
                content=f"chunk {i}",
                source=source,
                metadata_={**meta, "chunk_index": i},
            ))
        await db_session.commit()

        resp = await client.get("/api/v1/admin/skills", headers=AUTH_HEADERS)
        ws_skills = [s for s in resp.json() if s["source_type"] == "workspace"]
        assert len(ws_skills) == 1
        assert ws_skills[0]["chunk_count"] == 3
        assert ws_skills[0]["mode"] == "rag"

    async def test_bot_specific_workspace_skill(self, client, db_session):
        _, ws_str = await _create_ws(db_session, "WS3")
        await _insert_workspace_skill(
            db_session, ws_str,
            skill_id="ws:test:botskill",
            skill_name="Bot Specific",
            bot_id="coder-bot",
            source_path="bots/coder-bot/skills/coding.md",
            mode="on_demand",
        )

        resp = await client.get("/api/v1/admin/skills", headers=AUTH_HEADERS)
        ws_skills = [s for s in resp.json() if s["source_type"] == "workspace"]
        assert len(ws_skills) == 1
        assert ws_skills[0]["bot_id"] == "coder-bot"
        assert ws_skills[0]["mode"] == "on_demand"

    async def test_source_type_filter_excludes_workspace_skills(self, client, db_session):
        """Filtering by source_type=tool should NOT include workspace skills."""
        now = datetime.now(timezone.utc)
        # Add a bot-authored skill (source_type=tool)
        db_session.add(SkillRow(
            id="bots/mybot/my-skill", name="My Skill", content="hello",
            content_hash="abc", source_type="tool",
            created_at=now, updated_at=now,
        ))
        await db_session.commit()
        # Add a workspace skill
        _, ws_str = await _create_ws(db_session, "WS Filter Test")
        await _insert_workspace_skill(
            db_session, ws_str,
            skill_id="ws:test:filter",
            skill_name="Workspace Skill",
        )

        resp = await client.get(
            "/api/v1/admin/skills?source_type=tool&bot_id=mybot",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        skills = resp.json()
        assert len(skills) == 1
        assert skills[0]["id"] == "bots/mybot/my-skill"
        assert skills[0]["source_type"] == "tool"
        # Workspace skills should NOT be in the response
        assert all(s["source_type"] != "workspace" for s in skills)


# ---------------------------------------------------------------------------
# Bot editor data — workspace_skills field
# ---------------------------------------------------------------------------

class TestBotEditorWorkspaceSkills:
    async def test_editor_data_no_workspace_skills(self, client, db_session):
        """Bot without workspace has empty workspace_skills."""
        resp = await client.get(
            "/api/v1/admin/bots/test-bot/editor-data", headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "workspace_skills" in body
        assert body["workspace_skills"] == []

    async def test_editor_data_new_bot_no_workspace_skills(self, client, db_session):
        """New bot template has empty workspace_skills."""
        resp = await client.get(
            "/api/v1/admin/bots/new/editor-data", headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["workspace_skills"] == []

    async def test_editor_data_with_workspace_skills(self, client, db_session):
        """Bot in a workspace gets workspace skills in editor data."""
        from app.agent.bots import BotConfig, WorkspaceConfig

        _, ws_str = await _create_ws(db_session, "Editor WS")
        await _insert_workspace_skill(
            db_session, ws_str,
            skill_id="ws:ed:abc123",
            skill_name="Editing Tips",
            mode="pinned",
            source_path="common/skills/editing.md",
        )

        bot = BotConfig(
            id="ws-bot", name="WS Bot", model="test/model",
            system_prompt="test",
            shared_workspace_id=ws_str,
            workspace=WorkspaceConfig(enabled=True),
        )
        registry = {"ws-bot": bot, "test-bot": bot, "default": bot}
        with (
            patch("app.agent.bots._registry", registry),
            patch("app.agent.bots.get_bot", side_effect=lambda bid: registry.get(bid, bot)),
        ):
            resp = await client.get(
                "/api/v1/admin/bots/ws-bot/editor-data", headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        ws_skills = resp.json()["workspace_skills"]
        assert len(ws_skills) == 1
        assert ws_skills[0]["name"] == "Editing Tips"
        assert ws_skills[0]["mode"] == "pinned"
        assert ws_skills[0]["workspace_id"] == ws_str
        assert ws_skills[0]["workspace_name"] == "Editor WS"
