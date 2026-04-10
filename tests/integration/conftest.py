"""Integration test fixtures: in-memory SQLite DB, test FastAPI app, mock bot registry."""
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Text, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ---------------------------------------------------------------------------
# Ensure env vars are set before any app import
# ---------------------------------------------------------------------------
os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

# Register SQLite-compatible compilers for PostgreSQL-specific types
from pgvector.sqlalchemy import Vector  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID, TIMESTAMP as PG_TIMESTAMP, TSVECTOR as PG_TSVECTOR  # noqa: E402


@compiles(Vector, "sqlite")
def _compile_vector_sqlite(type_, compiler, **kw):
    return "TEXT"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(PG_UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):
    return "CHAR(36)"


# SQLite doesn't have native UUID support.  Register bind/result processors
# so uuid.UUID objects survive the round-trip through CHAR(36) columns.
import uuid as _uuid_mod

_orig_bind = PG_UUID.bind_processor

def _patched_bind_processor(self, dialect):
    if dialect.name == "sqlite":
        def process(value):
            if value is None:
                return value
            if isinstance(value, _uuid_mod.UUID):
                return str(value)
            return value
        return process
    return _orig_bind(self, dialect)

_orig_result = PG_UUID.result_processor

def _patched_result_processor(self, dialect, coltype):
    if dialect.name == "sqlite":
        def process(value):
            if value is None:
                return value
            if isinstance(value, _uuid_mod.UUID):
                return value
            return _uuid_mod.UUID(str(value))
        return process
    return _orig_result(self, dialect, coltype)

PG_UUID.bind_processor = _patched_bind_processor
PG_UUID.result_processor = _patched_result_processor


@compiles(PG_TSVECTOR, "sqlite")
def _compile_tsvector_sqlite(type_, compiler, **kw):
    return "TEXT"


@compiles(PG_TIMESTAMP, "sqlite")
def _compile_timestamp_sqlite(type_, compiler, **kw):
    return "TIMESTAMP"


from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.dependencies import ApiKeyAuth, get_db, verify_auth, verify_admin_auth, verify_auth_or_user  # noqa: E402

# ---------------------------------------------------------------------------
# Test bot configuration
# ---------------------------------------------------------------------------

TEST_BOT = BotConfig(
    id="test-bot",
    name="Test Bot",
    model="test/model",
    system_prompt="You are a test bot.",
    memory=MemoryConfig(enabled=False),
    knowledge=KnowledgeConfig(enabled=False),
)

DEFAULT_BOT = BotConfig(
    id="default",
    name="Default Bot",
    model="test/default-model",
    system_prompt="You are the default bot.",
    memory=MemoryConfig(enabled=False),
    knowledge=KnowledgeConfig(enabled=False),
)

_TEST_REGISTRY = {"test-bot": TEST_BOT, "default": DEFAULT_BOT}

AUTH_HEADERS = {"Authorization": "Bearer test-key"}


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    # Replace pg-specific server defaults with SQLite equivalents.
    from sqlalchemy import text as sa_text
    from sqlalchemy.schema import FetchedValue
    originals = {}
    _REPLACEMENTS = {
        "now()": "CURRENT_TIMESTAMP",
        "gen_random_uuid()": None,  # strip — Python provides UUIDs
    }
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            sd = col.server_default
            if sd is None:
                continue
            sd_text = str(sd.arg) if hasattr(sd, "arg") else str(sd)
            new_default = None
            needs_replace = False
            # Check for direct replacements
            for pg_expr, sqlite_expr in _REPLACEMENTS.items():
                if pg_expr in sd_text:
                    needs_replace = True
                    new_default = sqlite_expr
                    break
            # Check for ::jsonb or ::json casting — strip the cast
            if not needs_replace and "::jsonb" in sd_text:
                needs_replace = True
                # e.g. "'{}'::jsonb" → "'{}'"
                new_default = sd_text.replace("::jsonb", "")
            if not needs_replace and "::json" in sd_text:
                needs_replace = True
                new_default = sd_text.replace("::json", "")
            if needs_replace:
                originals[(table.name, col.name)] = sd
                if new_default:
                    from sqlalchemy.schema import DefaultClause
                    col.server_default = DefaultClause(sa_text(new_default))
                else:
                    col.server_default = None

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Restore original server defaults so the real app is unaffected
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


# ---------------------------------------------------------------------------
# FastAPI test app (no lifespan — avoids migrations, bot loading, etc.)
# ---------------------------------------------------------------------------

def _build_test_app():
    """Build a minimal FastAPI app with only the routers under test."""
    from fastapi import FastAPI
    from app.routers.api_v1 import router as api_v1_router
    from app.routers.chat import router as chat_router
    from integrations.mission_control.router import router as mc_router

    test_app = FastAPI()
    test_app.include_router(api_v1_router)
    test_app.include_router(chat_router)
    test_app.include_router(mc_router, prefix="/integrations/mission_control")
    return test_app


@pytest_asyncio.fixture
async def client(engine, db_session):
    app = _build_test_app()

    _admin_auth = ApiKeyAuth(
        key_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
        scopes=["admin"],
        name="test",
    )

    # Build a session factory from the test engine so services that create their
    # own sessions (via async_session()) use the test DB instead of the real one.
    _test_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_get_db():
        yield db_session

    async def _override_verify_auth():
        return "test-key"

    async def _override_admin_auth():
        return _admin_auth

    async def _override_auth_or_user():
        return _admin_auth

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[verify_auth] = _override_verify_auth
    app.dependency_overrides[verify_admin_auth] = _override_admin_auth
    app.dependency_overrides[verify_auth_or_user] = _override_auth_or_user

    # Patch bot registry + get_bot to use test bots, and get_persona to return None.
    # Also patch async_session in services that create their own sessions.
    with (
        patch("app.agent.bots._registry", _TEST_REGISTRY),
        patch("app.agent.bots.get_bot", side_effect=_get_test_bot),
        patch("app.agent.persona.get_persona", return_value=None),
        patch("app.services.workflows.async_session", _test_session_factory),
        patch("app.services.workflow_executor.async_session", _test_session_factory),
        patch("app.services.bot_hooks.async_session", _test_session_factory),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    app.dependency_overrides.clear()


def _get_test_bot(bot_id: str) -> BotConfig:
    from fastapi import HTTPException
    bot = _TEST_REGISTRY.get(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail=f"Unknown bot: {bot_id}")
    return bot
