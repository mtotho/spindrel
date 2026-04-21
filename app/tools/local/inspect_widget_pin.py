"""Bot tool: inspect_widget_pin — read a pinned widget's recent debug events.

Closes the widget-authoring feedback loop. The SDK preamble ambiently
captures every ``callTool`` / ``loadAttachment`` request+response pair,
plus uncaught JS errors, unhandled promise rejections, ``console.*``
output, and explicit ``spindrel.log.*`` entries, and POSTs them to
``/api/v1/widget-debug/events`` under the pin's id. This tool reads the
same ring, so after pinning a widget the authoring bot can call
``inspect_widget_pin(pin_id=...)`` to see the REAL response envelope
shape returned by every tool the widget invoked — no guessing.

Iteration recipe:
    1. Emit widget v1 (best guess at shape).
    2. Pin it.
    3. Call ``inspect_widget_pin(pin_id)``.
    4. Read the ``tool-call`` event's ``response`` — that is the ground
       truth for extraction paths. Read any ``error`` / ``rejection``
       events for JS bugs (line numbers, stack traces).
    5. Rewrite against the confirmed path; re-emit. No fallback chains.

Events are held in-memory per pin (cap 50, newest-first on read); the
buffer is process-local and wipes on server restart. For authoring
flows this is almost always enough — the bot inspects right after
pinning.
"""
from __future__ import annotations

import json
import logging
from uuid import UUID

from app.services import widget_debug
from app.tools.registry import register

logger = logging.getLogger(__name__)


_SCHEMA = {
    "type": "function",
    "function": {
        "name": "inspect_widget_pin",
        "description": (
            "Read the recent debug event log for a pinned HTML widget — "
            "every tool call (request args + response JSON), every "
            "attachment load, every JS error / unhandled rejection / "
            "console output, and every explicit spindrel.log.* entry. "
            "Call this AFTER pinning a widget you just authored to see "
            "what the widget is actually doing and what shape the tools "
            "returned. Returns a newest-first timeline so you can learn "
            "the real envelope shape without guessing. Events include: "
            "{kind: 'tool-call', tool, args, ok, response, error, "
            "durationMs}, {kind: 'load-attachment', id, ok, status, "
            "sizeBytes}, {kind: 'error', message, src, line, col, stack}, "
            "{kind: 'rejection', reason, stack}, {kind: 'console', level, "
            "args}, {kind: 'log', level, message}."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pin_id": {
                    "type": "string",
                    "description": (
                        "UUID of the dashboard pin to inspect. Usually "
                        "the id returned by `pin_widget` on the preceding "
                        "turn; `describe_dashboard` also lists pin ids."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Max events to return (1-50). Default 20.",
                    "minimum": 1,
                    "maximum": 50,
                },
            },
            "required": ["pin_id"],
        },
    },
}


@register(
    _SCHEMA,
    safety_tier="readonly",
    returns={
        "type": "object",
        "properties": {
            "pin_id": {"type": "string"},
            "count": {"type": "integer"},
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string"},
                        "ts": {"type": ["number", "null"]},
                        "ts_server": {"type": "number"},
                    },
                    "additionalProperties": True,
                },
            },
        },
        "required": ["pin_id", "count", "events"],
    },
)
async def inspect_widget_pin(pin_id: str, limit: int = 20) -> str:
    try:
        pid = UUID(pin_id)
    except (TypeError, ValueError):
        return json.dumps({"error": f"Invalid pin_id: {pin_id!r}"})

    bounded = max(1, min(int(limit or 20), 50))
    events = widget_debug.get_events(pid, limit=bounded)
    return json.dumps(
        {"pin_id": str(pid), "count": len(events), "events": events},
        ensure_ascii=False,
        indent=2,
    )
