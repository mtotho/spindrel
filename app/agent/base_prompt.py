"""Workspace-authored base prompt helpers."""

from __future__ import annotations


def resolve_workspace_base_prompt(workspace_id: str, bot_id: str) -> str | None:
    """Read common/prompts/base.md + bots/{bot_id}/prompts/base.md from workspace.

    Returns concatenated content, or None if common/prompts/base.md doesn't exist.
    This is an additive workspace-authored prompt layer; it does not replace
    the server-wide GLOBAL_BASE_PROMPT.
    """
    from app.services.shared_workspace import SharedWorkspaceError, shared_workspace_service

    try:
        common = shared_workspace_service.read_file(workspace_id, "common/prompts/base.md")["content"]
    except (SharedWorkspaceError, OSError):
        return None

    parts = [common]
    try:
        bot_specific = shared_workspace_service.read_file(
            workspace_id,
            f"bots/{bot_id}/prompts/base.md",
        )["content"]
        parts.append(bot_specific)
    except (SharedWorkspaceError, OSError):
        pass

    return "\n\n".join(parts)
