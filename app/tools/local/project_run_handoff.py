"""Project coding-run branch and PR handoff tool."""
from __future__ import annotations

import json
from typing import Any

from app.agent.context import (
    current_bot_id,
    current_channel_id,
    current_correlation_id,
    current_session_id,
    current_task_id,
)
from app.tools.registry import register


_RETURNS = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "status": {"type": "string"},
        "action": {"type": "string"},
        "branch": {"type": "string"},
        "base_branch": {"type": "string"},
        "repo_root": {"type": "string"},
        "dirty": {"type": "boolean"},
        "remote_url": {"type": "string"},
        "pr_url": {"type": "string"},
        "handoff": {"type": "object"},
        "blockers": {"type": "array", "items": {"type": "string"}},
        "receipts": {"type": "array", "items": {"type": "object"}},
        "commands": {"type": "array", "items": {"type": "object"}},
        "error": {"type": "string"},
    },
    "required": ["ok"],
}


@register({
    "type": "function",
    "function": {
        "name": "prepare_project_run_handoff",
        "description": (
            "Prepare the configured Project coding-run git branch, optionally push it and open a draft PR, "
            "and write durable Project run progress receipts. Use prepare_branch before editing and open_pr "
            "near handoff when credentials are available."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "prepare_branch", "push", "open_pr"],
                    "description": "Which handoff phase to run. Defaults to prepare_branch.",
                },
                "project_id": {"type": "string", "description": "Optional Project UUID; inferred from task/channel when omitted."},
                "task_id": {"type": "string", "description": "Optional Task UUID; inferred from the current task run when omitted."},
                "branch": {"type": "string", "description": "Optional work branch override."},
                "base_branch": {"type": "string", "description": "Optional base branch override."},
                "repo_path": {"type": "string", "description": "Optional Project-relative repository path override."},
                "title": {"type": "string", "description": "Draft PR title for action=open_pr."},
                "body": {"type": "string", "description": "Draft PR body for action=open_pr."},
                "draft": {"type": "boolean", "description": "Create a draft PR when action=open_pr. Defaults true."},
                "remote": {"type": "string", "description": "Git remote name. Defaults origin."},
            },
        },
    },
}, safety_tier="exec_capable", requires_bot_context=True, requires_channel_context=True, returns=_RETURNS)
async def prepare_project_run_handoff(
    action: str = "prepare_branch",
    project_id: str | None = None,
    task_id: str | None = None,
    branch: str | None = None,
    base_branch: str | None = None,
    repo_path: str | None = None,
    title: str | None = None,
    body: str | None = None,
    draft: bool = True,
    remote: str = "origin",
) -> str:
    bot_id = current_bot_id.get()
    channel_id = current_channel_id.get()
    if not bot_id:
        return json.dumps({"ok": False, "error": "No bot context available."}, ensure_ascii=False)
    if not channel_id:
        return json.dumps({"ok": False, "error": "No channel context available."}, ensure_ascii=False)

    try:
        from app.db.engine import async_session
        from app.services.project_run_handoff import prepare_project_run_handoff as prepare_handoff

        async with async_session() as db:
            payload: dict[str, Any] = await prepare_handoff(
                db,
                action=action,
                project_id=project_id,
                task_id=task_id or current_task_id.get(),
                channel_id=channel_id,
                bot_id=bot_id,
                session_id=current_session_id.get(),
                correlation_id=current_correlation_id.get(),
                branch=branch,
                base_branch=base_branch,
                repo_path=repo_path,
                title=title,
                body=body,
                draft=draft,
                remote=remote or "origin",
            )
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    return json.dumps(payload, ensure_ascii=False)
