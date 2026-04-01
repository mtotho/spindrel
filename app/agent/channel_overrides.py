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


def _resolve_list(bot_list: list[str], override: list | None, disabled: list | None) -> list[str]:
    """Resolve a single tool list with override/disabled semantics.

    - override set  → whitelist: only items present in both override AND bot_list
    - disabled set  → blacklist: remove disabled items from bot_list
    - both None     → inherit bot_list as-is
    - override takes precedence if both are set
    """
    if override is not None:
        bot_set = set(bot_list)
        return [t for t in override if t in bot_set]
    if disabled is not None:
        disabled_set = set(disabled)
        return [t for t in bot_list if t not in disabled_set]
    return list(bot_list)


def _resolve_skills(
    bot_skills: list[SkillConfig],
    override: list | None,
    disabled: list | None,
    extras: list | None = None,
) -> list[SkillConfig]:
    """Resolve skills with override/disabled/extras semantics.

    - override (legacy): whitelist — only matching bot skills kept
    - extras: add new skills from global pool
    - disabled: remove skills by id
    """
    if override is not None:
        # Legacy override path — whitelist only bot skills
        bot_skill_map = {s.id: s for s in bot_skills}
        result = []
        for entry in override:
            sid = entry if isinstance(entry, str) else entry.get("id", "")
            base = bot_skill_map.get(sid)
            if base is None:
                continue
            if isinstance(entry, dict):
                result.append(SkillConfig(
                    id=sid,
                    mode=entry.get("mode", base.mode),
                    similarity_threshold=entry.get("similarity_threshold", base.similarity_threshold),
                ))
            else:
                result.append(base)
        return result

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
                        similarity_threshold=entry.get("similarity_threshold"),
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

    Tools: channel overrides restrict the bot's tool lists (override/disabled).
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
    if channel is not None:
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

    return EffectiveTools(
        local_tools=_resolve_list(
            bot.local_tools,
            channel.local_tools_override,
            channel.local_tools_disabled,
        ),
        mcp_servers=_resolve_list(
            bot.mcp_servers,
            channel.mcp_servers_override,
            channel.mcp_servers_disabled,
        ),
        client_tools=_resolve_list(
            bot.client_tools,
            channel.client_tools_override,
            channel.client_tools_disabled,
        ),
        pinned_tools=_resolve_list(
            bot.pinned_tools,
            channel.pinned_tools_override,
            None,  # no disabled for pinned — use override or inherit
        ),
        skills=_resolve_skills(
            bot.skills,
            channel.skills_override,
            channel.skills_disabled,
            getattr(channel, "skills_extra", None),
        ),
        carapaces=_carapaces,
    )
