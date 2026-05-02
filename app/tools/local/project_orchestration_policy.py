"""Phase 4BC - canonical orchestration policy view, agent-readable.

Read-only tool wrapping ``get_project_orchestration_policy``. Lets a runtime
skill answer "is the cap saturated? what's the stall timeout? does WORKFLOW.md
override anything?" without rederiving from Blueprint + WORKFLOW.md + run rows.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.agent.context import current_channel_id, current_project_instance_id
from app.tools.registry import register


_RETURNS = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "policy": {"type": "object"},
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
        "name": "get_project_orchestration_policy",
        "description": (
            "Return the merged orchestration-policy view for the current Project: concurrency cap "
            "with live in-flight + headroom, stall/turn timeouts with their source (blueprint vs "
            "default vs unset), intake convention, canonical repo, and the raw `## Policy` section "
            "from .spindrel/WORKFLOW.md when present. Call this before launching runs in a loop or "
            "before deciding whether the current Project can absorb another implementation run."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Optional Project UUID. Inferred from the current Project-bound channel or run when omitted.",
                },
            },
            "required": [],
        },
    },
}, safety_tier="readonly", requires_bot_context=True, returns=_RETURNS)
async def get_project_orchestration_policy_tool(project_id: str | None = None) -> str:
    from app.db.engine import async_session
    from app.db.models import Project
    from app.services.project_orchestration_policy import get_project_orchestration_policy

    try:
        async with async_session() as db:
            resolved_project_id = await _infer_project_id(db, project_id)
            project = await db.get(Project, resolved_project_id)
            if project is None:
                return json.dumps({"ok": False, "error": "project not found"}, ensure_ascii=False)
            policy: dict[str, Any] = await get_project_orchestration_policy(db, project)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    return json.dumps({"ok": True, "policy": policy}, ensure_ascii=False)
