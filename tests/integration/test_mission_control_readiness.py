"""Integration tests for Mission Control readiness + reference file endpoints."""
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.agent.bots import BotConfig, KnowledgeConfig, MemoryConfig
from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Readiness endpoint
# ---------------------------------------------------------------------------

class TestMCReadiness:
    async def test_readiness_no_channels(self, client, db_session):
        """No workspace channels → all features not ready."""
        resp = await client.get("/integrations/mission_control/readiness", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["dashboard"]["ready"] is False
        assert body["kanban"]["ready"] is False
        assert body["journal"]["ready"] is False
        assert body["memory"]["ready"] is False
        assert len(body["dashboard"]["issues"]) > 0

    async def test_readiness_with_channels_no_tasks(self, client, db_session):
        """Workspace channels but no tasks.md → dashboard ready, kanban not ready."""
        from app.db.models import Channel

        ch = Channel(
            id=uuid.uuid4(),
            name="ready-test",
            bot_id="test-bot",
            channel_workspace_enabled=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(ch)
        await db_session.commit()

        # _has_tasks_file does os.path.isfile — mock it to return False
        with patch(
            "integrations.mission_control.helpers.has_tasks_file",
            return_value=False,
        ):
            resp = await client.get(
                "/integrations/mission_control/readiness", headers=AUTH_HEADERS
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["dashboard"]["ready"] is True
        assert body["dashboard"]["count"] == 1
        assert body["kanban"]["ready"] is False
        assert "No channels have tasks.md" in body["kanban"]["issues"][0]

    async def test_readiness_with_memory_bot(self, client, db_session):
        """Bot with memory_scheme=workspace-files + filesystem → journal/memory ready."""
        from app.db.models import Channel

        mem_bot = BotConfig(
            id="test-bot",
            name="Test Bot",
            model="test/model",
            system_prompt="You are a test bot.",
            memory=MemoryConfig(enabled=False),
            knowledge=KnowledgeConfig(enabled=False),
            memory_scheme="workspace-files",
        )

        ch = Channel(
            id=uuid.uuid4(),
            name="mem-test",
            bot_id="test-bot",
            channel_workspace_enabled=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(ch)
        await db_session.commit()

        with (
            patch("integrations.mission_control.router.has_tasks_file", return_value=True),
            patch("integrations.mission_control.router_memory.get_bot", return_value=mem_bot),
            patch("app.agent.bots.list_bots", return_value=[mem_bot]),
            patch("app.services.memory_scheme.get_memory_root", return_value="/tmp/test-mem"),
            patch("os.path.isdir", return_value=True),
            patch("os.path.isfile", return_value=True),
        ):
            resp = await client.get(
                "/integrations/mission_control/readiness", headers=AUTH_HEADERS
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["dashboard"]["ready"] is True
        assert body["kanban"]["ready"] is True
        assert body["journal"]["ready"] is True
        assert body["memory"]["ready"] is True

    async def test_readiness_all_features_ready(self, client, db_session):
        """Full setup: channels + tasks + memory → all ready."""
        from app.db.models import Channel

        mem_bot = BotConfig(
            id="test-bot",
            name="Test Bot",
            model="test/model",
            system_prompt="You are a test bot.",
            memory=MemoryConfig(enabled=False),
            knowledge=KnowledgeConfig(enabled=False),
            memory_scheme="workspace-files",
        )

        ch = Channel(
            id=uuid.uuid4(),
            name="full-test",
            bot_id="test-bot",
            channel_workspace_enabled=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(ch)
        await db_session.commit()

        with (
            patch("integrations.mission_control.router.has_tasks_file", return_value=True),
            patch("integrations.mission_control.router.has_timeline_file", return_value=True),
            patch("integrations.mission_control.router_memory.get_bot", return_value=mem_bot),
            patch("app.agent.bots.list_bots", return_value=[mem_bot]),
            patch("app.services.memory_scheme.get_memory_root", return_value="/tmp/test-mem"),
            patch("os.path.isdir", return_value=True),
            patch("os.path.isfile", return_value=True),
        ):
            resp = await client.get(
                "/integrations/mission_control/readiness", headers=AUTH_HEADERS
            )

        body = resp.json()
        for feature in ["dashboard", "kanban", "journal", "memory", "timeline"]:
            assert body[feature]["ready"] is True, f"{feature} should be ready"
            assert body[feature]["issues"] == [], f"{feature} should have no issues"


# ---------------------------------------------------------------------------
# Reference file endpoint
# ---------------------------------------------------------------------------

class TestMCReferenceFile:
    async def test_reference_file_valid(self, client, db_session, tmp_path):
        """Valid filename returns file content."""
        mem_bot = BotConfig(
            id="ref-bot",
            name="Ref Bot",
            model="test/model",
            system_prompt="test",
            memory_scheme="workspace-files",
        )

        ref_dir = tmp_path / "reference"
        ref_dir.mkdir(parents=True)
        (ref_dir / "notes.md").write_text("# Reference notes\nSome content here.")

        with (
            patch("integrations.mission_control.router_memory.get_bot", return_value=mem_bot),
            patch(
                "app.services.memory_scheme.get_memory_root",
                return_value=str(tmp_path),
            ),
        ):
            resp = await client.get(
                "/integrations/mission_control/memory/ref-bot/reference/notes.md",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "Reference notes" in body["content"]
        assert "Some content here." in body["content"]

    async def test_reference_file_backslash_rejected(self, client, db_session):
        """Filenames with backslash are rejected."""
        mem_bot = BotConfig(
            id="test-bot",
            name="Test Bot",
            model="test/model",
            system_prompt="test",
            memory_scheme="workspace-files",
        )
        with patch("integrations.mission_control.router_memory.get_bot", return_value=mem_bot):
            resp = await client.get(
                "/integrations/mission_control/memory/test-bot/reference/foo%5Cbar.md",
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 400

    async def test_reference_file_with_dotdot(self, client, db_session):
        """Filename containing .. is rejected."""
        resp = await client.get(
            "/integrations/mission_control/memory/test-bot/reference/..secret.md",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 400

    async def test_reference_file_not_found(self, client, db_session, tmp_path):
        """Non-existent file returns 404."""
        mem_bot = BotConfig(
            id="test-bot",
            name="Test Bot",
            model="test/model",
            system_prompt="test",
            memory_scheme="workspace-files",
        )

        ref_dir = tmp_path / "reference"
        ref_dir.mkdir(parents=True)

        with (
            patch("integrations.mission_control.router_memory.get_bot", return_value=mem_bot),
            patch(
                "app.services.memory_scheme.get_memory_root",
                return_value=str(tmp_path),
            ),
        ):
            resp = await client.get(
                "/integrations/mission_control/memory/test-bot/reference/nonexistent.md",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 404

    async def test_reference_file_wrong_memory_scheme(self, client, db_session):
        """Bot without workspace-files memory scheme returns 400."""
        # test-bot from conftest has no memory_scheme set
        resp = await client.get(
            "/integrations/mission_control/memory/test-bot/reference/notes.md",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Scope parameter
# ---------------------------------------------------------------------------

class TestMCScope:
    async def test_overview_scope_param(self, client, db_session):
        """Overview accepts scope param without error."""
        resp = await client.get(
            "/integrations/mission_control/overview?scope=fleet",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "is_admin" in body

    async def test_overview_personal_scope(self, client, db_session):
        """Personal scope doesn't crash."""
        resp = await client.get(
            "/integrations/mission_control/overview?scope=personal",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200

    async def test_kanban_scope_param(self, client, db_session):
        """Kanban accepts scope param."""
        resp = await client.get(
            "/integrations/mission_control/kanban?scope=fleet",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200

    async def test_journal_scope_param(self, client, db_session):
        """Journal accepts scope param."""
        resp = await client.get(
            "/integrations/mission_control/journal?scope=fleet",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200

    async def test_memory_scope_param(self, client, db_session):
        """Memory accepts scope param."""
        resp = await client.get(
            "/integrations/mission_control/memory?scope=fleet",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Modules endpoint
# ---------------------------------------------------------------------------

class TestMCModules:
    async def test_modules_empty(self, client, db_session):
        """No integrations with dashboard_modules → empty list."""
        with patch("integrations.discover_dashboard_modules", return_value=[]):
            resp = await client.get(
                "/integrations/mission_control/modules",
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["modules"] == []

    async def test_modules_with_data(self, client, db_session):
        """Integration with dashboard_modules returns module list."""
        mock_modules = [
            {
                "integration_id": "test_int",
                "module_id": "test-mod",
                "label": "Test Module",
                "icon": "Zap",
                "description": "A test module",
                "api_base": "/integrations/test_int/mc/test-mod",
            }
        ]
        with patch("integrations.discover_dashboard_modules", return_value=mock_modules):
            resp = await client.get(
                "/integrations/mission_control/modules",
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["modules"]) == 1
        assert body["modules"][0]["module_id"] == "test-mod"
