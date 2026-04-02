"""Tests for Mission Control kanban operations backed by SQLite DB."""
import asyncio
import os
import tempfile
import uuid

import pytest
import pytest_asyncio

# Set up env before any app imports
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("API_KEY", "test-key")

from unittest.mock import AsyncMock, patch


@pytest_asyncio.fixture
async def mc_db(tmp_path):
    """Set up a temporary MC SQLite database for each test."""
    db_path = str(tmp_path / "mc_test.db")

    with patch("integrations.mission_control.db.engine._get_db_path", return_value=db_path):
        # Reset global engine state
        import integrations.mission_control.db.engine as eng_mod
        eng_mod._engine = None
        eng_mod._session_factory = None

        from integrations.mission_control.db.engine import get_mc_engine, mc_session, close_mc_engine

        await get_mc_engine()
        yield mc_session

        await close_mc_engine()

    # Clear migration caches
    from integrations.mission_control import services
    services._kanban_migrated.clear()
    services._timeline_migrated.clear()
    services._plans_migrated.clear()


@pytest.fixture
def mock_workspace():
    """Mock workspace file I/O so services don't try to touch real filesystem."""
    with (
        patch("integrations.mission_control.services._resolve_bot", new_callable=AsyncMock),
        patch("app.services.channel_workspace.ensure_channel_workspace"),
        patch("app.services.channel_workspace.write_workspace_file"),
        patch("app.services.channel_workspace.read_workspace_file", return_value=None),
    ):
        yield


CHANNEL_ID = str(uuid.uuid4())


@pytest.mark.asyncio
class TestCreateCard:
    async def test_create_card_inserts_into_db(self, mc_db, mock_workspace):
        from integrations.mission_control.services import create_card

        result = await create_card(CHANNEL_ID, "Test task", column="Backlog", priority="high")

        assert result["card"]["title"] == "Test task"
        assert result["card"]["meta"]["priority"] == "high"
        assert result["column"] == "Backlog"
        assert result["card_id"].startswith("mc-")

        # Verify it's in the DB
        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McKanbanCard
        from sqlalchemy import select

        async with await mc_session() as session:
            res = await session.execute(
                select(McKanbanCard).where(McKanbanCard.card_id == result["card_id"])
            )
            card = res.scalar_one()
            assert card.title == "Test task"
            assert card.priority == "high"
            assert card.channel_id == CHANNEL_ID

    async def test_create_card_renders_markdown(self, mc_db, tmp_path):
        """Markdown file should be updated after card creation."""
        written_content = {}

        def _capture_write(channel_id, bot, filename, content):
            written_content[filename] = content

        with (
            patch("integrations.mission_control.services._resolve_bot", new_callable=AsyncMock),
            patch("app.services.channel_workspace.ensure_channel_workspace"),
            patch("app.services.channel_workspace.write_workspace_file", side_effect=_capture_write),
            patch("app.services.channel_workspace.read_workspace_file", return_value=None),
        ):
            from integrations.mission_control.services import create_card

            await create_card(CHANNEL_ID, "Rendered task")

        assert "tasks.md" in written_content
        assert "Rendered task" in written_content["tasks.md"]


@pytest.mark.asyncio
class TestMoveCard:
    async def test_move_card_updates_column(self, mc_db, mock_workspace):
        from integrations.mission_control.services import create_card, move_card

        result = await create_card(CHANNEL_ID, "Moving task", column="Backlog")
        card_id = result["card_id"]

        move_result = await move_card(CHANNEL_ID, card_id, "In Progress")

        assert move_result["from_column"] == "Backlog"
        assert move_result["to_column"] == "In Progress"

        # Verify in DB
        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McKanbanCard, McKanbanColumn
        from sqlalchemy import select

        async with await mc_session() as session:
            card = (await session.execute(
                select(McKanbanCard).where(McKanbanCard.card_id == card_id)
            )).scalar_one()
            col = await session.get(McKanbanColumn, card.column_id)
            assert col.name == "In Progress"

    async def test_move_card_adds_transition_dates(self, mc_db, mock_workspace):
        from integrations.mission_control.services import create_card, move_card

        result = await create_card(CHANNEL_ID, "Date task", column="Backlog")
        card_id = result["card_id"]

        move_result = await move_card(CHANNEL_ID, card_id, "In Progress")
        assert "started" in move_result["card"]["meta"]

        move_result2 = await move_card(CHANNEL_ID, card_id, "Done")
        assert "completed" in move_result2["card"]["meta"]

    async def test_move_card_not_found(self, mc_db, mock_workspace):
        from integrations.mission_control.services import move_card

        # Ensure migration has run so we have default columns
        from integrations.mission_control.services import _ensure_kanban_migrated
        await _ensure_kanban_migrated(CHANNEL_ID)

        with pytest.raises(ValueError, match="not found"):
            await move_card(CHANNEL_ID, "mc-nonexistent", "Done")


@pytest.mark.asyncio
class TestUpdateCard:
    async def test_update_card_fields(self, mc_db, mock_workspace):
        from integrations.mission_control.services import create_card, update_card

        result = await create_card(CHANNEL_ID, "Update me", priority="low")
        card_id = result["card_id"]

        update_result = await update_card(
            CHANNEL_ID, card_id,
            title="Updated title",
            priority="critical",
            tags="bug,urgent",
        )

        assert "title" in update_result["changes"]
        assert "priority" in update_result["changes"]
        assert "tags" in update_result["changes"]
        assert update_result["card"]["title"] == "Updated title"
        assert update_result["card"]["meta"]["priority"] == "critical"
        assert update_result["card"]["meta"]["tags"] == "bug,urgent"


@pytest.mark.asyncio
class TestLazyMigration:
    async def test_lazy_migration_imports_from_markdown(self, mc_db, tmp_path):
        """When DB is empty but tasks.md exists, import into DB."""
        tasks_md = (
            "# Tasks\n\n"
            "## Backlog\n\n"
            "### Existing task\n"
            "- **id**: mc-aaa111\n"
            "- **priority**: high\n"
            "- **created**: 2026-04-01\n\n"
            "## Done\n\n"
        )

        with (
            patch("integrations.mission_control.services._resolve_bot", new_callable=AsyncMock),
            patch("app.services.channel_workspace.ensure_channel_workspace"),
            patch("app.services.channel_workspace.write_workspace_file"),
            patch("app.services.channel_workspace.read_workspace_file", return_value=tasks_md),
        ):
            from integrations.mission_control.services import _get_kanban_columns_as_dicts

            # Clear migration cache for this channel
            ch_id = str(uuid.uuid4())
            columns = await _get_kanban_columns_as_dicts(ch_id)

            assert len(columns) >= 2
            backlog = next(c for c in columns if c["name"] == "Backlog")
            assert len(backlog["cards"]) == 1
            assert backlog["cards"][0]["meta"]["id"] == "mc-aaa111"
            assert backlog["cards"][0]["title"] == "Existing task"


@pytest.mark.asyncio
class TestConcurrency:
    async def test_concurrent_creates_no_data_loss(self, mc_db, mock_workspace):
        """Two concurrent creates should both succeed (DB transactions vs file clobbering)."""
        from integrations.mission_control.services import create_card

        ch_id = str(uuid.uuid4())

        results = await asyncio.gather(
            create_card(ch_id, "Task A", column="Backlog"),
            create_card(ch_id, "Task B", column="Backlog"),
        )

        assert results[0]["card_id"] != results[1]["card_id"]

        # Verify both in DB
        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McKanbanCard
        from sqlalchemy import select, func

        async with await mc_session() as session:
            count = (await session.execute(
                select(func.count()).select_from(McKanbanCard)
                .where(McKanbanCard.channel_id == ch_id)
            )).scalar()
            assert count == 2


@pytest.mark.asyncio
class TestCardHistory:
    async def test_matching_events_returned(self, mc_db, mock_workspace):
        from integrations.mission_control.services import create_card, get_card_history

        result = await create_card(CHANNEL_ID, "History test", column="Backlog")
        card_id = result["card_id"]

        # The create_card call should have logged a timeline event containing the card_id
        events = await get_card_history(CHANNEL_ID, card_id)
        assert len(events) >= 1
        assert any(card_id in ev["event"] for ev in events)

    async def test_empty_returns_empty_list(self, mc_db, mock_workspace):
        from integrations.mission_control.services import get_card_history

        # Ensure migration is triggered so timeline table exists
        from integrations.mission_control.services import _ensure_timeline_migrated
        await _ensure_timeline_migrated(CHANNEL_ID)

        events = await get_card_history(CHANNEL_ID, "mc-nonexistent")
        assert events == []

    async def test_limit_respected(self, mc_db, mock_workspace):
        from integrations.mission_control.services import (
            create_card, move_card, update_card, get_card_history,
        )

        result = await create_card(CHANNEL_ID, "Limit test")
        card_id = result["card_id"]
        await move_card(CHANNEL_ID, card_id, "In Progress")
        await update_card(CHANNEL_ID, card_id, title="Renamed")
        await move_card(CHANNEL_ID, card_id, "Done")

        all_events = await get_card_history(CHANNEL_ID, card_id)
        limited = await get_card_history(CHANNEL_ID, card_id, limit=2)
        assert len(limited) == 2
        assert len(all_events) >= 3


@pytest.mark.asyncio
class TestColumnManagement:
    async def test_create_column(self, mc_db, mock_workspace):
        from integrations.mission_control.services import create_column, _get_kanban_columns_as_dicts

        ch_id = str(uuid.uuid4())
        col = await create_column(ch_id, "Review")

        assert col["name"] == "Review"
        columns = await _get_kanban_columns_as_dicts(ch_id)
        names = [c["name"] for c in columns]
        assert "Review" in names

    async def test_rename_column(self, mc_db, mock_workspace):
        from integrations.mission_control.services import create_column, rename_column

        ch_id = str(uuid.uuid4())
        col = await create_column(ch_id, "Review")
        await rename_column(ch_id, col["id"], "Code Review")

        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McKanbanColumn

        async with await mc_session() as session:
            db_col = await session.get(McKanbanColumn, col["id"])
            assert db_col.name == "Code Review"

    async def test_delete_empty_column(self, mc_db, mock_workspace):
        from integrations.mission_control.services import create_column, delete_column

        ch_id = str(uuid.uuid4())
        col = await create_column(ch_id, "Temp")
        await delete_column(ch_id, col["id"])

        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McKanbanColumn

        async with await mc_session() as session:
            db_col = await session.get(McKanbanColumn, col["id"])
            assert db_col is None

    async def test_delete_non_empty_column_fails(self, mc_db, mock_workspace):
        from integrations.mission_control.services import create_card, delete_column, _ensure_kanban_migrated

        ch_id = str(uuid.uuid4())
        await create_card(ch_id, "Blocking card", column="Backlog")

        # Get the Backlog column ID
        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McKanbanColumn
        from sqlalchemy import select, func as sa_func

        async with await mc_session() as session:
            result = await session.execute(
                select(McKanbanColumn)
                .where(McKanbanColumn.channel_id == ch_id)
                .where(sa_func.lower(McKanbanColumn.name) == "backlog")
            )
            col = result.scalar_one()

        with pytest.raises(ValueError, match="has cards"):
            await delete_column(ch_id, col.id)

    async def test_reorder_columns(self, mc_db, mock_workspace):
        from integrations.mission_control.services import create_column, reorder_columns, _get_kanban_columns_as_dicts

        ch_id = str(uuid.uuid4())
        col_a = await create_column(ch_id, "A")
        col_b = await create_column(ch_id, "B")
        col_c = await create_column(ch_id, "C")

        # Get all column IDs (including default Backlog, Done)
        columns = await _get_kanban_columns_as_dicts(ch_id)
        all_ids = [c["id"] for c in columns]

        # Reorder: C, B, A, then the rest
        reordered = [col_c["id"], col_b["id"], col_a["id"]] + [
            cid for cid in all_ids if cid not in (col_a["id"], col_b["id"], col_c["id"])
        ]
        await reorder_columns(ch_id, reordered)

        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McKanbanColumn
        from sqlalchemy import select

        async with await mc_session() as session:
            result = await session.execute(
                select(McKanbanColumn)
                .where(McKanbanColumn.channel_id == ch_id)
                .order_by(McKanbanColumn.position)
            )
            names = [r.name for r in result.scalars().all()]
            # C, B, A should be first three
            assert names[:3] == ["C", "B", "A"]


@pytest.mark.asyncio
class TestPlanKanbanBridge:
    async def _create_plan_with_steps(self, channel_id, title="Test Plan", steps=None):
        """Helper: create a plan in MC DB, return (plan_db_id, plan_id)."""
        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McPlan, McPlanStep
        from integrations.mission_control.services import _ensure_plans_migrated

        await _ensure_plans_migrated(channel_id)

        pid = f"plan-{uuid.uuid4().hex[:6]}"
        steps = steps or ["Step 1", "Step 2", "Step 3"]

        async with await mc_session() as session:
            db_plan = McPlan(
                channel_id=channel_id,
                plan_id=pid,
                title=title,
                status="approved",
            )
            session.add(db_plan)
            await session.flush()
            plan_db_id = db_plan.id

            for i, content in enumerate(steps, 1):
                session.add(McPlanStep(
                    plan_id=plan_db_id,
                    position=i,
                    content=content,
                    status="pending",
                ))
            await session.commit()

        return plan_db_id, pid

    async def test_create_cards_from_plan(self, mc_db, mock_workspace):
        from integrations.mission_control.services import create_cards_from_plan, _get_kanban_columns_as_dicts

        ch_id = str(uuid.uuid4())
        plan_db_id, plan_id = await self._create_plan_with_steps(ch_id)

        card_ids = await create_cards_from_plan(ch_id, plan_id)
        assert len(card_ids) == 3

        columns = await _get_kanban_columns_as_dicts(ch_id)
        backlog = next((c for c in columns if c["name"] == "Backlog"), None)
        assert backlog is not None
        assert len(backlog["cards"]) == 3

    async def test_cards_linked_to_plan(self, mc_db, mock_workspace):
        from integrations.mission_control.services import create_cards_from_plan

        ch_id = str(uuid.uuid4())
        plan_db_id, plan_id = await self._create_plan_with_steps(ch_id)

        card_ids = await create_cards_from_plan(ch_id, plan_id)

        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McKanbanCard
        from sqlalchemy import select

        async with await mc_session() as session:
            for i, card_id in enumerate(card_ids, 1):
                result = await session.execute(
                    select(McKanbanCard).where(McKanbanCard.card_id == card_id)
                )
                card = result.scalar_one()
                assert card.plan_id == plan_id
                assert card.plan_step_position == i

    async def test_move_plan_card_on_step_start(self, mc_db, mock_workspace):
        from integrations.mission_control.services import create_cards_from_plan, move_plan_card

        ch_id = str(uuid.uuid4())
        _, plan_id = await self._create_plan_with_steps(ch_id)
        await create_cards_from_plan(ch_id, plan_id)

        await move_plan_card(ch_id, plan_id, 1, "In Progress")

        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McKanbanCard, McKanbanColumn
        from sqlalchemy import select

        async with await mc_session() as session:
            result = await session.execute(
                select(McKanbanCard)
                .where(McKanbanCard.plan_id == plan_id)
                .where(McKanbanCard.plan_step_position == 1)
            )
            card = result.scalar_one()
            col = await session.get(McKanbanColumn, card.column_id)
            assert col.name == "In Progress"

    async def test_move_plan_card_on_step_complete(self, mc_db, mock_workspace):
        from integrations.mission_control.services import create_cards_from_plan, move_plan_card

        ch_id = str(uuid.uuid4())
        _, plan_id = await self._create_plan_with_steps(ch_id)
        await create_cards_from_plan(ch_id, plan_id)

        await move_plan_card(ch_id, plan_id, 2, "Done")

        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McKanbanCard, McKanbanColumn
        from sqlalchemy import select

        async with await mc_session() as session:
            result = await session.execute(
                select(McKanbanCard)
                .where(McKanbanCard.plan_id == plan_id)
                .where(McKanbanCard.plan_step_position == 2)
            )
            card = result.scalar_one()
            col = await session.get(McKanbanColumn, card.column_id)
            assert col.name == "Done"

    async def test_move_plan_card_on_step_fail(self, mc_db, mock_workspace):
        from integrations.mission_control.services import create_cards_from_plan, move_plan_card

        ch_id = str(uuid.uuid4())
        _, plan_id = await self._create_plan_with_steps(ch_id)
        await create_cards_from_plan(ch_id, plan_id)

        await move_plan_card(ch_id, plan_id, 1, "Failed")

        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McKanbanCard, McKanbanColumn
        from sqlalchemy import select

        async with await mc_session() as session:
            result = await session.execute(
                select(McKanbanCard)
                .where(McKanbanCard.plan_id == plan_id)
                .where(McKanbanCard.plan_step_position == 1)
            )
            card = result.scalar_one()
            col = await session.get(McKanbanColumn, card.column_id)
            assert col.name == "Failed"

    async def test_no_linked_card_no_error(self, mc_db, mock_workspace):
        """move_plan_card should silently no-op when no card is linked."""
        from integrations.mission_control.services import move_plan_card, _ensure_kanban_migrated

        ch_id = str(uuid.uuid4())
        await _ensure_kanban_migrated(ch_id)

        # Should not raise
        await move_plan_card(ch_id, "plan-nonexistent", 1, "Done")

    async def test_duplicate_guard(self, mc_db, mock_workspace):
        """Calling create_cards_from_plan twice should not create duplicates."""
        from integrations.mission_control.services import create_cards_from_plan

        ch_id = str(uuid.uuid4())
        _, plan_id = await self._create_plan_with_steps(ch_id)

        first = await create_cards_from_plan(ch_id, plan_id)
        second = await create_cards_from_plan(ch_id, plan_id)

        assert len(first) == 3
        assert len(second) == 0  # no new cards created


@pytest.mark.asyncio
class TestPlanTemplates:
    async def test_create_and_list(self, mc_db):
        from integrations.mission_control.services import (
            create_plan_template, list_plan_templates,
        )

        tpl = await create_plan_template(
            "Deploy Template",
            "Standard deploy steps",
            [{"content": "Build", "requires_approval": False}, {"content": "Deploy", "requires_approval": True}],
        )
        assert tpl["name"] == "Deploy Template"
        assert tpl["id"]

        templates = await list_plan_templates()
        assert len(templates) == 1
        assert templates[0]["name"] == "Deploy Template"

    async def test_delete(self, mc_db):
        from integrations.mission_control.services import (
            create_plan_template, delete_plan_template, list_plan_templates,
        )

        tpl = await create_plan_template("Temp", "desc", [{"content": "A"}])
        await delete_plan_template(tpl["id"])
        assert await list_plan_templates() == []

    async def test_create_plan_from_template(self, mc_db, mock_workspace):
        from integrations.mission_control.services import (
            create_plan_template, create_plan_from_template, get_single_plan,
        )

        ch_id = str(uuid.uuid4())
        tpl = await create_plan_template(
            "Review Template", "",
            [{"content": "Review code"}, {"content": "Approve", "requires_approval": True}],
        )

        plan_id = await create_plan_from_template(tpl["id"], ch_id, "Review PR #42")
        plan = await get_single_plan(ch_id, plan_id)
        assert plan is not None
        assert plan["title"] == "Review PR #42"
        assert len(plan["steps"]) == 2
        assert plan["steps"][1]["requires_approval"] is True

    async def test_save_plan_as_template(self, mc_db, mock_workspace):
        from integrations.mission_control.services import (
            save_plan_as_template, list_plan_templates, _ensure_plans_migrated,
        )
        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McPlan, McPlanStep

        ch_id = str(uuid.uuid4())
        await _ensure_plans_migrated(ch_id)

        # Create a plan directly in DB
        async with await mc_session() as session:
            plan = McPlan(
                channel_id=ch_id,
                plan_id="plan-save-test",
                title="Saveable Plan",
                status="complete",
            )
            session.add(plan)
            await session.flush()
            session.add(McPlanStep(plan_id=plan.id, position=1, content="Step A", requires_approval=False))
            session.add(McPlanStep(plan_id=plan.id, position=2, content="Step B", requires_approval=True))
            await session.commit()

        tpl = await save_plan_as_template(ch_id, "plan-save-test", "Saved Template", "From a real plan")
        assert tpl["name"] == "Saved Template"

        templates = await list_plan_templates()
        assert len(templates) == 1
        import json
        steps = json.loads(templates[0]["steps_json"])
        assert len(steps) == 2
        assert steps[1]["requires_approval"] is True


@pytest.mark.asyncio
class TestExport:
    async def test_export_kanban_md(self, mc_db, mock_workspace):
        from integrations.mission_control.services import create_card, export_kanban_md

        ch_id = str(uuid.uuid4())
        await create_card(ch_id, "Export me", column="Backlog")

        md = await export_kanban_md(ch_id)
        assert "Export me" in md
        assert "## Backlog" in md

    async def test_export_kanban_json(self, mc_db, mock_workspace):
        from integrations.mission_control.services import create_card, export_kanban_json

        ch_id = str(uuid.uuid4())
        await create_card(ch_id, "JSON card", column="Backlog", priority="high")

        data = await export_kanban_json(ch_id)
        assert isinstance(data, list)
        assert any(
            any(c["title"] == "JSON card" for c in col["cards"])
            for col in data
        )

    async def test_export_plan_md(self, mc_db, mock_workspace):
        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McPlan, McPlanStep
        from integrations.mission_control.services import export_plan_md, _ensure_plans_migrated

        ch_id = str(uuid.uuid4())
        await _ensure_plans_migrated(ch_id)

        async with await mc_session() as session:
            plan = McPlan(channel_id=ch_id, plan_id="plan-export", title="Export Plan", status="draft")
            session.add(plan)
            await session.flush()
            session.add(McPlanStep(plan_id=plan.id, position=1, content="Do thing"))
            await session.commit()

        md = await export_plan_md(ch_id, "plan-export")
        assert "Export Plan" in md
        assert "Do thing" in md

    async def test_export_plan_json(self, mc_db, mock_workspace):
        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McPlan, McPlanStep
        from integrations.mission_control.services import export_plan_json, _ensure_plans_migrated

        ch_id = str(uuid.uuid4())
        await _ensure_plans_migrated(ch_id)

        async with await mc_session() as session:
            plan = McPlan(channel_id=ch_id, plan_id="plan-json", title="JSON Plan", status="draft")
            session.add(plan)
            await session.flush()
            session.add(McPlanStep(plan_id=plan.id, position=1, content="JSON step"))
            await session.commit()

        data = await export_plan_json(ch_id, "plan-json")
        assert data["title"] == "JSON Plan"
        assert len(data["steps"]) == 1

    async def test_export_plan_not_found(self, mc_db, mock_workspace):
        from integrations.mission_control.services import export_plan_md, _ensure_plans_migrated

        ch_id = str(uuid.uuid4())
        await _ensure_plans_migrated(ch_id)

        with pytest.raises(ValueError, match="not found"):
            await export_plan_md(ch_id, "plan-nonexistent")
