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
) -> list[SkillConfig]:
    """Resolve skills with override/disabled semantics.

    override entries are dicts: {id, mode?, similarity_threshold?}
    disabled entries are skill id strings.
    """
    if override is not None:
        bot_skill_map = {s.id: s for s in bot_skills}
        result = []
        for entry in override:
            sid = entry if isinstance(entry, str) else entry.get("id", "")
            base = bot_skill_map.get(sid)
            if base is None:
                continue  # can't add skills the bot doesn't have
            if isinstance(entry, dict):
                result.append(SkillConfig(
                    id=sid,
                    mode=entry.get("mode", base.mode),
                    similarity_threshold=entry.get("similarity_threshold", base.similarity_threshold),
                ))
            else:
                result.append(base)
        return result
    if disabled is not None:
        disabled_set = set(disabled)
        return [s for s in bot_skills if s.id not in disabled_set]
    return list(bot_skills)


def resolve_effective_tools(bot: BotConfig, channel: "Channel | None") -> EffectiveTools:
    """Resolve effective tool/skill configuration for a channel.

    Channel overrides can only *restrict* what the bot offers, never expand it.
    Returns bot defaults when channel is None or has no overrides set.
    """
    if channel is None:
        return EffectiveTools(
            local_tools=list(bot.local_tools),
            mcp_servers=list(bot.mcp_servers),
            client_tools=list(bot.client_tools),
            pinned_tools=list(bot.pinned_tools),
            skills=list(bot.skills),
        )

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
        ),
    )
