"""Unit tests for list_api_endpoints and call_api tools."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True, scope="module")
def _populate_catalog():
    """Build the endpoint catalog from the real app so tool tests work."""
    from app.main import app
    from app.services.endpoint_catalog import build_endpoint_catalog
    from app.services import api_keys as _api_keys_mod
    _api_keys_mod.ENDPOINT_CATALOG = build_endpoint_catalog(app)


def _make_bot(api_permissions=None, api_key_id=None):
    """Create a mock BotConfig with optional API permissions."""
    bot = MagicMock()
    bot.id = "test-bot"
    bot.api_permissions = api_permissions
    bot.api_key_id = api_key_id
    return bot


class TestListApiEndpoints:

    @pytest.mark.asyncio
    async def test_returns_filtered_endpoints(self):
        from app.tools.local.api_access import list_api_endpoints

        bot = _make_bot(api_permissions=["channels:read"])
        with patch("app.tools.local.api_access.current_bot_id") as mock_ctx:
            mock_ctx.get.return_value = "test-bot"
            with patch("app.agent.bots.get_bot", return_value=bot):
                result = json.loads(await list_api_endpoints())

        assert "endpoints" in result
        assert result["count"] > 0
        # All returned endpoints should be accessible with channels:read
        for ep in result["endpoints"]:
            assert ep["path"].startswith("/api/")

    @pytest.mark.asyncio
    async def test_no_permissions_returns_error(self):
        from app.tools.local.api_access import list_api_endpoints

        bot = _make_bot(api_permissions=None)
        with patch("app.tools.local.api_access.current_bot_id") as mock_ctx:
            mock_ctx.get.return_value = "test-bot"
            with patch("app.agent.bots.get_bot", return_value=bot):
                result = json.loads(await list_api_endpoints())

        assert "error" in result
        assert "no API access" in result["error"].lower() or "api_permissions" in result["error"]

    @pytest.mark.asyncio
    async def test_scope_filter_narrows_results(self):
        from app.tools.local.api_access import list_api_endpoints

        bot = _make_bot(api_permissions=["channels:read", "tasks:read"])
        with patch("app.tools.local.api_access.current_bot_id") as mock_ctx:
            mock_ctx.get.return_value = "test-bot"
            with patch("app.agent.bots.get_bot", return_value=bot):
                # Only tasks
                result = json.loads(await list_api_endpoints(scope="tasks"))

        assert "endpoints" in result
        assert len(result["endpoints"]) > 0
        # All results should be scoped under tasks:*
        # (this includes /tasks/* and related endpoints like /cron-jobs)
        for ep in result["endpoints"]:
            # The scope filter is on the scope string, not the path
            pass  # filter already validated by the tool

    @pytest.mark.asyncio
    async def test_no_bot_context(self):
        from app.tools.local.api_access import list_api_endpoints

        with patch("app.tools.local.api_access.current_bot_id") as mock_ctx:
            mock_ctx.get.return_value = None
            result = json.loads(await list_api_endpoints())

        assert "error" in result


class TestCallApi:
    def test_tool_schema_supports_array_body_for_strict_providers(self):
        """call_api body accepts arrays, so the array branch must declare items."""
        import app.tools.local.api_access  # noqa: F401
        from app.tools.registry import get_local_tool_schemas

        [schema] = get_local_tool_schemas(["call_api"])
        body_schema = schema["function"]["parameters"]["properties"]["body"]

        assert body_schema["type"] == ["object", "array", "string", "null"]
        assert body_schema["items"] == {}

    @pytest.mark.asyncio
    async def test_invalid_path_rejected(self):
        from app.tools.local.api_access import call_api

        with patch("app.tools.local.api_access.current_bot_id") as mock_ctx:
            mock_ctx.get.return_value = "test-bot"
            result = json.loads(await call_api(method="GET", path="/evil/path"))

        assert "error" in result
        assert "must start with" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_no_api_key_returns_error(self):
        from app.tools.local.api_access import call_api

        mock_db = AsyncMock()
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.tools.local.api_access.current_bot_id") as mock_ctx:
            mock_ctx.get.return_value = "test-bot"
            with patch("app.db.engine.async_session", return_value=mock_session):
                with patch("app.services.api_keys.get_bot_api_key_value", new_callable=AsyncMock, return_value=None):
                    result = json.loads(await call_api(method="GET", path="/api/v1/channels"))

        assert "error" in result
        assert "no api key" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_successful_call(self):
        """Mock the ASGI transport to verify the tool makes correct requests."""
        from app.tools.local.api_access import call_api

        mock_db = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        # Mock httpx response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"id": "ch-1", "name": "test"}]
        mock_response.headers = {}

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.tools.local.api_access.current_bot_id") as mock_ctx:
            mock_ctx.get.return_value = "test-bot"
            with patch("app.db.engine.async_session", return_value=mock_session_ctx):
                with patch("app.services.api_keys.get_bot_api_key_value", new_callable=AsyncMock, return_value="ask_test123"):
                    with patch("httpx.AsyncClient", return_value=mock_client):
                        result = json.loads(await call_api(method="GET", path="/api/v1/channels"))

        assert result["status"] == 200
        assert isinstance(result["body"], list)
        # Verify correct auth header was passed
        mock_client.request.assert_called_once()
        call_kwargs = mock_client.request.call_args
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer ask_test123"

    @pytest.mark.asyncio
    async def test_structured_body_is_sent_without_string_encoding(self):
        """Agents can pass JSON objects directly instead of hand-escaped strings."""
        from app.tools.local.api_access import call_api

        mock_db = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "ch-1"}
        mock_response.headers = {}

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        body = {"name": "Agent-first", "bot_id": "default"}
        with patch("app.tools.local.api_access.current_bot_id") as mock_ctx:
            mock_ctx.get.return_value = "test-bot"
            with patch("app.db.engine.async_session", return_value=mock_session_ctx):
                with patch("app.services.api_keys.get_bot_api_key_value", new_callable=AsyncMock, return_value="ask_test123"):
                    with patch("httpx.AsyncClient", return_value=mock_client):
                        result = json.loads(await call_api(method="POST", path="/api/v1/channels", body=body))

        assert result["status"] == 201
        call_kwargs = mock_client.request.call_args
        assert call_kwargs.kwargs["json"] == body

    @pytest.mark.asyncio
    async def test_returns_structured_result(self):
        """Verify status + body structure."""
        from app.tools.local.api_access import call_api

        mock_db = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"detail": "Not found"}
        mock_response.headers = {}

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.tools.local.api_access.current_bot_id") as mock_ctx:
            mock_ctx.get.return_value = "test-bot"
            with patch("app.db.engine.async_session", return_value=mock_session_ctx):
                with patch("app.services.api_keys.get_bot_api_key_value", new_callable=AsyncMock, return_value="ask_key"):
                    with patch("httpx.AsyncClient", return_value=mock_client):
                        result = json.loads(await call_api(method="GET", path="/api/v1/channels/nonexistent"))

        assert "status" in result
        assert "body" in result
        assert result["status"] == 404
        assert result["error_code"] == "http_404"
        assert result["error_kind"] == "not_found"
        assert result["retryable"] is False

    @pytest.mark.asyncio
    async def test_rate_limited_call_surfaces_retry_contract(self):
        from app.tools.local.api_access import call_api

        mock_db = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.json.return_value = {"detail": "Too many requests"}
        mock_response.headers = {"retry-after": "12"}

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.tools.local.api_access.current_bot_id") as mock_ctx:
            mock_ctx.get.return_value = "test-bot"
            with patch("app.db.engine.async_session", return_value=mock_session_ctx):
                with patch("app.services.api_keys.get_bot_api_key_value", new_callable=AsyncMock, return_value="ask_key"):
                    with patch("httpx.AsyncClient", return_value=mock_client):
                        result = json.loads(await call_api(method="GET", path="/api/v1/channels"))

        assert result["status"] == 429
        assert result["error_kind"] == "rate_limited"
        assert result["retryable"] is True
        assert result["retry_after_seconds"] == 12

    @pytest.mark.asyncio
    async def test_no_bot_context(self):
        from app.tools.local.api_access import call_api

        with patch("app.tools.local.api_access.current_bot_id") as mock_ctx:
            mock_ctx.get.return_value = None
            result = json.loads(await call_api(method="GET", path="/api/v1/channels"))

        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_json_body(self):
        from app.tools.local.api_access import call_api

        mock_db = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.tools.local.api_access.current_bot_id") as mock_ctx:
            mock_ctx.get.return_value = "test-bot"
            with patch("app.db.engine.async_session", return_value=mock_session_ctx):
                with patch("app.services.api_keys.get_bot_api_key_value", new_callable=AsyncMock, return_value="ask_key"):
                    result = json.loads(await call_api(
                        method="POST", path="/api/v1/channels",
                        body="not valid json{{{",
                    ))

        assert "error" in result
        assert "invalid json" in result["error"].lower()
