"""Unit tests for single-workspace API guards on the workspaces router."""
import os
import uuid

os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import DefaultClause
from unittest.mock import patch

# Register SQLite-compatible compilers
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


from app.db.models import Base, SharedWorkspace
from app.dependencies import get_db, verify_auth, verify_auth_or_user

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
    from app.routers.api_v1_workspaces import router as ws_router

    app = FastAPI()
    app.include_router(ws_router, prefix="/api/v1/admin")

    async def _override_get_db():
        yield db_session

    async def _override_verify_auth():
        return "test-key"

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[verify_auth] = _override_verify_auth
    app.dependency_overrides[verify_auth_or_user] = _override_verify_auth

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


class TestCreateWorkspaceGuard:
    @pytest.mark.asyncio
    async def test_create_blocked_when_workspace_exists(self, client, db_session):
        # Pre-create a workspace
        ws = SharedWorkspace(name="Existing")
        db_session.add(ws)
        await db_session.flush()
        await db_session.commit()

        resp = await client.post(
            "/api/v1/admin/workspaces",
            json={"name": "Second Workspace"},
        )
        assert resp.status_code == 400
        assert "Single workspace mode" in resp.json()["detail"]


class TestDeleteWorkspaceGuard:
    @pytest.mark.asyncio
    async def test_delete_always_blocked(self, client, db_session):
        ws = SharedWorkspace(name="Default")
        db_session.add(ws)
        await db_session.flush()
        await db_session.commit()

        resp = await client.delete(f"/api/v1/admin/workspaces/{ws.id}")
        assert resp.status_code == 400
        assert "cannot be deleted" in resp.json()["detail"]


class TestGetDefaultWorkspace:
    @pytest.mark.asyncio
    async def test_returns_single_workspace(self, client, db_session):
        ws = SharedWorkspace(name="My Workspace")
        db_session.add(ws)
        await db_session.flush()
        await db_session.commit()

        resp = await client.get("/api/v1/admin/workspaces/default")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "My Workspace"

    @pytest.mark.asyncio
    async def test_404_when_no_workspace(self, client):
        resp = await client.get("/api/v1/admin/workspaces/default")
        assert resp.status_code == 404
