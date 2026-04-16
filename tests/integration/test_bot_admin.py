"""Integration tests for bot admin endpoints: DELETE, scope enforcement, source_type."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import AUTH_HEADERS, _TEST_REGISTRY, _get_test_bot

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_bot(db: AsyncSession, bot_id: str, *, source_type: str = "manual") -> None:
    """Insert a bot row directly into the DB."""
    from app.db.models import Bot as BotRow
    row = BotRow(
        id=bot_id,
        name=f"Bot {bot_id}",
        model="test/model",
        system_prompt="test",
        source_type=source_type,
    )
    db.add(row)
    await db.commit()


async def _create_channel(db: AsyncSession, bot_id: str) -> uuid.UUID:
    """Insert a channel row linked to the given bot."""
    from app.db.models import Channel
    ch_id = uuid.uuid4()
    ch = Channel(id=ch_id, name="test-channel", bot_id=bot_id)
    db.add(ch)
    await db.commit()
    return ch_id


# ---------------------------------------------------------------------------
# DELETE /api/v1/admin/bots/{bot_id}
# ---------------------------------------------------------------------------

class TestBotDelete:
    async def test_delete_manual_bot(self, client, db_session):
        """Deleting a manual bot succeeds with 204."""
        await _create_bot(db_session, "deletable-bot")

        # Patch reload_bots and load_bots to avoid full registry refresh
        with patch("app.agent.bots.load_bots", new_callable=AsyncMock):
            resp = await client.delete(
                "/api/v1/admin/bots/deletable-bot",
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 204

        # Verify it's gone from DB
        from app.db.models import Bot as BotRow
        row = await db_session.get(BotRow, "deletable-bot")
        assert row is None

    async def test_delete_not_found(self, client, db_session):
        """Deleting a non-existent bot returns 404."""
        resp = await client.delete(
            "/api/v1/admin/bots/nonexistent-bot",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404

    async def test_delete_system_bot_rejected(self, client, db_session):
        """System bots cannot be deleted (403)."""
        await _create_bot(db_session, "system-bot", source_type="system")

        resp = await client.delete(
            "/api/v1/admin/bots/system-bot",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 403
        assert "system bot" in resp.json()["detail"].lower()

    async def test_delete_bot_with_channels_blocked(self, client, db_session):
        """Deleting a bot with channels is blocked without force (409)."""
        await _create_bot(db_session, "busy-bot")
        await _create_channel(db_session, "busy-bot")

        with patch("app.agent.bots.load_bots", new_callable=AsyncMock):
            resp = await client.delete(
                "/api/v1/admin/bots/busy-bot",
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 409
        assert "active channel" in resp.json()["detail"].lower()

    async def test_delete_bot_force_cascades(self, client, db_session):
        """Force delete removes bot and its channels."""
        await _create_bot(db_session, "force-bot")
        ch_id = await _create_channel(db_session, "force-bot")

        with patch("app.agent.bots.load_bots", new_callable=AsyncMock):
            resp = await client.delete(
                "/api/v1/admin/bots/force-bot?force=true",
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 204

        # Both bot and channel are gone
        from app.db.models import Bot as BotRow, Channel
        assert await db_session.get(BotRow, "force-bot") is None
        assert await db_session.get(Channel, ch_id) is None

    async def test_delete_file_bot_allowed(self, client, db_session):
        """File-sourced bots can be deleted (only system bots are protected)."""
        await _create_bot(db_session, "file-bot", source_type="file")

        with patch("app.agent.bots.load_bots", new_callable=AsyncMock):
            resp = await client.delete(
                "/api/v1/admin/bots/file-bot",
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Scope enforcement
# ---------------------------------------------------------------------------

class TestBotScopeEnforcement:
    """Verify that bot endpoints use require_scopes instead of verify_auth_or_user."""

    @pytest_asyncio.fixture
    async def scoped_client(self, db_session):
        """Client that does NOT override auth — uses real scoped key validation."""
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient
        from app.routers.api_v1 import router as api_v1_router
        from app.dependencies import get_db

        app = FastAPI()
        app.include_router(api_v1_router)

        async def _override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = _override_get_db

        with (
            patch("app.agent.bots._registry", _TEST_REGISTRY),
            patch("app.agent.bots.get_bot", side_effect=_get_test_bot),
            patch("app.agent.persona.get_persona", return_value=None),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ac

        app.dependency_overrides.clear()

    async def test_read_scope_grants_list(self, scoped_client, db_session):
        """A key with bots:read can list bots."""
        from app.services.api_keys import create_api_key
        _, key = await create_api_key(db_session, "test-read", ["bots:read"])

        resp = await scoped_client.get(
            "/api/v1/admin/bots",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200

    async def test_read_scope_denies_create(self, scoped_client, db_session):
        """A key with bots:read cannot create bots (requires bots:write)."""
        from app.services.api_keys import create_api_key
        _, key = await create_api_key(db_session, "test-read-only", ["bots:read"])

        resp = await scoped_client.post(
            "/api/v1/admin/bots",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"id": "new-bot", "name": "New", "model": "test/m"},
        )
        assert resp.status_code == 403

    async def test_write_scope_denies_delete(self, scoped_client, db_session):
        """A key with bots:write cannot delete bots (requires bots:delete)."""
        from app.services.api_keys import create_api_key
        _, key = await create_api_key(db_session, "test-write", ["bots:write"])

        await _create_bot(db_session, "write-test-bot")

        resp = await scoped_client.delete(
            "/api/v1/admin/bots/write-test-bot",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 403

    async def test_delete_scope_grants_delete(self, scoped_client, db_session):
        """A key with bots:delete can delete bots."""
        from app.services.api_keys import create_api_key
        _, key = await create_api_key(db_session, "test-delete", ["bots:delete"])

        await _create_bot(db_session, "del-test-bot")

        with patch("app.agent.bots.load_bots", new_callable=AsyncMock):
            resp = await scoped_client.delete(
                "/api/v1/admin/bots/del-test-bot",
                headers={"Authorization": f"Bearer {key}"},
            )
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# source_type field
# ---------------------------------------------------------------------------

class TestBotSourceType:
    async def test_source_type_in_list(self, client, db_session):
        """Bot list includes source_type field."""
        await _create_bot(db_session, "typed-bot", source_type="file")

        # Patch registry to include the typed bot
        from app.agent.bots import BotConfig, MemoryConfig
        typed_bot = BotConfig(
            id="typed-bot", name="Typed Bot", model="test/model",
            system_prompt="test", source_type="file",
            memory=MemoryConfig(),
        )
        registry = {**_TEST_REGISTRY, "typed-bot": typed_bot}

        with (
            patch("app.agent.bots._registry", registry),
            patch("app.agent.bots.list_bots", return_value=list(registry.values())),
        ):
            resp = await client.get("/api/v1/admin/bots", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        bots = resp.json()["bots"]
        typed = next(b for b in bots if b["id"] == "typed-bot")
        assert typed["source_type"] == "file"
