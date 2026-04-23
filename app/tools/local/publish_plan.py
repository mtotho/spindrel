from __future__ import annotations

import json

from app.agent.context import current_session_id
from app.db.engine import async_session
from app.db.models import Session
from app.services.session_plan_mode import (
    PLAN_MODE_PLANNING,
    build_session_plan_response,
    get_session_plan_mode,
    publish_session_plan,
    publish_session_plan_event,
)
from app.tools.registry import register

PLAN_CONTENT_TYPE = "application/vnd.spindrel.plan+json"

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
                "assumptions": {"type": "array", "items": {"type": "string"}},
                "open_questions": {"type": "array", "items": {"type": "string"}},
                "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                "outcome": {"type": "string"},
                "steps": {
                    "type": "array",
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
            "required": ["title", "summary", "scope", "steps"],
        },
    },
}


@register(
    _SCHEMA,
    safety_tier="mutating",
    requires_bot_context=True,
    requires_channel_context=True,
    returns={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "_envelope": {"type": "object"},
            "llm": {"type": "string"},
            "plan": {"type": "object"},
            "validation": {"type": "object"},
        },
        "required": ["_envelope", "llm", "plan", "validation"],
    },
)
async def publish_plan(
    title: str,
    summary: str,
    scope: str,
    steps: list[dict],
    assumptions: list[str] | None = None,
    open_questions: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
    outcome: str | None = None,
) -> str:
    session_id = current_session_id.get()
    if not session_id:
        raise RuntimeError("publish_plan requires an active session context.")

    async with async_session() as db:
        session = await db.get(Session, session_id)
        if session is None:
            raise RuntimeError("Session not found.")
        if get_session_plan_mode(session) != PLAN_MODE_PLANNING:
            raise RuntimeError("publish_plan can only be used while the session is in planning mode.")

        plan = publish_session_plan(
            session,
            title=title,
            summary=summary,
            scope=scope,
            assumptions=assumptions,
            open_questions=open_questions,
            acceptance_criteria=acceptance_criteria,
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
            "validation": payload["validation"],
        }
    )
