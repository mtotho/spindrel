"""Regression tests: pinned tools must always have schemas loaded, regardless
of whether they also appear in local_tools / mcp_servers / client_tools.

Pinning is labeled in the UI as "always available every turn". Before the fix,
pinning a tool that wasn't also in one of the declared buckets was silently
ignored — the schema never made it into `by_name`, the tool was dropped from
`_effective_pinned`, and the authorization check rejected it if the LLM tried
to call it by name.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.agent.bots import BotConfig
from app.agent.message_utils import _all_tool_schemas_by_name


def _bot(**overrides) -> BotConfig:
    return BotConfig(
        id="test-bot",
        name="Test",
        model="gpt-4",
        system_prompt="",
        **overrides,
    )


_LOCAL_TOOL_REGISTRY = {
    "web_search": {"type": "function", "function": {"name": "web_search", "description": "Search the web"}},
    "search_memory": {"type": "function", "function": {"name": "search_memory", "description": "Search memory"}},
    "get_tool_info": {"type": "function", "function": {"name": "get_tool_info", "description": "Inspect a tool"}},
}

_CLIENT_TOOL_REGISTRY = {
    "shell_exec": {"type": "function", "function": {"name": "shell_exec", "description": "Run a shell command"}},
}

_MCP_TOOL_REGISTRY = {
    "firecrawl": [
        {"type": "function", "function": {"name": "firecrawl-search", "description": "Firecrawl search"}},
        {"type": "function", "function": {"name": "firecrawl-scrape", "description": "Firecrawl scrape"}},
    ],
    "homeassistant": [
        {"type": "function", "function": {"name": "homeassistant-GetLiveContext", "description": "HA state"}},
    ],
}


def _fake_get_local(names):
    return [_LOCAL_TOOL_REGISTRY[n] for n in names if n in _LOCAL_TOOL_REGISTRY]


def _fake_get_client(names):
    return [_CLIENT_TOOL_REGISTRY[n] for n in names if n in _CLIENT_TOOL_REGISTRY]


async def _fake_fetch_mcp(servers):
    out = []
    for s in servers:
        out.extend(_MCP_TOOL_REGISTRY.get(s, []))
    return out


def _fake_server_for_tool(name):
    for server, tools in _MCP_TOOL_REGISTRY.items():
        for t in tools:
            if t["function"]["name"] == name:
                return server
    return None


@pytest.mark.asyncio
async def test_pinned_local_tool_loaded_when_not_in_local_tools():
    """pinned_tools=['web_search'], local_tools=[] → web_search schema is loaded."""
    bot = _bot(pinned_tools=["web_search"], local_tools=[], mcp_servers=[], client_tools=[])
    with patch("app.agent.message_utils.get_local_tool_schemas", side_effect=_fake_get_local), \
         patch("app.agent.message_utils.fetch_mcp_tools", new=AsyncMock(side_effect=_fake_fetch_mcp)), \
         patch("app.agent.message_utils.get_client_tool_schemas", side_effect=_fake_get_client), \
         patch("app.agent.message_utils.get_mcp_server_for_tool", side_effect=_fake_server_for_tool):
        by_name = await _all_tool_schemas_by_name(bot)
    assert "web_search" in by_name


@pytest.mark.asyncio
async def test_pinned_mcp_tool_pulls_in_undeclared_server():
    """pinned_tools=['firecrawl-search'], mcp_servers=[] → firecrawl server is fetched, tool loaded."""
    bot = _bot(pinned_tools=["firecrawl-search"], local_tools=[], mcp_servers=[], client_tools=[])
    fetch_mock = AsyncMock(side_effect=_fake_fetch_mcp)
    with patch("app.agent.message_utils.get_local_tool_schemas", side_effect=_fake_get_local), \
         patch("app.agent.message_utils.fetch_mcp_tools", new=fetch_mock), \
         patch("app.agent.message_utils.get_client_tool_schemas", side_effect=_fake_get_client), \
         patch("app.agent.message_utils.get_mcp_server_for_tool", side_effect=_fake_server_for_tool):
        by_name = await _all_tool_schemas_by_name(bot)
    assert "firecrawl-search" in by_name
    # Confirm the undeclared server got pulled in
    called_servers = fetch_mock.call_args.args[0]
    assert "firecrawl" in called_servers


@pytest.mark.asyncio
async def test_pinned_client_tool_loaded():
    """pinned_tools=['shell_exec'], client_tools=[] → shell_exec loaded from client registry."""
    bot = _bot(pinned_tools=["shell_exec"], local_tools=[], mcp_servers=[], client_tools=[])
    with patch("app.agent.message_utils.get_local_tool_schemas", side_effect=_fake_get_local), \
         patch("app.agent.message_utils.fetch_mcp_tools", new=AsyncMock(side_effect=_fake_fetch_mcp)), \
         patch("app.agent.message_utils.get_client_tool_schemas", side_effect=_fake_get_client), \
         patch("app.agent.message_utils.get_mcp_server_for_tool", side_effect=_fake_server_for_tool):
        by_name = await _all_tool_schemas_by_name(bot)
    assert "shell_exec" in by_name


@pytest.mark.asyncio
async def test_declared_local_tool_still_loaded_with_no_pins():
    """Regression: pinned_tools=[], local_tools=['web_search'] → unchanged behavior."""
    bot = _bot(pinned_tools=[], local_tools=["web_search"], mcp_servers=[], client_tools=[])
    with patch("app.agent.message_utils.get_local_tool_schemas", side_effect=_fake_get_local), \
         patch("app.agent.message_utils.fetch_mcp_tools", new=AsyncMock(side_effect=_fake_fetch_mcp)), \
         patch("app.agent.message_utils.get_client_tool_schemas", side_effect=_fake_get_client), \
         patch("app.agent.message_utils.get_mcp_server_for_tool", side_effect=_fake_server_for_tool):
        by_name = await _all_tool_schemas_by_name(bot)
    assert "web_search" in by_name
    assert set(by_name.keys()) == {"web_search"}


@pytest.mark.asyncio
async def test_pin_and_local_both_set_no_double_fetch():
    """Pinning a tool already in local_tools doesn't add duplicate fetches."""
    bot = _bot(
        pinned_tools=["web_search"],
        local_tools=["web_search", "search_memory"],
        mcp_servers=[],
        client_tools=[],
    )
    with patch("app.agent.message_utils.get_local_tool_schemas", side_effect=_fake_get_local) as local_mock, \
         patch("app.agent.message_utils.fetch_mcp_tools", new=AsyncMock(side_effect=_fake_fetch_mcp)), \
         patch("app.agent.message_utils.get_client_tool_schemas", side_effect=_fake_get_client), \
         patch("app.agent.message_utils.get_mcp_server_for_tool", side_effect=_fake_server_for_tool):
        by_name = await _all_tool_schemas_by_name(bot)
    assert by_name.keys() == {"web_search", "search_memory"}
    passed_names = local_mock.call_args.args[0]
    assert sorted(set(passed_names)) == sorted(passed_names), "no duplicate names passed to registry"


@pytest.mark.asyncio
async def test_pinned_unknown_tool_silently_dropped():
    """A pin to a non-existent tool doesn't error; registries filter unknowns."""
    bot = _bot(pinned_tools=["nonexistent_tool"], local_tools=[], mcp_servers=[], client_tools=[])
    with patch("app.agent.message_utils.get_local_tool_schemas", side_effect=_fake_get_local), \
         patch("app.agent.message_utils.fetch_mcp_tools", new=AsyncMock(side_effect=_fake_fetch_mcp)), \
         patch("app.agent.message_utils.get_client_tool_schemas", side_effect=_fake_get_client), \
         patch("app.agent.message_utils.get_mcp_server_for_tool", side_effect=_fake_server_for_tool):
        by_name = await _all_tool_schemas_by_name(bot)
    assert by_name == {}


@pytest.mark.asyncio
async def test_declared_mcp_server_plus_pin_to_undeclared_server():
    """Bot has homeassistant declared; also pins a firecrawl tool. Both servers fetched."""
    bot = _bot(
        pinned_tools=["firecrawl-search"],
        local_tools=[],
        mcp_servers=["homeassistant"],
        client_tools=[],
    )
    fetch_mock = AsyncMock(side_effect=_fake_fetch_mcp)
    with patch("app.agent.message_utils.get_local_tool_schemas", side_effect=_fake_get_local), \
         patch("app.agent.message_utils.fetch_mcp_tools", new=fetch_mock), \
         patch("app.agent.message_utils.get_client_tool_schemas", side_effect=_fake_get_client), \
         patch("app.agent.message_utils.get_mcp_server_for_tool", side_effect=_fake_server_for_tool):
        by_name = await _all_tool_schemas_by_name(bot)
    assert "firecrawl-search" in by_name
    assert "homeassistant-GetLiveContext" in by_name
    called_servers = fetch_mock.call_args.args[0]
    assert "firecrawl" in called_servers and "homeassistant" in called_servers
