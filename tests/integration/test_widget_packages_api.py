"""Integration tests for /api/v1/admin/widget-packages/* endpoints."""
from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.models import Base, WidgetTemplatePackage


@pytest_asyncio.fixture
async def shared_engine():
    """Engine with StaticPool so multiple sessions share one in-memory DB.

    Default QueuePool can open extra connections while a session is still
    acquired; those see private `:memory:` DBs without our tables. Needed
    for endpoints that call reload_tool (which opens its own session) while
    the request's db_session is still active.
    """
    from sqlalchemy import text as sa_text
    from sqlalchemy.schema import DefaultClause

    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    originals = {}
    _REPLACEMENTS = {"now()": "CURRENT_TIMESTAMP", "gen_random_uuid()": None}
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
                col.server_default = DefaultClause(sa_text(new_default)) if new_default else None

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    for (tname, cname), default in originals.items():
        Base.metadata.tables[tname].c[cname].server_default = default

    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def shared_session(shared_engine):
    factory = async_sessionmaker(shared_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def shared_client(shared_engine, shared_session):
    """Test client whose get_db + reload_tool share the shared_engine."""
    from app.db import engine as engine_mod
    from app.dependencies import get_db, verify_admin_auth, verify_auth, verify_auth_or_user, ApiKeyAuth
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    import uuid
    from app.routers.api_v1 import router as api_v1_router

    app = FastAPI()
    app.include_router(api_v1_router)

    factory = async_sessionmaker(shared_engine, class_=AsyncSession, expire_on_commit=False)
    admin_auth = ApiKeyAuth(
        key_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
        scopes=["admin"], name="test",
    )

    async def _override_get_db():
        yield shared_session

    async def _override_admin():
        return admin_auth

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[verify_admin_auth] = _override_admin
    app.dependency_overrides[verify_auth] = lambda: "test-key"
    app.dependency_overrides[verify_auth_or_user] = lambda: admin_auth

    with patch.object(engine_mod, "async_session", factory):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    app.dependency_overrides.clear()


AUTH_HEADERS = {"Authorization": "Bearer test-key"}
MINIMAL_YAML = "template:\n  v: 1\n  components: []\n"
RICH_YAML = (
    "display: inline\n"
    "template:\n"
    "  v: 1\n"
    "  components:\n"
    "    - type: status\n"
    "      text: Hello\n"
)


@pytest_asyncio.fixture
async def seed_row(db_session):
    row = WidgetTemplatePackage(
        tool_name="t1",
        name="t1 default",
        description="Seed for t1",
        yaml_template=MINIMAL_YAML,
        source="seed",
        is_readonly=True,
        is_active=True,
        source_integration="foo",
        content_hash="hash1",
        version=1,
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


@pytest_asyncio.fixture
async def shared_seed_row(shared_session):
    row = WidgetTemplatePackage(
        tool_name="t1",
        name="t1 default",
        description="Seed for t1",
        yaml_template=MINIMAL_YAML,
        source="seed",
        is_readonly=True,
        is_active=True,
        source_integration="foo",
        content_hash="hash1",
        version=1,
    )
    shared_session.add(row)
    await shared_session.commit()
    await shared_session.refresh(row)
    return row


class TestList:
    @pytest.mark.asyncio
    async def test_list_empty(self, client):
        r = await client.get("/api/v1/admin/widget-packages", headers=AUTH_HEADERS)
        assert r.status_code == 200
        assert r.json() == []

    @pytest.mark.asyncio
    async def test_list_returns_seed(self, client, seed_row):
        r = await client.get("/api/v1/admin/widget-packages", headers=AUTH_HEADERS)
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["tool_name"] == "t1"
        assert data[0]["is_active"] is True
        assert data[0]["source"] == "seed"
        assert data[0]["has_python_code"] is False

    @pytest.mark.asyncio
    async def test_filter_by_tool(self, client, seed_row):
        r = await client.get(
            "/api/v1/admin/widget-packages?tool_name=t2", headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        assert r.json() == []


class TestDetail:
    @pytest.mark.asyncio
    async def test_detail_returns_bodies(self, client, seed_row):
        r = await client.get(
            f"/api/v1/admin/widget-packages/{seed_row.id}", headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["yaml_template"] == MINIMAL_YAML
        assert data["python_code"] is None

    @pytest.mark.asyncio
    async def test_detail_404(self, client):
        from uuid import uuid4
        r = await client.get(
            f"/api/v1/admin/widget-packages/{uuid4()}", headers=AUTH_HEADERS,
        )
        assert r.status_code == 404


class TestCreate:
    @pytest.mark.asyncio
    async def test_create_user_package(self, client):
        r = await client.post(
            "/api/v1/admin/widget-packages",
            json={
                "tool_name": "new_tool",
                "name": "My Template",
                "yaml_template": RICH_YAML,
                "python_code": "def transform(d, c): return c\n",
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 201
        data = r.json()
        assert data["source"] == "user"
        assert data["is_readonly"] is False
        assert data["is_active"] is False
        assert data["has_python_code"] is True

    @pytest.mark.asyncio
    async def test_create_invalid_yaml_422(self, client):
        r = await client.post(
            "/api/v1/admin/widget-packages",
            json={
                "tool_name": "t",
                "name": "bad",
                "yaml_template": "template:\n  v: 2\n  components: []\n",
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 422
        assert "errors" in r.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_syntax_error_python_422(self, client):
        r = await client.post(
            "/api/v1/admin/widget-packages",
            json={
                "tool_name": "t",
                "name": "bad",
                "yaml_template": MINIMAL_YAML,
                "python_code": "def bad(:",
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 422


class TestUpdate:
    @pytest.mark.asyncio
    async def test_update_seed_returns_409(self, client, seed_row):
        r = await client.put(
            f"/api/v1/admin/widget-packages/{seed_row.id}",
            json={"name": "renamed"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 409
        detail = r.json()["detail"]
        assert "fork" in detail.get("message", "").lower()

    @pytest.mark.asyncio
    async def test_update_user_bumps_version(self, client, seed_row, db_session):
        # Create a user package first.
        r = await client.post(
            "/api/v1/admin/widget-packages",
            json={
                "tool_name": "t1",
                "name": "user",
                "yaml_template": MINIMAL_YAML,
            },
            headers=AUTH_HEADERS,
        )
        pkg_id = r.json()["id"]

        r2 = await client.put(
            f"/api/v1/admin/widget-packages/{pkg_id}",
            json={"yaml_template": RICH_YAML},
            headers=AUTH_HEADERS,
        )
        assert r2.status_code == 200
        assert r2.json()["version"] == 2


class TestFork:
    @pytest.mark.asyncio
    async def test_fork_creates_user_copy(self, client, seed_row):
        r = await client.post(
            f"/api/v1/admin/widget-packages/{seed_row.id}/fork",
            json={"name": "My Fork"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 201
        data = r.json()
        assert data["source"] == "user"
        assert data["is_readonly"] is False
        assert data["is_active"] is False
        assert data["name"] == "My Fork"
        assert data["tool_name"] == "t1"

    @pytest.mark.asyncio
    async def test_fork_default_name(self, client, seed_row):
        r = await client.post(
            f"/api/v1/admin/widget-packages/{seed_row.id}/fork",
            json={},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 201
        assert "(copy)" in r.json()["name"]


class TestActivate:
    @pytest.mark.asyncio
    async def test_activate_user_deactivates_seed(
        self, shared_client, shared_seed_row, shared_session,
    ):
        r = await shared_client.post(
            "/api/v1/admin/widget-packages",
            json={
                "tool_name": "t1",
                "name": "user",
                "yaml_template": MINIMAL_YAML,
            },
            headers=AUTH_HEADERS,
        )
        user_id = r.json()["id"]

        r2 = await shared_client.post(
            f"/api/v1/admin/widget-packages/{user_id}/activate",
            headers=AUTH_HEADERS,
        )
        assert r2.status_code == 200
        assert r2.json()["is_active"] is True

        rows = (await shared_session.execute(
            select(WidgetTemplatePackage).where(WidgetTemplatePackage.tool_name == "t1"),
        )).scalars().all()
        active = [r for r in rows if r.is_active]
        assert len(active) == 1
        assert str(active[0].id) == user_id


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_seed_returns_409(self, client, seed_row):
        r = await client.delete(
            f"/api/v1/admin/widget-packages/{seed_row.id}", headers=AUTH_HEADERS,
        )
        assert r.status_code == 409

    @pytest.mark.asyncio
    async def test_delete_active_user_falls_back_to_seed(
        self, shared_client, shared_seed_row, shared_session,
    ):
        # Deactivate seed, create + activate a user row.
        shared_seed_row.is_active = False
        await shared_session.commit()

        r = await shared_client.post(
            "/api/v1/admin/widget-packages",
            json={
                "tool_name": "t1",
                "name": "user",
                "yaml_template": MINIMAL_YAML,
            },
            headers=AUTH_HEADERS,
        )
        user_id = r.json()["id"]
        await shared_client.post(
            f"/api/v1/admin/widget-packages/{user_id}/activate",
            headers=AUTH_HEADERS,
        )

        r_del = await shared_client.delete(
            f"/api/v1/admin/widget-packages/{user_id}", headers=AUTH_HEADERS,
        )
        assert r_del.status_code == 204

        await shared_session.refresh(shared_seed_row)
        assert shared_seed_row.is_active is True


class TestValidate:
    @pytest.mark.asyncio
    async def test_validate_ok(self, client):
        r = await client.post(
            "/api/v1/admin/widget-packages/validate",
            json={"yaml_template": MINIMAL_YAML},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

    @pytest.mark.asyncio
    async def test_validate_errors_returned(self, client):
        r = await client.post(
            "/api/v1/admin/widget-packages/validate",
            json={"yaml_template": "template:\n  v: 99\n  components: []\n"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert any("v must be 1" in e["message"] for e in body["errors"])


class TestPreview:
    @pytest.mark.asyncio
    async def test_preview_renders_envelope(self, client, seed_row):
        r = await client.post(
            f"/api/v1/admin/widget-packages/{seed_row.id}/preview",
            json={"sample_payload": {"message": "hi"}},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["envelope"]["content_type"] == "application/vnd.spindrel.components+json"
        assert body["envelope"]["display"] == "inline"

    @pytest.mark.asyncio
    async def test_preview_uses_draft_overrides(self, client, seed_row):
        r = await client.post(
            f"/api/v1/admin/widget-packages/{seed_row.id}/preview",
            json={
                "yaml_template": (
                    "display: inline\n"
                    "template:\n"
                    "  v: 1\n"
                    "  components:\n"
                    "    - type: status\n"
                    "      text: '{{message}}'\n"
                ),
                "sample_payload": {"message": "draft-rendered"},
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        import json as _json
        rendered = _json.loads(body["envelope"]["body"])
        assert rendered["components"][0]["text"] == "draft-rendered"

    @pytest.mark.asyncio
    async def test_preview_with_inline_transform(self, client, seed_row):
        r = await client.post(
            f"/api/v1/admin/widget-packages/{seed_row.id}/preview",
            json={
                "yaml_template": (
                    "display: inline\n"
                    "transform: self:transform\n"
                    "template:\n"
                    "  v: 1\n"
                    "  components:\n"
                    "    - type: status\n"
                    "      text: original\n"
                ),
                "python_code": (
                    "def transform(data, components):\n"
                    "    return components + [{'type': 'text', 'content': 'added'}]\n"
                ),
                "sample_payload": {},
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        import json as _json
        rendered = _json.loads(body["envelope"]["body"])
        assert len(rendered["components"]) == 2
        assert rendered["components"][1]["content"] == "added"

    @pytest.mark.asyncio
    async def test_preview_invalid_yaml_returns_422_style(self, client, seed_row):
        r = await client.post(
            f"/api/v1/admin/widget-packages/{seed_row.id}/preview",
            json={"yaml_template": "template:\n  v: 99\n  components: []\n"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert body["envelope"] is None
        assert body["errors"]
