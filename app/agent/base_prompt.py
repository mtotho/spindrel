"""Load, cache, and render the universal base prompt for all bots."""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)

_BASE_PROMPT_PATH = Path("prompts/base.md")
_cached_template: str | None = None


def load_base_prompt() -> None:
    """Read prompts/base.md into module-level cache. Called once at startup."""
    global _cached_template
    if not _BASE_PROMPT_PATH.exists():
        logger.warning("Base prompt file not found at %s — base prompt disabled", _BASE_PROMPT_PATH)
        _cached_template = None
        return
    _cached_template = _BASE_PROMPT_PATH.read_text(encoding="utf-8")
    logger.info("Loaded base prompt (%d chars) from %s", len(_cached_template), _BASE_PROMPT_PATH)


def render_base_prompt(bot) -> str | None:
    """Render the base prompt template with bot-specific variables.

    Returns None if the bot opts out (base_prompt=False) or the template is not loaded.
    """
    if not getattr(bot, "base_prompt", True):
        return None
    if _cached_template is None:
        return None

    has_skills = True  # skills are shared documents, always available to all bots
    has_memory = False  # DB memory deprecated
    has_knowledge = False  # DB knowledge deprecated
    has_delegation = bool(getattr(bot, "delegate_bots", None))
    has_subagents = "spawn_subagents" in (getattr(bot, "local_tools", None) or [])

    variables = defaultdict(str, {
        "bot_name": getattr(bot, "name", "Assistant"),
        "skills_section": "\n- **Skills**: Skill documents contain detailed procedures and reference material. Call `get_skill(skill_id)` to load a skill before responding to questions it covers. Skills marked as relevant in your skill index should be loaded before you respond. Use `get_skill_list()` to see all available skills — check it when you're unsure how to proceed." if has_skills else "",
        "memory_section": "\n- **Memory**: You have persistent memory across conversations. Relevant memories are automatically recalled." if has_memory else "",
        "knowledge_section": "\n- **Knowledge**: You can read and write knowledge documents for long-term reference." if has_knowledge else "",
        "delegation_section": "\n- **Delegation**: Use delegate_to_agent to send work to a specific named bot. The result is posted to the channel under that bot's identity. Use only when the task requires that bot's expertise and the user should see the result from it." if has_delegation else "",
        "subagent_section": "\n- **Sub-agents**: Use spawn_subagents for parallel grunt work (file scanning, summarizing, research). Results return directly to you — nothing is posted to the channel. Prefer this over delegate_to_agent when you need help thinking or gathering information." if has_subagents else "",
        "memory_guidelines": "\n- Use memory naturally: reference recalled memories when relevant, save important information for future recall." if has_memory else "",
        "knowledge_guidelines": "\n- Use knowledge docs to persist structured information that should survive across sessions." if has_knowledge else "",
    })

    try:
        return _cached_template.format_map(variables)
    except (KeyError, ValueError):
        logger.exception("Failed to render base prompt template")
        return None


def resolve_workspace_base_prompt(workspace_id: str, bot_id: str) -> str | None:
    """Read common/prompts/base.md + bots/{bot_id}/prompts/base.md from workspace.

    Returns concatenated content, or None if common/prompts/base.md doesn't exist.
    """
    from app.services.shared_workspace import shared_workspace_service, SharedWorkspaceError

    try:
        common = shared_workspace_service.read_file(workspace_id, "common/prompts/base.md")["content"]
    except (SharedWorkspaceError, OSError):
        return None

    parts = [common]
    try:
        bot_specific = shared_workspace_service.read_file(
            workspace_id, f"bots/{bot_id}/prompts/base.md",
        )["content"]
        parts.append(bot_specific)
    except (SharedWorkspaceError, OSError):
        pass

    return "\n\n".join(parts)
