"""MCP outbound URL guard wiring.

Verifies that ``fetch_mcp_tools`` and ``call_mcp_tool`` consult the URL guard
(``app.services.url_safety.assert_public_url``) before issuing any HTTP
request, and respect the operator opt-ins ``MCP_ALLOW_PRIVATE_NETWORKS`` /
``MCP_ALLOW_LOOPBACK``. Before this fix the runtime path had no SSRF
protection — only the admin "test connection" endpoint did.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.config import settings
from app.tools import mcp as mcp_module
from app.tools.mcp import MCPServerConfig


def _drop_background_task(coro):
    coro.close()
    return None


@pytest.fixture(autouse=True)
def _reset_mcp_state():
    mcp_module._servers.clear()
    mcp_module._cache.clear()
    prev_private = settings.MCP_ALLOW_PRIVATE_NETWORKS
    prev_loopback = settings.MCP_ALLOW_LOOPBACK
    settings.MCP_ALLOW_PRIVATE_NETWORKS = False
    settings.MCP_ALLOW_LOOPBACK = False
    try:
        yield
    finally:
        settings.MCP_ALLOW_PRIVATE_NETWORKS = prev_private
        settings.MCP_ALLOW_LOOPBACK = prev_loopback
        mcp_module._servers.clear()
        mcp_module._cache.clear()


def test_fetch_mcp_tools_blocks_metadata_ip() -> None:
    server = MCPServerConfig(name="evil", url="http://169.254.169.254/", api_key="abc")
    mcp_module._servers["evil"] = server

    async def run():
        with patch("httpx.AsyncClient.post") as post:
            tools = await mcp_module.fetch_mcp_tools(["evil"])
            assert post.call_count == 0
            assert tools == []

    asyncio.run(run())


def test_call_mcp_tool_blocks_private_ip() -> None:
    server = MCPServerConfig(name="postgres-leak", url="http://10.0.0.5:5432/", api_key="abc")
    mcp_module._servers["postgres-leak"] = server
    mcp_module._cache["postgres-leak"] = {
        "tools": [
            {"type": "function", "function": {"name": "leak", "description": "", "parameters": {}}}
        ],
        "fetched_at": 0.0,
    }

    async def run():
        with patch("httpx.AsyncClient.post") as post:
            result = await mcp_module.call_mcp_tool("leak", "{}")
            assert post.call_count == 0
            assert "blocked" in result.lower() or "private" in result.lower()

    asyncio.run(run())


def test_opt_in_lets_private_through() -> None:
    server = MCPServerConfig(name="lan", url="http://10.0.0.5/", api_key="")
    mcp_module._servers["lan"] = server
    settings.MCP_ALLOW_PRIVATE_NETWORKS = True

    captured: dict = {}

    class _Resp:
        status_code = 200
        text = '{"jsonrpc": "2.0", "result": {"tools": []}, "id": 1}'
        headers = {"content-type": "application/json"}

        def raise_for_status(self):
            pass

        def json(self):
            return {"jsonrpc": "2.0", "result": {"tools": []}, "id": 1}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kwargs):
            captured["url"] = url
            return _Resp()

    async def run():
        with patch("app.tools.mcp.asyncio.create_task", side_effect=_drop_background_task), patch(
            "app.tools.mcp.httpx.AsyncClient", _Client
        ):
            tools = await mcp_module.fetch_mcp_tools(["lan"])
            assert tools == []  # server returned 0 tools, but the call went through
            assert captured["url"] == "http://10.0.0.5/"

    asyncio.run(run())


def test_per_server_opt_in_lets_private_through() -> None:
    server = MCPServerConfig(
        name="lan",
        url="http://10.0.0.5/",
        api_key="",
        allow_private_networks=True,
    )
    mcp_module._servers["lan"] = server

    captured: dict = {}

    class _Resp:
        status_code = 200
        text = '{"jsonrpc": "2.0", "result": {"tools": []}, "id": 1}'
        headers = {"content-type": "application/json"}

        def raise_for_status(self):
            pass

        def json(self):
            return {"jsonrpc": "2.0", "result": {"tools": []}, "id": 1}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kwargs):
            captured["url"] = url
            return _Resp()

    async def run():
        with patch("app.tools.mcp.asyncio.create_task", side_effect=_drop_background_task), patch(
            "app.tools.mcp.httpx.AsyncClient", _Client
        ):
            tools = await mcp_module.fetch_mcp_tools(["lan"])
            assert tools == []
            assert captured["url"] == "http://10.0.0.5/"

    asyncio.run(run())


def test_loopback_blocked_even_with_private_opt_in() -> None:
    server = MCPServerConfig(name="local", url="http://127.0.0.1:8080/", api_key="")
    mcp_module._servers["local"] = server
    settings.MCP_ALLOW_PRIVATE_NETWORKS = True
    settings.MCP_ALLOW_LOOPBACK = False

    async def run():
        with patch("httpx.AsyncClient.post") as post:
            tools = await mcp_module.fetch_mcp_tools(["local"])
            assert post.call_count == 0
            assert tools == []

    asyncio.run(run())
