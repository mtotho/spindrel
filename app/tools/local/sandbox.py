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
            "Each profile includes network_mode: 'none' means no outbound network; "
            "'bridge' allows internet access (e.g. git push, package installs). "
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
            "Response includes network_mode from the profile (none = no outbound network). "
            "Returns instance_id — pass it to exec_sandbox, stop_sandbox, and remove_sandbox."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "profile_name": {
                    "type": "string",
                    "description": "Profile name from list_sandbox_profiles, e.g. 'python-scratch'.",
                },
                "port_mappings": {
                    "type": "array",
                    "description": (
                        "Optional port mappings for this specific container instance. "
                        "Each entry maps a container port to a host port. "
                        "Use host_port 0 to let Docker auto-assign a free host port. "
                        "Example: [{\"container_port\": 8080, \"host_port\": 0}]"
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "container_port": {"type": "integer", "description": "Port inside the container."},
                            "host_port": {"type": "integer", "description": "Port on the host. 0 = auto-assign."},
                            "protocol": {"type": "string", "enum": ["tcp", "udp"], "description": "Default: tcp."},
                        },
                        "required": ["container_port"],
                    },
                },
            },
            "required": ["profile_name"],
        },
    },
})
async def ensure_sandbox(profile_name: str, port_mappings: list | None = None) -> str:
    bot_id = current_bot_id.get()
    session_id = current_session_id.get()

    if not bot_id or not session_id:
        return _sandbox_error("No bot/session context available.")

    try:
        bot = get_bot(bot_id)
        allowed = bot.docker_sandbox_profiles or None
        instance, resolved_port_mappings, network_mode = await sandbox_service.ensure(
            profile_name=profile_name,
            bot_id=bot_id,
            allowed_profiles=allowed,
            port_mappings=port_mappings,
        )
    except SandboxLockedError as e:
        return json.dumps({"error": "locked", "message": str(e)})
    except SandboxAccessDeniedError as e:
        return _sandbox_error(str(e), "access_denied")
    except SandboxNotFoundError as e:
        return _sandbox_error(str(e), "not_found")
    except SandboxError as e:
        return _sandbox_error(str(e))

    result: dict = {
        "instance_id": str(instance.id),
        "container_name": instance.container_name,
        "status": instance.status,
        "profile": profile_name,
        "network_mode": network_mode,
    }
    notes: list[str] = []
    if resolved_port_mappings:
        result["port_mappings"] = resolved_port_mappings
        notes.append(
            "Port mappings show host_port:container_port. "
            "Connect to the service at localhost:<host_port>."
        )
    if network_mode == "none":
        notes.append(
            "network_mode is 'none': no outbound internet in this container "
            "(git push/curl will fail unless you use a profile with network_mode bridge)."
        )
    if notes:
        result["note"] = " ".join(notes)
    return json.dumps(result)


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
            "To run Claude Code / a configured harness CLI inside this container with the same argv as "
            "harnesses.yaml, use delegate_to_harness(..., sandbox_instance_id=<this id>, working_directory="
            "'/path/inside/container'). "
            "If the container was stopped, it is started automatically. "
            "Output is capped at 64 KB. "
            "For verbose commands, use quiet flags (apt-get -qq, pip -q, npm --silent, etc.)."
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


@register({
    "type": "function",
    "function": {
        "name": "get_sandbox_info",
        "description": (
            "Get current status and port mappings for an existing sandbox instance. "
            "Useful when you need to re-check which host ports are mapped after the original "
            "ensure_sandbox call, or to verify container status."
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
async def get_sandbox_info(instance_id: str) -> str:
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

    meta = await sandbox_service.get_profile_meta(instance.profile_id)

    result: dict = {
        "instance_id": str(instance.id),
        "container_name": instance.container_name,
        "status": instance.status,
        "port_mappings": instance.port_mappings or [],
        "profile_network_mode": meta["network_mode"],
    }
    if meta.get("description"):
        result["profile_description"] = meta["description"]
    notes: list[str] = []
    if instance.port_mappings:
        notes.append(
            "Port mappings show host_port:container_port. "
            "Connect to the service at localhost:<host_port>."
        )
    notes.append(
        "profile_network_mode is the profile setting now; an existing container keeps "
        "the network it was created with until you remove it and call ensure_sandbox again."
    )
    if notes:
        result["note"] = " ".join(notes)
    return json.dumps(result)
