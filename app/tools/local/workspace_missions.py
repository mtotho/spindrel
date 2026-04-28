"""Bot-facing mission tools."""
from __future__ import annotations

import json
import uuid

from app.agent.context import current_bot_id
from app.db.engine import async_session
from app.domain.errors import NotFoundError, ValidationError
from app.tools.registry import register


REPORT_MISSION_PROGRESS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "report_mission_progress",
        "description": "Append a concise progress update and next actions for a Workspace Mission assigned to you.",
        "parameters": {
            "type": "object",
            "properties": {
                "mission_id": {"type": "string"},
                "summary": {"type": "string"},
                "next_actions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "One to three concrete next actions.",
                },
            },
            "required": ["mission_id", "summary"],
        },
    },
}


@register(REPORT_MISSION_PROGRESS_SCHEMA, safety_tier="mutating", requires_bot_context=True)
async def report_mission_progress(mission_id: str, summary: str, next_actions: list[str] | None = None) -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."})
    try:
        parsed_id = uuid.UUID(mission_id)
    except (TypeError, ValueError):
        return json.dumps({"error": f"Invalid mission_id: {mission_id!r}"})
    async with async_session() as db:
        try:
            from app.services.workspace_missions import report_mission_progress as report

            update = await report(
                db,
                parsed_id,
                bot_id=bot_id,
                summary=summary,
                next_actions=next_actions,
            )
            payload = {
                "id": str(update.id),
                "mission_id": str(update.mission_id),
                "bot_id": update.bot_id,
                "kind": update.kind,
                "summary": update.summary,
                "next_actions": update.next_actions,
                "created_at": update.created_at.isoformat() if update.created_at else None,
            }
        except (NotFoundError, ValidationError) as exc:
            return json.dumps({"error": str(exc)})
    return json.dumps({"update": payload}, default=str)
