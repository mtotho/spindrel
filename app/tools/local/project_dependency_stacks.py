"""Project Dependency Stack tools for Docker-backed Project dependencies."""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.agent.context import current_channel_id, current_project_instance_id, current_task_id
from app.tools.registry import register


def _tool_error(error: str, error_code: str, *, retryable: bool = False, error_kind: str = "validation", **extra: Any) -> str:
    payload = {
        "ok": False,
        "status": "blocked",
        "error": error,
        "error_code": error_code,
        "error_kind": error_kind,
        "retryable": retryable,
    }
    payload.update({key: value for key, value in extra.items() if value is not None})
    return json.dumps(payload, ensure_ascii=False)


async def _resolve_project_dependencies_context(db, project_id: str | None = None, task_id: str | None = None):
    from app.db.models import Channel, Project, ProjectInstance, Task

    resolved_task_id = uuid.UUID(str(task_id or current_task_id.get())) if (task_id or current_task_id.get()) else None
    resolved_project_id = uuid.UUID(str(project_id)) if project_id else None
    task = await db.get(Task, resolved_task_id) if resolved_task_id else None
    if resolved_project_id is None and task is not None and isinstance(task.execution_config, dict):
        cfg = task.execution_config.get("project_coding_run") or task.execution_config.get("project_coding_run_review") or {}
        raw_project_id = cfg.get("project_id")
        if raw_project_id:
            resolved_project_id = uuid.UUID(str(raw_project_id))
    channel = None
    if resolved_project_id is None:
        channel_id = task.channel_id if task is not None else current_channel_id.get()
        channel = await db.get(Channel, channel_id) if channel_id else None
        if channel is not None and channel.project_id is not None:
            resolved_project_id = channel.project_id
    project = await db.get(Project, resolved_project_id) if resolved_project_id else None
    if project is None:
        raise ValueError("Project dependency stack requires a Project-bound task or channel")
    project_instance_id = getattr(task, "project_instance_id", None) if task is not None else None
    project_instance_id = project_instance_id or current_project_instance_id.get()
    project_instance = await db.get(ProjectInstance, project_instance_id) if project_instance_id else None
    return project, task, project_instance


@register({
    "type": "function",
    "function": {
        "name": "get_project_dependency_stack",
        "description": (
            "Inspect the Project Dependency Stack spec and current stack instance for this Project/task. "
            "Use this before Docker-backed databases or other dependency services."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Optional Project UUID; inferred from task/channel when omitted."},
                "task_id": {"type": "string", "description": "Optional Task UUID; inferred from the current task when omitted."},
            },
        },
    },
}, safety_tier="readonly", requires_channel_context=True, returns={"type": "object"})
async def get_project_dependency_stack(project_id: str | None = None, task_id: str | None = None) -> str:
    try:
        from app.db.engine import async_session
        from app.services.project_dependency_stacks import get_project_dependency_stack as get_stack

        async with async_session() as db:
            project, task, _project_instance = await _resolve_project_dependencies_context(db, project_id, task_id)
            scope = "task" if task is not None else "project"
            payload = await get_stack(db, project, task_id=task.id if task is not None else None, scope=scope)
        return json.dumps({"ok": True, **payload}, ensure_ascii=False)
    except Exception as exc:
        return _tool_error(str(exc), "project_dependency_stack_status_failed")


@register({
    "type": "function",
    "function": {
        "name": "manage_project_dependency_stack",
        "description": (
            "Manage the scoped Project Dependency Stack through Spindrel. "
            "Actions: prepare/reload creates or reapplies the stack from the Project compose file; "
            "restart, rebuild, stop, status, logs, exec, health, destroy operate on dependency services. "
            "Use this instead of raw docker or docker compose from a harness shell. Start app/dev servers yourself with native bash."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["prepare", "reload", "restart", "rebuild", "stop", "status", "logs", "exec", "health", "destroy"],
                },
                "project_id": {"type": "string", "description": "Optional Project UUID; inferred from task/channel when omitted."},
                "task_id": {"type": "string", "description": "Optional Task UUID; inferred from the current task when omitted."},
                "service": {"type": "string", "description": "Compose service for logs/exec."},
                "command": {"type": "string", "description": "Shell command for exec."},
                "command_name": {"type": "string", "description": "Named command from the Project dependency_stack.commands map."},
                "tail": {"type": "integer", "description": "Log lines for logs action."},
                "keep_volumes": {"type": "boolean", "description": "Preserve volumes when destroying the stack."},
            },
            "required": ["action"],
        },
    },
}, safety_tier="exec_capable", requires_channel_context=True, returns={"type": "object"})
async def manage_project_dependency_stack(
    action: str,
    project_id: str | None = None,
    task_id: str | None = None,
    service: str | None = None,
    command: str | None = None,
    command_name: str | None = None,
    tail: int | None = None,
    keep_volumes: bool = False,
) -> str:
    try:
        from app.db.engine import async_session
        from app.services.project_dependency_stacks import (
            destroy_project_dependency_stack,
            ensure_project_dependency_stack_instance,
            exec_project_dependency_stack_command,
            get_project_dependency_stack as get_stack,
            health_project_dependency_stack,
            prepare_project_dependency_stack,
            project_dependency_stack_logs,
            project_dependency_stack_status,
            restart_project_dependency_stack,
            stop_project_dependency_stack,
        )

        async with async_session() as db:
            project, task, project_instance = await _resolve_project_dependencies_context(db, project_id, task_id)
            scope = "task" if task is not None else "project"
            if action == "status":
                payload = await get_stack(db, project, task_id=task.id if task is not None else None, scope=scope)
                instance_payload = payload.get("instance")
                if not instance_payload:
                    return json.dumps({"ok": True, **payload}, ensure_ascii=False)
                runtime = await ensure_project_dependency_stack_instance(db, project, task=task, project_instance=project_instance, scope=scope)
                return json.dumps({"ok": True, "dependency_stack": await project_dependency_stack_status(db, runtime)}, ensure_ascii=False)

            runtime = await ensure_project_dependency_stack_instance(db, project, task=task, project_instance=project_instance, scope=scope)

            if action in {"prepare", "reload", "rebuild"}:
                payload = await prepare_project_dependency_stack(db, project, runtime=runtime, force_recreate=action == "rebuild")
                return json.dumps({"ok": True, "dependency_stack": payload}, ensure_ascii=False)
            if action == "restart":
                return json.dumps({"ok": True, "dependency_stack": await restart_project_dependency_stack(db, runtime)}, ensure_ascii=False)
            if action == "stop":
                return json.dumps({"ok": True, "dependency_stack": await stop_project_dependency_stack(db, runtime)}, ensure_ascii=False)
            if action == "logs":
                return json.dumps(await project_dependency_stack_logs(db, runtime, service=service, tail=tail), ensure_ascii=False)
            if action == "health":
                return json.dumps(await health_project_dependency_stack(db, runtime), ensure_ascii=False)
            if action == "destroy":
                return json.dumps({"ok": True, "dependency_stack": await destroy_project_dependency_stack(db, runtime, keep_volumes=keep_volumes)}, ensure_ascii=False)
            if action == "exec":
                named_commands = runtime.commands if isinstance(runtime.commands, dict) else {}
                resolved_command = command or (named_commands.get(command_name or "") if command_name else None)
                if not resolved_command:
                    return _tool_error("command or command_name is required for exec", "project_dependency_stack_command_required")
                resolved_service = service
                if not resolved_service:
                    return _tool_error("service is required for dependency stack exec", "project_dependency_stack_service_required")
                return json.dumps(
                    await exec_project_dependency_stack_command(db, runtime, service=resolved_service, command=resolved_command),
                    ensure_ascii=False,
                )
        return _tool_error(f"Unknown action: {action}", "project_dependency_stack_unknown_action")
    except Exception as exc:
        return _tool_error(str(exc), "project_dependency_stack_action_failed", error_kind="execution", retryable=True)
