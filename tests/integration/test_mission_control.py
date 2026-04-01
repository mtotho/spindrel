"""Integration tests for Mission Control API router."""
import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Shared MC DB fixture for integration tests
# ---------------------------------------------------------------------------

@pytest.fixture
def _mc_db(tmp_path):
    """Set up a temporary MC SQLite DB and mock _resolve_bot for each test."""
    db_path = str(tmp_path / "mc_test.db")

    with (
        patch("integrations.mission_control.db.engine._get_db_path", return_value=db_path),
        patch("integrations.mission_control.services._resolve_bot", new_callable=AsyncMock),
        patch("app.services.channel_workspace.ensure_channel_workspace"),
        patch("app.services.channel_workspace.write_workspace_file"),
        patch("app.services.channel_workspace.read_workspace_file", return_value=None),
    ):
        # Reset MC engine state
        import integrations.mission_control.db.engine as eng_mod
        eng_mod._engine = None
        eng_mod._session_factory = None

        # Clear migration caches
        from integrations.mission_control import services
        services._kanban_migrated.clear()
        services._timeline_migrated.clear()
        services._plans_migrated.clear()

        yield

        # Cleanup
        import asyncio
        from integrations.mission_control.db.engine import close_mc_engine
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(close_mc_engine())
            else:
                loop.run_until_complete(close_mc_engine())
        except Exception:
            pass

        services._kanban_migrated.clear()
        services._timeline_migrated.clear()
        services._plans_migrated.clear()


class TestMCOverview:
    async def test_overview_empty(self, client, db_session):
        resp = await client.get("/integrations/mission_control/overview", headers=AUTH_HEADERS)
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

        resp = await client.get("/integrations/mission_control/overview", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_channels"] == 1
        assert body["channels"][0]["name"] == "test-project"
        assert body["channels"][0]["bot_id"] == "test-bot"


class TestMCKanban:
    async def test_kanban_empty(self, client, db_session):
        resp = await client.get("/integrations/mission_control/kanban", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["columns"] == []

    async def test_kanban_with_tasks(self, client, db_session, _mc_db):
        """Channels with cards in MC DB show up in aggregated kanban."""
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

        # Seed a card directly into MC DB
        from integrations.mission_control.services import create_card
        await create_card(str(ch.id), "Test task", column="Backlog", priority="high")

        resp = await client.get("/integrations/mission_control/kanban", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["columns"]) >= 1
        backlog = next((c for c in body["columns"] if c["name"] == "Backlog"), None)
        assert backlog is not None
        assert len(backlog["cards"]) == 1
        assert backlog["cards"][0]["title"] == "Test task"
        assert backlog["cards"][0]["channel_name"] == "kanban-test"

    async def test_kanban_create(self, client, db_session, _mc_db):
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

        resp = await client.post(
            "/integrations/mission_control/kanban/create",
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

    async def test_kanban_move(self, client, db_session, _mc_db):
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

        # Create a card first
        from integrations.mission_control.services import create_card
        result = await create_card(str(ch.id), "Move me", column="Backlog", priority="medium")
        card_id = result["card_id"]

        resp = await client.post(
            "/integrations/mission_control/kanban/move",
            json={
                "card_id": card_id,
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

    async def test_kanban_move_not_found(self, client, db_session, _mc_db):
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

        resp = await client.post(
            "/integrations/mission_control/kanban/move",
            json={
                "card_id": "mc-nonexistent",
                "from_column": "Backlog",
                "to_column": "Done",
                "channel_id": str(ch.id),
            },
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 404

    async def test_kanban_move_wrong_from_column(self, client, db_session, _mc_db):
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

        # Create a card in Backlog
        from integrations.mission_control.services import create_card
        result = await create_card(str(ch.id), "Card", column="Backlog")

        resp = await client.post(
            "/integrations/mission_control/kanban/move",
            json={
                "card_id": result["card_id"],
                "from_column": "In Progress",  # card is actually in Backlog
                "to_column": "Done",
                "channel_id": str(ch.id),
            },
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 409


class TestMCTimeline:
    async def test_timeline_empty(self, client, db_session):
        resp = await client.get("/integrations/mission_control/timeline?days=7", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["events"] == []

    async def test_timeline_with_events(self, client, db_session, _mc_db):
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

        # Seed events directly into MC DB
        from integrations.mission_control.services import append_timeline
        await append_timeline(str(ch.id), "Sprint 5 kicked off")
        await append_timeline(str(ch.id), "Card mc-abc123 moved to **Done** (was: Review)")

        resp = await client.get(
            "/integrations/mission_control/timeline?days=7",
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["events"]) == 2
        assert body["events"][0]["channel_name"] == "timeline-test"


class TestMCJournal:
    async def test_journal_empty(self, client, db_session):
        resp = await client.get("/integrations/mission_control/journal?days=7", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["entries"] == []


class TestMCMemory:
    async def test_memory_empty(self, client, db_session):
        resp = await client.get("/integrations/mission_control/memory", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["sections"] == []


class TestMCChannelContext:
    async def test_context_not_found(self, client, db_session):
        fake_id = str(uuid.uuid4())
        resp = await client.get(
            f"/integrations/mission_control/channels/{fake_id}/context",
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
                f"/integrations/mission_control/channels/{ch.id}/context",
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
        resp = await client.get("/integrations/mission_control/prefs", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        # API key auth returns empty prefs (no user)
        assert body.get("tracked_channel_ids") is None

    async def test_update_prefs_requires_user(self, client, db_session):
        """API key auth cannot save prefs (needs JWT user)."""
        resp = await client.put(
            "/integrations/mission_control/prefs",
            json={"tracked_channel_ids": ["abc"]},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 400


class TestMCPlanApprove:
    """Tests for plan approval with the plan execution engine."""

    async def test_approve_starts_execution_engine(self, client, db_session, _mc_db):
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
        await db_session.commit()

        # Create a draft plan via MC DB
        from integrations.mission_control.tools.plans import draft_plan
        import re
        result_text = await draft_plan(str(ch.id), "Test Plan", ["Step 1", "Step 2", "Step 3"])
        plan_id = re.search(r"plan-\w+", result_text).group()

        # Mock advance_plan to avoid core DB access (imported lazily inside function)
        with patch(
            "integrations.mission_control.plan_executor.advance_plan",
            new_callable=AsyncMock,
        ):
            resp = await client.post(
                f"/integrations/mission_control/channels/{ch.id}/plans/{plan_id}/approve",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["status"] == "approved"
        assert body["execution_started"] is True

        # Verify plan status changed to approved in MC DB
        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McPlan
        from sqlalchemy import select

        async with await mc_session() as session:
            db_plan = (await session.execute(
                select(McPlan).where(McPlan.plan_id == plan_id)
            )).scalar_one()
            assert db_plan.status == "approved"

    async def test_approve_rejects_non_draft(self, client, db_session, _mc_db):
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
        await db_session.commit()

        # Create and then reject a plan
        from integrations.mission_control.tools.plans import draft_plan
        from integrations.mission_control.services import reject_plan
        import re
        result_text = await draft_plan(str(ch.id), "Reject me", ["Step 1"])
        plan_id = re.search(r"plan-\w+", result_text).group()
        await reject_plan(str(ch.id), plan_id)

        resp = await client.post(
            f"/integrations/mission_control/channels/{ch.id}/plans/{plan_id}/approve",
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 409


class TestMCPlanResume:
    """Tests for plan resume with the plan execution engine."""

    async def test_resume_restarts_execution(self, client, db_session, _mc_db):
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
        await db_session.commit()

        # Create a plan and set to executing status
        from integrations.mission_control.tools.plans import draft_plan
        from integrations.mission_control.services import approve_plan
        import re
        result_text = await draft_plan(
            str(ch.id), "Multi-Step Plan",
            ["First step", "Second step", "Third step", "Fourth step"],
        )
        plan_id = re.search(r"plan-\w+", result_text).group()
        await approve_plan(str(ch.id), plan_id)

        # Mark some steps as done to simulate partial execution
        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McPlan
        from sqlalchemy import select

        async with await mc_session() as session:
            db_plan = (await session.execute(
                select(McPlan).where(McPlan.plan_id == plan_id)
            )).scalar_one()
            await session.refresh(db_plan, ["steps"])
            db_plan.steps[0].status = "done"
            db_plan.steps[1].status = "done"
            db_plan.status = "executing"
            await session.commit()

        with patch(
            "integrations.mission_control.plan_executor.advance_plan",
            new_callable=AsyncMock,
        ):
            resp = await client.post(
                f"/integrations/mission_control/channels/{ch.id}/plans/{plan_id}/resume",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["execution_started"] is True

    async def test_resume_rejects_non_executing(self, client, db_session, _mc_db):
        from app.db.models import Channel

        ch = Channel(
            id=uuid.uuid4(),
            name="resume-reject",
            bot_id="test-bot",
            channel_workspace_enabled=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(ch)
        await db_session.commit()

        from integrations.mission_control.tools.plans import draft_plan
        import re
        result_text = await draft_plan(str(ch.id), "Draft Plan", ["Do something"])
        plan_id = re.search(r"plan-\w+", result_text).group()

        resp = await client.post(
            f"/integrations/mission_control/channels/{ch.id}/plans/{plan_id}/resume",
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 409
