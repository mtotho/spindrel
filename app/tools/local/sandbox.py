"""Docker sandbox tools — list, create, exec, stop, remove."""
import json
import uuid

from app.agent.context import current_bot_id, current_session_id
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
            "List Docker sandbox profiles (container templates) this bot may use. "
            "Each profile describes an image and resource limits. "
            "Call ensure_sandbox with a profile name to start a new container from that template."
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
            "Create and start a new Docker sandbox from a profile (template). "
            "Each call provisions a separate container until the server's max concurrent limit. "
            "Returns instance_id — pass it to exec_sandbox, stop_sandbox, and remove_sandbox."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "profile_name": {
                    "type": "string",
                    "description": "Profile name from list_sandbox_profiles, e.g. 'python-scratch'.",
                },
            },
            "required": ["profile_name"],
        },
    },
})
async def ensure_sandbox(profile_name: str) -> str:
    bot_id = current_bot_id.get()
    session_id = current_session_id.get()

    if not bot_id or not session_id:
        return _sandbox_error("No bot/session context available.")

    try:
        bot = get_bot(bot_id)
        allowed = bot.docker_sandbox_profiles or None
        instance = await sandbox_service.ensure(
            profile_name=profile_name,
            bot_id=bot_id,
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
        "instance_id": str(instance.id),
        "container_name": instance.container_name,
        "status": instance.status,
        "profile": profile_name,
    })


def _parse_instance_id(raw: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(raw).strip())
    except (ValueError, TypeError, AttributeError):
        return None


@register({
    "type": "function",
    "function": {
        "name": "exec_sandbox",
        "description": (
            "Run a shell command inside an existing sandbox. "
            "Requires instance_id from ensure_sandbox. "
            "If the container was stopped, it is started automatically. "
            "Output is capped at 64 KB."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "instance_id": {
                    "type": "string",
                    "description": "UUID returned by ensure_sandbox.",
                },
                "command": {
                    "type": "string",
                    "description": "Shell command, e.g. 'python3 -c \"print(1+1)\"'",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Max seconds to wait. Default: server default (usually 30).",
                },
            },
            "required": ["instance_id", "command"],
        },
    },
})
async def exec_sandbox(
    instance_id: str,
    command: str,
    timeout_seconds: int | None = None,
) -> str:
    bot_id = current_bot_id.get()
    session_id = current_session_id.get()
    iid = _parse_instance_id(instance_id)

    if not bot_id or not session_id:
        return _sandbox_error("No bot/session context available.")
    if iid is None:
        return _sandbox_error("Invalid instance_id (expected UUID).", "invalid_argument")

    bot = get_bot(bot_id)
    allowed = bot.docker_sandbox_profiles or None
    instance = await sandbox_service.get_instance_for_bot(iid, bot_id, allowed_profiles=allowed)
    if instance is None:
        return _sandbox_error("Sandbox instance not found or not allowed for this bot.", "not_found")

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
            "Stop a sandbox container without removing it. "
            "Use exec_sandbox later to start it again, or remove_sandbox to delete it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "instance_id": {
                    "type": "string",
                    "description": "UUID from ensure_sandbox.",
                },
            },
            "required": ["instance_id"],
        },
    },
})
async def stop_sandbox(instance_id: str) -> str:
    bot_id = current_bot_id.get()
    session_id = current_session_id.get()
    iid = _parse_instance_id(instance_id)

    if not bot_id or not session_id:
        return _sandbox_error("No bot/session context available.")
    if iid is None:
        return _sandbox_error("Invalid instance_id (expected UUID).", "invalid_argument")

    bot = get_bot(bot_id)
    allowed = bot.docker_sandbox_profiles or None
    instance = await sandbox_service.get_instance_for_bot(iid, bot_id, allowed_profiles=allowed)
    if instance is None:
        return _sandbox_error("Sandbox instance not found or not allowed for this bot.", "not_found")

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
            "Stop and remove a sandbox container and delete its database record. "
            "Does not affect other instances from the same profile."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "instance_id": {
                    "type": "string",
                    "description": "UUID from ensure_sandbox.",
                },
            },
            "required": ["instance_id"],
        },
    },
})
async def remove_sandbox(instance_id: str) -> str:
    bot_id = current_bot_id.get()
    session_id = current_session_id.get()
    iid = _parse_instance_id(instance_id)

    if not bot_id or not session_id:
        return _sandbox_error("No bot/session context available.")
    if iid is None:
        return _sandbox_error("Invalid instance_id (expected UUID).", "invalid_argument")

    bot = get_bot(bot_id)
    allowed = bot.docker_sandbox_profiles or None
    instance = await sandbox_service.get_instance_for_bot(iid, bot_id, allowed_profiles=allowed)
    if instance is None:
        return _sandbox_error("Sandbox instance not found or not allowed for this bot.", "not_found")

    name = instance.container_name
    try:
        await sandbox_service.remove(instance)
    except SandboxLockedError as e:
        return json.dumps({"error": "locked", "message": str(e)})
    except SandboxError as e:
        return _sandbox_error(str(e))

    return json.dumps({"message": f"Sandbox '{name}' removed."})
