"""Generic execution receipt tools."""
from __future__ import annotations

import json
from typing import Any

from app.agent.context import (
    current_bot_id,
    current_channel_id,
    current_correlation_id,
    current_session_id,
    current_task_id,
)
from app.db.engine import async_session
from app.services.execution_receipts import create_execution_receipt, serialize_execution_receipt
from app.tools.registry import register


_RETURNS = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "receipt_id": {"type": "string"},
        "receipt": {"type": "object"},
        "created": {"type": "boolean"},
        "updated": {"type": "boolean"},
        "error": {"type": "string"},
    },
    "required": ["ok"],
}


@register({
    "type": "function",
    "function": {
        "name": "publish_execution_receipt",
        "description": (
            "Publish a durable execution receipt after an approval-gated or agent-important action. "
            "Use this when the action changed configuration, staged a repair, or produced an outcome "
            "that future agents and Mission Control Review should be able to audit."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "description": "Receipt family, e.g. agent_readiness, project_run, widget_authoring. Defaults agent_readiness.",
                },
                "action_type": {"type": "string", "description": "Machine-readable action kind, e.g. bot_patch."},
                "status": {
                    "type": "string",
                    "enum": ["reported", "succeeded", "failed", "blocked", "needs_review"],
                    "description": "Outcome status. Defaults succeeded.",
                },
                "summary": {"type": "string", "description": "Concise user-facing outcome summary."},
                "target": {"type": "object", "description": "Machine-readable target identifiers."},
                "before_summary": {"type": "string", "description": "What was true before the action."},
                "after_summary": {"type": "string", "description": "What changed or what is true after the action."},
                "approval_required": {"type": "boolean", "description": "Whether this action required human approval."},
                "approval_ref": {"type": "string", "description": "Approval or UI reference, when available."},
                "result": {"type": "object", "description": "Small structured result payload."},
                "rollback_hint": {"type": "string", "description": "How to undo or inspect the change."},
                "idempotency_key": {"type": "string", "description": "Stable key for retry-safe receipt updates."},
                "metadata": {"type": "object", "description": "Extra structured evidence."},
            },
            "required": ["action_type", "summary"],
        },
    },
}, safety_tier="mutating", requires_bot_context=True, returns=_RETURNS)
async def publish_execution_receipt(
    action_type: str,
    summary: str,
    scope: str = "agent_readiness",
    status: str = "succeeded",
    target: dict[str, Any] | None = None,
    before_summary: str | None = None,
    after_summary: str | None = None,
    approval_required: bool = False,
    approval_ref: str | None = None,
    result: dict[str, Any] | None = None,
    rollback_hint: str | None = None,
    idempotency_key: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"ok": False, "error": "No bot context available."}, ensure_ascii=False)

    actor = {
        "kind": "bot",
        "bot_id": bot_id,
        "session_id": str(current_session_id.get()) if current_session_id.get() else None,
        "task_id": str(current_task_id.get()) if current_task_id.get() else None,
    }
    normalized_target = dict(target or {})
    normalized_target.setdefault("bot_id", bot_id)
    if current_channel_id.get() and "channel_id" not in normalized_target:
        normalized_target["channel_id"] = str(current_channel_id.get())

    try:
        async with async_session() as db:
            receipt = await create_execution_receipt(
                db,
                scope=scope or "agent_readiness",
                action_type=action_type,
                status=status or "succeeded",
                summary=summary,
                actor=actor,
                target=normalized_target,
                before_summary=before_summary,
                after_summary=after_summary,
                approval_required=approval_required,
                approval_ref=approval_ref,
                result=result or {},
                rollback_hint=rollback_hint,
                bot_id=bot_id,
                channel_id=current_channel_id.get(),
                session_id=current_session_id.get(),
                task_id=current_task_id.get(),
                correlation_id=current_correlation_id.get(),
                idempotency_key=idempotency_key,
                metadata=metadata or {},
            )
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    payload = serialize_execution_receipt(receipt)
    created = bool(getattr(receipt, "_spindrel_created", True))
    return json.dumps(
        {
            "ok": True,
            "receipt_id": payload["id"],
            "receipt": payload,
            "created": created,
            "updated": not created,
        },
        ensure_ascii=False,
    )
