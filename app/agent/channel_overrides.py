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
    carapaces: list[str] = field(default_factory=list)


def apply_auto_injections(eff: EffectiveTools, bot: BotConfig) -> EffectiveTools:
    """Apply all auto-injected tools based on bot config.

    This is the single source of truth for tools that get added at runtime
    by context_assembly. Call this after resolve_effective_tools() to get
    the complete tool list that the LLM will actually see.

    Injections:
    - memory_scheme="workspace-files" → search_memory, get_memory_file, file, manage_bot_skill
    - tool_retrieval=true → get_tool_info
    - bot has skills → get_skill, get_skill_list
    - history_mode="file" → read_conversation_history
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

    # History mode
    if getattr(bot, "history_mode", None) == "file":
        _inject("read_conversation_history")

    # activate_capability is conditional on capability RAG matches at runtime,
    # so we always include it as available (it's low-cost and always registered)
    _inject("activate_capability")

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
    disabled: list | None,
    extras: list | None = None,
) -> list[SkillConfig]:
    """Resolve skills with disabled/extras semantics.

    - extras: add new skills from global pool
    - disabled: remove skills by id
    """
    # Start with bot skills (already includes workspace DB skills)
    result_map = {s.id: s for s in bot_skills}
    # Merge channel extras (new skills from global pool)
    if extras:
        for entry in extras:
            sid = entry if isinstance(entry, str) else entry.get("id", "")
            if sid and sid not in result_map:
                if isinstance(entry, dict):
                    result_map[sid] = SkillConfig(
                        id=sid,
                        mode=entry.get("mode", "on_demand"),
                    )
                else:
                    result_map[sid] = SkillConfig(id=sid)
    # Remove disabled
    if disabled:
        disabled_set = set(disabled)
        return [s for s in result_map.values() if s.id not in disabled_set]
    return list(result_map.values())


def resolve_effective_tools(bot: BotConfig, channel: "Channel | None") -> EffectiveTools:
    """Resolve effective tool/skill configuration for a channel.

    Tools: channel disabled lists restrict the bot's tool lists (blacklist only).
    Skills: channel extras can ADD skills from the global pool; disabled removes.
    Returns bot defaults when channel is None.
    """
    if channel is None:
        return EffectiveTools(
            local_tools=list(bot.local_tools),
            mcp_servers=list(bot.mcp_servers),
            client_tools=list(bot.client_tools),
            pinned_tools=list(bot.pinned_tools),
            skills=list(bot.skills),
            carapaces=list(bot.carapaces),
        )

    # Resolve carapaces: extras add, activation inject, disabled removes
    _carapaces = list(bot.carapaces)
    _ch_extra = getattr(channel, "carapaces_extra", None) or []
    for cid in _ch_extra:
        if cid not in _carapaces:
            _carapaces.append(cid)
    _ch_disabled = set(getattr(channel, "carapaces_disabled", None) or [])

    # Inject carapaces from activated integrations (mirrors context_assembly.py)
    try:
        from integrations import get_activation_manifests
        _manifests = get_activation_manifests()
        for _ci in (getattr(channel, "integrations", None) or []):
            if not _ci.activated:
                continue
            _manifest = _manifests.get(_ci.integration_type)
            if _manifest:
                for cap_id in _manifest.get("carapaces", []):
                    if cap_id not in _carapaces and cap_id not in _ch_disabled:
                        _carapaces.append(cap_id)
    except Exception:
        pass

    if _ch_disabled:
        _carapaces = [c for c in _carapaces if c not in _ch_disabled]

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

    return EffectiveTools(
        local_tools=_apply_disabled(bot.local_tools, channel.local_tools_disabled),
        mcp_servers=_apply_disabled(_mcp, channel.mcp_servers_disabled),
        client_tools=_apply_disabled(bot.client_tools, channel.client_tools_disabled),
        pinned_tools=list(bot.pinned_tools),
        skills=_resolve_skills(
            bot.skills,
            channel.skills_disabled,
            getattr(channel, "skills_extra", None),
        ),
        carapaces=_carapaces,
    )
