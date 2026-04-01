"""Local tool: manage_workflow — list, get, trigger, and create workflows."""

import json
import logging

from app.tools.registry import register

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "manage_workflow",
        "description": (
            "List, inspect, trigger, or create reusable workflow templates. "
            "Workflows are parameterized multi-step sequences with conditionals, "
            "approval gates, and scoped secrets. Each step runs an independent LLM call."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "trigger", "create"],
                    "description": "The action to perform.",
                },
                "id": {
                    "type": "string",
                    "description": "Workflow ID (required for get, trigger, create).",
                },
                "params": {
                    "type": "string",
                    "description": 'JSON object of parameter values for trigger, e.g. \'{"series_name": "Breaking Bad"}\'.',
                },
                "bot_id": {
                    "type": "string",
                    "description": "Bot ID to execute the workflow (overrides workflow default).",
                },
                "channel_id": {
                    "type": "string",
                    "description": "Channel ID for workflow context.",
                },
                "name": {
                    "type": "string",
                    "description": "Display name (required for create).",
                },
                "description": {
                    "type": "string",
                    "description": "Workflow description (for create).",
                },
                "steps": {
                    "type": "string",
                    "description": "JSON array of step definitions (for create).",
                },
                "defaults": {
                    "type": "string",
                    "description": "JSON object of default execution config (for create).",
                },
            },
            "required": ["action"],
        },
    },
})
async def manage_workflow(
    action: str,
    id: str | None = None,
    params: str | None = None,
    bot_id: str | None = None,
    channel_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    steps: str | None = None,
    defaults: str | None = None,
    **kwargs,
) -> str:
    import uuid

    if action == "list":
        from app.services.workflows import list_workflows
        workflows = list_workflows()
        items = []
        for w in workflows:
            items.append({
                "id": w.id,
                "name": w.name,
                "description": w.description,
                "source_type": w.source_type,
                "param_count": len(w.params or {}),
                "step_count": len(w.steps or []),
            })
        return json.dumps({"workflows": items, "count": len(items)}, indent=2)

    if action == "get":
        if not id:
            return json.dumps({"error": "id is required for get"})
        from app.services.workflows import get_workflow
        w = get_workflow(id)
        if not w:
            return json.dumps({"error": f"Workflow '{id}' not found"})
        return json.dumps({
            "id": w.id,
            "name": w.name,
            "description": w.description,
            "params": w.params,
            "secrets": w.secrets,
            "defaults": w.defaults,
            "steps": w.steps,
            "triggers": w.triggers,
            "tags": w.tags,
            "session_mode": w.session_mode,
            "source_type": w.source_type,
        }, indent=2)

    if action == "trigger":
        if not id:
            return json.dumps({"error": "id is required for trigger"})

        parsed_params = {}
        if params:
            try:
                parsed_params = json.loads(params)
            except json.JSONDecodeError:
                return json.dumps({"error": "Invalid JSON in params"})

        parsed_channel_id = None
        if channel_id:
            try:
                parsed_channel_id = uuid.UUID(channel_id)
            except ValueError:
                return json.dumps({"error": "Invalid channel_id UUID"})

        from app.services.workflow_executor import trigger_workflow
        try:
            run = await trigger_workflow(
                id,
                parsed_params,
                bot_id=bot_id,
                channel_id=parsed_channel_id,
                triggered_by="tool",
            )
        except ValueError as e:
            return json.dumps({"error": str(e)})

        return json.dumps({
            "run_id": str(run.id),
            "workflow_id": run.workflow_id,
            "status": run.status,
            "step_count": len(run.step_states),
        })

    if action == "create":
        if not id or not name:
            return json.dumps({"error": "id and name are required for create"})

        parsed_steps = []
        if steps:
            try:
                parsed_steps = json.loads(steps)
            except json.JSONDecodeError:
                return json.dumps({"error": "Invalid JSON in steps"})

        parsed_defaults = {}
        if defaults:
            try:
                parsed_defaults = json.loads(defaults)
            except json.JSONDecodeError:
                return json.dumps({"error": "Invalid JSON in defaults"})

        from app.services.workflows import create_workflow
        try:
            w = await create_workflow({
                "id": id,
                "name": name,
                "description": description,
                "steps": parsed_steps,
                "defaults": parsed_defaults,
                "source_type": "bot",
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

        return json.dumps({
            "id": w.id,
            "name": w.name,
            "created": True,
        })

    return json.dumps({"error": f"Unknown action: {action}"})
