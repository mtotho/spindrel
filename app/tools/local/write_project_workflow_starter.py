"""Write a starter ``.spindrel/WORKFLOW.md`` for a Project.

Phase 4BE.4 of the Project Factory cohesion pass. The tool refuses to
overwrite an existing file - the runtime is not allowed to silently rewrite
a repo-owned contract. Setup/init offers this tool when the Project does not
already have a WORKFLOW.md, under explicit user confirmation.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.agent.context import (
    current_channel_id,
    current_project_instance_id,
)
from app.tools.registry import register


_RETURNS = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "host_path": {"type": ["string", "null"]},
        "relative_path": {"type": "string"},
        "error": {"type": "string"},
    },
    "required": ["ok"],
}


async def _infer_project_id(db, explicit_project_id: str | None) -> uuid.UUID:
    from app.db.models import Channel, ProjectInstance

    if explicit_project_id:
        return uuid.UUID(str(explicit_project_id))

    instance_id = current_project_instance_id.get()
    if instance_id:
        instance = await db.get(ProjectInstance, uuid.UUID(str(instance_id)))
        if instance is not None:
            return instance.project_id

    channel_id = current_channel_id.get()
    if channel_id is not None:
        channel = await db.get(Channel, uuid.UUID(str(channel_id)))
        if channel is not None and channel.project_id is not None:
            return channel.project_id

    raise ValueError("project_id is required when the current channel is not Project-bound")


@register({
    "type": "function",
    "function": {
        "name": "write_project_workflow_starter",
        "description": (
            "Write a starter `.spindrel/WORKFLOW.md` to the canonical repo. "
            "Refuses to overwrite an existing file - the runtime never silently "
            "mutates a repo-owned contract. Returns ok=False with an error when "
            "the file already exists or the Project has no canonical repo. "
            "Setup/init offers this under explicit user confirmation; do not call "
            "without asking the user first."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Optional Project UUID. Inferred from the current Project-bound channel or run when omitted.",
                },
            },
        },
    },
}, safety_tier="mutating", requires_bot_context=True, returns=_RETURNS)
async def write_project_workflow_starter_tool(
    project_id: str | None = None,
) -> str:
    from app.db.engine import async_session
    from app.db.models import Project
    from app.services.project_workflow_file import write_workflow_starter

    try:
        async with async_session() as db:
            resolved_project_id = await _infer_project_id(db, project_id)
            project = await db.get(Project, resolved_project_id)
            if project is None:
                return json.dumps({"ok": False, "error": "project not found"}, ensure_ascii=False)

            result = write_workflow_starter(project)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    payload: dict[str, Any] = {
        "ok": result.ok,
        "relative_path": result.relative_path,
        "host_path": result.host_path,
    }
    if result.error:
        payload["error"] = result.error
    return json.dumps(payload, ensure_ascii=False)
