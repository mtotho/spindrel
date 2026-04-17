"""Tests for forgiving MCP tool name resolution.

LiteLLM's MCP gateway namespaces tools as ``<server>-<tool>``. Smaller
models (Gemini 2.5 Flash and friends) frequently drop the prefix when
calling the tool. ``resolve_mcp_tool_name`` recovers those bare calls so
dispatch doesn't have to fail + round-trip through ``get_tool_info``.
"""
from unittest.mock import patch

from app.tools.mcp import _cache, resolve_mcp_tool_name


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
