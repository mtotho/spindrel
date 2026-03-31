"""Integration tests for Mission Control API router."""
import uuid
from datetime import date, datetime, timezone
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


class TestMCTimeline:
    async def test_timeline_empty(self, client, db_session):
        resp = await client.get("/api/v1/mission-control/timeline?days=7", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["events"] == []

    async def test_timeline_with_events(self, client, db_session):
        from app.db.models import Channel

        ch = Channel(
            id=uuid.uuid4(),
            name="timeline-test",
            bot_id="test-bot",
            channel_workspace_enabled=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(ch)
        await db_session.commit()

        from datetime import date
        today = date.today().isoformat()
        timeline_content = (
            f"## {today}\n\n"
            "- 14:30 — Card mc-abc123 moved to **Done** (was: Review)\n"
            "- 10:00 — Sprint 5 kicked off\n"
        )

        with patch(
            "app.services.channel_workspace.read_workspace_file",
            return_value=timeline_content,
        ):
            resp = await client.get(
                "/api/v1/mission-control/timeline?days=7",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["events"]) == 2
        assert body["events"][0]["time"] == "14:30"
        assert "mc-abc123" in body["events"][0]["event"]
        assert body["events"][0]["channel_name"] == "timeline-test"
        assert body["events"][1]["time"] == "10:00"


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


class TestMCPlanApprove:
    """Tests for plan approval with execution_config and callback_config."""

    def _make_channel(self, db_session):
        from app.db.models import Channel
        ch = Channel(
            id=uuid.uuid4(),
            name="plan-test",
            bot_id="test-bot",
            channel_workspace_enabled=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(ch)
        return ch

    def _draft_plan_md(self, plan_id="plan-abc123", title="Test Plan", num_steps=3):
        steps = "\n".join(f"{i+1}. [ ] Step {i+1}" for i in range(num_steps))
        return (
            f"# Plans\n\n"
            f"## {title} [draft]\n"
            f"- **id**: {plan_id}\n"
            f"- **created**: {date.today().isoformat()}\n\n"
            f"### Steps\n{steps}\n"
        )

    async def test_approve_creates_task_with_execution_config(self, client, db_session):
        ch = self._make_channel(db_session)
        await db_session.commit()

        plans_md = self._draft_plan_md()
        written_content = {}

        def mock_write(channel_id, bot, path, content):
            written_content[path] = content

        with (
            patch("app.services.channel_workspace.read_workspace_file", return_value=plans_md),
            patch("app.services.channel_workspace.write_workspace_file", side_effect=mock_write),
            patch("app.services.channel_workspace.ensure_channel_workspace"),
        ):
            resp = await client.post(
                f"/api/v1/mission-control/channels/{ch.id}/plans/plan-abc123/approve",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["status"] == "approved"
        assert body["task_created"] is True

        # Verify a Task was created with execution_config and callback_config
        from app.db.models import Task as TaskModel
        from sqlalchemy import select
        result = await db_session.execute(
            select(TaskModel).where(TaskModel.channel_id == ch.id)
        )
        task = result.scalar_one()
        assert task.execution_config is not None
        assert "system_preamble" in task.execution_config
        assert "plan-abc123" in task.execution_config["system_preamble"]
        assert "ONE step at a time" in task.execution_config["system_preamble"]
        assert "schedule_task()" in task.execution_config["system_preamble"]
        assert task.callback_config is not None
        assert task.callback_config.get("trigger_rag_loop") is True

    async def test_approve_prompt_includes_step_summary(self, client, db_session):
        ch = self._make_channel(db_session)
        await db_session.commit()

        plans_md = self._draft_plan_md(num_steps=2)

        with (
            patch("app.services.channel_workspace.read_workspace_file", return_value=plans_md),
            patch("app.services.channel_workspace.write_workspace_file"),
            patch("app.services.channel_workspace.ensure_channel_workspace"),
        ):
            resp = await client.post(
                f"/api/v1/mission-control/channels/{ch.id}/plans/plan-abc123/approve",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200

        from app.db.models import Task as TaskModel
        from sqlalchemy import select
        result = await db_session.execute(
            select(TaskModel).where(TaskModel.channel_id == ch.id)
        )
        task = result.scalar_one()
        assert "Step 1" in task.prompt
        assert "Step 2" in task.prompt
        assert "Next step: #1" in task.prompt

    async def test_approve_rejects_non_draft(self, client, db_session):
        ch = self._make_channel(db_session)
        await db_session.commit()

        executing_plan = (
            "# Plans\n\n"
            "## Running Plan [executing]\n"
            "- **id**: plan-run001\n\n"
            "### Steps\n1. [~] In progress step\n"
        )

        with patch("app.services.channel_workspace.read_workspace_file", return_value=executing_plan):
            resp = await client.post(
                f"/api/v1/mission-control/channels/{ch.id}/plans/plan-run001/approve",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 409


class TestMCPlanResume:
    """Tests for plan resume with step-aware prompts."""

    def _make_channel(self, db_session):
        from app.db.models import Channel
        ch = Channel(
            id=uuid.uuid4(),
            name="resume-test",
            bot_id="test-bot",
            channel_workspace_enabled=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(ch)
        return ch

    async def test_resume_creates_task_with_step_context(self, client, db_session):
        ch = self._make_channel(db_session)
        await db_session.commit()

        executing_plan = (
            "# Plans\n\n"
            "## Multi-Step Plan [executing]\n"
            "- **id**: plan-res001\n\n"
            "### Steps\n"
            "1. [x] First step\n"
            "2. [x] Second step\n"
            "3. [ ] Third step\n"
            "4. [ ] Fourth step\n"
        )

        with (
            patch("app.services.channel_workspace.read_workspace_file", return_value=executing_plan),
            patch("app.services.channel_workspace.ensure_channel_workspace"),
        ):
            resp = await client.post(
                f"/api/v1/mission-control/channels/{ch.id}/plans/plan-res001/resume",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["task_created"] is True

        from app.db.models import Task as TaskModel
        from sqlalchemy import select
        result = await db_session.execute(
            select(TaskModel).where(TaskModel.channel_id == ch.id)
        )
        task = result.scalar_one()
        # Prompt should include step summary with next step info
        assert "plan-res001" in task.prompt
        assert "Next step: #3" in task.prompt
        assert "Third step" in task.prompt
        # Should have execution_config and callback_config
        assert task.execution_config is not None
        assert "system_preamble" in task.execution_config
        assert task.callback_config is not None
        assert task.callback_config.get("trigger_rag_loop") is True

    async def test_resume_rejects_non_executing(self, client, db_session):
        ch = self._make_channel(db_session)
        await db_session.commit()

        draft_plan = (
            "# Plans\n\n"
            "## Draft Plan [draft]\n"
            "- **id**: plan-drf001\n\n"
            "### Steps\n1. [ ] Do something\n"
        )

        with patch("app.services.channel_workspace.read_workspace_file", return_value=draft_plan):
            resp = await client.post(
                f"/api/v1/mission-control/channels/{ch.id}/plans/plan-drf001/resume",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 409
