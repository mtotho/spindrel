"""Helper to regenerate approval suggestions by index.

Used by the Discord approval handler to look up a suggestion by its
positional index, since we can't encode the full suggestion in the
custom_id (100-char limit).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def build_suggestion_rule(tool_name: str, arguments: dict, index: int) -> tuple[dict | None, str]:
    """Regenerate suggestions and return the rule dict + label at the given index.

    Returns (rule_dict, label) or (None, "") if the index is out of range.
    """
    try:
        from app.services.approval_suggestions import build_suggestions
        suggestions = build_suggestions(tool_name, arguments)
        if index < 0 or index >= len(suggestions):
            return None, ""
        sug = suggestions[index]
        rule = {
            "tool_name": sug.tool_name,
            "conditions": sug.conditions,
            "scope": getattr(sug, "scope", "bot"),
        }
        return rule, sug.label
    except Exception:
        logger.exception("Failed to rebuild suggestion %d for %s", index, tool_name)
        return None, ""
