from __future__ import annotations

import json

from integrations.sdk import register_tool as register

from app.services.local_machine_control import validate_current_execution_policy

from ..bridge import bridge


@register(
    {
        "type": "function",
        "function": {
            "name": "local_status",
            "description": (
                "Show enrolled local machine targets, their connection state, and "
                "the current session lease if one exists."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    safety_tier="readonly",
    execution_policy="interactive_user",
    returns={
        "type": "object",
        "properties": {
            "targets": {"type": "array"},
            "lease": {"type": ["object", "null"]},
        },
    },
)
async def local_status() -> str:
    from app.agent.context import current_session_id
    from app.db.engine import async_session
    from app.db.models import Session
    from app.services.local_machine_control import build_session_machine_target_payload, build_targets_status

    resolution = await validate_current_execution_policy("interactive_user")
    if not resolution.allowed:
        return json.dumps({"error": "local_control_required", "message": resolution.reason}, ensure_ascii=False)

    session_id = current_session_id.get()
    if session_id is None:
        return json.dumps({"targets": build_targets_status(), "lease": None}, ensure_ascii=False)

    async with async_session() as db:
        session = await db.get(Session, session_id)
        if session is None:
            return json.dumps({"targets": build_targets_status(), "lease": None}, ensure_ascii=False)
        payload = await build_session_machine_target_payload(db, session=session)
    return json.dumps({"targets": payload["targets"], "lease": payload["lease"]}, ensure_ascii=False)


@register(
    {
        "type": "function",
        "function": {
            "name": "local_inspect_command",
            "description": (
                "Run a readonly inspection command on the leased local machine. "
                "Intended for listing files, checking git status, process info, and similar "
                "safe inspection tasks."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                },
                "required": ["command"],
            },
        },
    },
    safety_tier="readonly",
    execution_policy="live_target_lease",
    returns={
        "type": "object",
        "properties": {
            "stdout": {"type": "string"},
            "stderr": {"type": "string"},
            "exit_code": {"type": "integer"},
            "duration_ms": {"type": "integer"},
            "target_id": {"type": "string"},
        },
    },
)
async def local_inspect_command(command: str) -> str:
    resolution = await validate_current_execution_policy("live_target_lease")
    if not resolution.allowed or resolution.lease is None:
        return json.dumps({"error": "local_control_required", "message": resolution.reason}, ensure_ascii=False)
    try:
        result = await bridge.request(
            resolution.lease["target_id"],
            "inspect_command",
            {"command": command},
        )
    except Exception as exc:
        return json.dumps({"error": "local_companion_error", "message": str(exc)}, ensure_ascii=False)
    result["target_id"] = resolution.lease["target_id"]
    return json.dumps(result, ensure_ascii=False)


@register(
    {
        "type": "function",
        "function": {
            "name": "local_exec_command",
            "description": (
                "Run a shell command on the leased local machine. Requires an active "
                "session-bound machine-control lease from a live admin user."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "working_dir": {"type": "string"},
                },
                "required": ["command"],
            },
        },
    },
    safety_tier="exec_capable",
    execution_policy="live_target_lease",
    returns={
        "type": "object",
        "properties": {
            "stdout": {"type": "string"},
            "stderr": {"type": "string"},
            "exit_code": {"type": "integer"},
            "duration_ms": {"type": "integer"},
            "target_id": {"type": "string"},
        },
    },
)
async def local_exec_command(command: str, working_dir: str = "") -> str:
    resolution = await validate_current_execution_policy("live_target_lease")
    if not resolution.allowed or resolution.lease is None:
        return json.dumps({"error": "local_control_required", "message": resolution.reason}, ensure_ascii=False)
    try:
        result = await bridge.request(
            resolution.lease["target_id"],
            "exec_command",
            {"command": command, "working_dir": working_dir},
        )
    except Exception as exc:
        return json.dumps({"error": "local_companion_error", "message": str(exc)}, ensure_ascii=False)
    result["target_id"] = resolution.lease["target_id"]
    return json.dumps(result, ensure_ascii=False)
