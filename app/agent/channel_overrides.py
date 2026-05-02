"""Resolve effective tools/skills for a channel with bot-level inheritance."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.agent.bots import BotConfig, SkillConfig

if False:  # TYPE_CHECKING
    from app.db.models import Channel


@dataclass
class EffectiveTools:
    local_tools: list[str] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)
    client_tools: list[str] = field(default_factory=list)
    pinned_tools: list[str] = field(default_factory=list)
    skills: list[SkillConfig] = field(default_factory=list)


def _tool_names_for_metadata(**filters: str) -> frozenset[str]:
    from app.tools.registry import get_local_tool_names_by_metadata

    return frozenset(get_local_tool_names_by_metadata(**filters))


def auto_injected_pin_names() -> frozenset[str]:
    """Tools injected by runtime policy rather than operator curation."""
    groups = (
        "chat_baseline",
        "workspace_files_memory",
        "channel_workspace",
        "api_access",
        "tool_retrieval",
    )
    names: frozenset[str] = frozenset()
    for group in groups:
        names = names | _tool_names_for_metadata(auto_inject=group)
    return names


def discovery_hatch_tool_names() -> frozenset[str]:
    """Escape tools the LLM uses to find or hydrate other tool schemas."""
    return _tool_names_for_metadata(domain="tool_schema") | _tool_names_for_metadata(domain="tool_discovery")


def plan_mode_control_tool_names() -> tuple[str, ...]:
    """Plan-mode control tools declared by their own tool metadata."""
    return tuple(_tool_names_for_metadata(domain="plan_control"))


def apply_auto_injections(eff: EffectiveTools, bot: BotConfig) -> EffectiveTools:
    """Apply all auto-injected tools based on bot config.

    This is the single source of truth for tools that get added at runtime
    by context_assembly. Call this after resolve_effective_tools() to get
    the complete tool list that the LLM will actually see.

    Injections are declared by tool metadata. Runtime code selects groups such
    as chat_baseline, tool_retrieval, and workspace_files_memory; it does not
    check concrete tool names.
    """
    import dataclasses
    from app.services.memory_scheme import MEMORY_SCHEME_HIDDEN_TOOLS
    from app.tools.registry import get_local_tool_names_by_metadata

    local = list(eff.local_tools)
    pinned = list(eff.pinned_tools or [])

    def _inject(tool_name: str) -> None:
        if tool_name not in local:
            local.append(tool_name)
        if tool_name not in pinned:
            pinned.append(tool_name)

    # Memory scheme
    if getattr(bot, "memory_scheme", None) == "workspace-files":
        local[:] = [t for t in local if t not in MEMORY_SCHEME_HIDDEN_TOOLS]
        for t in get_local_tool_names_by_metadata(auto_inject="workspace_files_memory"):
            _inject(t)

    # Tool retrieval
    if getattr(bot, "tool_retrieval", False):
        for t in get_local_tool_names_by_metadata(auto_inject="tool_retrieval"):
            _inject(t)

    for t in get_local_tool_names_by_metadata(auto_inject="chat_baseline"):
        _inject(t)

    return dataclasses.replace(eff, local_tools=local, pinned_tools=pinned)


def _apply_disabled(bot_list: list[str], disabled: list | None) -> list[str]:
    """Apply a blacklist to a bot tool list.

    - disabled set  → remove disabled items from bot_list
    - None          → inherit bot_list as-is
    """
    if not disabled:
        return list(bot_list)
    disabled_set = set(disabled)
    return [t for t in bot_list if t not in disabled_set]


def _resolve_skills(
    bot_skills: list[SkillConfig],
    channel_skill_ids: list[str],
) -> list[SkillConfig]:
    """Merge bot skills with channel-enrolled skill IDs."""
    skills = list(bot_skills)
    existing = {s.id for s in skills}
    for skill_id in channel_skill_ids:
        if skill_id not in existing:
            skills.append(SkillConfig(id=skill_id, mode="on_demand"))
            existing.add(skill_id)
    return skills


def _collect_activated_integration_tools(channel: "Channel | None") -> list[str]:
    """Return local tool names shipped by integrations activated on this channel."""
    if channel is None:
        return []
    try:
        from app.tools.registry import _tools

        active_integrations = {
            ci.integration_type
            for ci in (getattr(channel, "integrations", None) or [])
            if getattr(ci, "activated", False)
        }
        if not active_integrations:
            return []
        names: list[str] = []
        for tool_name, entry in _tools.items():
            if entry.get("source_integration") in active_integrations:
                names.append(tool_name)
        return names
    except Exception:
        return []


def resolve_effective_tools(bot: BotConfig, channel: "Channel | None") -> EffectiveTools:
    """Resolve effective tool/skill configuration for a channel.

    Tools: channel disabled lists restrict the bot's tool lists (blacklist only).
    Skills: channel-level enrollments can ADD skills from the global pool.
    Returns bot defaults when channel is None.
    """
    if channel is None:
        return EffectiveTools(
            local_tools=list(bot.local_tools),
            mcp_servers=list(bot.mcp_servers),
            client_tools=list(bot.client_tools),
            pinned_tools=list(bot.pinned_tools),
            skills=list(bot.skills),
        )

    # Inject MCP servers from activated integrations
    _mcp = list(bot.mcp_servers)
    try:
        from app.services.integration_manifests import collect_integration_mcp_servers
        _int_mcp = collect_integration_mcp_servers(
            getattr(channel, "integrations", None),
            exclude=set(_mcp),
        )
        _mcp.extend(_int_mcp)
    except ImportError:
        pass

    _channel_skill_ids = getattr(channel, "_channel_skill_enrollment_ids", None) or []
    _integration_tools = _collect_activated_integration_tools(channel)
    _local_tools = list(bot.local_tools)
    for tool_name in _integration_tools:
        if tool_name not in _local_tools:
            _local_tools.append(tool_name)

    return EffectiveTools(
        local_tools=_apply_disabled(_local_tools, channel.local_tools_disabled),
        mcp_servers=_apply_disabled(_mcp, channel.mcp_servers_disabled),
        client_tools=_apply_disabled(bot.client_tools, channel.client_tools_disabled),
        pinned_tools=list(bot.pinned_tools),
        skills=_resolve_skills(bot.skills, list(_channel_skill_ids)),
    )
