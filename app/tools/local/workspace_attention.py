"""Bot-facing tools for Attention assignments."""
from __future__ import annotations

import json
import uuid

from app.agent.context import (
    current_bot_id,
    current_channel_id,
    current_correlation_id,
    current_issue_reporting_enabled,
    current_run_origin,
    current_session_id,
    current_task_id,
)
from app.db.engine import async_session
from app.domain.errors import NotFoundError, ValidationError
from app.tools.registry import register


def _created_work_pack_result(
    *,
    work_packs: list[dict],
    project_id: str | None,
    channel_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
) -> dict:
    launchable = [
        pack for pack in work_packs
        if pack.get("status") == "proposed" and pack.get("launch_prompt")
    ]
    needs_info = [pack for pack in work_packs if pack.get("status") == "needs_info"]
    pack_summaries = []
    for pack in work_packs:
        project_url = (
            f"/admin/projects/{pack['project_id']}#Runs"
            if pack.get("project_id")
            else None
        )
        channel_url = (
            f"/channels/{pack['channel_id']}"
            if pack.get("channel_id")
            else None
        )
        pack_summaries.append({
            "id": pack.get("id"),
            "title": pack.get("title"),
            "status": pack.get("status"),
            "category": pack.get("category"),
            "confidence": pack.get("confidence"),
            "launchable": bool(pack.get("launch_prompt")) and pack.get("status") == "proposed",
            "project_id": pack.get("project_id"),
            "project_name": pack.get("project_name"),
            "channel_id": pack.get("channel_id"),
            "channel_name": pack.get("channel_name"),
            "source_item_ids": pack.get("source_item_ids") or [],
            "links": {
                "project_runs": project_url,
                "channel": channel_url,
            },
        })

    links = {}
    if project_id:
        links["project_runs"] = f"/admin/projects/{project_id}#Runs"
        links["project"] = f"/admin/projects/{project_id}"
    if channel_id:
        links["channel"] = f"/channels/{channel_id}"
        if session_id:
            links["source_session"] = f"/channels/{channel_id}/session/{session_id}?surface=channel"

    return {
        "ok": True,
        "message": (
            f"Created {len(work_packs)} issue work pack"
            f"{'' if len(work_packs) == 1 else 's'}: "
            f"{len(launchable)} launchable, {len(needs_info)} needs-info."
        ),
        "count": len(work_packs),
        "launchable_count": len(launchable),
        "needs_info_count": len(needs_info),
        "created_work_packs": pack_summaries,
        "links": links,
        "next_actions": [
            "Review launchable proposed packs on the Project Runs page.",
            "Launch accepted code packs as Project coding runs.",
            "Resolve needs-info packs before launch.",
        ],
        "work_packs": work_packs,
    }


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


REPORT_ISSUE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "report_issue",
        "description": (
            "Create or refresh a human-visible issue discovered during an enabled scheduled task "
            "or heartbeat. Use only for durable blockers, missing permissions, recurring system/tool "
            "failures, setup problems, or user decisions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short issue title."},
                "summary": {"type": "string", "description": "What happened and why it matters."},
                "category": {
                    "type": "string",
                    "enum": [
                        "needs_review",
                        "needs_fix",
                        "blocked",
                        "missing_permission",
                        "system_issue",
                        "setup_issue",
                        "user_decision",
                    ],
                },
                "suggested_action": {"type": "string", "description": "The next useful human action."},
                "severity": {"type": "string", "enum": ["info", "warning", "error", "critical"]},
                "target": {
                    "type": "object",
                    "description": "Optional explicit target. Defaults to the current channel when present.",
                    "properties": {
                        "kind": {"type": "string", "enum": ["channel", "bot", "widget", "system"]},
                        "id": {"type": "string"},
                    },
                },
                "dedupe": {"type": "string", "description": "Stable key for this issue if known."},
                "evidence": {
                    "type": "object",
                    "description": (
                        "Optional structured evidence. If reporting a tool/system pattern, include "
                        "tool_name, error_kind, and error/message so matching automatic alerts can fold in."
                    ),
                    "additionalProperties": True,
                },
            },
            "required": ["title", "summary", "category"],
        },
    },
}


PUBLISH_ISSUE_INTAKE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "publish_issue_intake",
        "description": (
            "Publish a user-requested conversational issue note into Mission Control Review. "
            "Use this only when the user asks to save/add/report an issue, or after you clarify "
            "that they want the rough note captured for later triage."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "observed_behavior": {"type": "string"},
                "expected_behavior": {"type": "string"},
                "steps": {"type": "array", "items": {"type": "string"}},
                "severity": {"type": "string", "enum": ["info", "warning", "error", "critical"]},
                "category_hint": {
                    "type": "string",
                    "enum": ["bug", "regression", "quality", "idea", "planning", "feature", "test_failure", "config_issue", "environment_issue", "user_decision", "other"],
                },
                "project_hint": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "summary"],
        },
    },
}


LIST_ISSUE_INTAKE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_issue_intake",
        "description": (
            "Read pending conversational issue intake and active issue work packs. "
            "Use this before discussing a sweep/grouping pass, or when the user asks "
            "what rough notes, ideas, or work packs are currently waiting."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["current_channel", "workspace"],
                    "description": "current_channel lists this channel's intake. workspace lists visible workspace issue intake.",
                },
                "include_work_packs": {
                    "type": "boolean",
                    "description": "Include proposed and needs-info work packs alongside raw intake.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of pending intake items and work packs to return. Defaults to 25, max 100.",
                },
            },
        },
    },
}


CREATE_ISSUE_WORK_PACKS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "create_issue_work_packs",
        "description": (
            "Create proposed issue work packs from the current planning conversation. "
            "Use this after the user asks you to turn a plan, rough issue list, or multi-part track "
            "into launchable Project work units. This does not launch Project coding runs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Optional Project id for all packs. Defaults to the current channel's Project.",
                },
                "triage_receipt": {
                    "type": "object",
                    "description": "Audit receipt for this grouping pass: what was grouped, why, launch readiness, follow-up questions, and excluded/not-code items.",
                    "properties": {
                        "summary": {"type": "string"},
                        "grouping_rationale": {"type": "string"},
                        "launch_readiness": {"type": "string"},
                        "follow_up_questions": {"type": "array", "items": {"type": "string"}},
                        "excluded_items": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "packs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "summary": {"type": "string"},
                            "category": {
                                "type": "string",
                                "enum": ["code_bug", "test_failure", "config_issue", "environment_issue", "user_decision", "not_code_work", "needs_info", "other"],
                            },
                            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                            "source_item_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Optional existing issue-intake/Attention item ids. If omitted, Spindrel creates backing conversation intake items.",
                            },
                            "launch_prompt": {
                                "type": "string",
                                "description": "Prompt to use later when this pack is launched as a Project coding run.",
                            },
                            "rationale": {"type": "string"},
                            "conversation_summary": {"type": "string"},
                            "project_id": {
                                "type": "string",
                                "description": "Optional per-pack Project id override.",
                            },
                            "channel_id": {
                                "type": "string",
                                "description": "Optional per-pack channel id override.",
                            },
                            "target_project_hint": {"type": "string"},
                            "target_channel_hint": {"type": "string"},
                            "non_code_reason": {"type": "string"},
                            "tags": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["title", "summary", "category", "confidence"],
                    },
                },
            },
            "required": ["packs"],
        },
    },
}


REPORT_ISSUE_WORK_PACKS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "report_issue_work_packs",
        "description": (
            "Submit grouped issue work packs during an issue-intake triage run. "
            "Use one pack per discrete implementation or follow-up unit; non-code work should be categorized accordingly."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "packs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "summary": {"type": "string"},
                            "category": {
                                "type": "string",
                                "enum": ["code_bug", "test_failure", "config_issue", "environment_issue", "user_decision", "not_code_work", "needs_info", "other"],
                            },
                            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                            "source_item_ids": {"type": "array", "items": {"type": "string"}},
                            "launch_prompt": {"type": "string"},
                            "rationale": {"type": "string"},
                            "target_project_hint": {"type": "string"},
                            "target_channel_hint": {"type": "string"},
                            "non_code_reason": {"type": "string"},
                        },
                        "required": ["title", "summary", "category", "confidence", "source_item_ids"],
                    },
                },
                "item_outcomes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "string"},
                            "disposition": {"type": "string", "enum": ["packed", "dismissed", "needs_info"]},
                            "summary": {"type": "string"},
                        },
                        "required": ["item_id", "disposition"],
                    },
                },
                "triage_receipt": {
                    "type": "object",
                    "description": "Audit receipt for this triage run: what was grouped, why, launch readiness, follow-up questions, and excluded/not-code items.",
                    "properties": {
                        "summary": {"type": "string"},
                        "grouping_rationale": {"type": "string"},
                        "launch_readiness": {"type": "string"},
                        "follow_up_questions": {"type": "array", "items": {"type": "string"}},
                        "excluded_items": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "required": ["packs"],
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


@register(PUBLISH_ISSUE_INTAKE_SCHEMA, safety_tier="mutating", requires_bot_context=True, requires_channel_context=True)
async def publish_issue_intake(
    title: str,
    summary: str,
    observed_behavior: str | None = None,
    expected_behavior: str | None = None,
    steps: list[str] | None = None,
    severity: str = "warning",
    category_hint: str = "bug",
    project_hint: str | None = None,
    tags: list[str] | None = None,
) -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."})
    async with async_session() as db:
        try:
            from app.services.workspace_attention import publish_issue_intake as publish, serialize_attention_item
            item = await publish(
                db,
                bot_id=bot_id,
                channel_id=current_channel_id.get(),
                title=title,
                summary=summary,
                observed_behavior=observed_behavior,
                expected_behavior=expected_behavior,
                steps=steps or [],
                severity=severity,
                category_hint=category_hint,
                project_hint=project_hint,
                tags=tags or [],
                latest_correlation_id=current_correlation_id.get(),
            )
            payload = await serialize_attention_item(db, item)
        except (NotFoundError, ValidationError) as exc:
            return json.dumps({"error": str(exc)})
    channel_id = current_channel_id.get()
    item_summary = {
        "id": payload.get("id"),
        "title": payload.get("title"),
        "status": payload.get("status"),
        "severity": payload.get("severity"),
        "category_hint": (payload.get("evidence") or {}).get("issue_intake", {}).get("category_hint"),
        "channel_id": payload.get("channel_id"),
        "channel_name": payload.get("channel_name"),
    }
    return json.dumps({
        "ok": True,
        "message": "Saved 1 pending issue-intake note for later triage.",
        "state": "pending_intake",
        "item_summary": item_summary,
        "links": {
            "mission_control_issues": "/hub/attention?mode=issues",
            "channel": f"/channels/{channel_id}" if channel_id else None,
        },
        "next_actions": [
            "Review pending notes in Mission Control Issue Intake.",
            "Use list_issue_intake before a later sweep/grouping conversation.",
            "Use create_issue_work_packs only when the user asks to group or create packs.",
        ],
        "item": payload,
    }, default=str)


@register(LIST_ISSUE_INTAKE_SCHEMA, safety_tier="readonly", requires_bot_context=True, requires_channel_context=True)
async def list_issue_intake(
    scope: str = "current_channel",
    include_work_packs: bool = True,
    limit: int = 25,
) -> str:
    async with async_session() as db:
        try:
            from app.services.workspace_attention import list_issue_intake_state
            payload = await list_issue_intake_state(
                db,
                channel_id=current_channel_id.get(),
                scope=scope,
                include_work_packs=include_work_packs,
                limit=limit,
            )
        except (NotFoundError, ValidationError) as exc:
            return json.dumps({"error": str(exc)})
    return json.dumps(payload, default=str)


@register(CREATE_ISSUE_WORK_PACKS_SCHEMA, safety_tier="mutating", requires_bot_context=True, requires_channel_context=True)
async def create_issue_work_packs(
    packs: list[dict],
    project_id: str | None = None,
    triage_receipt: dict | None = None,
) -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."})
    parsed_project_id = None
    if project_id:
        try:
            parsed_project_id = uuid.UUID(str(project_id))
        except (TypeError, ValueError):
            return json.dumps({"error": f"Invalid project_id: {project_id!r}"})
    async with async_session() as db:
        try:
            from app.services.workspace_attention import create_conversational_issue_work_packs as create, serialize_issue_work_pack
            rows = await create(
                db,
                bot_id=bot_id,
                channel_id=current_channel_id.get(),
                packs=packs,
                session_id=current_session_id.get(),
                task_id=current_task_id.get(),
                project_id=parsed_project_id,
                latest_correlation_id=current_correlation_id.get(),
                triage_receipt=triage_receipt,
            )
            payload = [await serialize_issue_work_pack(db, row) for row in rows]
        except (NotFoundError, ValidationError) as exc:
            return json.dumps({"error": str(exc)})
    result = _created_work_pack_result(
        work_packs=payload,
        project_id=str(parsed_project_id) if parsed_project_id else (payload[0].get("project_id") if payload else None),
        channel_id=current_channel_id.get(),
        session_id=current_session_id.get(),
    )
    return json.dumps(result, default=str)


@register(REPORT_ISSUE_WORK_PACKS_SCHEMA, safety_tier="mutating", requires_bot_context=True)
async def report_issue_work_packs(
    packs: list[dict],
    item_outcomes: list[dict] | None = None,
    triage_receipt: dict | None = None,
) -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."})
    async with async_session() as db:
        try:
            from app.services.workspace_attention import report_issue_work_packs as report, serialize_issue_work_pack
            rows = await report(
                db,
                bot_id=bot_id,
                triage_task_id=current_task_id.get(),
                packs=packs,
                item_outcomes=item_outcomes or [],
                triage_receipt=triage_receipt,
            )
            payload = [await serialize_issue_work_pack(db, row) for row in rows]
        except (NotFoundError, ValidationError) as exc:
            return json.dumps({"error": str(exc)})
    return json.dumps({"work_packs": payload, "count": len(payload)}, default=str)


@register(REPORT_ISSUE_SCHEMA, safety_tier="mutating", requires_bot_context=True)
async def report_issue(
    title: str,
    summary: str,
    category: str,
    suggested_action: str | None = None,
    severity: str = "warning",
    target: dict | None = None,
    dedupe: str | None = None,
    evidence: dict | None = None,
) -> str:
    if not current_issue_reporting_enabled.get():
        return json.dumps({"error": "Issue reporting is not enabled for this run."})
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."})
    target_kind = None
    target_id = None
    if isinstance(target, dict):
        target_kind = target.get("kind")
        target_id = target.get("id")
    async with async_session() as db:
        try:
            from app.services.workspace_attention import report_bot_issue, serialize_attention_item
            item = await report_bot_issue(
                db,
                bot_id=bot_id,
                channel_id=current_channel_id.get(),
                title=title,
                summary=summary,
                category=category,
                suggested_action=suggested_action,
                severity=severity,
                target_kind=target_kind,
                target_id=target_id,
                dedupe_key=dedupe,
                evidence=evidence or {},
                task_id=current_task_id.get(),
                run_origin=current_run_origin.get(),
                latest_correlation_id=current_correlation_id.get(),
            )
            payload = await serialize_attention_item(db, item)
        except (NotFoundError, ValidationError) as exc:
            return json.dumps({"error": str(exc)})
    return json.dumps({"item": payload}, default=str)
