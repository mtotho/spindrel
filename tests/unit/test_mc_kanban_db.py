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
