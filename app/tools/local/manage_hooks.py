"""Local tool: manage_hooks — bot-configurable lifecycle hooks CRUD."""
import json
import logging
import uuid as _uuid

from app.agent.context import current_bot_id
from app.services.bot_hooks import VALID_TRIGGERS
from app.tools.registry import register

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "manage_hooks",
        "description": (
            "Manage lifecycle hooks that run shell commands automatically. "
            "Hooks fire before/after file access or command execution matching a path pattern. "
            "Use cases: git pull before reading a repo, git commit+push after writing, "
            "cleanup after exec."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "create", "update", "delete"],
                    "description": "CRUD action.",
                },
                "hook_id": {
                    "type": "string",
                    "description": "Hook UUID (required for update/delete).",
                },
                "name": {
                    "type": "string",
                    "description": "Human-readable name, e.g. 'vault-sync-pull'.",
                },
                "trigger": {
                    "type": "string",
                    "enum": ["before_access", "after_write", "after_exec"],
                    "description": (
                        "When to fire: before_access (before read/write/exec on path), "
                        "after_write (after file mutation), after_exec (after command execution)."
                    ),
                },
                "conditions": {
                    "type": "object",
                    "description": (
                        "Matching criteria. For path-based triggers: "
                        '{\"path\": \"/workspace/repos/myrepo/**\"}'
                    ),
                },
                "command": {
                    "type": "string",
                    "description": "Shell command to run, e.g. 'cd /workspace/repos/myrepo && git pull'.",
                },
                "cooldown_seconds": {
                    "type": "integer",
                    "description": "Minimum seconds between firings (default: 60).",
                },
                "on_failure": {
                    "type": "string",
                    "enum": ["block", "warn"],
                    "description": (
                        "block = abort triggering operation on failure; "
                        "warn = log and continue. Default: block for before_access, warn for after_*."
                    ),
                },
                "enabled": {
                    "type": "boolean",
                    "description": "Whether the hook is active (default: true).",
                },
            },
            "required": ["action"],
        },
    },
}, safety_tier="mutating")
async def manage_hooks(
    action: str,
    hook_id: str | None = None,
    name: str | None = None,
    trigger: str | None = None,
    conditions: dict | None = None,
    command: str | None = None,
    cooldown_seconds: int | None = None,
    on_failure: str | None = None,
    enabled: bool | None = None,
) -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."}, ensure_ascii=False)

    from app.services.bot_hooks import create_hook, update_hook, delete_hook, list_hooks

    if action == "list":
        hooks = await list_hooks(bot_id)
        return json.dumps({"hooks": [
            {
                "id": str(h.id),
                "name": h.name,
                "trigger": h.trigger,
                "conditions": h.conditions,
                "command": h.command,
                "cooldown_seconds": h.cooldown_seconds,
                "on_failure": h.on_failure,
                "enabled": h.enabled,
            }
            for h in hooks
        ]}, ensure_ascii=False)

    elif action == "create":
        if not trigger or not command:
            return json.dumps({"error": "trigger and command are required for create."}, ensure_ascii=False)
        if trigger not in VALID_TRIGGERS:
            return json.dumps({"error": f"Invalid trigger: {trigger}. Valid: {sorted(VALID_TRIGGERS)}"}, ensure_ascii=False)
        hook_name = name or f"{trigger}-hook"
        data = {
            "name": hook_name,
            "trigger": trigger,
            "conditions": conditions or {},
            "command": command,
        }
        if cooldown_seconds is not None:
            data["cooldown_seconds"] = cooldown_seconds
        if on_failure is not None:
            data["on_failure"] = on_failure
        if enabled is not None:
            data["enabled"] = enabled
        hook = await create_hook(bot_id, data)
        return json.dumps({"ok": True, "id": str(hook.id), "name": hook_name}, ensure_ascii=False)

    elif action == "update":
        if not hook_id:
            return json.dumps({"error": "hook_id is required for update."}, ensure_ascii=False)
        data: dict = {}
        if name is not None:
            data["name"] = name
        if trigger is not None:
            if trigger not in VALID_TRIGGERS:
                return json.dumps({"error": f"Invalid trigger: {trigger}"}, ensure_ascii=False)
            data["trigger"] = trigger
        if conditions is not None:
            data["conditions"] = conditions
        if command is not None:
            data["command"] = command
        if cooldown_seconds is not None:
            data["cooldown_seconds"] = cooldown_seconds
        if on_failure is not None:
            data["on_failure"] = on_failure
        if enabled is not None:
            data["enabled"] = enabled
        hook = await update_hook(_uuid.UUID(hook_id), bot_id, data)
        if not hook:
            return json.dumps({"error": "Hook not found or not owned by this bot."}, ensure_ascii=False)
        return json.dumps({"ok": True, "id": str(hook.id)}, ensure_ascii=False)

    elif action == "delete":
        if not hook_id:
            return json.dumps({"error": "hook_id is required for delete."}, ensure_ascii=False)
        deleted = await delete_hook(_uuid.UUID(hook_id), bot_id)
        if not deleted:
            return json.dumps({"error": "Hook not found or not owned by this bot."}, ensure_ascii=False)
        return json.dumps({"ok": True, "deleted": True}, ensure_ascii=False)

    return json.dumps({"error": f"Unknown action: {action}"}, ensure_ascii=False)
