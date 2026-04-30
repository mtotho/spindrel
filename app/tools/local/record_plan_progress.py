from __future__ import annotations

import json
import logging
import re
import uuid

from app.agent.context import current_correlation_id, current_session_id, current_turn_id
from app.db.engine import async_session
from app.db.models import Session, ToolCall
from app.services.session_plan_mode import (
    build_session_plan_response,
    load_session_plan,
    publish_session_plan_event,
    record_plan_progress_outcome,
)
from app.services.tool_error_contract import build_tool_error
from app.tools.registry import register
from sqlalchemy import select

PLAN_CONTENT_TYPE = "application/vnd.spindrel.plan+json"
logger = logging.getLogger(__name__)

_VERIFICATION_CLAIM_RE = re.compile(
    r"\b(verified|verify|verification|readback|read\s+back|contains\s+the\s+exact|exact\s+content)\b",
    re.IGNORECASE,
)
_READBACK_OPERATIONS = {"read", "cat", "show"}

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


def _claims_step_verification(*, outcome: str, summary: str, status_note: str | None) -> bool:
    if outcome != "step_done":
        return False
    text = " ".join(part for part in (summary, status_note or "") if part)
    return bool(_VERIFICATION_CLAIM_RE.search(text))


def _path_matches_evidence(arguments: dict, evidence: str | None) -> bool:
    if not evidence:
        return True
    evidence_text = str(evidence).strip()
    if not evidence_text:
        return True
    paths = [
        str(arguments.get(key) or "").strip()
        for key in ("path", "target_path", "source_path")
    ]
    return any(path and (path == evidence_text or path.endswith(evidence_text)) for path in paths)


def _tool_call_is_readback(tool: ToolCall, *, evidence: str | None) -> bool:
    if tool.status != "done" or tool.error:
        return False
    arguments = tool.arguments if isinstance(tool.arguments, dict) else {}
    operation = str(arguments.get("operation") or arguments.get("action") or "").strip().lower()
    if tool.tool_name == "file":
        return operation in _READBACK_OPERATIONS and _path_matches_evidence(arguments, evidence)
    if re.search(r"(read|verify|check|inspect|test)", tool.tool_name, flags=re.IGNORECASE):
        return _path_matches_evidence(arguments, evidence)
    return False


async def _turn_has_successful_readback(
    db,
    *,
    session_id: uuid.UUID,
    correlation_id: uuid.UUID | None,
    evidence: str | None,
) -> bool:
    if correlation_id is None:
        return False
    result = await db.execute(
        select(ToolCall)
        .where(
            ToolCall.session_id == session_id,
            ToolCall.correlation_id == correlation_id,
            ToolCall.tool_name != "record_plan_progress",
        )
        .order_by(ToolCall.created_at.asc())
    )
    return any(_tool_call_is_readback(tool, evidence=evidence) for tool in result.scalars().all())


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
        if _claims_step_verification(outcome=outcome, summary=summary, status_note=status_note):
            has_readback = await _turn_has_successful_readback(
                db,
                session_id=session_id,
                correlation_id=correlation_id,
                evidence=evidence,
            )
            if not has_readback:
                return json.dumps(
                    build_tool_error(
                        message=(
                            "step_done claims verification/readback succeeded, but this turn has no successful "
                            "read or verification tool result for the evidence path."
                        ),
                        error_code="plan_progress_verification_missing",
                        error_kind="validation",
                        retryable=False,
                        fallback=(
                            "Use the requested read/check tool for the evidence path, confirm the result, "
                            "then retry record_plan_progress with step_done."
                        ),
                        tool_name="record_plan_progress",
                    )
                )
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
