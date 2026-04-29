"""Bot-facing tools for Attention assignments."""
from __future__ import annotations

import json
import uuid

from app.agent.context import current_bot_id
from app.db.engine import async_session
from app.domain.errors import NotFoundError, ValidationError
from app.tools.registry import register


REPORT_ATTENTION_ASSIGNMENT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "report_attention_assignment",
        "description": (
            "Report findings for an Attention Item assigned to you. Use this "
            "after investigating; do not use it to claim fixes were executed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "item_id": {"type": "string"},
                "findings": {"type": "string"},
            },
            "required": ["item_id", "findings"],
        },
    },
}


REPORT_ATTENTION_TRIAGE_BATCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "report_attention_triage_batch",
        "description": (
            "Submit one structured outcome for each Attention Item in an operator triage run. "
            "Use processed classifications for benign/noise/duplicate/expected/already_recovered/"
            "informational items. Set review_required true for real defects, unknown risk, user "
            "decisions, likely Spindrel code issues, or anything that needs human review."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "outcomes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "string"},
                            "classification": {
                                "type": "string",
                                "description": (
                                    "benign, noise, duplicate, expected, already_recovered, "
                                    "informational, needs_review, needs_fix, "
                                    "likely_spindrel_code_issue, or user_decision"
                                ),
                            },
                            "review_required": {"type": "boolean"},
                            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                            "summary": {"type": "string"},
                            "suggested_action": {"type": "string"},
                            "route": {
                                "type": "string",
                                "description": "Optional routing hint, such as developer_channel, owner_channel, automation, or acknowledge.",
                            },
                        },
                        "required": ["item_id", "classification", "review_required", "confidence", "summary"],
                    },
                },
            },
            "required": ["outcomes"],
        },
    },
}


@register(REPORT_ATTENTION_ASSIGNMENT_SCHEMA, safety_tier="mutating", requires_bot_context=True)
async def report_attention_assignment(item_id: str, findings: str) -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."})
    try:
        parsed_id = uuid.UUID(item_id)
    except (TypeError, ValueError):
        return json.dumps({"error": f"Invalid item_id: {item_id!r}"})
    async with async_session() as db:
        try:
            from app.services.workspace_attention import report_attention_assignment as report, serialize_attention_item
            item = await report(db, parsed_id, bot_id=bot_id, findings=findings)
            payload = await serialize_attention_item(db, item)
        except (NotFoundError, ValidationError) as exc:
            return json.dumps({"error": str(exc)})
    return json.dumps({"item": payload}, default=str)


@register(REPORT_ATTENTION_TRIAGE_BATCH_SCHEMA, safety_tier="mutating", requires_bot_context=True)
async def report_attention_triage_batch(outcomes: list[dict]) -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."})
    async with async_session() as db:
        try:
            from app.services.workspace_attention import report_attention_triage_batch as report, serialize_attention_items
            items = await report(db, bot_id=bot_id, outcomes=outcomes)
            payload = await serialize_attention_items(db, items)
        except (NotFoundError, ValidationError) as exc:
            return json.dumps({"error": str(exc)})
    processed = sum(1 for item in payload if (item.get("evidence") or {}).get("operator_triage", {}).get("state") == "processed")
    ready = sum(1 for item in payload if (item.get("evidence") or {}).get("operator_triage", {}).get("state") == "ready_for_review")
    return json.dumps({
        "processed": processed,
        "ready_for_review": ready,
        "items": payload,
    }, default=str)
