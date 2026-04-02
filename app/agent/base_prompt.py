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

    has_skills = bool(getattr(bot, "skills", None))
    has_memory = False  # DB memory deprecated
    has_knowledge = False  # DB knowledge deprecated
    has_delegation = bool(getattr(bot, "delegate_bots", None))

    variables = defaultdict(str, {
        "bot_name": getattr(bot, "name", "Assistant"),
        "skills_section": "\n- **Skills**: You can retrieve skill documents with get_skill for specialized knowledge." if has_skills else "",
        "memory_section": "\n- **Memory**: You have persistent memory across conversations. Relevant memories are automatically recalled." if has_memory else "",
        "knowledge_section": "\n- **Knowledge**: You can read and write knowledge documents for long-term reference." if has_knowledge else "",
        "delegation_section": "\n- **Delegation**: You can delegate tasks to sub-agents via delegate_to_agent or @bot-id mentions." if has_delegation else "",
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
