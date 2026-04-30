from __future__ import annotations

import json

from app.agent.context import current_session_id
from app.db.engine import async_session
from app.db.models import Session
from app.services.session_plan_mode import (
    PLAN_MODE_PLANNING,
    build_session_plan_response,
    get_planning_state,
    get_session_plan_mode,
    preview_session_plan_publish,
    publish_session_plan,
    publish_session_plan_event,
    validate_plan_for_approval,
    validate_plan_for_publish,
)
from app.services.tool_error_contract import build_tool_error
from app.tools.registry import register

PLAN_CONTENT_TYPE = "application/vnd.spindrel.plan+json"


_SUCCESS_RETURN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "_envelope": {"type": "object"},
        "llm": {"type": "string"},
        "plan": {"type": "object"},
        "readiness": {"type": "object"},
        "validation": {"type": "object"},
    },
    "required": ["_envelope", "llm", "plan", "readiness", "validation"],
}

_ERROR_RETURN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "success": {"type": "boolean"},
        "error": {"type": "string"},
        "error_code": {"type": "string"},
        "error_kind": {"type": "string"},
        "retryable": {"type": "boolean"},
        "retry_after_seconds": {"type": ["integer", "null"]},
        "fallback": {"type": ["string", "null"]},
    },
    "required": ["success", "error", "error_code", "error_kind", "retryable", "fallback"],
}


def _tool_error_result(
    message: str,
    *,
    error_code: str,
    error_kind: str,
    fallback: str,
) -> str:
    return json.dumps(
        build_tool_error(
            message=message,
            error_code=error_code,
            error_kind=error_kind,
            retryable=False,
            fallback=fallback,
            tool_name="publish_plan",
        )
    )

_SCHEMA = {
    "type": "function",
    "function": {
        "name": "publish_plan",
        "description": (
            "Create or revise the current session plan and publish it into the chat feed. "
            "Use this only while the session is already in plan mode, after you have enough "
            "information to propose a concrete plan."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "scope": {"type": "string"},
                "key_changes": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                "interfaces": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                "assumptions": {"type": "array", "items": {"type": "string"}},
                "assumptions_and_defaults": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                "open_questions": {"type": "array", "items": {"type": "string"}},
                "acceptance_criteria": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                "test_plan": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                "risks": {"type": "array", "items": {"type": "string"}},
                "outcome": {"type": "string"},
                "steps": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "done", "blocked"],
                            },
                            "note": {"type": "string"},
                        },
                        "required": ["label"],
                    },
                },
            },
            "required": [
                "title",
                "summary",
                "scope",
                "key_changes",
                "interfaces",
                "assumptions_and_defaults",
                "test_plan",
                "acceptance_criteria",
                "steps",
            ],
        },
    },
}


@register(
    _SCHEMA,
    safety_tier="mutating",
    requires_bot_context=True,
    requires_channel_context=True,
    returns={"oneOf": [_SUCCESS_RETURN_SCHEMA, _ERROR_RETURN_SCHEMA]},
)
async def publish_plan(
    title: str,
    summary: str,
    scope: str,
    steps: list[dict],
    key_changes: list[str] | None = None,
    interfaces: list[str] | None = None,
    assumptions: list[str] | None = None,
    assumptions_and_defaults: list[str] | None = None,
    open_questions: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
    test_plan: list[str] | None = None,
    risks: list[str] | None = None,
    outcome: str | None = None,
) -> str:
    session_id = current_session_id.get()
    if not session_id:
        return _tool_error_result(
            "publish_plan requires an active session context.",
            error_code="publish_plan_session_missing",
            error_kind="config_missing",
            fallback="Start or attach to a channel-backed session before calling publish_plan.",
        )

    async with async_session() as db:
        session = await db.get(Session, session_id)
        if session is None:
            return _tool_error_result(
                "Session not found.",
                error_code="publish_plan_session_not_found",
                error_kind="not_found",
                fallback="Refresh the current session and retry publish_plan only for an existing session.",
            )
        if get_session_plan_mode(session) != PLAN_MODE_PLANNING:
            return _tool_error_result(
                "publish_plan can only be used while the session is in planning mode.",
                error_code="publish_plan_wrong_mode",
                error_kind="conflict",
                fallback="Enter or resume plan mode before publishing a plan revision.",
            )

        readiness = validate_plan_for_publish(
            session,
            assumptions=assumptions,
            assumptions_and_defaults=assumptions_and_defaults,
            open_questions=open_questions,
        )
        if not readiness["ok"]:
            messages = "; ".join(issue["message"] for issue in readiness["issues"])
            return _tool_error_result(
                messages or "Plan is not ready to publish.",
                error_code="publish_plan_readiness_failed",
                error_kind="validation",
                fallback="Answer open questions or provide explicit assumptions/defaults, then call publish_plan again.",
            )

        candidate = preview_session_plan_publish(
            session,
            title=title,
            summary=summary,
            scope=scope,
            key_changes=key_changes,
            interfaces=interfaces,
            assumptions=assumptions,
            assumptions_and_defaults=assumptions_and_defaults,
            open_questions=open_questions,
            acceptance_criteria=acceptance_criteria,
            test_plan=test_plan,
            risks=risks,
            outcome=outcome,
            steps=steps,
        )
        validation = validate_plan_for_approval(candidate, planning_state=get_planning_state(session))
        if not validation["ok"]:
            messages = "; ".join(
                issue["message"]
                for issue in validation["issues"]
                if issue.get("severity") == "error"
            )
            return _tool_error_result(
                messages or "Plan has blocking validation issues; revise before publishing.",
                error_code="publish_plan_validation_failed",
                error_kind="validation",
                fallback="Revise the rejected fields, especially concrete outcome-oriented step labels, then call publish_plan again.",
            )

        plan = publish_session_plan(
            session,
            title=title,
            summary=summary,
            scope=scope,
            key_changes=key_changes,
            interfaces=interfaces,
            assumptions=assumptions,
            assumptions_and_defaults=assumptions_and_defaults,
            open_questions=open_questions,
            acceptance_criteria=acceptance_criteria,
            test_plan=test_plan,
            risks=risks,
            outcome=outcome,
            steps=steps,
        )
        await db.commit()
        publish_session_plan_event(session, "revise")
        payload = build_session_plan_response(session, plan)

    assert payload is not None
    from app.agent.tool_dispatch import ToolResultEnvelope

    envelope = ToolResultEnvelope(
        content_type=PLAN_CONTENT_TYPE,
        body=json.dumps(payload),
        plain_body=f"Plan revision {plan.revision}: {plan.title}",
        display="inline",
        display_label="Plan",
    )
    return json.dumps(
        {
            "_envelope": envelope.compact_dict(),
            "llm": (
                f"Published plan revision {plan.revision} for {plan.title}. "
                "If validation has blocking issues, revise the plan before approval."
            ),
            "plan": payload,
            "readiness": readiness,
            "validation": payload["validation"],
        }
    )
