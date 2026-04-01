"""Tests for Mission Control timeline operations backed by SQLite DB."""
import os
import uuid

import pytest
import pytest_asyncio

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("API_KEY", "test-key")

from unittest.mock import AsyncMock, patch


@pytest_asyncio.fixture
async def mc_db(tmp_path):
    """Set up a temporary MC SQLite database for each test."""
    db_path = str(tmp_path / "mc_test.db")

    with patch("integrations.mission_control.db.engine._get_db_path", return_value=db_path):
        import integrations.mission_control.db.engine as eng_mod
        eng_mod._engine = None
        eng_mod._session_factory = None

        from integrations.mission_control.db.engine import get_mc_engine, close_mc_engine

        await get_mc_engine()
        yield

        await close_mc_engine()

    from integrations.mission_control import services
    services._kanban_migrated.clear()
    services._timeline_migrated.clear()
    services._plans_migrated.clear()


@pytest.fixture
def mock_workspace():
    """Mock workspace file I/O."""
    with (
        patch("integrations.mission_control.services._resolve_bot", new_callable=AsyncMock),
        patch("app.services.channel_workspace.ensure_channel_workspace"),
        patch("app.services.channel_workspace.write_workspace_file"),
        patch("app.services.channel_workspace.read_workspace_file", return_value=None),
    ):
        yield


CHANNEL_ID = str(uuid.uuid4())


@pytest.mark.asyncio
class TestAppendTimeline:
    async def test_append_timeline_inserts_event(self, mc_db, mock_workspace):
        from integrations.mission_control.services import append_timeline

        await append_timeline(CHANNEL_ID, "Deployed v2.1.0")

        # Verify in DB
        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McTimelineEvent
        from sqlalchemy import select

        async with await mc_session() as session:
            events = (await session.execute(
                select(McTimelineEvent).where(McTimelineEvent.channel_id == CHANNEL_ID)
            )).scalars().all()
            assert len(events) == 1
            assert events[0].event == "Deployed v2.1.0"
            assert events[0].event_date  # should have a date
            assert events[0].event_time  # should have a time

    async def test_timeline_renders_markdown(self, mc_db, tmp_path):
        """Markdown file should be written after appending."""
        written_content = {}

        def _capture_write(channel_id, bot, filename, content):
            written_content[filename] = content

        with (
            patch("integrations.mission_control.services._resolve_bot", new_callable=AsyncMock),
            patch("app.services.channel_workspace.ensure_channel_workspace"),
            patch("app.services.channel_workspace.write_workspace_file", side_effect=_capture_write),
            patch("app.services.channel_workspace.read_workspace_file", return_value=None),
        ):
            from integrations.mission_control.services import append_timeline

            await append_timeline(CHANNEL_ID, "Test event for rendering")

        assert "timeline.md" in written_content
        assert "Test event for rendering" in written_content["timeline.md"]


@pytest.mark.asyncio
class TestTimelineMigration:
    async def test_lazy_migration_imports_timeline(self, mc_db, tmp_path):
        """When DB is empty but timeline.md exists, import it."""
        timeline_md = (
            "## 2026-04-01\n"
            "- 14:32 \u2014 Deployed v2.1.0\n"
            "- 13:00 \u2014 Sprint started\n\n"
            "## 2026-03-31\n"
            "- 18:00 \u2014 Release candidate tagged\n"
        )

        ch_id = str(uuid.uuid4())

        with (
            patch("integrations.mission_control.services._resolve_bot", new_callable=AsyncMock),
            patch("app.services.channel_workspace.ensure_channel_workspace"),
            patch("app.services.channel_workspace.write_workspace_file"),
            patch("app.services.channel_workspace.read_workspace_file", return_value=timeline_md),
        ):
            from integrations.mission_control.services import get_timeline_events

            events = await get_timeline_events(ch_id)

        assert len(events) == 3
        assert events[0]["event"] == "Deployed v2.1.0"
        assert events[0]["date"] == "2026-04-01"
        assert events[2]["date"] == "2026-03-31"
