"""Bot-facing widget authoring diagnostics."""
from __future__ import annotations

import json
from typing import Any

from app.agent.context import current_bot_id, current_channel_id
from app.services.widget_authoring_check import run_widget_authoring_check
from app.tools.registry import register


_SCHEMA = {
    "type": "function",
    "function": {
        "name": "check_widget_authoring",
        "description": (
            "Run the full authoring feedback loop for a draft tool-widget YAML "
            "template before saving, pinning, or asking the user to rely on it. "
            "Checks YAML/Python/schema validation, preview rendering, static "
            "widget health, and optionally a Playwright runtime smoke check in "
            "the real widget host. Use this for tool-widget authoring; use "
            "preview_widget/check_widget for standalone HTML widgets."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "yaml_template": {"type": "string", "description": "Tool-widget YAML template body."},
                "python_code": {"type": "string", "description": "Optional transform code referenced by self:* hooks."},
                "sample_payload": {"type": "object", "description": "Representative tool result JSON used for preview."},
                "widget_config": {"type": "object", "description": "Optional runtime widget_config used during substitution."},
                "tool_name": {"type": "string", "description": "Tool name this renderer targets."},
                "include_runtime": {
                    "type": "boolean",
                    "description": "When true, run Playwright against the real widget preview host.",
                },
                "include_screenshot": {
                    "type": "boolean",
                    "description": "When true and runtime smoke runs, include a PNG data URL for visual inspection.",
                },
            },
            "required": ["yaml_template"],
        },
    },
}


_RETURNS = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "readiness": {"type": "string"},
        "summary": {"type": "string"},
        "phases": {"type": "array"},
        "issues": {"type": "array"},
        "envelope": {"type": ["object", "null"]},
        "artifacts": {"type": "object"},
    },
    "additionalProperties": True,
}


@register(_SCHEMA, safety_tier="readonly", requires_bot_context=True, requires_channel_context=False, returns=_RETURNS)
async def check_widget_authoring(
    yaml_template: str,
    python_code: str | None = None,
    sample_payload: dict[str, Any] | None = None,
    widget_config: dict[str, Any] | None = None,
    tool_name: str | None = None,
    include_runtime: bool = True,
    include_screenshot: bool = False,
) -> str:
    channel_id = current_channel_id.get()
    result = await run_widget_authoring_check(
        yaml_template=yaml_template,
        python_code=python_code,
        sample_payload=sample_payload,
        widget_config=widget_config,
        tool_name=tool_name,
        source_bot_id=current_bot_id.get(),
        source_channel_id=str(channel_id) if channel_id else None,
        include_runtime=include_runtime,
        include_screenshot=include_screenshot,
    )
    return json.dumps(result, ensure_ascii=False, default=str)
