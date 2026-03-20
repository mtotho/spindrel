"""Docker sandbox tools — list, ensure, exec, stop, remove."""
import json

from app.agent.context import current_bot_id, current_client_id, current_session_id
from app.agent.bots import get_bot
from app.services.sandbox import (
    SandboxAccessDeniedError,
    SandboxError,
    SandboxLockedError,
    SandboxNotFoundError,
    sandbox_service,
)
from app.tools.registry import register


def _sandbox_error(msg: str, error_type: str = "error") -> str:
    return json.dumps({"error": error_type, "message": msg})


@register({
    "type": "function",
    "function": {
        "name": "list_sandbox_profiles",
        "description": (
            "List Docker sandbox environments this bot is authorized to use. "
            "Returns each profile's name, description, scope mode, and image."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
})
async def list_sandbox_profiles() -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return _sandbox_error("No bot context available.")

    try:
        bot = get_bot(bot_id)
        allowed = bot.docker_sandbox_profiles or None
        profiles = await sandbox_service.list_profiles(bot_id, allowed_profiles=allowed)
    except Exception as e:
        return _sandbox_error(str(e))

    if not profiles:
        return json.dumps({"profiles": [], "message": "No sandbox profiles available for this bot."})

    return json.dumps({"profiles": profiles})


@register({
    "type": "function",
    "function": {
        "name": "ensure_sandbox",
        "description": (
            "Ensure a Docker sandbox container is running. "
            "Creates and starts it if needed (idempotent — safe to call multiple times). "
            "Use list_sandbox_profiles to find available profile names."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "profile_name": {
                    "type": "string",
                    "description": "Sandbox profile name, e.g. 'python-scratch'",
                },
            },
            "required": ["profile_name"],
        },
    },
})
async def ensure_sandbox(profile_name: str) -> str:
    bot_id = current_bot_id.get()
    session_id = current_session_id.get()
    client_id = current_client_id.get()

    if not bot_id or not session_id:
        return _sandbox_error("No bot/session context available.")

    try:
        bot = get_bot(bot_id)
        allowed = bot.docker_sandbox_profiles or None
        instance = await sandbox_service.ensure(
            profile_name=profile_name,
            bot_id=bot_id,
            session_id=session_id,
            client_id=client_id,
            allowed_profiles=allowed,
        )
    except SandboxLockedError as e:
        return json.dumps({"error": "locked", "message": str(e)})
    except SandboxAccessDeniedError as e:
        return _sandbox_error(str(e), "access_denied")
    except SandboxNotFoundError as e:
        return _sandbox_error(str(e), "not_found")
    except SandboxError as e:
        return _sandbox_error(str(e))

    return json.dumps({
        "container_name": instance.container_name,
        "status": instance.status,
        "profile": profile_name,
    })


@register({
    "type": "function",
    "function": {
        "name": "exec_sandbox",
        "description": (
            "Run a shell command inside a sandbox container. "
            "The container is started automatically if needed. "
            "Output is capped at 64 KB. "
            "Use ensure_sandbox first if you need the container ready before running commands."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "profile_name": {
                    "type": "string",
                    "description": "Sandbox profile name, e.g. 'python-scratch'",
                },
                "command": {
                    "type": "string",
                    "description": "Shell command to run inside the container, e.g. 'python3 -c \"print(1+1)\"'",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Max seconds to wait for the command. Default: 30.",
                },
            },
            "required": ["profile_name", "command"],
        },
    },
})
async def exec_sandbox(
    profile_name: str,
    command: str,
    timeout_seconds: int | None = None,
) -> str:
    bot_id = current_bot_id.get()
    session_id = current_session_id.get()
    client_id = current_client_id.get()

    if not bot_id or not session_id:
        return _sandbox_error("No bot/session context available.")

    # Auto-ensure the container is running
    try:
        bot = get_bot(bot_id)
        allowed = bot.docker_sandbox_profiles or None
        instance = await sandbox_service.ensure(
            profile_name=profile_name,
            bot_id=bot_id,
            session_id=session_id,
            client_id=client_id,
            allowed_profiles=allowed,
        )
    except SandboxLockedError as e:
        return json.dumps({"error": "locked", "message": str(e)})
    except SandboxAccessDeniedError as e:
        return _sandbox_error(str(e), "access_denied")
    except SandboxNotFoundError as e:
        return _sandbox_error(str(e), "not_found")
    except SandboxError as e:
        return _sandbox_error(str(e))

    try:
        result = await sandbox_service.exec(instance, command, timeout=timeout_seconds)
    except SandboxLockedError as e:
        return json.dumps({"error": "locked", "message": str(e)})
    except SandboxError as e:
        return _sandbox_error(str(e))

    return json.dumps({
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "truncated": result.truncated,
        "duration_ms": result.duration_ms,
    })


@register({
    "type": "function",
    "function": {
        "name": "stop_sandbox",
        "description": (
            "Stop a running sandbox container without removing it. "
            "The container is preserved and can be restarted with ensure_sandbox."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "profile_name": {
                    "type": "string",
                    "description": "Sandbox profile name to stop.",
                },
            },
            "required": ["profile_name"],
        },
    },
})
async def stop_sandbox(profile_name: str) -> str:
    bot_id = current_bot_id.get()
    session_id = current_session_id.get()
    client_id = current_client_id.get()

    if not bot_id or not session_id:
        return _sandbox_error("No bot/session context available.")

    instance = await sandbox_service.get_instance(profile_name, bot_id, session_id, client_id)
    if instance is None:
        return _sandbox_error(f"No sandbox instance found for profile '{profile_name}'.", "not_found")

    try:
        await sandbox_service.stop(instance)
    except SandboxLockedError as e:
        return json.dumps({"error": "locked", "message": str(e)})
    except SandboxError as e:
        return _sandbox_error(str(e))

    return json.dumps({"message": f"Sandbox '{instance.container_name}' stopped."})


@register({
    "type": "function",
    "function": {
        "name": "remove_sandbox",
        "description": (
            "Stop and permanently remove a sandbox container. "
            "A new one can be created later with ensure_sandbox."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "profile_name": {
                    "type": "string",
                    "description": "Sandbox profile name to remove.",
                },
            },
            "required": ["profile_name"],
        },
    },
})
async def remove_sandbox(profile_name: str) -> str:
    bot_id = current_bot_id.get()
    session_id = current_session_id.get()
    client_id = current_client_id.get()

    if not bot_id or not session_id:
        return _sandbox_error("No bot/session context available.")

    instance = await sandbox_service.get_instance(profile_name, bot_id, session_id, client_id)
    if instance is None:
        return _sandbox_error(f"No sandbox instance found for profile '{profile_name}'.", "not_found")

    try:
        await sandbox_service.remove(instance)
    except SandboxLockedError as e:
        return json.dumps({"error": "locked", "message": str(e)})
    except SandboxError as e:
        return _sandbox_error(str(e))

    return json.dumps({"message": f"Sandbox '{instance.container_name}' removed."})
