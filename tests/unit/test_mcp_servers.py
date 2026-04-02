"""Tests for MCP server DB management: seed, service layer, API endpoints."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.mcp_servers import list_server_names
from app.tools.mcp import MCPServerConfig, _servers


# ---------------------------------------------------------------------------
# list_server_names — reads from in-memory _servers dict
# ---------------------------------------------------------------------------

class TestListServerNames:
    def test_empty(self):
        with patch.dict(_servers, {}, clear=True):
            assert list_server_names() == []

    def test_sorted(self):
        with patch.dict(_servers, {
            "beta": MCPServerConfig(name="beta", url="http://b"),
            "alpha": MCPServerConfig(name="alpha", url="http://a"),
        }, clear=True):
            assert list_server_names() == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# seed_from_yaml — one-time YAML → DB migration
# ---------------------------------------------------------------------------

class TestSeedFromYaml:
    @pytest.mark.asyncio
    async def test_skips_when_no_yaml(self, tmp_path):
        """When mcp.yaml doesn't exist, seed_from_yaml should be a no-op."""
        from app.services.mcp_servers import seed_from_yaml
        # No file at tmp_path/mcp.yaml — should not raise
        await seed_from_yaml(config_path=tmp_path / "mcp.yaml")

    @pytest.mark.asyncio
    async def test_seeds_from_yaml_when_table_empty(self, tmp_path):
        """When DB table is empty and mcp.yaml exists, should insert entries."""
        yaml_path = tmp_path / "mcp.yaml"
        yaml_path.write_text(
            "ha:\n  url: http://ha.local/mcp\n  api_key: secret123\n"
            "empty:\n  url: http://empty.local/mcp\n"
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = None  # table is empty
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.engine.async_session", return_value=mock_session_cm), \
             patch("app.services.encryption.encrypt", side_effect=lambda x: f"enc:{x}"):
            from app.services.mcp_servers import seed_from_yaml
            await seed_from_yaml(config_path=yaml_path)

        # Should have added 2 servers
        assert mock_db.add.call_count == 2
        assert mock_db.commit.await_count == 1

    @pytest.mark.asyncio
    async def test_skips_when_table_populated(self, tmp_path):
        """When DB table already has entries, should skip seeding."""
        yaml_path = tmp_path / "mcp.yaml"
        yaml_path.write_text("ha:\n  url: http://ha.local/mcp\n")

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = MagicMock()  # table has entries
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.engine.async_session", return_value=mock_session_cm):
            from app.services.mcp_servers import seed_from_yaml
            await seed_from_yaml(config_path=yaml_path)

        # Should NOT have called add or commit
        assert not hasattr(mock_db, "add") or mock_db.add.call_count == 0


# ---------------------------------------------------------------------------
# load_mcp_servers — loads from DB into _servers dict
# ---------------------------------------------------------------------------

class TestLoadMCPServers:
    @pytest.mark.asyncio
    async def test_loads_enabled_servers(self):
        """Should populate _servers dict from DB rows."""
        mock_row = MagicMock()
        mock_row.id = "test-server"
        mock_row.url = "http://test.local/mcp"
        mock_row.api_key = "enc:secret"

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_row]
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.engine.async_session", return_value=mock_session_cm), \
             patch("app.services.encryption.decrypt", side_effect=lambda x: x.replace("enc:", "")), \
             patch.dict(_servers, {}, clear=True):
            from app.services.mcp_servers import load_mcp_servers
            await load_mcp_servers()

            assert "test-server" in _servers
            assert _servers["test-server"].url == "http://test.local/mcp"
            assert _servers["test-server"].api_key == "secret"

    @pytest.mark.asyncio
    async def test_clears_existing_servers(self):
        """Should clear _servers before loading from DB."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.engine.async_session", return_value=mock_session_cm), \
             patch.dict(_servers, {"old": MCPServerConfig(name="old", url="http://old")}, clear=False):
            from app.services.mcp_servers import load_mcp_servers
            await load_mcp_servers()

            assert "old" not in _servers
            assert len(_servers) == 0


# ---------------------------------------------------------------------------
# API router — schemas and helpers
# ---------------------------------------------------------------------------

class TestMCPServerSchemas:
    def test_server_to_out_masks_api_key(self):
        """_server_to_out should expose has_api_key bool, not the actual key."""
        from app.routers.api_v1_admin.mcp_servers import _server_to_out
        from datetime import datetime, timezone

        mock_row = MagicMock()
        mock_row.id = "test"
        mock_row.display_name = "Test Server"
        mock_row.url = "http://test.local"
        mock_row.api_key = "enc:secret"
        mock_row.is_enabled = True
        mock_row.config = {}
        mock_row.source = "manual"
        mock_row.source_path = None
        mock_row.created_at = datetime.now(timezone.utc)
        mock_row.updated_at = datetime.now(timezone.utc)

        out = _server_to_out(mock_row)
        assert out.has_api_key is True
        assert not hasattr(out, "api_key")

    def test_server_to_out_no_api_key(self):
        """When api_key is None, has_api_key should be False."""
        from app.routers.api_v1_admin.mcp_servers import _server_to_out
        from datetime import datetime, timezone

        mock_row = MagicMock()
        mock_row.id = "test"
        mock_row.display_name = "Test"
        mock_row.url = "http://test.local"
        mock_row.api_key = None
        mock_row.is_enabled = True
        mock_row.config = {}
        mock_row.source = "file"
        mock_row.source_path = "/path/mcp.yaml"
        mock_row.created_at = datetime.now(timezone.utc)
        mock_row.updated_at = datetime.now(timezone.utc)

        out = _server_to_out(mock_row)
        assert out.has_api_key is False
        assert out.source == "file"


# ---------------------------------------------------------------------------
# _test_mcp_connection — MCP endpoint test
# ---------------------------------------------------------------------------

class TestMCPConnection:
    @pytest.mark.asyncio
    async def test_successful_connection(self):
        """Should return ok=True with tool count on success."""
        from app.routers.api_v1_admin.mcp_servers import _test_mcp_connection

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {
            "result": {
                "tools": [
                    {"name": "tool_a", "description": "Tool A"},
                    {"name": "tool_b", "description": "Tool B"},
                ]
            }
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.routers.api_v1_admin.mcp_servers.httpx.AsyncClient", return_value=mock_client):
            result = await _test_mcp_connection("http://test.local/mcp", "key123")

        assert result.ok is True
        assert result.tool_count == 2
        assert result.tools == ["tool_a", "tool_b"]

    @pytest.mark.asyncio
    async def test_failed_connection(self):
        """Should return ok=False on HTTP error."""
        from app.routers.api_v1_admin.mcp_servers import _test_mcp_connection

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_response.headers = {}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.routers.api_v1_admin.mcp_servers.httpx.AsyncClient", return_value=mock_client):
            result = await _test_mcp_connection("http://test.local/mcp", "bad-key")

        assert result.ok is False
        assert "401" in result.message

    @pytest.mark.asyncio
    async def test_connection_exception(self):
        """Should return ok=False on connection exception."""
        from app.routers.api_v1_admin.mcp_servers import _test_mcp_connection

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.routers.api_v1_admin.mcp_servers.httpx.AsyncClient", return_value=mock_client):
            result = await _test_mcp_connection("http://unreachable.local", "")

        assert result.ok is False
        assert "Connection refused" in result.message


# ---------------------------------------------------------------------------
# _reload_mcp — cache clearing
# ---------------------------------------------------------------------------

class TestReloadMCP:
    @pytest.mark.asyncio
    async def test_reload_clears_cache(self):
        """_reload_mcp should call load_mcp_servers and clear _cache."""
        from app.routers.api_v1_admin.mcp_servers import _reload_mcp
        from app.tools.mcp import _cache

        _cache["test"] = {"tools": [], "fetched_at": 0}

        with patch("app.services.mcp_servers.load_mcp_servers", new_callable=AsyncMock):
            await _reload_mcp()

        assert len(_cache) == 0
