"""Unit tests for app.services.workspace_bootstrap."""
import os
import uuid

os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
import pytest_asyncio
from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import DefaultClause

# Register SQLite-compatible compilers for PostgreSQL-specific types
from pgvector.sqlalchemy import Vector
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID, TIMESTAMP as PG_TIMESTAMP, TSVECTOR as PG_TSVECTOR


@compiles(Vector, "sqlite")
def _compile_vector_sqlite(type_, compiler, **kw):
    return "TEXT"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "TEXT"


@compiles(PG_UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):
    return "CHAR(32)"


@compiles(PG_TSVECTOR, "sqlite")
def _compile_tsvector_sqlite(type_, compiler, **kw):
    return "TEXT"


@compiles(PG_TIMESTAMP, "sqlite")
def _compile_timestamp_sqlite(type_, compiler, **kw):
    return "TIMESTAMP"


from app.db.models import Base, Bot as BotRow, SharedWorkspace, SharedWorkspaceBot
from app.services.workspace_bootstrap import ensure_default_workspace, ensure_all_bots_enrolled


_REPLACEMENTS = {
    "now()": "CURRENT_TIMESTAMP",
    "gen_random_uuid()": None,
}


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    originals = {}
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            sd = col.server_default
            if sd is None:
                continue
            sd_text = str(sd.arg) if hasattr(sd, "arg") else str(sd)
            new_default = None
            needs_replace = False
            for pg_expr, sqlite_expr in _REPLACEMENTS.items():
                if pg_expr in sd_text:
                    needs_replace = True
                    new_default = sqlite_expr
                    break
            if not needs_replace and "::jsonb" in sd_text:
                needs_replace = True
                new_default = sd_text.replace("::jsonb", "")
            if not needs_replace and "::json" in sd_text:
                needs_replace = True
                new_default = sd_text.replace("::json", "")
            if needs_replace:
                originals[(table.name, col.name)] = sd
                if new_default:
                    col.server_default = DefaultClause(sa_text(new_default))
                else:
                    col.server_default = None

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    for (tname, cname), default in originals.items():
        table = Base.metadata.tables[tname]
        table.c[cname].server_default = default

    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


def _make_bot_row(bot_id: str) -> BotRow:
    return BotRow(
        id=bot_id,
        name=f"Bot {bot_id}",
        model="test/model",
        system_prompt="test",
    )


class TestEnsureDefaultWorkspace:
    @pytest.mark.asyncio
    async def test_creates_workspace_when_empty(self, db):
        ws = await ensure_default_workspace(db)
        assert ws is not None
        assert ws.name == "Default Workspace"
        assert ws.id is not None

    @pytest.mark.asyncio
    async def test_returns_existing_workspace(self, db):
        # Create a workspace first
        existing = SharedWorkspace(name="My Workspace")
        db.add(existing)
        await db.flush()
        await db.commit()

        ws = await ensure_default_workspace(db)
        assert str(ws.id) == str(existing.id)
        assert ws.name == "My Workspace"

    @pytest.mark.asyncio
    async def test_idempotent_no_duplicate(self, db):
        ws1 = await ensure_default_workspace(db)
        ws2 = await ensure_default_workspace(db)
        assert str(ws1.id) == str(ws2.id)

        # Should still be only 1 workspace
        result = await db.execute(select(SharedWorkspace))
        all_ws = result.scalars().all()
        assert len(all_ws) == 1


class TestEnsureAllBotsEnrolled:
    @pytest.mark.asyncio
    async def test_enrolls_all_bots(self, db):
        # Create workspace and bots
        ws = SharedWorkspace(name="Test WS")
        db.add(ws)
        await db.flush()

        for bid in ["bot-a", "bot-b", "bot-c"]:
            db.add(_make_bot_row(bid))
        await db.flush()
        await db.commit()

        added = await ensure_all_bots_enrolled(db, ws.id)
        assert added == 3

        # Verify all enrolled
        result = await db.execute(select(SharedWorkspaceBot))
        rows = result.scalars().all()
        enrolled_ids = {r.bot_id for r in rows}
        assert enrolled_ids == {"bot-a", "bot-b", "bot-c"}

    @pytest.mark.asyncio
    async def test_idempotent_no_duplicates(self, db):
        ws = SharedWorkspace(name="Test WS")
        db.add(ws)
        await db.flush()
        db.add(_make_bot_row("bot-x"))
        await db.flush()
        await db.commit()

        added1 = await ensure_all_bots_enrolled(db, ws.id)
        assert added1 == 1

        added2 = await ensure_all_bots_enrolled(db, ws.id)
        assert added2 == 0

    @pytest.mark.asyncio
    async def test_preserves_existing_roles(self, db):
        ws = SharedWorkspace(name="Test WS")
        db.add(ws)
        await db.flush()
        db.add(_make_bot_row("bot-orch"))
        await db.flush()

        # Manually enroll with orchestrator role
        db.add(SharedWorkspaceBot(
            workspace_id=ws.id,
            bot_id="bot-orch",
            role="orchestrator",
        ))
        await db.flush()

        # Add another bot
        db.add(_make_bot_row("bot-new"))
        await db.flush()
        await db.commit()

        added = await ensure_all_bots_enrolled(db, ws.id)
        assert added == 1  # only the new bot

        # Check orchestrator role preserved
        result = await db.execute(
            select(SharedWorkspaceBot).where(SharedWorkspaceBot.bot_id == "bot-orch")
        )
        orch = result.scalar_one()
        assert orch.role == "orchestrator"

    @pytest.mark.asyncio
    async def test_no_bots_returns_zero(self, db):
        ws = SharedWorkspace(name="Test WS")
        db.add(ws)
        await db.flush()
        await db.commit()

        added = await ensure_all_bots_enrolled(db, ws.id)
        assert added == 0

    @pytest.mark.asyncio
    async def test_default_role_is_member(self, db):
        ws = SharedWorkspace(name="Test WS")
        db.add(ws)
        await db.flush()
        db.add(_make_bot_row("bot-1"))
        await db.flush()
        await db.commit()

        await ensure_all_bots_enrolled(db, ws.id)

        result = await db.execute(
            select(SharedWorkspaceBot).where(SharedWorkspaceBot.bot_id == "bot-1")
        )
        row = result.scalar_one()
        assert row.role == "member"


class TestLoadBotsAutoEnrollment:
    """Verify that load_bots() auto-enrolls new bots into the default workspace."""

    @pytest.mark.asyncio
    async def test_load_bots_enrolls_new_bot(self, engine, db):
        """A bot added to the DB should be auto-enrolled after load_bots()."""
        from unittest.mock import patch
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

        # Create the default workspace
        ws = SharedWorkspace(name="Default Workspace")
        db.add(ws)
        await db.flush()

        # Create a bot
        db.add(_make_bot_row("new-bot"))
        await db.flush()
        await db.commit()

        # Verify NOT enrolled yet
        result = await db.execute(
            select(SharedWorkspaceBot).where(SharedWorkspaceBot.bot_id == "new-bot")
        )
        assert result.scalar_one_or_none() is None

        # Patch async_session to use the test engine
        test_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        with patch("app.agent.bots.async_session", test_session_factory):
            from app.agent.bots import load_bots, _registry
            await load_bots()

        # Now the bot should be enrolled in the DB
        result = await db.execute(
            select(SharedWorkspaceBot).where(SharedWorkspaceBot.bot_id == "new-bot")
        )
        row = result.scalar_one_or_none()
        assert row is not None, "Bot should be auto-enrolled after load_bots()"
        assert str(row.workspace_id) == str(ws.id)
        assert row.role == "member"

        # The in-memory registry should also reflect the enrollment
        from app.agent.bots import _registry
        bot_cfg = _registry.get("new-bot")
        assert bot_cfg is not None
        assert bot_cfg.shared_workspace_id == str(ws.id)
        assert bot_cfg.shared_workspace_role == "member"

    @pytest.mark.asyncio
    async def test_load_bots_skips_when_no_workspace(self, engine, db):
        """If no workspace exists, load_bots() should not crash."""
        from unittest.mock import patch
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

        # Create a bot but NO workspace
        db.add(_make_bot_row("orphan-bot"))
        await db.flush()
        await db.commit()

        test_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        with patch("app.agent.bots.async_session", test_session_factory):
            from app.agent.bots import load_bots
            # Should not raise
            await load_bots()

        # No enrollment rows
        result = await db.execute(select(SharedWorkspaceBot))
        assert result.scalars().all() == []

    @pytest.mark.asyncio
    async def test_load_bots_preserves_existing_enrollment(self, engine, db):
        """Existing enrollments (e.g., orchestrator role) should not be overwritten."""
        from unittest.mock import patch
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

        ws = SharedWorkspace(name="Default Workspace")
        db.add(ws)
        await db.flush()

        db.add(_make_bot_row("orch-bot"))
        await db.flush()

        # Pre-enroll with orchestrator role
        db.add(SharedWorkspaceBot(
            workspace_id=ws.id,
            bot_id="orch-bot",
            role="orchestrator",
        ))
        await db.flush()
        await db.commit()

        test_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        with patch("app.agent.bots.async_session", test_session_factory):
            from app.agent.bots import load_bots
            await load_bots()

        # Role should still be orchestrator
        result = await db.execute(
            select(SharedWorkspaceBot).where(SharedWorkspaceBot.bot_id == "orch-bot")
        )
        row = result.scalar_one()
        assert row.role == "orchestrator"
