"""Admin tool: integration management for the orchestrator bot."""
import json
import logging

from app.tools.registry import register

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "manage_integration",
        "description": (
            "Discover, configure, and control integration processes. "
            "Actions: list, get_settings, update_settings, start_process, "
            "stop_process, restart_process."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list", "get_settings", "update_settings",
                        "start_process", "stop_process", "restart_process",
                    ],
                    "description": "The action to perform.",
                },
                "integration_id": {
                    "type": "string",
                    "description": "Integration ID (required for all actions except list).",
                },
                "settings": {
                    "type": "object",
                    "description": (
                        "Key-value pairs for update_settings. "
                        "Keys are env var names (e.g. SLACK_BOT_TOKEN)."
                    ),
                },
            },
            "required": ["action"],
        },
    },
})
async def manage_integration(
    action: str,
    integration_id: str | None = None,
    settings: dict | None = None,
) -> str:
    if action == "list":
        try:
            from integrations import discover_setup_status
            integrations = discover_setup_status()
            return json.dumps([
                {
                    "id": i["id"],
                    "name": i.get("name", i["id"]),
                    "status": i.get("status", "unknown"),
                    "has_process": i.get("has_process", False),
                    "process_status": i.get("process_status", {}).get("status") if i.get("process_status") else None,
                    "env_vars": [
                        {"key": v["key"], "required": v.get("required", False), "is_set": v.get("is_set", False)}
                        for v in i.get("env_vars", [])
                    ],
                }
                for i in integrations
            ])
        except Exception as e:
            return json.dumps({"error": f"Failed to discover integrations: {e}"})

    if not integration_id:
        return json.dumps({"error": "integration_id is required for this action"})

    if action == "get_settings":
        from integrations import _iter_integration_candidates, _import_module
        from app.services.integration_settings import get_all_for_integration
        # Find setup_vars for this integration
        setup_vars = []
        for candidate, iid, is_external, source in _iter_integration_candidates():
            if iid == integration_id:
                setup_file = candidate / "setup.py"
                if setup_file.exists():
                    mod = _import_module(iid, "setup", setup_file, is_external, source)
                    setup_vars = getattr(mod, "SETUP", {}).get("env_vars", [])
                break
        all_settings = get_all_for_integration(integration_id, setup_vars)
        return json.dumps({
            "integration_id": integration_id,
            "settings": all_settings,
        })

    if action == "update_settings":
        if not settings:
            return json.dumps({"error": "settings dict is required for update_settings"})
        from integrations import _iter_integration_candidates, _import_module
        from app.services.integration_settings import update_settings as _update
        from app.db.engine import async_session
        # Find setup_vars for this integration
        setup_vars = []
        for candidate, iid, is_external, source in _iter_integration_candidates():
            if iid == integration_id:
                setup_file = candidate / "setup.py"
                if setup_file.exists():
                    mod = _import_module(iid, "setup", setup_file, is_external, source)
                    setup_vars = getattr(mod, "SETUP", {}).get("env_vars", [])
                break
        async with async_session() as db:
            await _update(integration_id, settings, setup_vars, db)
        return json.dumps({"ok": True, "message": f"Updated {len(settings)} setting(s) for '{integration_id}'"})

    if action in ("start_process", "stop_process", "restart_process"):
        from app.services.integration_processes import process_manager
        if action == "start_process":
            ok = await process_manager.start(integration_id)
            if not ok:
                return json.dumps({"error": f"Failed to start process for '{integration_id}'. Check env vars and logs."})
            return json.dumps({"ok": True, "message": f"Process started for '{integration_id}'"})
        elif action == "stop_process":
            await process_manager.stop(integration_id)
            return json.dumps({"ok": True, "message": f"Process stopped for '{integration_id}'"})
        else:
            await process_manager.restart(integration_id)
            return json.dumps({"ok": True, "message": f"Process restarted for '{integration_id}'"})

    return json.dumps({"error": f"Unknown action: {action}"})
