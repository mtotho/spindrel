from __future__ import annotations

import json
import logging

from app.agent.context import current_correlation_id, current_session_id, current_turn_id
from app.db.engine import async_session
from app.db.models import Session
from app.services.session_plan_mode import (
    build_session_plan_response,
    load_session_plan,
    publish_session_plan_event,
    record_plan_progress_outcome,
)
from app.tools.registry import register

PLAN_CONTENT_TYPE = "application/vnd.spindrel.plan+json"
logger = logging.getLogger(__name__)

_SCHEMA = {
    "type": "function",
    "function": {
        "name": "record_plan_progress",
        "description": (
            "Record the required end-of-turn plan outcome while executing an approved plan. "
            "Use this before ending every execution turn with progress, verification, step_done, blocked, or no_progress. "
            "Use step_done only after the step is actually complete and requested verification/readback has succeeded."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "outcome": {
                    "type": "string",
                    "enum": ["progress", "verification", "step_done", "blocked", "no_progress"],
                },
                "summary": {"type": "string"},
                "step_id": {"type": "string"},
                "evidence": {"type": "string"},
                "status_note": {"type": "string"},
            },
            "required": ["outcome", "summary"],
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
            "outcome": {"type": "object"},
            "plan": {"type": "object"},
        },
        "required": ["_envelope", "llm", "outcome", "plan"],
    },
)
async def record_plan_progress(
    outcome: str,
    summary: str,
    step_id: str | None = None,
    evidence: str | None = None,
    status_note: str | None = None,
) -> str:
    session_id = current_session_id.get()
    if not session_id:
        raise RuntimeError("record_plan_progress requires an active session context.")

    turn_id = current_turn_id.get()
    correlation_id = current_correlation_id.get()
    semantic_review: dict | None = None
    async with async_session() as db:
        session = await db.get(Session, session_id)
        if session is None:
            raise RuntimeError("Session not found.")
        outcome_record = record_plan_progress_outcome(
            session,
            outcome=outcome,
            summary=summary,
            step_id=step_id,
            evidence=evidence,
            status_note=status_note,
            turn_id=str(turn_id) if turn_id else None,
            correlation_id=str(correlation_id) if correlation_id else None,
        )
        try:
            from app.services.plan_semantic_review import auto_review_latest_plan_outcome

            semantic_review = await auto_review_latest_plan_outcome(
                db,
                session,
                correlation_id=str(correlation_id) if correlation_id else None,
            )
        except Exception:
            logger.exception("Automatic plan adherence review failed for session %s", session_id)
        await db.commit()
        publish_session_plan_event(session, "plan_progress")
        if semantic_review:
            publish_session_plan_event(session, "semantic_review")
        plan = load_session_plan(session, required=True)
        payload = build_session_plan_response(session, plan)

    assert payload is not None
    from app.agent.tool_dispatch import ToolResultEnvelope

    envelope = ToolResultEnvelope(
        content_type=PLAN_CONTENT_TYPE,
        body=json.dumps(payload),
        plain_body=f"Plan outcome recorded for {plan.title}: {outcome_record['outcome']}",
        display="inline",
        display_label="Plan",
    )
    llm_message = f"Recorded plan outcome: {outcome_record['outcome']}."
    if semantic_review:
        llm_message += f" Automatic adherence review: {semantic_review.get('verdict', 'reviewed')}."
    return json.dumps(
        {
            "_envelope": envelope.compact_dict(),
            "llm": llm_message,
            "outcome": outcome_record,
            "plan": payload,
        }
    )
