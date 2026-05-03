"""Agent-facing Project run environment profile validation."""
from __future__ import annotations

import json
import uuid

from app.agent.context import current_channel_id
from app.tools.registry import register


_RETURNS = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "validation": {"type": "object"},
        "error": {"type": "string"},
    },
    "required": ["ok"],
}


@register({
    "type": "function",
    "function": {
        "name": "validate_project_run_environment_profile",
        "description": (
            "Validate a Project coding-run environment profile without executing setup commands. "
            "Returns source layer, trust state, approval hash state, schema/work-surface errors, "
            "and whether a run would block before the model starts."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Optional Project UUID. Inferred from the current Project-bound channel when omitted.",
                },
                "profile_id": {
                    "type": "string",
                    "description": "Optional profile id. Defaults through Project/Blueprint default_run_environment_profile.",
                },
                "repo_path": {
                    "type": "string",
                    "description": "Optional repo path from the Project Blueprint snapshot.",
                },
                "work_surface_mode": {
                    "type": "string",
                    "enum": ["isolated_worktree", "fresh_project_instance", "shared_repo"],
                    "description": "Work surface mode to validate against. Defaults to isolated_worktree.",
                },
            },
            "required": [],
        },
    },
}, safety_tier="readonly", requires_bot_context=True, requires_channel_context=True, returns=_RETURNS)
async def validate_project_run_environment_profile(
    project_id: str | None = None,
    profile_id: str | None = None,
    repo_path: str | None = None,
    work_surface_mode: str = "isolated_worktree",
) -> str:
    try:
        from app.db.engine import async_session
        from app.db.models import Channel, Project
        from app.services.project_run_environment_profiles import validate_project_run_environment_profile_selection

        async with async_session() as db:
            resolved_project_id = uuid.UUID(str(project_id)) if project_id else None
            if resolved_project_id is None:
                channel_id = current_channel_id.get()
                if channel_id is None:
                    return json.dumps({"ok": False, "error": "current channel is not Project-bound"}, ensure_ascii=False)
                channel = await db.get(Channel, uuid.UUID(str(channel_id)))
                if channel is None or channel.project_id is None:
                    return json.dumps({"ok": False, "error": "current channel is not Project-bound"}, ensure_ascii=False)
                resolved_project_id = channel.project_id
            project = await db.get(Project, resolved_project_id)
            if project is None:
                return json.dumps({"ok": False, "error": "project not found"}, ensure_ascii=False)
            validation = await validate_project_run_environment_profile_selection(
                project,
                profile_id=profile_id,
                repo_path=repo_path,
                work_surface_mode=work_surface_mode,
            )
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    return json.dumps({"ok": bool(validation.get("ok")), "validation": validation}, ensure_ascii=False, default=str)
