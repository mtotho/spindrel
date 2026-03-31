"""Integration tests for Mission Control API router."""
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


class TestMCOverview:
    async def test_overview_empty(self, client, db_session):
        resp = await client.get("/api/v1/mission-control/overview", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_channels"] == 0
        assert body["total_bots"] >= 0  # test bots are in registry, not DB
        assert body["total_tasks"] == 0
        assert body["channels"] == []

    async def test_overview_with_channel(self, client, db_session):
        from app.db.models import Channel
        ch = Channel(
            id=uuid.uuid4(),
            name="test-project",
            bot_id="test-bot",
            channel_workspace_enabled=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(ch)
        await db_session.commit()

        resp = await client.get("/api/v1/mission-control/overview", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_channels"] == 1
        assert body["channels"][0]["name"] == "test-project"
        assert body["channels"][0]["bot_id"] == "test-bot"


class TestMCKanban:
    async def test_kanban_empty(self, client, db_session):
        resp = await client.get("/api/v1/mission-control/kanban", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["columns"] == []

    async def test_kanban_with_tasks(self, client, db_session):
        """Channels with tasks.md show up in aggregated kanban."""
        from app.db.models import Channel

        ch = Channel(
            id=uuid.uuid4(),
            name="kanban-test",
            bot_id="test-bot",
            channel_workspace_enabled=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(ch)
        await db_session.commit()

        # Mock workspace file reading to return a tasks.md
        tasks_content = (
            "# Tasks\n\n"
            "## Backlog\n\n"
            "### Test task\n"
            "- **id**: mc-aaa111\n"
            "- **priority**: high\n"
            "\n"
            "## Done\n\n"
        )

        # Patch at the source module — router does lazy import inside function
        with patch(
            "app.services.channel_workspace.read_workspace_file",
            return_value=tasks_content,
        ):
            resp = await client.get("/api/v1/mission-control/kanban", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["columns"]) >= 1
        backlog = next((c for c in body["columns"] if c["name"] == "Backlog"), None)
        assert backlog is not None
        assert len(backlog["cards"]) == 1
        assert backlog["cards"][0]["title"] == "Test task"
        assert backlog["cards"][0]["channel_name"] == "kanban-test"

    async def test_kanban_create(self, client, db_session):
        from app.db.models import Channel

        ch = Channel(
            id=uuid.uuid4(),
            name="create-test",
            bot_id="test-bot",
            channel_workspace_enabled=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(ch)
        await db_session.commit()

        with (
            patch("app.services.channel_workspace.read_workspace_file", return_value=None),
            patch("app.services.channel_workspace.write_workspace_file") as mock_write,
            patch("app.services.channel_workspace.ensure_channel_workspace"),
        ):
            resp = await client.post(
                "/api/v1/mission-control/kanban/create",
                json={
                    "channel_id": str(ch.id),
                    "title": "New task",
                    "priority": "high",
                },
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["card"]["title"] == "New task"
        assert body["card"]["meta"]["priority"] == "high"
        assert body["card"]["meta"]["id"].startswith("mc-")
        assert body["column"] == "Backlog"
        # Verify write was called
        assert mock_write.called

    async def test_kanban_move(self, client, db_session):
        from app.db.models import Channel

        ch = Channel(
            id=uuid.uuid4(),
            name="move-test",
            bot_id="test-bot",
            channel_workspace_enabled=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(ch)
        await db_session.commit()

        tasks_content = (
            "# Tasks\n\n"
            "## Backlog\n\n"
            "### Move me\n"
            "- **id**: mc-mov001\n"
            "- **priority**: medium\n"
            "\n"
            "## In Progress\n\n"
            "## Done\n\n"
        )

        with (
            patch("app.services.channel_workspace.read_workspace_file", return_value=tasks_content),
            patch("app.services.channel_workspace.write_workspace_file") as mock_write,
        ):
            resp = await client.post(
                "/api/v1/mission-control/kanban/move",
                json={
                    "card_id": "mc-mov001",
                    "from_column": "Backlog",
                    "to_column": "In Progress",
                    "channel_id": str(ch.id),
                },
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["card"]["title"] == "Move me"
        assert body["card"]["meta"].get("started")  # transition metadata
        assert mock_write.called

    async def test_kanban_move_not_found(self, client, db_session):
        from app.db.models import Channel

        ch = Channel(
            id=uuid.uuid4(),
            name="move-404",
            bot_id="test-bot",
            channel_workspace_enabled=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(ch)
        await db_session.commit()

        tasks_content = "# Tasks\n\n## Backlog\n\n## Done\n\n"

        with patch("app.services.channel_workspace.read_workspace_file", return_value=tasks_content):
            resp = await client.post(
                "/api/v1/mission-control/kanban/move",
                json={
                    "card_id": "mc-nonexistent",
                    "from_column": "Backlog",
                    "to_column": "Done",
                    "channel_id": str(ch.id),
                },
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 404

    async def test_kanban_move_wrong_from_column(self, client, db_session):
        """Moving a card with wrong from_column returns 409."""
        from app.db.models import Channel

        ch = Channel(
            id=uuid.uuid4(),
            name="move-conflict",
            bot_id="test-bot",
            channel_workspace_enabled=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(ch)
        await db_session.commit()

        tasks_content = (
            "# Tasks\n\n"
            "## Backlog\n\n"
            "### Card\n"
            "- **id**: mc-abc123\n\n"
            "## In Progress\n\n"
            "## Done\n\n"
        )

        with patch("app.services.channel_workspace.read_workspace_file", return_value=tasks_content):
            resp = await client.post(
                "/api/v1/mission-control/kanban/move",
                json={
                    "card_id": "mc-abc123",
                    "from_column": "In Progress",  # card is actually in Backlog
                    "to_column": "Done",
                    "channel_id": str(ch.id),
                },
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 409


class TestMCJournal:
    async def test_journal_empty(self, client, db_session):
        resp = await client.get("/api/v1/mission-control/journal?days=7", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["entries"] == []


class TestMCMemory:
    async def test_memory_empty(self, client, db_session):
        resp = await client.get("/api/v1/mission-control/memory", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["sections"] == []


class TestMCChannelContext:
    async def test_context_not_found(self, client, db_session):
        fake_id = str(uuid.uuid4())
        resp = await client.get(
            f"/api/v1/mission-control/channels/{fake_id}/context",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404

    async def test_context_returns_data(self, client, db_session):
        from app.db.models import Channel

        ch = Channel(
            id=uuid.uuid4(),
            name="debug-channel",
            bot_id="test-bot",
            channel_workspace_enabled=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(ch)
        await db_session.commit()

        with patch("app.services.channel_workspace.list_workspace_files", return_value=[]):
            resp = await client.get(
                f"/api/v1/mission-control/channels/{ch.id}/context",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["config"]["channel_name"] == "debug-channel"
        assert body["config"]["bot_id"] == "test-bot"
        assert body["config"]["bot_name"] == "Test Bot"
        assert isinstance(body["files"], list)
        assert isinstance(body["tool_calls"], list)
        assert isinstance(body["trace_events"], list)


class TestMCPrefs:
    async def test_get_prefs_default(self, client, db_session):
        resp = await client.get("/api/v1/mission-control/prefs", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        # API key auth returns empty prefs (no user)
        assert body.get("tracked_channel_ids") is None

    async def test_update_prefs_requires_user(self, client, db_session):
        """API key auth cannot save prefs (needs JWT user)."""
        resp = await client.put(
            "/api/v1/mission-control/prefs",
            json={"tracked_channel_ids": ["abc"]},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 400
