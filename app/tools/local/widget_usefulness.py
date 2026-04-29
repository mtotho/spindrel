"""Bot-facing widget usefulness assessment."""
from __future__ import annotations

import json
import uuid

from app.agent.context import current_bot_id, current_channel_id
from app.db.engine import async_session
from app.services.widget_usefulness import assess_channel_widget_usefulness
from app.tools.registry import register


_SCHEMA = {
    "type": "function",
    "function": {
        "name": "assess_widget_usefulness",
        "description": (
            "Assess whether a channel dashboard's widgets are useful, healthy, "
            "visible in the intended surfaces, and exporting helpful context. "
            "Start here for recurring widget improvement reviews; use "
            "check_dashboard_widgets/check_widget only when this assessment "
            "points to health or runtime evidence that needs deeper inspection."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "channel_id": {
                    "type": "string",
                    "description": "Optional channel UUID. Defaults to the current channel context.",
                },
            },
        },
    },
}


_RETURNS = {
    "type": "object",
    "properties": {
        "channel_id": {"type": "string"},
        "dashboard_key": {"type": "string"},
        "status": {"type": "string"},
        "summary": {"type": "string"},
        "pin_count": {"type": "integer"},
        "chat_visible_pin_count": {"type": "integer"},
        "layout_mode": {"type": "string"},
        "widget_agency_mode": {"type": "string"},
        "project_scope_available": {"type": "boolean"},
        "project": {"type": ["object", "null"]},
        "context_export": {"type": "object"},
        "recommendations": {"type": "array"},
    },
    "additionalProperties": True,
}


@register(_SCHEMA, safety_tier="readonly", requires_bot_context=False, requires_channel_context=False, returns=_RETURNS)
async def assess_widget_usefulness(channel_id: str | None = None) -> str:
    resolved_channel_id = channel_id or (str(current_channel_id.get()) if current_channel_id.get() else None)
    if not resolved_channel_id:
        return json.dumps({"error": "channel_id is required outside channel context."})
    try:
        parsed = uuid.UUID(str(resolved_channel_id))
    except (TypeError, ValueError):
        return json.dumps({"error": f"Invalid channel_id: {resolved_channel_id!r}"})
    async with async_session() as db:
        try:
            result = await assess_channel_widget_usefulness(
                db,
                parsed,
                bot_id=current_bot_id.get(),
            )
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
    return json.dumps(result, ensure_ascii=False, default=str)
