from __future__ import annotations

import json

from app.agent.context import current_session_id
from app.db.engine import async_session
from app.db.models import Session
from app.services.session_plan_mode import (
    build_session_plan_response,
    publish_session_plan_event,
    request_plan_replan as request_plan_replan_service,
)
from app.tools.registry import register

PLAN_CONTENT_TYPE = "application/vnd.spindrel.plan+json"

_SCHEMA = {
    "type": "function",
    "function": {
        "name": "request_plan_replan",
        "description": (
            "Stop execution and return the session to planning when the accepted plan is stale. "
            "Use this during plan execution instead of continuing around the plan."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "reason": {"type": "string"},
                "affected_step_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "evidence": {"type": "string"},
                "revision": {"type": "integer"},
            },
            "required": ["reason"],
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
        },
        "required": ["_envelope", "llm", "plan"],
    },
)
async def request_plan_replan(
    reason: str,
    affected_step_ids: list[str] | None = None,
    evidence: str | None = None,
    revision: int | None = None,
) -> str:
    session_id = current_session_id.get()
    if not session_id:
        raise RuntimeError("request_plan_replan requires an active session context.")

    async with async_session() as db:
        session = await db.get(Session, session_id)
        if session is None:
            raise RuntimeError("Session not found.")
        plan = request_plan_replan_service(
            session,
            reason=reason,
            affected_step_ids=affected_step_ids,
            evidence=evidence,
            revision=revision,
        )
        await db.commit()
        publish_session_plan_event(session, "replan")
        payload = build_session_plan_response(session, plan)

    from app.agent.tool_dispatch import ToolResultEnvelope

    envelope = ToolResultEnvelope(
        content_type=PLAN_CONTENT_TYPE,
        body=json.dumps(payload),
        plain_body=f"Replan requested for revision {plan.revision}: {plan.title}",
        display="inline",
        display_label="Plan",
    )
    return json.dumps(
        {
            "_envelope": envelope.compact_dict(),
            "llm": "Returned the session to planning. Publish a revised plan before continuing execution.",
            "plan": payload,
        }
    )
