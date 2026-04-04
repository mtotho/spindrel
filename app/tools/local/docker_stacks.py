"""Local tool: manage_docker_stack — create, start, stop, destroy, and inspect Docker Compose stacks."""

import json
import logging

from app.tools.registry import register

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "manage_docker_stack",
        "description": (
            "Manage Docker Compose stacks for multi-container services (databases, caches, APIs). "
            "Actions: list, create, start, stop, restart, destroy, status, logs, exec, update. "
            "Stacks are isolated per-bot with resource limits enforced. "
            "Services are reachable by DNS name from the workspace container (e.g., postgres:5432)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "create", "start", "stop", "restart", "destroy", "status", "logs", "exec", "update"],
                    "description": (
                        "list=all stacks, create=new stack (needs name + compose_definition), "
                        "start/stop/restart/destroy=lifecycle (needs stack_id), "
                        "status=live container info, logs=container logs, "
                        "exec=run command in service (needs stack_id + service + command), "
                        "update=change compose definition (stack must be stopped)."
                    ),
                },
                "stack_id": {
                    "type": "string",
                    "description": "Stack ID (UUID). Required for start, stop, restart, destroy, status, logs, exec, update.",
                },
                "name": {
                    "type": "string",
                    "description": "Human-readable stack name (required for create).",
                },
                "description": {
                    "type": "string",
                    "description": "Optional stack description (for create).",
                },
                "compose_definition": {
                    "type": "string",
                    "description": "Docker Compose YAML content (required for create and update). Defines services, images, ports, etc.",
                },
                "service": {
                    "type": "string",
                    "description": "Service name within the stack (for logs and exec).",
                },
                "command": {
                    "type": "string",
                    "description": "Shell command to execute (for exec action).",
                },
                "tail": {
                    "type": "integer",
                    "description": "Number of log lines to retrieve (for logs action, default 100).",
                },
                "keep_volumes": {
                    "type": "boolean",
                    "description": "If true, preserve data volumes on destroy (default false).",
                },
            },
            "required": ["action"],
        },
    },
})
async def manage_docker_stack(
    action: str,
    stack_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    compose_definition: str | None = None,
    service: str | None = None,
    command: str | None = None,
    tail: int | None = None,
    keep_volumes: bool = False,
    **kwargs,
) -> str:
    import uuid as uuid_mod

    from app.config import settings
    if not settings.DOCKER_STACKS_ENABLED:
        return json.dumps({"error": "Docker stacks are not enabled (DOCKER_STACKS_ENABLED=false)"})

    from app.agent.context import current_bot_id, current_channel_id
    from app.agent.bots import get_bot
    from app.services.docker_stacks import (
        stack_service, StackError, StackNotFoundError,
        StackValidationError, StackLimitError,
    )

    bot_id = current_bot_id.get() or "default"
    channel_id = current_channel_id.get()
    bot = get_bot(bot_id)

    if bot and not bot.docker_stacks.enabled:
        return json.dumps({"error": f"Docker stacks not enabled for bot '{bot_id}' (set docker_stacks.enabled: true in bot YAML)"})

    async def _get_stack(required_creator: bool = False):
        if not stack_id:
            return None, json.dumps({"error": "stack_id is required"})
        try:
            sid = uuid_mod.UUID(stack_id)
        except ValueError:
            return None, json.dumps({"error": f"Invalid stack_id UUID: {stack_id}"})
        stack = await stack_service.get_by_id(sid)
        if not stack:
            return None, json.dumps({"error": f"Stack '{stack_id}' not found"})
        if required_creator and stack.created_by_bot != bot_id:
            return None, json.dumps({"error": "Only the creating bot can perform this action"})
        return stack, None

    try:
        if action == "list":
            stacks = await stack_service.list_for_bot(bot_id, channel_id)
            items = []
            for s in stacks:
                items.append({
                    "id": str(s.id),
                    "name": s.name,
                    "description": s.description,
                    "status": s.status,
                    "created_by_bot": s.created_by_bot,
                    "project_name": s.project_name,
                    "service_count": len((s.container_ids or {})),
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                })
            return json.dumps({"stacks": items, "count": len(items)}, indent=2)

        if action == "create":
            if not name:
                return json.dumps({"error": "name is required for create"})
            if not compose_definition:
                return json.dumps({"error": "compose_definition is required for create"})

            allowed_images = bot.docker_stacks.allowed_images if bot else []
            max_stacks = bot.docker_stacks.max_stacks if bot else None

            stack = await stack_service.create(
                bot_id=bot_id,
                name=name,
                compose_definition=compose_definition,
                channel_id=channel_id,
                description=description,
                allowed_images=allowed_images or None,
                max_stacks=max_stacks,
            )
            return json.dumps({
                "id": str(stack.id),
                "name": stack.name,
                "project_name": stack.project_name,
                "status": stack.status,
                "created": True,
                "hint": "Use action=start with this stack_id to launch the services.",
            }, indent=2)

        if action == "start":
            stack, err = await _get_stack()
            if err:
                return err
            stack = await stack_service.start(stack)
            return json.dumps({
                "id": str(stack.id),
                "status": stack.status,
                "container_ids": stack.container_ids,
                "exposed_ports": stack.exposed_ports,
                "network_name": stack.network_name,
            }, indent=2)

        if action == "stop":
            stack, err = await _get_stack()
            if err:
                return err
            stack = await stack_service.stop(stack)
            return json.dumps({
                "id": str(stack.id),
                "status": stack.status,
            }, indent=2)

        if action == "restart":
            stack, err = await _get_stack()
            if err:
                return err
            stack = await stack_service.restart(stack)
            return json.dumps({
                "id": str(stack.id),
                "status": stack.status,
                "container_ids": stack.container_ids,
            }, indent=2)

        if action == "destroy":
            stack, err = await _get_stack(required_creator=True)
            if err:
                return err
            await stack_service.destroy(stack, remove_volumes=not keep_volumes)
            return json.dumps({
                "id": str(stack.id),
                "destroyed": True,
                "volumes_preserved": keep_volumes,
            }, indent=2)

        if action == "status":
            stack, err = await _get_stack()
            if err:
                return err
            services = await stack_service.get_status(stack)
            return json.dumps({
                "id": str(stack.id),
                "stack_status": stack.status,
                "services": [
                    {
                        "name": s.name,
                        "state": s.state,
                        "health": s.health,
                        "ports": s.ports,
                    }
                    for s in services
                ],
            }, indent=2)

        if action == "logs":
            stack, err = await _get_stack()
            if err:
                return err
            logs = await stack_service.get_logs(stack, service=service, tail=tail)
            return json.dumps({
                "id": str(stack.id),
                "service": service or "(all)",
                "logs": logs,
            }, indent=2)

        if action == "exec":
            stack, err = await _get_stack()
            if err:
                return err
            if not service:
                return json.dumps({"error": "service is required for exec"})
            if not command:
                return json.dumps({"error": "command is required for exec"})

            result = await stack_service.exec_in_service(stack, service, command)
            return json.dumps({
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "truncated": result.truncated,
                "duration_ms": result.duration_ms,
            }, indent=2)

        if action == "update":
            stack, err = await _get_stack(required_creator=True)
            if err:
                return err
            if not compose_definition:
                return json.dumps({"error": "compose_definition is required for update"})

            allowed_images = bot.docker_stacks.allowed_images if bot else []
            stack = await stack_service.update_definition(
                stack, compose_definition,
                allowed_images=allowed_images or None,
            )
            return json.dumps({
                "id": str(stack.id),
                "status": stack.status,
                "updated": True,
            }, indent=2)

        return json.dumps({"error": f"Unknown action: {action}"})

    except StackValidationError as e:
        return json.dumps({"error": f"Validation error: {e}"})
    except StackLimitError as e:
        return json.dumps({"error": f"Limit exceeded: {e}"})
    except StackNotFoundError as e:
        return json.dumps({"error": str(e)})
    except StackError as e:
        return json.dumps({"error": f"Stack error: {e}"})
    except Exception as e:
        logger.exception("Unexpected error in manage_docker_stack")
        return json.dumps({"error": f"Unexpected error: {e}"})
