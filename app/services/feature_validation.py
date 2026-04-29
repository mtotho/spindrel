"""Feature validation service — checks bots for missing prerequisites."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Static feature requirements keyed by feature ID.
# Each entry declares tools that must be in the bot's effective tool set
# for the feature to work correctly.
FEATURE_REQUIREMENTS: dict[str, dict] = {
    "memory_scheme:workspace-files": {
        "description": "Workspace-files memory scheme",
        "requires_tools": ["file", "search_memory", "get_memory_file"],
    },
    "history_mode:file": {
        "description": "File-based history mode",
        "requires_tools": ["read_conversation_history"],
    },
}


@dataclass
class FeatureWarning:
    bot_id: str
    feature: str
    description: str
    missing_tools: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "bot_id": self.bot_id,
            "feature": self.feature,
            "description": self.description,
            "missing_tools": self.missing_tools,
        }


def _check_static_features(bot, available_tools: set[str]) -> list[FeatureWarning]:
    """Check static FEATURE_REQUIREMENTS against a bot's available tools."""
    warnings = []

    # memory_scheme:workspace-files
    if bot.memory_scheme == "workspace-files":
        req = FEATURE_REQUIREMENTS["memory_scheme:workspace-files"]
        missing = [t for t in req["requires_tools"] if t not in available_tools]
        if missing:
            warnings.append(FeatureWarning(
                bot_id=bot.id,
                feature="memory_scheme:workspace-files",
                description=req["description"],
                missing_tools=missing,
            ))

    # history_mode:file
    if bot.history_mode == "file":
        req = FEATURE_REQUIREMENTS["history_mode:file"]
        missing = [t for t in req["requires_tools"] if t not in available_tools]
        if missing:
            warnings.append(FeatureWarning(
                bot_id=bot.id,
                feature="history_mode:file",
                description=req["description"],
                missing_tools=missing,
            ))

    return warnings


async def validate_activation(bot_id: str, integration_type: str) -> list[FeatureWarning]:
    """Check if a bot has the tools required by an integration manifest."""
    from app.agent.bots import get_bot
    from app.tools.mcp import fetch_mcp_tools

    try:
        bot = get_bot(bot_id)
    except Exception:
        return []

    # Build the bot's effective tool set
    available: set[str] = set(bot.local_tools) | set(bot.client_tools)
    if bot.mcp_servers:
        try:
            mcp_schemas = await fetch_mcp_tools(bot.mcp_servers)
            available |= {t["function"]["name"] for t in mcp_schemas}
        except Exception:
            pass

    from app.services.integration_catalog import get_activation_manifests
    manifests = get_activation_manifests()
    manifest = manifests.get(integration_type)
    if not manifest:
        return []

    required_tools = list(manifest.get("tools", []) or [])
    if not required_tools:
        return []

    missing = [t for t in required_tools if t not in available]
    if not missing:
        return []

    return [
        FeatureWarning(
            bot_id=bot_id,
            feature=f"activation:{integration_type}",
            description=f"Integration '{integration_type}' requires tools",
            missing_tools=missing,
        )
    ]


async def validate_features() -> list[FeatureWarning]:
    """Check all bots for missing feature prerequisites. Returns warnings."""
    from app.agent.bots import list_bots
    from app.tools.registry import is_local_tool
    from app.tools.mcp import fetch_mcp_tools

    all_warnings: list[FeatureWarning] = []

    for bot in list_bots():
        # Build the bot's effective tool set: local + client + MCP
        # When tool_discovery is enabled (default), any registered local tool
        # can be found at runtime via tool RAG, so include them all.
        available: set[str] = set(bot.local_tools) | set(bot.client_tools)
        if getattr(bot, "tool_discovery", True):
            from app.tools.registry import _tools as _all_local_tools
            available |= set(_all_local_tools.keys())

        # Add MCP tool names
        if bot.mcp_servers:
            try:
                mcp_schemas = await fetch_mcp_tools(bot.mcp_servers)
                available |= {t["function"]["name"] for t in mcp_schemas}
            except Exception:
                logger.warning(
                    "Bot %r: failed to fetch MCP tools for feature validation",
                    bot.id,
                )

        # Check static features
        all_warnings.extend(_check_static_features(bot, available))

    for w in all_warnings:
        logger.warning(
            "Feature validation: bot %r feature %r missing tools: %s",
            w.bot_id, w.feature, w.missing_tools,
        )

    return all_warnings
