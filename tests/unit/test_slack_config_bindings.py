"""Tests for /integrations/slack/config — verifies both legacy (Channel.integration='slack')
and modern (ChannelIntegration table) bindings are returned correctly."""
import os
os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import DefaultClause

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


from app.db.models import Base, Bot as BotRow, Channel, ChannelIntegration

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
async def db_session(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session):
    from fastapi import FastAPI
    from integrations.slack.router import router as slack_router

    test_app = FastAPI()
    test_app.include_router(slack_router, prefix="/integrations/slack")

    # Patch async_session to use our test DB session
    from unittest.mock import patch, AsyncMock
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _mock_session():
        yield db_session

    with patch("integrations.slack.router.async_session", _mock_session):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture
async def seed_bots(db_session):
    """Seed two bots for testing."""
    for bid, name in [("bot-a", "Bot A"), ("bot-b", "Bot B")]:
        db_session.add(BotRow(id=bid, name=name, display_name=name, system_prompt="test", model="test/model"))
    await db_session.flush()


@pytest_asyncio.fixture
async def legacy_channel(db_session, seed_bots):
    """Create a legacy channel with integration='slack' and client_id set directly."""
    ch_id = uuid.uuid4()
    db_session.add(Channel(
        id=ch_id,
        name="legacy-channel",
        bot_id="bot-a",
        client_id="slack:CLEGACY001",
        integration="slack",
        require_mention=False,
        passive_memory=False,
    ))
    await db_session.flush()
    return ch_id


@pytest_asyncio.fixture
async def modern_channel(db_session, seed_bots):
    """Create a channel bound via ChannelIntegration (the UI binding flow)."""
    ch_id = uuid.uuid4()
    db_session.add(Channel(
        id=ch_id,
        name="modern-channel",
        bot_id="bot-b",
        require_mention=False,
        passive_memory=True,
    ))
    await db_session.flush()
    db_session.add(ChannelIntegration(
        channel_id=ch_id,
        integration_type="slack",
        client_id="slack:CMODERN001",
        display_name="#modern-channel",
    ))
    await db_session.flush()
    return ch_id


@pytest_asyncio.fixture
async def both_channels(legacy_channel, modern_channel):
    """Both channel types exist."""
    return legacy_channel, modern_channel


class TestSlackConfigLegacyBindings:
    @pytest.mark.asyncio
    async def test_legacy_channel_appears_in_config(self, client, legacy_channel):
        r = await client.get(
            "/integrations/slack/config",
            headers={"X-API-Key": "test-key"},
        )
        assert r.status_code == 200
        channels = r.json()["channels"]
        assert "CLEGACY001" in channels
        ch = channels["CLEGACY001"]
        assert ch["bot_id"] == "bot-a"
        assert ch["require_mention"] is False
        assert ch["passive_memory"] is False


class TestSlackConfigModernBindings:
    @pytest.mark.asyncio
    async def test_modern_binding_appears_in_config(self, client, modern_channel):
        """Channels bound via ChannelIntegration should appear in /config."""
        r = await client.get(
            "/integrations/slack/config",
            headers={"X-API-Key": "test-key"},
        )
        assert r.status_code == 200
        channels = r.json()["channels"]
        assert "CMODERN001" in channels
        ch = channels["CMODERN001"]
        assert ch["bot_id"] == "bot-b"
        assert ch["require_mention"] is False
        assert ch["passive_memory"] is True

    @pytest.mark.asyncio
    async def test_modern_binding_has_all_config_fields(self, client, modern_channel):
        """Modern bindings should return the same fields as legacy."""
        r = await client.get(
            "/integrations/slack/config",
            headers={"X-API-Key": "test-key"},
        )
        assert r.status_code == 200
        ch = r.json()["channels"]["CMODERN001"]
        for field in ("bot_id", "require_mention", "passive_memory", "allow_bot_messages", "thinking_display"):
            assert field in ch, f"Missing field: {field}"


class TestSlackConfigBothBindingTypes:
    @pytest.mark.asyncio
    async def test_both_binding_types_coexist(self, client, both_channels):
        """Both legacy and modern channels should appear in the same /config response."""
        r = await client.get(
            "/integrations/slack/config",
            headers={"X-API-Key": "test-key"},
        )
        assert r.status_code == 200
        channels = r.json()["channels"]
        assert "CLEGACY001" in channels
        assert "CMODERN001" in channels

    @pytest.mark.asyncio
    async def test_legacy_takes_precedence_over_modern(self, client, db_session, seed_bots):
        """If the same Slack ID has both a legacy channel AND a modern binding,
        the legacy one should take precedence."""
        ch_id_legacy = uuid.uuid4()
        ch_id_modern = uuid.uuid4()
        # Legacy channel
        db_session.add(Channel(
            id=ch_id_legacy,
            name="legacy-dup",
            bot_id="bot-a",
            client_id="slack:CDUP001",
            integration="slack",
            require_mention=True,
        ))
        # Modern channel pointing to same Slack ID
        db_session.add(Channel(
            id=ch_id_modern,
            name="modern-dup",
            bot_id="bot-b",
            require_mention=False,
        ))
        await db_session.flush()
        db_session.add(ChannelIntegration(
            channel_id=ch_id_modern,
            integration_type="slack",
            client_id="slack:CDUP001",
        ))
        await db_session.flush()

        r = await client.get(
            "/integrations/slack/config",
            headers={"X-API-Key": "test-key"},
        )
        assert r.status_code == 200
        ch = r.json()["channels"]["CDUP001"]
        # Legacy should win
        assert ch["bot_id"] == "bot-a"
        assert ch["require_mention"] is True

    @pytest.mark.asyncio
    async def test_non_slack_binding_ignored(self, client, db_session, seed_bots):
        """ChannelIntegration with integration_type != 'slack' should not appear."""
        ch_id = uuid.uuid4()
        db_session.add(Channel(
            id=ch_id,
            name="discord-channel",
            bot_id="bot-a",
        ))
        await db_session.flush()
        db_session.add(ChannelIntegration(
            channel_id=ch_id,
            integration_type="discord",
            client_id="discord:123456",
        ))
        await db_session.flush()

        r = await client.get(
            "/integrations/slack/config",
            headers={"X-API-Key": "test-key"},
        )
        assert r.status_code == 200
        channels = r.json()["channels"]
        assert "123456" not in channels
        assert "discord:123456" not in channels
