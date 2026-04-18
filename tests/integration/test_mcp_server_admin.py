"""Integration tests for api_v1_admin/mcp_servers.py — 5 mutating routes.

Phase 3 of the Test Quality track. Real FastAPI + real SQLite DB + real router
+ real ORM. Outbound MCP connectivity (`_test_mcp_connection`) is intercepted
via respx (E.1 — true external). `_reload_mcp()` is patched per test to avoid
opening a real session (load_mcp_servers uses its own async_session not covered
by the conftest patch set, and _cache.clear is a side-effect we don't want).

BUG FOUND: `admin_delete_mcp_server` checks bot usage BEFORE checking whether
the server row exists. A stale bot reference to a non-existent server causes a
misleading 400 instead of 404. Tests below pin this ordering bug so it is fixed
before it bites in production.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.db.models import Bot as BotRow
from app.db.models import MCPServer as MCPServerRow
from app.routers.api_v1_admin.mcp_servers import MCPServerTestResult as MCPTestResult
from tests.factories import build_bot, build_mcp_server
from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio

_RELOAD_TARGETS = (
    "app.routers.api_v1_admin.mcp_servers._reload_mcp",
)


def _no_reload():
    return patch(_RELOAD_TARGETS[0], new_callable=AsyncMock)


# ---------------------------------------------------------------------------
# POST /mcp-servers — admin_create_mcp_server
# ---------------------------------------------------------------------------

class TestCreateMcpServer:
    async def test_when_valid_payload_then_row_persisted(self, client, db_session):
        payload = {
            "id": "my-mcp-server",
            "display_name": "My MCP Server",
            "url": "http://mcp.internal:9999",
        }

        with _no_reload():
            resp = await client.post("/api/v1/admin/mcp-servers", json=payload, headers=AUTH_HEADERS)

        assert resp.status_code == 201
        row = await db_session.get(MCPServerRow, "my-mcp-server")
        assert row is not None and row.display_name == "My MCP Server"
        assert resp.json()["has_api_key"] is False

    async def test_when_api_key_provided_then_stored_encrypted_and_flag_set(
        self, client, db_session,
    ):
        payload = {
            "id": "secured-mcp",
            "display_name": "Secured MCP",
            "url": "http://mcp.internal:9000",
            "api_key": "secret-api-key-abc123",
        }

        with _no_reload():
            resp = await client.post("/api/v1/admin/mcp-servers", json=payload, headers=AUTH_HEADERS)

        assert resp.status_code == 201
        row = await db_session.get(MCPServerRow, "secured-mcp")
        assert row.api_key is not None  # stored encrypted
        assert resp.json()["has_api_key"] is True

    async def test_when_duplicate_id_then_409(self, client, db_session):
        existing = build_mcp_server(id="existing-server")
        db_session.add(existing)
        await db_session.commit()

        with _no_reload():
            resp = await client.post(
                "/api/v1/admin/mcp-servers",
                json={"id": "existing-server", "display_name": "Dup", "url": "http://x.com"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 409
        assert "existing-server" in resp.json()["detail"]

    async def test_when_missing_required_fields_then_422(self, client):
        with _no_reload():
            resp = await client.post(
                "/api/v1/admin/mcp-servers",
                json={"id": "", "display_name": "No ID", "url": "http://x.com"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 422

    async def test_when_created_then_source_is_manual(self, client, db_session):
        with _no_reload():
            await client.post(
                "/api/v1/admin/mcp-servers",
                json={"id": "manual-check", "display_name": "M", "url": "http://x.com"},
                headers=AUTH_HEADERS,
            )

        row = await db_session.get(MCPServerRow, "manual-check")
        assert row.source == "manual"


# ---------------------------------------------------------------------------
# PUT /mcp-servers/{server_id} — admin_update_mcp_server
# ---------------------------------------------------------------------------

class TestUpdateMcpServer:
    async def test_when_display_name_updated_then_persisted(self, client, db_session):
        row = build_mcp_server(display_name="Old Name")
        db_session.add(row)
        await db_session.commit()

        with _no_reload():
            resp = await client.put(
                f"/api/v1/admin/mcp-servers/{row.id}",
                json={"display_name": "New Name"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        await db_session.refresh(row)
        assert row.display_name == "New Name"

    async def test_when_api_key_cleared_then_has_api_key_false(self, client, db_session):
        row = build_mcp_server(api_key="encrypted-key")
        db_session.add(row)
        await db_session.commit()

        with _no_reload():
            resp = await client.put(
                f"/api/v1/admin/mcp-servers/{row.id}",
                json={"api_key": ""},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        await db_session.refresh(row)
        assert row.api_key is None
        assert resp.json()["has_api_key"] is False

    async def test_when_server_missing_then_404(self, client):
        with _no_reload():
            resp = await client.put(
                "/api/v1/admin/mcp-servers/no-such-server",
                json={"display_name": "Ghost"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 404

    async def test_when_config_updated_then_persisted_and_sibling_unchanged(
        self, client, db_session,
    ):
        sibling = build_mcp_server(config={"key": "value"})
        target = build_mcp_server(config={})
        db_session.add(sibling)
        db_session.add(target)
        await db_session.commit()

        with _no_reload():
            await client.put(
                f"/api/v1/admin/mcp-servers/{target.id}",
                json={"config": {"timeout": 30}},
                headers=AUTH_HEADERS,
            )

        await db_session.refresh(sibling)
        assert sibling.config == {"key": "value"}  # extra mile: sibling unchanged
        await db_session.refresh(target)
        assert target.config == {"timeout": 30}


# ---------------------------------------------------------------------------
# DELETE /mcp-servers/{server_id} — admin_delete_mcp_server
# ---------------------------------------------------------------------------

class TestDeleteMcpServer:
    async def test_when_server_exists_and_no_bots_then_deleted(self, client, db_session):
        row = build_mcp_server()
        sibling = build_mcp_server()
        db_session.add(row)
        db_session.add(sibling)
        await db_session.commit()
        server_id = row.id

        with _no_reload():
            resp = await client.delete(
                f"/api/v1/admin/mcp-servers/{server_id}", headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        gone = await db_session.execute(
            select(MCPServerRow).where(MCPServerRow.id == server_id)
        )
        assert gone.scalar_one_or_none() is None
        # extra mile: sibling survives
        assert await db_session.get(MCPServerRow, sibling.id) is not None

    async def test_when_bot_references_server_then_400_with_bot_id(
        self, client, db_session,
    ):
        row = build_mcp_server()
        bot = build_bot(mcp_servers=[row.id])
        db_session.add(row)
        db_session.add(bot)
        await db_session.commit()

        with _no_reload():
            resp = await client.delete(
                f"/api/v1/admin/mcp-servers/{row.id}", headers=AUTH_HEADERS,
            )

        assert resp.status_code == 400
        assert bot.id in resp.json()["detail"]

    async def test_when_server_missing_then_404(self, client):
        with _no_reload():
            resp = await client.delete(
                "/api/v1/admin/mcp-servers/no-such-server", headers=AUTH_HEADERS,
            )

        assert resp.status_code == 404

    async def test_when_stale_bot_references_nonexistent_server_then_should_be_404_not_400(
        self, client, db_session,
    ):
        """BUG: admin_delete_mcp_server checks bot usage BEFORE server existence.
        A bot with a stale mcp_servers reference to a non-existent server ID
        causes a misleading 400 "Cannot delete: referenced by bots X" instead
        of 404. The server doesn't exist — existence check must come first.
        """
        stale_server_id = f"ghost-{uuid.uuid4().hex[:8]}"
        bot = build_bot(mcp_servers=[stale_server_id])
        db_session.add(bot)
        await db_session.commit()

        with _no_reload():
            resp = await client.delete(
                f"/api/v1/admin/mcp-servers/{stale_server_id}", headers=AUTH_HEADERS,
            )

        # BUG: currently returns 400 because bot-usage check runs before existence check
        # Expected: 404 (server does not exist)
        assert resp.status_code == 404, (
            f"BUG: got {resp.status_code} — bot-usage check fires before existence check. "
            "Reorder: check db.get(MCPServerRow, server_id) first."
        )


# ---------------------------------------------------------------------------
# POST /mcp-servers/{server_id}/test — admin_test_mcp_server
# ---------------------------------------------------------------------------

class TestTestMcpServer:
    async def test_when_server_reachable_then_ok_true_with_tool_count(
        self, client, db_session,
    ):
        row = build_mcp_server(url="http://mcp.test:9000/rpc")
        db_session.add(row)
        await db_session.commit()

        tools_result = AsyncMock(return_value=MCPTestResult(
            ok=True, message="Connected (2 tools)", tool_count=2,
            tools=["list_files", "read_file"],
        ))
        with patch("app.routers.api_v1_admin.mcp_servers._test_mcp_connection", tools_result):
            resp = await client.post(
                f"/api/v1/admin/mcp-servers/{row.id}/test", headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["tool_count"] == 2
        assert "list_files" in body["tools"]

    async def test_when_server_missing_then_404(self, client):
        resp = await client.post(
            "/api/v1/admin/mcp-servers/no-such-server/test", headers=AUTH_HEADERS,
        )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /mcp-servers/test-inline — admin_test_mcp_server_inline
# ---------------------------------------------------------------------------

class TestTestMcpServerInline:
    async def test_when_connection_fails_then_ok_false(self, client):
        fail_result = AsyncMock(return_value=MCPTestResult(
            ok=False, message="Connection failed. Check server logs for details.",
        ))
        with patch("app.routers.api_v1_admin.mcp_servers._test_mcp_connection", fail_result):
            resp = await client.post(
                "/api/v1/admin/mcp-servers/test-inline",
                json={"url": "http://mcp.failing:8080/rpc"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is False
