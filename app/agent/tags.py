"""Parse and resolve @mention tags for explicit context/tool injection.

Supported syntax:
  @name             — auto-detect type: skill → tool → bot
  @skill:name       — force inject skill by ID (bypasses similarity threshold)
  @tool:name        — force include tool in this request's tool list
  @bot:name         — force ephemeral delegation to bot by ID

Slack safety: Slack user mentions arrive as <@USERID> (angle-bracket format).
The regex's negative lookbehind skips those, so @tags and Slack mentions never
conflict in the raw API payload.
"""
import logging
import re
import uuid
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Match @name or @type:name.
# Negative lookbehind: skip Slack's <@USERID> and email addresses (foo@bar).
# Names must start with a letter or underscore (not a digit).
# Allows slashes for path-style IDs (e.g. integrations/marp_slides/marp_slides).
# tool-pack must appear before tool in the alternation to avoid partial matching.
_TAG_RE = re.compile(r"(?<![<\w@])@((?:skill|tool-pack|tool|bot):)?([A-Za-z_][\w\-\./]*)")


@dataclass
class ResolvedTag:
    raw: str       # original text, e.g. "@arch_linux" or "@skill:arch_linux"
    name: str      # resolved name, e.g. "arch_linux"
    tag_type: str  # "skill", "tool", or "bot"


def _match_skill_short_name(short: str, skill_set: set[str]) -> str | None:
    """Match a short name like 'marp_slides' to a full path-style skill ID like 'integrations/marp_slides/marp_slides'.

    Returns the full ID if exactly one skill ends with the short name as its final segment.
    """
    matches = [s for s in skill_set if s.rsplit("/", 1)[-1] == short]
    return matches[0] if len(matches) == 1 else None


async def resolve_tags(
    message: str,
    bot_skills: list[str],
    bot_local_tools: list[str],
    bot_client_tools: list[str],
    bot_id: str,
    client_id: str | None,
    session_id: uuid.UUID | None = None,
) -> list[ResolvedTag]:
    """Parse @tags from a message and resolve each to skill/tool/bot.

    Resolution order for un-namespaced tags:
      1. skill  (checked against bot's skills list)
      2. tool   (checked against bot's local + client tools)
      3. bot    (checked against bot registry — enables ephemeral delegation)
    """
    raw_tags: list[tuple[str, str | None, str]] = []
    seen_names: set[str] = set()

    for m in _TAG_RE.finditer(message):
        raw = m.group(0)
        prefix = m.group(1)       # e.g. "skill:" or None
        name = m.group(2)
        if name in seen_names:
            continue
        seen_names.add(name)
        forced_type = prefix.rstrip(":") if prefix else None
        raw_tags.append((raw, forced_type, name))

    if not raw_tags:
        return []

    skill_set = set(bot_skills or [])
    tool_set = set(bot_local_tools or []) | set(bot_client_tools or [])

    # Load bot registry for bot @-tags
    from app.agent.bots import _registry as _bot_registry
    bot_id_set = set(_bot_registry.keys())

    resolved: list[ResolvedTag] = []

    for raw, forced_type, name in raw_tags:
        if forced_type == "skill":
            resolved.append(ResolvedTag(raw=raw, name=name, tag_type="skill"))
        elif forced_type == "tool":
            resolved.append(ResolvedTag(raw=raw, name=name, tag_type="tool"))
        elif forced_type == "tool-pack":
            from app.tools.packs import get_tool_packs
            for tool_name in get_tool_packs().get(name, []):
                if tool_name not in seen_names:
                    seen_names.add(tool_name)
                    resolved.append(ResolvedTag(raw=raw, name=tool_name, tag_type="tool"))
        elif forced_type == "bot":
            if name != bot_id:
                resolved.append(ResolvedTag(raw=raw, name=name, tag_type="bot"))
        elif name in skill_set:
            resolved.append(ResolvedTag(raw=raw, name=name, tag_type="skill"))
        elif (full_id := _match_skill_short_name(name, skill_set)):
            resolved.append(ResolvedTag(raw=raw, name=full_id, tag_type="skill"))
        elif name in tool_set:
            resolved.append(ResolvedTag(raw=raw, name=name, tag_type="tool"))
        elif name in bot_id_set and name != bot_id:
            # @bot-id → ephemeral delegation override (skip tagging the current bot)
            resolved.append(ResolvedTag(raw=raw, name=name, tag_type="bot"))
        else:
            logger.info("Tag @%s not resolved: not a skill, tool, or bot", name)

    return resolved
