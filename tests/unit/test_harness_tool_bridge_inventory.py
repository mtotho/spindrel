from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

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


@pytest.mark.asyncio
async def test_bridge_inventory_exports_selected_local_tools():
    bot = BotConfig(
        id="harness-bot",
        name="Harness Bot",
        model="claude-sonnet-4-6",
        system_prompt="",
        local_tools=["bennie_loggins_health_summary"],
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
            return_value=[_schema("bennie_loggins_health_summary")],
        ),
        patch("app.services.agent_harnesses.tools.fetch_mcp_tools", new=AsyncMock(return_value=[])),
    ):
        inventory = await resolve_harness_bridge_inventory(
            _Db(),
            bot_id="harness-bot",
            channel_id=None,
        )

    assert [spec.name for spec in inventory.specs] == ["bennie_loggins_health_summary"]
    assert inventory.errors == ()


@pytest.mark.asyncio
async def test_bridge_inventory_reports_selected_local_tools_missing_from_registry():
    bot = BotConfig(
        id="harness-bot",
        name="Harness Bot",
        model="claude-sonnet-4-6",
        system_prompt="",
        local_tools=["bennie_loggins_health_summary", "missing_tool"],
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
            return_value=[_schema("bennie_loggins_health_summary")],
        ),
        patch("app.services.agent_harnesses.tools.fetch_mcp_tools", new=AsyncMock(return_value=[])),
    ):
        inventory = await resolve_harness_bridge_inventory(
            _Db(),
            bot_id="harness-bot",
            channel_id=None,
        )

    assert [spec.name for spec in inventory.specs] == ["bennie_loggins_health_summary"]
    assert inventory.errors == ("local tools not registered: missing_tool",)
