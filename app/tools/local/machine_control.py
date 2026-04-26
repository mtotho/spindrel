from __future__ import annotations

import json

from app.agent.context import current_session_id
from app.db.engine import async_session
from app.db.models import Session
from app.services.machine_control import (
    build_session_machine_target_payload,
    build_targets_status,
    get_provider,
    get_target_by_id,
    validate_inspect_command,
    validate_current_execution_policy,
)
from app.tools.registry import register


def _components_envelope(
    *,
    plain_body: str,
    display_label: str,
    view_key: str,
    data: dict,
    refreshable: bool = False,
    refresh_interval_seconds: int | None = None,
):
    from app.agent.tool_dispatch import ToolResultEnvelope
    return ToolResultEnvelope(
        content_type="application/vnd.spindrel.components+json",
        body=json.dumps({
            "v": 1,
            "components": [
                {"type": "heading", "text": display_label, "level": 3},
            ],
        }),
        plain_body=plain_body,
        display="inline",
        display_label=display_label,
        refreshable=refreshable,
        refresh_interval_seconds=refresh_interval_seconds,
        view_key=view_key,
        data=data,
    )


def _command_payload(
    *,
    provider_id: str,
    command: str,
    working_dir: str,
    target_id: str,
    result: dict,
) -> dict:
    target = get_target_by_id(provider_id, target_id) or {}
    provider = get_provider(provider_id)
    return {
        "provider_id": provider_id,
        "provider_label": getattr(provider, "label", provider_id),
        "command": command,
        "working_dir": working_dir,
        "target_id": target_id,
        "target_label": target.get("label") or target_id,
        "target_hostname": target.get("hostname") or "",
        "target_platform": target.get("platform") or "",
        "stdout": str(result.get("stdout") or ""),
        "stderr": str(result.get("stderr") or ""),
        "exit_code": int(result.get("exit_code") or 0),
        "duration_ms": int(result.get("duration_ms") or 0),
        "truncated": bool(result.get("truncated")),
    }


@register(
    {
        "type": "function",
        "function": {
            "name": "machine_status",
            "description": (
                "Show available machine-control providers, enrolled machine targets, "
                "their connection state, and the current session lease if one exists."
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
            "_envelope": {"type": "object"},
            "llm": {"type": "string"},
            "targets": {"type": "array"},
            "lease": {"type": ["object", "null"]},
        },
        "required": ["_envelope", "llm", "targets"],
    },
)
async def machine_status() -> str:
    resolution = await validate_current_execution_policy("interactive_user")
    if not resolution.allowed:
        return json.dumps({"error": "local_control_required", "message": resolution.reason}, ensure_ascii=False)

    session_id = current_session_id.get()
    if session_id is None:
        payload = {"session_id": None, "targets": build_targets_status(), "lease": None}
    else:
        async with async_session() as db:
            session = await db.get(Session, session_id)
        if session is None:
            payload = {"session_id": str(session_id), "targets": build_targets_status(), "lease": None}
        else:
            payload = await build_session_machine_target_payload(db, session=session)
    payload["ready_target_count"] = sum(1 for target in payload["targets"] if target.get("ready"))
    payload["connected_target_count"] = payload["ready_target_count"]
    envelope = _components_envelope(
        plain_body="Machine control status",
        display_label="Machine Control",
        view_key="core.machine_target_status",
        data=payload,
        refreshable=True,
        refresh_interval_seconds=5,
    )
    return json.dumps(
        {
            "_envelope": envelope.compact_dict(),
            "llm": (
                f"{payload['connected_target_count']} connected machine target(s); "
                f"{'an active lease exists' if payload.get('lease') else 'no active session lease'}."
            ),
            **payload,
        },
        ensure_ascii=False,
    )


@register(
    {
        "type": "function",
        "function": {
            "name": "machine_inspect_command",
            "description": (
                "Run a readonly inspection command on the leased machine target. "
                "Use for safe discovery like git status, ls, ps, or environment inspection."
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
            "_envelope": {"type": "object"},
            "llm": {"type": "string"},
            "stdout": {"type": "string"},
            "stderr": {"type": "string"},
            "exit_code": {"type": "integer"},
            "duration_ms": {"type": "integer"},
        },
        "required": ["_envelope", "llm"],
    },
)
async def machine_inspect_command(command: str) -> str:
    resolution = await validate_current_execution_policy("live_target_lease")
    if not resolution.allowed or resolution.lease is None:
        return json.dumps({"error": "local_control_required", "message": resolution.reason}, ensure_ascii=False)
    try:
        validate_inspect_command(command)
    except ValueError as exc:
        return json.dumps({"error": "machine_control_error", "message": str(exc)}, ensure_ascii=False)
    lease = resolution.lease
    provider = get_provider(lease["provider_id"])
    try:
        result = await provider.inspect_command(lease["target_id"], command)
    except Exception as exc:
        return json.dumps({"error": "machine_control_error", "message": str(exc)}, ensure_ascii=False)
    payload = _command_payload(
        provider_id=lease["provider_id"],
        command=command,
        working_dir="",
        target_id=lease["target_id"],
        result=result,
    )
    envelope = _components_envelope(
        plain_body=f"Inspect command on {payload['target_label']}: {command}",
        display_label=payload["target_label"] or "Command",
        view_key="core.command_result",
        data=payload,
    )
    return json.dumps(
        {
            "_envelope": envelope.compact_dict(),
            "llm": (
                f"Ran readonly machine inspection command on {payload['target_label']} "
                f"with exit code {payload['exit_code']}."
            ),
            **payload,
        },
        ensure_ascii=False,
    )


@register(
    {
        "type": "function",
        "function": {
            "name": "machine_exec_command",
            "description": (
                "Run a shell command on the leased machine target. Requires an active "
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
            "_envelope": {"type": "object"},
            "llm": {"type": "string"},
            "stdout": {"type": "string"},
            "stderr": {"type": "string"},
            "exit_code": {"type": "integer"},
            "duration_ms": {"type": "integer"},
        },
        "required": ["_envelope", "llm"],
    },
)
async def machine_exec_command(command: str, working_dir: str = "") -> str:
    resolution = await validate_current_execution_policy("live_target_lease")
    if not resolution.allowed or resolution.lease is None:
        return json.dumps({"error": "local_control_required", "message": resolution.reason}, ensure_ascii=False)
    lease = resolution.lease
    provider = get_provider(lease["provider_id"])
    try:
        result = await provider.exec_command(lease["target_id"], command, working_dir)
    except Exception as exc:
        return json.dumps({"error": "machine_control_error", "message": str(exc)}, ensure_ascii=False)
    payload = _command_payload(
        provider_id=lease["provider_id"],
        command=command,
        working_dir=working_dir,
        target_id=lease["target_id"],
        result=result,
    )
    envelope = _components_envelope(
        plain_body=f"Machine command on {payload['target_label']}: {command}",
        display_label=payload["target_label"] or "Command",
        view_key="core.command_result",
        data=payload,
    )
    return json.dumps(
        {
            "_envelope": envelope.compact_dict(),
            "llm": (
                f"Ran machine command on {payload['target_label']} "
                f"with exit code {payload['exit_code']}."
            ),
            **payload,
        },
        ensure_ascii=False,
    )
