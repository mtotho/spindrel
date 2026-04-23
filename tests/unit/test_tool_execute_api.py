"""Tests for the direct tool execution API endpoint."""

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.dependencies import ApiKeyAuth, verify_admin_auth, verify_auth_or_user
from app.main import app


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-key"}


# ---------------------------------------------------------------------------
# Admin key tests (existing — admin scope bypasses all checks)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_local_tool(auth_headers):
    """Execute a known local tool and get structured JSON back."""
    with patch("app.tools.registry.is_local_tool", return_value=True), \
         patch("app.tools.registry.call_local_tool", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = json.dumps({"count": 3, "items": ["a", "b", "c"]})
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/admin/tools/my_tool/execute",
                json={"arguments": {"limit": 10}},
                headers=auth_headers,
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data["tool_name"] == "my_tool"
    assert data["result"]["count"] == 3
    assert data["error"] is None
    mock_call.assert_called_once_with("my_tool", '{"limit": 10}')


@pytest.mark.asyncio
async def test_execute_unknown_tool_404(auth_headers):
    """Unknown tool — neither local nor MCP — returns 404."""
    with patch("app.tools.registry.is_local_tool", return_value=False), \
         patch("app.tools.mcp.is_mcp_tool", return_value=False):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/admin/tools/nonexistent/execute",
                json={"arguments": {}},
                headers=auth_headers,
            )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_execute_tool_error_passthrough(auth_headers):
    """Tool errors are passed through in the error field."""
    with patch("app.tools.registry.is_local_tool", return_value=True), \
         patch("app.tools.registry.call_local_tool", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = json.dumps({"error": "SONARR_URL is not configured"})
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/admin/tools/sonarr_queue/execute",
                json={"arguments": {}},
                headers=auth_headers,
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data["error"] == "SONARR_URL is not configured"


@pytest.mark.asyncio
async def test_execute_tool_empty_args(auth_headers):
    """Calling with no arguments works."""
    with patch("app.tools.registry.is_local_tool", return_value=True), \
         patch("app.tools.registry.call_local_tool", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = json.dumps({"ok": True})
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/admin/tools/my_tool/execute",
                json={},
                headers=auth_headers,
            )
    assert resp.status_code == 200
    mock_call.assert_called_once_with("my_tool", "{}")


@pytest.mark.asyncio
async def test_execute_tool_string_result(auth_headers):
    """Tool returning a plain string (not JSON) is handled."""
    with patch("app.tools.registry.is_local_tool", return_value=True), \
         patch("app.tools.registry.call_local_tool", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = "plain text result"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/admin/tools/my_tool/execute",
                json={"arguments": {}},
                headers=auth_headers,
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"] == "plain text result"
    assert data["error"] is None


# ---------------------------------------------------------------------------
# Bot-scoped API key permission tests
# ---------------------------------------------------------------------------

def _scoped_auth_overrides(auth_obj):
    """Set dependency overrides for both admin gate and endpoint auth."""
    async def _fake_admin():
        return auth_obj

    async def _fake_auth():
        return auth_obj

    app.dependency_overrides[verify_admin_auth] = _fake_admin
    app.dependency_overrides[verify_auth_or_user] = _fake_auth


def _clear_overrides():
    app.dependency_overrides.pop(verify_admin_auth, None)
    app.dependency_overrides.pop(verify_auth_or_user, None)


@pytest.mark.asyncio
async def test_bot_key_allowed_tool():
    """Bot-scoped key with tools:execute can run tools in its local_tools list."""
    auth = ApiKeyAuth(key_id=uuid4(), scopes=["tools:execute"], name="bot:test-bot")
    _scoped_auth_overrides(auth)
    try:
        with patch("app.tools.registry.is_local_tool", return_value=True), \
             patch("app.tools.registry.call_local_tool", new_callable=AsyncMock) as mock_call, \
             patch("app.routers.api_v1_admin.tools._resolve_bot_tools", new_callable=AsyncMock) as mock_resolve:
            mock_call.return_value = json.dumps({"ok": True})
            mock_resolve.return_value = {"sonarr_queue", "radarr_movies"}
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/admin/tools/sonarr_queue/execute",
                    json={"arguments": {}},
                    headers={"Authorization": "Bearer fake"},
                )
        assert resp.status_code == 200
        mock_call.assert_called_once()
    finally:
        _clear_overrides()


@pytest.mark.asyncio
async def test_bot_key_denied_tool():
    """Bot-scoped key is rejected when requesting a tool not in its allowlist."""
    auth = ApiKeyAuth(key_id=uuid4(), scopes=["tools:execute"], name="bot:test-bot")
    _scoped_auth_overrides(auth)
    try:
        with patch("app.tools.registry.is_local_tool", return_value=True), \
             patch("app.routers.api_v1_admin.tools._resolve_bot_tools", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = {"sonarr_queue", "radarr_movies"}
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/admin/tools/jellyfin_library/execute",
                    json={"arguments": {}},
                    headers={"Authorization": "Bearer fake"},
                )
        assert resp.status_code == 403
        assert "does not have access" in resp.json()["detail"]
    finally:
        _clear_overrides()


@pytest.mark.asyncio
async def test_bot_key_missing_execute_scope():
    """Scoped key without tools:execute is rejected."""
    auth = ApiKeyAuth(key_id=uuid4(), scopes=["tools:read"], name="bot:test-bot")
    _scoped_auth_overrides(auth)
    try:
        with patch("app.tools.registry.is_local_tool", return_value=True):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/admin/tools/sonarr_queue/execute",
                    json={"arguments": {}},
                    headers={"Authorization": "Bearer fake"},
                )
        assert resp.status_code == 403
        assert "tools:execute" in resp.json()["detail"]
    finally:
        _clear_overrides()


@pytest.mark.asyncio
async def test_non_bot_scoped_key_allowed():
    """Non-bot scoped key (e.g. integration) with tools:execute is unrestricted."""
    auth = ApiKeyAuth(key_id=uuid4(), scopes=["tools:execute"], name="integration:slack")
    _scoped_auth_overrides(auth)
    try:
        with patch("app.tools.registry.is_local_tool", return_value=True), \
             patch("app.tools.registry.call_local_tool", new_callable=AsyncMock) as mock_call, \
             patch("app.routers.api_v1_admin.tools._resolve_bot_tools", new_callable=AsyncMock) as mock_resolve:
            mock_call.return_value = json.dumps({"ok": True})
            mock_resolve.return_value = None  # Not a bot key
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/admin/tools/any_tool/execute",
                    json={"arguments": {}},
                    headers={"Authorization": "Bearer fake"},
                )
        assert resp.status_code == 200
    finally:
        _clear_overrides()


# ---------------------------------------------------------------------------
# MCP tool execution tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_mcp_tool_admin(auth_headers):
    """Admin key can execute an MCP tool; dispatch routes to call_mcp_tool."""
    with patch("app.tools.registry.is_local_tool", return_value=False), \
         patch("app.tools.mcp.is_mcp_tool", return_value=True), \
         patch("app.tools.mcp.call_mcp_tool", new_callable=AsyncMock) as mock_mcp:
        mock_mcp.return_value = json.dumps({"temperature": 72, "conditions": "sunny"})
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/admin/tools/openweather-current/execute",
                json={"arguments": {"city": "Seattle"}},
                headers=auth_headers,
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data["tool_name"] == "openweather-current"
    assert data["result"]["temperature"] == 72
    assert data["error"] is None
    mock_mcp.assert_called_once_with("openweather-current", '{"city": "Seattle"}')


@pytest.mark.asyncio
async def test_execute_mcp_tool_error_passthrough(auth_headers):
    """MCP tool error JSON is surfaced in the error field."""
    with patch("app.tools.registry.is_local_tool", return_value=False), \
         patch("app.tools.mcp.is_mcp_tool", return_value=True), \
         patch("app.tools.mcp.call_mcp_tool", new_callable=AsyncMock) as mock_mcp:
        mock_mcp.return_value = json.dumps({"error": "MCP tool call failed: timeout"})
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/admin/tools/some-mcp-tool/execute",
                json={"arguments": {}},
                headers=auth_headers,
            )
    assert resp.status_code == 200
    assert "timeout" in resp.json()["error"]


@pytest.mark.asyncio
async def test_execute_mcp_tool_bot_scoped_forbidden():
    """Bot-scoped keys cannot execute MCP tools from this endpoint."""
    auth = ApiKeyAuth(key_id=uuid4(), scopes=["tools:execute"], name="bot:test-bot")
    _scoped_auth_overrides(auth)
    try:
        with patch("app.tools.registry.is_local_tool", return_value=False), \
             patch("app.tools.mcp.is_mcp_tool", return_value=True), \
             patch("app.tools.mcp.call_mcp_tool", new_callable=AsyncMock) as mock_mcp:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/admin/tools/openweather-current/execute",
                    json={"arguments": {"city": "Seattle"}},
                    headers={"Authorization": "Bearer fake"},
                )
        assert resp.status_code == 403
        assert "admin" in resp.json()["detail"].lower()
        mock_mcp.assert_not_called()
    finally:
        _clear_overrides()


# ---------------------------------------------------------------------------
# Bot/channel context propagation tests (dev-panel sandbox path)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_sets_bot_and_channel_context(auth_headers):
    """When bot_id/channel_id are passed, the ContextVars are set during the call."""
    from app.agent.context import current_bot_id, current_channel_id
    from app.agent.bots import _registry, BotConfig

    captured: dict = {}

    async def _probe(name: str, args: str) -> str:
        captured["bot_id"] = current_bot_id.get()
        captured["channel_id"] = current_channel_id.get()
        return json.dumps({"ok": True})

    _registry["test-bot"] = BotConfig(id="test-bot", name="Test", model="ollama/test", system_prompt="x")
    try:
        channel_uuid = str(uuid4())
        with patch("app.tools.registry.is_local_tool", return_value=True), \
             patch("app.tools.registry.call_local_tool", side_effect=_probe), \
             patch("app.tools.registry.get_tool_context_requirements", return_value=(True, True)):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/admin/tools/probe/execute",
                    json={"arguments": {}, "bot_id": "test-bot", "channel_id": channel_uuid},
                    headers=auth_headers,
                )
        assert resp.status_code == 200, resp.text
        assert captured["bot_id"] == "test-bot"
        assert str(captured["channel_id"]) == channel_uuid
    finally:
        _registry.pop("test-bot", None)


@pytest.mark.asyncio
async def test_execute_requires_bot_context_400(auth_headers):
    """A tool flagged requires_bot_context fails with 400 when bot_id is missing."""
    with patch("app.tools.registry.get_tool_context_requirements", return_value=(True, False)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/admin/tools/needs_bot/execute",
                json={"arguments": {}},
                headers=auth_headers,
            )
    assert resp.status_code == 400
    assert "bot context" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_execute_requires_channel_context_400(auth_headers):
    """A tool flagged requires_channel_context fails with 400 when channel_id is missing."""
    with patch("app.tools.registry.get_tool_context_requirements", return_value=(False, True)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/admin/tools/needs_channel/execute",
                json={"arguments": {}},
                headers=auth_headers,
            )
    assert resp.status_code == 400
    assert "channel context" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_execute_unknown_bot_id_400(auth_headers):
    """An unknown bot_id is rejected up front instead of being silently used."""
    with patch("app.tools.registry.is_local_tool", return_value=True), \
         patch("app.tools.registry.call_local_tool", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/admin/tools/whatever/execute",
                json={"arguments": {}, "bot_id": "ghost-bot-does-not-exist"},
                headers=auth_headers,
            )
    assert resp.status_code == 400
    assert "ghost-bot" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_execute_invalid_channel_uuid_400(auth_headers):
    """A non-UUID channel_id fails fast with 400 instead of crashing in the tool."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/admin/tools/whatever/execute",
            json={"arguments": {}, "channel_id": "not-a-uuid"},
            headers=auth_headers,
        )
    assert resp.status_code == 400
    assert "uuid" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_bot_key_with_resolved_tools():
    """Bot-scoped key can access tools resolved into its allowed tool set."""
    auth = ApiKeyAuth(key_id=uuid4(), scopes=["tools:execute"], name="bot:test-bot")
    _scoped_auth_overrides(auth)
    try:
        with patch("app.tools.registry.is_local_tool", return_value=True), \
             patch("app.tools.registry.call_local_tool", new_callable=AsyncMock) as mock_call, \
             patch("app.routers.api_v1_admin.tools._resolve_bot_tools", new_callable=AsyncMock) as mock_resolve:
            mock_call.return_value = json.dumps({"playing": []})
            mock_resolve.return_value = {"sonarr_queue", "jellyfin_library"}
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/admin/tools/jellyfin_library/execute",
                    json={"arguments": {}},
                    headers={"Authorization": "Bearer fake"},
                )
        assert resp.status_code == 200
        mock_call.assert_called_once()
    finally:
        _clear_overrides()
