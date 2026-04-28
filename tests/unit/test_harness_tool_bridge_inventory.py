from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app.agent.bots import BotConfig
from app.agent.channel_overrides import EffectiveTools
from app.services.agent_harnesses.tools import resolve_harness_bridge_inventory


class _Db:
    async def get(self, *_args, **_kwargs):
        return None


def _schema(name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": f"{name} desc",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def _schemas_for(names: list[str]) -> list[dict]:
    return [_schema(name) for name in names]


def test_core_harness_bridge_fixture_tools_are_registered():
    import app.tools.local  # noqa: F401
    from app.tools.registry import _tools

    for tool_name in (
        "get_tool_info",
        "list_channels",
        "read_conversation_history",
        "list_sub_sessions",
        "read_sub_session",
    ):
        assert tool_name in _tools


def test_bridge_inventory_exports_selected_local_tools():
    bot = BotConfig(
        id="harness-bot",
        name="Harness Bot",
        model="claude-sonnet-4-6",
        system_prompt="",
        local_tools=["list_channels"],
    )

    with (
        patch("app.services.agent_harnesses.tools.get_bot", return_value=bot),
        patch(
            "app.services.agent_harnesses.tools.resolve_effective_tools",
            return_value=EffectiveTools(local_tools=list(bot.local_tools)),
        ),
        patch(
            "app.services.agent_harnesses.tools.apply_auto_injections",
            side_effect=lambda eff, _bot: eff,
        ),
        patch(
            "app.services.agent_harnesses.tools.get_local_tool_schemas",
            return_value=[_schema("list_channels")],
        ),
        patch(
            "app.services.tool_enrollment.get_enrolled_tool_names",
            new=AsyncMock(return_value=[]),
        ),
        patch("app.services.agent_harnesses.tools.fetch_mcp_tools", new=AsyncMock(return_value=[])),
    ):
        inventory = asyncio.run(
            resolve_harness_bridge_inventory(
                _Db(),
                bot_id="harness-bot",
                channel_id=None,
            )
        )

    assert [spec.name for spec in inventory.specs] == ["list_channels"]
    assert inventory.errors == ()


def test_bridge_inventory_reports_selected_local_tools_missing_from_registry():
    bot = BotConfig(
        id="harness-bot",
        name="Harness Bot",
        model="claude-sonnet-4-6",
        system_prompt="",
        local_tools=["list_channels", "definitely_not_registered_tool"],
    )

    with (
        patch("app.services.agent_harnesses.tools.get_bot", return_value=bot),
        patch(
            "app.services.agent_harnesses.tools.resolve_effective_tools",
            return_value=EffectiveTools(local_tools=list(bot.local_tools)),
        ),
        patch(
            "app.services.agent_harnesses.tools.apply_auto_injections",
            side_effect=lambda eff, _bot: eff,
        ),
        patch(
            "app.services.agent_harnesses.tools.get_local_tool_schemas",
            return_value=[_schema("list_channels")],
        ),
        patch(
            "app.services.tool_enrollment.get_enrolled_tool_names",
            new=AsyncMock(return_value=[]),
        ),
        patch("app.services.agent_harnesses.tools.fetch_mcp_tools", new=AsyncMock(return_value=[])),
    ):
        inventory = asyncio.run(
            resolve_harness_bridge_inventory(
                _Db(),
                bot_id="harness-bot",
                channel_id=None,
            )
        )

    assert [spec.name for spec in inventory.specs] == ["list_channels"]
    assert inventory.errors == ("local tools not registered: definitely_not_registered_tool",)


def test_bridge_inventory_includes_pinned_and_enrolled_tools():
    bot = BotConfig(
        id="harness-bot",
        name="Harness Bot",
        model="claude-sonnet-4-6",
        system_prompt="",
        local_tools=["declared_tool"],
        pinned_tools=["pinned_tool"],
    )

    with (
        patch("app.services.agent_harnesses.tools.get_bot", return_value=bot),
        patch(
            "app.services.agent_harnesses.tools.resolve_effective_tools",
            return_value=EffectiveTools(
                local_tools=list(bot.local_tools),
                pinned_tools=list(bot.pinned_tools),
            ),
        ),
        patch(
            "app.services.agent_harnesses.tools.apply_auto_injections",
            side_effect=lambda eff, _bot: eff,
        ),
        patch(
            "app.services.tool_enrollment.get_enrolled_tool_names",
            new=AsyncMock(return_value=["fetched_tool"]),
        ),
        patch(
            "app.services.agent_harnesses.tools.get_local_tool_schemas",
            return_value=[
                _schema("declared_tool"),
                _schema("pinned_tool"),
                _schema("fetched_tool"),
            ],
        ) as schemas,
        patch("app.services.agent_harnesses.tools.fetch_mcp_tools", new=AsyncMock(return_value=[])),
    ):
        inventory = asyncio.run(
            resolve_harness_bridge_inventory(
                _Db(),
                bot_id="harness-bot",
                channel_id=None,
            )
        )

    assert schemas.call_args.args[0] == ["declared_tool", "pinned_tool", "fetched_tool"]
    assert [spec.name for spec in inventory.specs] == [
        "declared_tool",
        "pinned_tool",
        "fetched_tool",
    ]
    assert inventory.errors == ()


def test_bridge_inventory_enrolls_explicit_tool_tags():
    bot = BotConfig(
        id="harness-bot",
        name="Harness Bot",
        model="claude-sonnet-4-6",
        system_prompt="",
    )
    enroll = AsyncMock(return_value=1)

    with (
        patch("app.services.agent_harnesses.tools.get_bot", return_value=bot),
        patch(
            "app.services.agent_harnesses.tools.resolve_effective_tools",
            return_value=EffectiveTools(),
        ),
        patch(
            "app.services.agent_harnesses.tools.apply_auto_injections",
            side_effect=lambda eff, _bot: eff,
        ),
        patch("app.services.tool_enrollment.enroll_many", new=enroll),
        patch(
            "app.services.tool_enrollment.get_enrolled_tool_names",
            new=AsyncMock(return_value=["create_excalidraw"]),
        ),
        patch(
            "app.services.agent_harnesses.tools.get_local_tool_schemas",
            return_value=[_schema("create_excalidraw")],
        ) as schemas,
        patch("app.services.agent_harnesses.tools.fetch_mcp_tools", new=AsyncMock(return_value=[])),
    ):
        inventory = asyncio.run(
            resolve_harness_bridge_inventory(
                _Db(),
                bot_id="harness-bot",
                channel_id=None,
                explicit_tool_names=("create_excalidraw",),
            )
        )

    enroll.assert_awaited_once()
    assert enroll.call_args.args[:2] == ("harness-bot", ("create_excalidraw",))
    assert enroll.call_args.kwargs["source"] == "manual"
    assert schemas.call_args.args[0] == ["create_excalidraw"]
    assert [spec.name for spec in inventory.specs] == ["create_excalidraw"]


def test_bridge_inventory_tracks_auto_injected_history_baseline():
    bot = BotConfig(
        id="harness-bot",
        name="Harness Bot",
        model="claude-sonnet-4-6",
        system_prompt="",
    )

    with (
        patch("app.services.agent_harnesses.tools.get_bot", return_value=bot),
        patch(
            "app.services.agent_harnesses.tools.resolve_effective_tools",
            return_value=EffectiveTools(),
        ),
        patch(
            "app.services.agent_harnesses.tools.get_local_tool_schemas",
            side_effect=_schemas_for,
        ),
        patch(
            "app.services.tool_enrollment.get_enrolled_tool_names",
            new=AsyncMock(return_value=[]),
        ),
        patch("app.services.agent_harnesses.tools.fetch_mcp_tools", new=AsyncMock(return_value=[])),
    ):
        inventory = asyncio.run(
            resolve_harness_bridge_inventory(
                _Db(),
                bot_id="harness-bot",
                channel_id=None,
            )
        )

    assert set(inventory.required_baseline_tools) == {
        "list_channels",
        "read_conversation_history",
        "list_sub_sessions",
        "read_sub_session",
    }
    assert inventory.missing_baseline_tools == ()
    assert "read_conversation_history" in [spec.name for spec in inventory.specs]


def test_bridge_inventory_reports_missing_memory_baseline_tool():
    bot = BotConfig(
        id="harness-bot",
        name="Harness Bot",
        model="claude-sonnet-4-6",
        system_prompt="",
        memory_scheme="workspace-files",
    )

    def _without_search_memory(names: list[str]) -> list[dict]:
        return [_schema(name) for name in names if name != "search_memory"]

    with (
        patch("app.services.agent_harnesses.tools.get_bot", return_value=bot),
        patch(
            "app.services.agent_harnesses.tools.resolve_effective_tools",
            return_value=EffectiveTools(),
        ),
        patch(
            "app.services.agent_harnesses.tools.get_local_tool_schemas",
            side_effect=_without_search_memory,
        ),
        patch(
            "app.services.tool_enrollment.get_enrolled_tool_names",
            new=AsyncMock(return_value=[]),
        ),
        patch("app.services.agent_harnesses.tools.fetch_mcp_tools", new=AsyncMock(return_value=[])),
    ):
        inventory = asyncio.run(
            resolve_harness_bridge_inventory(
                _Db(),
                bot_id="harness-bot",
                channel_id=None,
            )
        )

    assert "search_memory" in inventory.required_baseline_tools
    assert inventory.missing_baseline_tools == ("search_memory",)
    assert "local tools not registered: search_memory" in inventory.errors
