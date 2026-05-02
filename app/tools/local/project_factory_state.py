"""Project Factory state - read-only stage-aware aggregate for agents.

Single tool. Returns the same payload as the UI cockpit so agents and humans
see the same world. Used by the project skill cluster's first action to route
to the right next-step skill without piecing together intake/packs/runs/receipts.
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
        "state": {"type": "object"},
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
        "name": "get_project_factory_state",
        "description": (
            "Return a single stage-aware aggregate for the current Project: blueprint readiness, "
            "runtime env, dependency stack, intake counts, Run Pack counts, runs by queue state, "
            "recent receipts, and a suggested_next_action with the skill to load. Call this first "
            "in any Project-bound conversation to know what stage you are in and what to do next."
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
async def get_project_factory_state_tool(project_id: str | None = None) -> str:
    from app.db.engine import async_session
    from app.db.models import Project
    from app.services.project_factory_state import get_project_factory_state

    try:
        async with async_session() as db:
            resolved_project_id = await _infer_project_id(db, project_id)
            project = await db.get(Project, resolved_project_id)
            if project is None:
                return json.dumps({"ok": False, "error": "project not found"}, ensure_ascii=False)
            state: dict[str, Any] = await get_project_factory_state(db, project)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    return json.dumps({"ok": True, "state": state}, ensure_ascii=False)
