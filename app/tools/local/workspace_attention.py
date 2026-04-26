"""Bot-facing tools for Attention assignments."""
from __future__ import annotations

import json
import uuid

from app.agent.context import current_bot_id
from app.db.engine import async_session
from app.domain.errors import NotFoundError, ValidationError
from app.tools.registry import register


REPORT_ATTENTION_ASSIGNMENT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "report_attention_assignment",
        "description": (
            "Report findings for an Attention Item assigned to you. Use this "
            "after investigating; do not use it to claim fixes were executed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "item_id": {"type": "string"},
                "findings": {"type": "string"},
            },
            "required": ["item_id", "findings"],
        },
    },
}


@register(REPORT_ATTENTION_ASSIGNMENT_SCHEMA, safety_tier="mutating", requires_bot_context=True)
async def report_attention_assignment(item_id: str, findings: str) -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."})
    try:
        parsed_id = uuid.UUID(item_id)
    except (TypeError, ValueError):
        return json.dumps({"error": f"Invalid item_id: {item_id!r}"})
    async with async_session() as db:
        try:
            from app.services.workspace_attention import report_attention_assignment as report, serialize_attention_item
            item = await report(db, parsed_id, bot_id=bot_id, findings=findings)
            payload = await serialize_attention_item(db, item)
        except (NotFoundError, ValidationError) as exc:
            return json.dumps({"error": str(exc)})
    return json.dumps({"item": payload}, default=str)
