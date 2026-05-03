"""Local tools for per-session execution environment operations."""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.agent.context import current_channel_id, current_session_id
from app.tools.registry import register


def _tool_error(error: str, error_code: str, *, retryable: bool = False, error_kind: str = "validation") -> str:
    return json.dumps({
        "ok": False,
        "status": "blocked",
        "error": error,
        "error_code": error_code,
        "error_kind": error_kind,
        "retryable": retryable,
    }, ensure_ascii=False)


async def _resolve_session_context(db, session_id: str | None = None):
    from app.db.models import Channel, Project, ProjectInstance, Session

    resolved_session_id = uuid.UUID(str(session_id or current_session_id.get())) if (session_id or current_session_id.get()) else None
    if resolved_session_id is None:
        raise ValueError("session_id is required outside a session context")
    session = await db.get(Session, resolved_session_id)
    if session is None:
        raise ValueError("session not found")
    channel = await db.get(Channel, session.channel_id) if session.channel_id else None
    if channel is None and current_channel_id.get():
        channel = await db.get(Channel, current_channel_id.get())
    project = await db.get(Project, channel.project_id) if channel is not None and channel.project_id else None
    project_instance = await db.get(ProjectInstance, session.project_instance_id) if session.project_instance_id else None
    return session, project, project_instance


@register({
    "type": "function",
    "function": {
        "name": "get_session_execution_environment",
        "description": (
            "Inspect the current or specified session execution environment: cwd/worktree, private Docker daemon, "
            "runtime env, TTL, pin state, and troubleshooting checks."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Optional Session UUID. Defaults to the current session."},
                "doctor": {"type": "boolean", "description": "Include doctor checks and next actions. Defaults false."},
            },
        },
    },
}, safety_tier="readonly", requires_channel_context=False, returns={"type": "object"})
async def get_session_execution_environment(session_id: str | None = None, doctor: bool = False) -> str:
    try:
        from app.db.engine import async_session
        from app.services.session_execution_environments import (
            doctor_session_execution_environment,
            get_session_execution_environment as get_env,
            session_execution_environment_out,
        )

        async with async_session() as db:
            session, _project, _project_instance = await _resolve_session_context(db, session_id)
            if doctor:
                payload = await doctor_session_execution_environment(db, session.id)
            else:
                env = await get_env(db, session.id)
                payload = {"ok": True, "environment": session_execution_environment_out(env, session_id=session.id)}
        return json.dumps(payload, ensure_ascii=False, default=str)
    except Exception as exc:
        return _tool_error(str(exc), "session_environment_inspect_failed")


@register({
    "type": "function",
    "function": {
        "name": "manage_session_execution_environment",
        "description": (
            "Manage the current or specified session execution environment. Actions: status, doctor, ensure_isolated, "
            "start, stop, restart, pin, unpin, cleanup. Stop preserves the worktree and Docker volume; cleanup is destructive."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "doctor", "ensure_isolated", "start", "stop", "restart", "pin", "unpin", "cleanup"],
                },
                "session_id": {"type": "string", "description": "Optional Session UUID. Defaults to the current session."},
                "ttl_seconds": {"type": "integer", "description": "TTL to apply when creating or unpinning an environment."},
            },
            "required": ["action"],
        },
    },
}, safety_tier="control_plane", requires_channel_context=False, returns={"type": "object"})
async def manage_session_execution_environment(
    action: str,
    session_id: str | None = None,
    ttl_seconds: int | None = None,
) -> str:
    try:
        from app.db.engine import async_session
        from app.services.session_execution_environments import manage_session_execution_environment as manage_env

        async with async_session() as db:
            session, project, project_instance = await _resolve_session_context(db, session_id)
            payload = await manage_env(
                db,
                session.id,
                action=action,
                project=project,
                project_instance=project_instance,
                ttl_seconds=ttl_seconds,
            )
        return json.dumps(payload, ensure_ascii=False, default=str)
    except Exception as exc:
        return _tool_error(str(exc), "session_environment_manage_failed", error_kind="execution", retryable=True)
