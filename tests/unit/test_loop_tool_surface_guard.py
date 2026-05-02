from unittest.mock import AsyncMock

import pytest

from app.agent.bots import BotConfig, MemoryConfig
from app.agent.loop_helpers import _resolve_loop_tools


def _schema(name: str) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "description": name, "parameters": {}},
    }


def _bot(**overrides) -> BotConfig:
    defaults = dict(
        id="bot-1",
        name="Test Bot",
        model="gpt-4",
        system_prompt="System.",
        memory=MemoryConfig(),
        local_tools=[],
        pinned_tools=[],
        tool_retrieval=False,
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


@pytest.mark.asyncio
async def test_large_non_retrieval_surface_filters_to_operator_and_required_tools():
    local_tools = [f"tool_{i}" for i in range(15)] + ["file", "exec_command"]
    bot = _bot(
        local_tools=local_tools,
        pinned_tools=["file", "exec_command"],
        tool_retrieval=False,
    )

    state = await _resolve_loop_tools(
        bot,
        pre_selected_tools=None,
        authorized_tool_names=None,
        tool_surface_policy="focused_escape",
        required_tool_names=["tool_3", "file"],
        compaction=False,
        get_local_tool_schemas_fn=lambda names: [_schema(name) for name in names],
        fetch_mcp_tools_fn=AsyncMock(return_value=[]),
        get_client_tool_schemas_fn=lambda names: [],
        merge_tool_schemas_fn=lambda tools: tools,
    )

    exposed = {t["function"]["name"] for t in state.tools_param or []}
    assert exposed == {"tool_3", "file", "exec_command", "get_skill", "get_skill_list"}


@pytest.mark.asyncio
async def test_explicit_full_surface_preserves_legacy_tool_dump():
    local_tools = [f"tool_{i}" for i in range(15)]
    bot = _bot(local_tools=local_tools, tool_retrieval=False)

    state = await _resolve_loop_tools(
        bot,
        pre_selected_tools=None,
        authorized_tool_names=None,
        tool_surface_policy="full",
        required_tool_names=None,
        compaction=False,
        get_local_tool_schemas_fn=lambda names: [_schema(name) for name in names],
        fetch_mcp_tools_fn=AsyncMock(return_value=[]),
        get_client_tool_schemas_fn=lambda names: [],
        merge_tool_schemas_fn=lambda tools: tools,
    )

    exposed = {t["function"]["name"] for t in state.tools_param or []}
    assert set(local_tools) <= exposed
