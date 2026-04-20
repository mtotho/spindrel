"""Integration tests for /api/v1/internal/tools/exec — the endpoint that
backs run_script's per-call dispatch.

Coverage:
- bot resolution: API key bound to a bot resolves; otherwise 403
- the static admin key is rejected (no admin elevation through this surface)
- a successful tool dispatch returns the parsed JSON result
- unknown tool returns 404
- ContextVars (current_bot_id) are set so tools that need them work
- list_tool_signatures HTTP mirror returns the same shape as the tool
"""
import json
import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ApiKey, Bot
from app.dependencies import ApiKeyAuth, get_db, verify_auth_or_user
from app.routers.api_v1 import router as api_v1_router
from tests.integration.conftest import _TEST_REGISTRY, _get_test_bot

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def bot_bound_client(engine, db_session):
    """Client whose verify_auth_or_user resolves to an ApiKey row bound to a real Bot row."""
    api_key_row = ApiKey(
        id=uuid.uuid4(),
        name="test-bot-key",
        key_prefix="ask_test",
        key_hash="hash-stub",
        scopes=["chat:read", "chat:write", "channels:read"],
        is_active=True,
    )
    db_session.add(api_key_row)
    await db_session.flush()

    bot_row = Bot(
        id="test-bot",
        name="Test Bot",
        model="test/model",
        system_prompt="You are a test bot.",
        api_key_id=api_key_row.id,
    )
    db_session.add(bot_row)
    await db_session.commit()

    app = FastAPI()
    app.include_router(api_v1_router)

    bot_auth = ApiKeyAuth(
        key_id=api_key_row.id,
        scopes=api_key_row.scopes,
        name=api_key_row.name,
    )

    async def _override_get_db():
        yield db_session

    async def _override_auth_or_user():
        return bot_auth

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[verify_auth_or_user] = _override_auth_or_user

    _test_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    with (
        patch("app.agent.bots._registry", _TEST_REGISTRY),
        patch("app.agent.bots.get_bot", side_effect=_get_test_bot),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, bot_auth, api_key_row.id

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def admin_client(engine, db_session):
    """Client whose verify_auth_or_user returns the static admin key — should be rejected."""
    app = FastAPI()
    app.include_router(api_v1_router)

    admin_auth = ApiKeyAuth(
        key_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
        scopes=["admin"],
        name="static-env-key",
    )

    async def _override_get_db():
        yield db_session

    async def _override_auth_or_user():
        return admin_auth

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[verify_auth_or_user] = _override_auth_or_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Auth / bot resolution
# ---------------------------------------------------------------------------


async def test_admin_key_rejected(admin_client):
    """The static admin key must NOT be a back-door for script-driven tool calls.
    Bot-bound keys only — keeps the per-bot scope ceiling honest."""
    r = await admin_client.post(
        "/api/v1/internal/tools/exec",
        json={"name": "list_tool_signatures", "arguments": {}},
    )
    assert r.status_code == 403
    assert "static admin key" in r.json()["detail"].lower()


async def test_unbound_api_key_rejected(engine, db_session):
    """An API key with no Bot row pointing at it returns 403."""
    app = FastAPI()
    app.include_router(api_v1_router)

    rogue_key_id = uuid.uuid4()
    rogue_auth = ApiKeyAuth(key_id=rogue_key_id, scopes=["admin"], name="rogue")

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[verify_auth_or_user] = lambda: rogue_auth

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/api/v1/internal/tools/exec",
            json={"name": "list_tool_signatures", "arguments": {}},
        )
    assert r.status_code == 403
    # Either "not bound" (no Bot row) or "static" (uuid all zeros) — both are rejections.
    assert "bot" in r.json()["detail"].lower() or "static" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


async def test_unknown_tool_returns_404(bot_bound_client):
    ac, _auth, _key_id = bot_bound_client
    # Disable policy so the unknown-tool branch is hit deterministically.
    with patch("app.config.settings.TOOL_POLICY_ENABLED", False):
        r = await ac.post(
            "/api/v1/internal/tools/exec",
            json={"name": "this_tool_does_not_exist", "arguments": {}},
        )
    assert r.status_code == 404
    assert "registered local tool" in r.json()["detail"]


async def test_list_tool_signatures_dispatches_through_endpoint(bot_bound_client):
    """Happy path: a real local tool (list_tool_signatures) is dispatched and
    returns ok=True with the parsed JSON shape we declared in its `returns`."""
    ac, _auth, _key_id = bot_bound_client
    # Make sure the tool is registered (importing forces decorator execution).
    import app.tools.local.discovery  # noqa: F401

    with patch("app.config.settings.TOOL_POLICY_ENABLED", False):
        r = await ac.post(
            "/api/v1/internal/tools/exec",
            json={"name": "list_tool_signatures", "arguments": {"limit": 5}},
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "list_tool_signatures"
    assert body["ok"] is True
    assert body["error"] is None
    # Result is the parsed JSON of the tool's return.
    assert isinstance(body["result"], dict)
    assert "signatures" in body["result"]
    assert "count" in body["result"]


async def test_signatures_endpoint_returns_catalog(bot_bound_client):
    """The HTTP mirror endpoint returns the same data shape as the tool, so
    a script can self-discover composable tools without round-tripping
    through tool dispatch."""
    ac, _auth, _key_id = bot_bound_client
    import app.tools.local.discovery  # noqa: F401
    import app.tools.local.pipelines  # noqa: F401  (registers list_pipelines with returns)

    r = await ac.get("/api/v1/internal/tools/signatures")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "signatures" in body
    assert "count" in body
    # At least the tools we know we backfilled in Phase 1 should appear.
    names = {s["name"] for s in body["signatures"]}
    assert "list_tool_signatures" in names
    assert "list_pipelines" in names
    # Every entry must declare a returns_schema (that's the whole point).
    for sig in body["signatures"]:
        assert sig["returns_schema"] is not None


async def test_signatures_endpoint_filters_by_category(bot_bound_client):
    ac, _auth, _key_id = bot_bound_client
    import app.tools.local.pipelines  # noqa: F401

    r = await ac.get("/api/v1/internal/tools/signatures", params={"category": "pipeline"})
    assert r.status_code == 200
    names = {s["name"] for s in r.json()["signatures"]}
    # All matching names should contain "pipeline" in name OR source_integration.
    for n in names:
        assert "pipeline" in n.lower() or any(
            "pipeline" in (s.get("source_integration") or "").lower()
            for s in r.json()["signatures"]
            if s["name"] == n
        )
