"""Tests for forgiving MCP tool name resolution.

LiteLLM's MCP gateway namespaces tools as ``<server>-<tool>``. Smaller
models (Gemini 2.5 Flash and friends) frequently drop the prefix when
calling the tool. ``resolve_mcp_tool_name`` recovers those bare calls so
dispatch doesn't have to fail + round-trip through ``get_tool_info``.
"""
from unittest.mock import patch

import pytest

from app.agent.bots import BotConfig
from app.agent.message_utils import _all_tool_schemas_by_name
from app.tools.mcp import (
    _cache,
    _servers,
    infer_mcp_server_from_tool_name,
    resolve_mcp_tool_name,
)


_FAKE_CACHE = {
    "homeassistant": {
        "tools": [
            {"type": "function", "function": {"name": "homeassistant-HassLightSet"}},
            {"type": "function", "function": {"name": "homeassistant-HassTurnOn"}},
        ],
        "fetched_at": 0.0,
    },
    "other": {
        "tools": [
            {"type": "function", "function": {"name": "other-DoThing"}},
        ],
        "fetched_at": 0.0,
    },
}


class TestResolveMcpToolName:
    def test_exact_match_returns_same(self):
        with patch.dict(_cache, _FAKE_CACHE, clear=True):
            assert resolve_mcp_tool_name("homeassistant-HassLightSet") == "homeassistant-HassLightSet"

    def test_bare_name_resolves_to_prefixed(self):
        with patch.dict(_cache, _FAKE_CACHE, clear=True):
            assert resolve_mcp_tool_name("HassLightSet") == "homeassistant-HassLightSet"
            assert resolve_mcp_tool_name("HassTurnOn") == "homeassistant-HassTurnOn"

    def test_unknown_returns_none(self):
        with patch.dict(_cache, _FAKE_CACHE, clear=True):
            assert resolve_mcp_tool_name("NotARealTool") is None

    def test_empty_cache_returns_none(self):
        with patch.dict(_cache, {}, clear=True):
            assert resolve_mcp_tool_name("HassLightSet") is None

    def test_bare_name_resolves_across_servers(self):
        with patch.dict(_cache, _FAKE_CACHE, clear=True):
            assert resolve_mcp_tool_name("DoThing") == "other-DoThing"

    def test_prefixed_name_infers_configured_server_with_cold_cache(self):
        with patch.dict(_cache, {}, clear=True), patch.dict(_servers, {"homeassistant": object()}, clear=True):
            assert infer_mcp_server_from_tool_name("homeassistant-HassTurnOn") == "homeassistant"

    def test_prefixed_name_does_not_infer_unknown_server(self):
        with patch.dict(_servers, {"homeassistant": object()}, clear=True):
            assert infer_mcp_server_from_tool_name("other-HassTurnOn") is None


@pytest.mark.asyncio
async def test_enrolled_prefixed_tool_fetches_mcp_server_when_cache_is_cold():
    bot = BotConfig(
        id="haos-bot",
        name="Haos",
        model="gpt-5.4",
        system_prompt="",
        local_tools=[],
        pinned_tools=[],
        mcp_servers=[],
        client_tools=[],
        skills=[],
    )
    mcp_schema = {
        "type": "function",
        "function": {"name": "homeassistant-GetLiveContext", "parameters": {}},
    }

    async def fake_fetch_mcp_tools(servers):
        assert servers == ["homeassistant"]
        return [mcp_schema]

    with patch.dict(_cache, {}, clear=True), patch.dict(_servers, {"homeassistant": object()}, clear=True), patch(
        "app.agent.message_utils.get_local_tool_schemas",
        return_value=[],
    ), patch("app.agent.message_utils.get_client_tool_schemas", return_value=[]), patch(
        "app.agent.message_utils.fetch_mcp_tools",
        side_effect=fake_fetch_mcp_tools,
    ):
        by_name = await _all_tool_schemas_by_name(
            bot,
            enrolled_tool_names=["homeassistant-HassTurnOn"],
        )

    assert by_name["homeassistant-GetLiveContext"] == mcp_schema
