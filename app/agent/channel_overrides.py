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


def apply_auto_injections(eff: EffectiveTools, bot: BotConfig) -> EffectiveTools:
    """Apply all auto-injected tools based on bot config.

    This is the single source of truth for tools that get added at runtime
    by context_assembly. Call this after resolve_effective_tools() to get
    the complete tool list that the LLM will actually see.

    Injections:
    - memory_scheme="workspace-files" → search_memory, get_memory_file, file, manage_bot_skill
    - tool_retrieval=true → get_tool_info
    - (unconditional) → get_skill, get_skill_list, list_agent_capabilities,
      run_agent_doctor, list_channels, read_conversation_history,
      list_sub_sessions, read_sub_session
    """
    import dataclasses
    from app.services.memory_scheme import MEMORY_SCHEME_TOOLS, MEMORY_SCHEME_HIDDEN_TOOLS

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
        for t in MEMORY_SCHEME_TOOLS:
            _inject(t)

    # Tool retrieval
    if getattr(bot, "tool_retrieval", False):
        _inject("get_tool_info")

    # Skills — shared documents, always available
    _inject("get_skill")
    _inject("get_skill_list")

    # Agent self-inspection — every bot can ask what it can do and why it may
    # be blocked before making humans inspect configuration manually.
    _inject("list_agent_capabilities")
    _inject("run_agent_doctor")

    # Channel awareness — any bot can inspect channel history and its
    # attached sub-sessions (threads, scratch chats, pipeline/eval runs)
    _inject("list_channels")
    _inject("read_conversation_history")
    _inject("list_sub_sessions")
    _inject("read_sub_session")

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
