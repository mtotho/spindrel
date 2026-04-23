from __future__ import annotations

import copy
import json
import re
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, Session, ToolCall, TraceEvent
from app.services.judge import judge_single_case
from app.services.session_plan_mode import (
    PLAN_PROGRESS_OUTCOME_BLOCKED,
    PLAN_PROGRESS_OUTCOME_NO_PROGRESS,
    PLAN_PROGRESS_OUTCOME_PROGRESS,
    PLAN_PROGRESS_OUTCOME_STEP_DONE,
    PLAN_PROGRESS_OUTCOME_VERIFICATION,
    PLAN_SEMANTIC_REVIEW_NEEDS_REPLAN,
    PLAN_SEMANTIC_REVIEW_SUPPORTED,
    PLAN_SEMANTIC_REVIEW_UNSUPPORTED,
    PLAN_SEMANTIC_REVIEW_WEAK_SUPPORT,
    PLAN_SEMANTIC_STATUS_NEEDS_REPLAN,
    PLAN_SEMANTIC_STATUS_OK,
    PLAN_SEMANTIC_STATUS_WARNING,
    _clip_plan_context,
    _normalize_adherence,
    _utc_now_iso,
    load_session_plan,
    load_session_plan_revision,
    record_plan_semantic_review,
)
from app.tools.registry import get_tool_safety_tier

_COMMAND_KEYWORDS = ("cmd", "command", "script", "shell_command")
_PATH_KEYWORDS = ("path", "paths", "file", "files", "target_path", "source_path")
_READ_ONLY_STEP_RE = re.compile(r"\b(audit|analy[sz]e|investigate|inspect|review|read|research|gather|plan|document)\b", re.I)
_EXECUTION_STEP_RE = re.compile(r"\b(add|build|change|create|edit|fix|implement|migrate|refactor|ship|update|verify|write)\b", re.I)
_VERIFY_TOOL_RE = re.compile(r"\b(test|verify|lint|check|build|compile|typecheck)\b", re.I)
_VERIFY_COMMAND_RE = re.compile(
    r"\b(pytest|vitest|jest|bun test|npm test|pnpm test|yarn test|cargo test|go test|npx tsc|tsc --noEmit|ruff|mypy|gradle test|./gradlew test|make test|ctest)\b",
    re.I,
)
_REPLAN_EVENT_RE = re.compile(r"replan", re.I)

_JUDGE_RUBRIC = """
You are reviewing whether an execution turn actually supports the recorded plan outcome.

Return ONLY JSON with this shape:
{
  "verdict": "supported" | "weak_support" | "unsupported" | "needs_replan",
  "confidence": 0.0-1.0,
  "reason": "short evidence-based explanation",
  "recommended_action": "continue" | "repeat_step" | "review_manually" | "request_replan",
  "semantic_status": "ok" | "warning" | "needs_replan"
}

Rules:
- Judge the recorded outcome against the evidence from THIS turn only.
- Be conservative. Missing evidence should lower the verdict, not increase it.
- If the turn appears to have revealed stale-plan drift or explicitly requested replanning, prefer "needs_replan".
- If the turn shows only weak evidence for the recorded outcome, use "weak_support".
- If the recorded outcome is not justified by the evidence, use "unsupported".
""".strip()


def _parse_uuid(value: str | None) -> uuid.UUID | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return uuid.UUID(text)
    except ValueError:
        return None


def _truncate_json(value: Any, limit: int = 1500) -> str | None:
    if value is None:
        return None
    try:
        text = json.dumps(value, default=str)
    except TypeError:
        text = str(value)
    return _clip_plan_context(text, limit)


def _extract_strings(payload: Any, *, keys: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).lower()
            if lowered in keys:
                if isinstance(value, str) and value.strip():
                    values.append(value.strip())
                elif isinstance(value, list):
                    values.extend(str(item).strip() for item in value if str(item).strip())
            else:
                values.extend(_extract_strings(value, keys=keys))
    elif isinstance(payload, list):
        for item in payload:
            values.extend(_extract_strings(item, keys=keys))
    return values


def _extract_paths(arguments: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    paths: list[str] = []
    for path in _extract_strings(arguments, keys=_PATH_KEYWORDS):
        clipped = _clip_plan_context(path, 180)
        if clipped and clipped not in seen:
            seen.add(clipped)
            paths.append(clipped)
    return paths[:8]


def _extract_commands(arguments: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    commands: list[str] = []
    for command in _extract_strings(arguments, keys=_COMMAND_KEYWORDS):
        clipped = _clip_plan_context(command, 180)
        if clipped and clipped not in seen:
            seen.add(clipped)
            commands.append(clipped)
    return commands[:5]


def _step_is_execution_oriented(step_label: str | None, step_note: str | None) -> bool:
    text = " ".join(part for part in [step_label or "", step_note or ""] if part).strip()
    if not text:
        return True
    if _READ_ONLY_STEP_RE.search(text) and not _EXECUTION_STEP_RE.search(text):
        return False
    return True


def _normalize_review_payload(
    judgment: Any,
    *,
    fallback_reason: str,
) -> dict[str, Any]:
    raw = judgment if isinstance(judgment, dict) else {}
    verdict = str(raw.get("verdict") or "").strip()
    if verdict not in {
        PLAN_SEMANTIC_REVIEW_SUPPORTED,
        PLAN_SEMANTIC_REVIEW_WEAK_SUPPORT,
        PLAN_SEMANTIC_REVIEW_UNSUPPORTED,
        PLAN_SEMANTIC_REVIEW_NEEDS_REPLAN,
    }:
        verdict = PLAN_SEMANTIC_REVIEW_WEAK_SUPPORT

    semantic_status = str(raw.get("semantic_status") or "").strip()
    if semantic_status not in {PLAN_SEMANTIC_STATUS_OK, PLAN_SEMANTIC_STATUS_WARNING, PLAN_SEMANTIC_STATUS_NEEDS_REPLAN}:
        semantic_status = {
            PLAN_SEMANTIC_REVIEW_SUPPORTED: PLAN_SEMANTIC_STATUS_OK,
            PLAN_SEMANTIC_REVIEW_NEEDS_REPLAN: PLAN_SEMANTIC_STATUS_NEEDS_REPLAN,
        }.get(verdict, PLAN_SEMANTIC_STATUS_WARNING)

    recommended_action = str(raw.get("recommended_action") or "").strip()
    if recommended_action not in {"continue", "repeat_step", "review_manually", "request_replan"}:
        recommended_action = {
            PLAN_SEMANTIC_REVIEW_SUPPORTED: "continue",
            PLAN_SEMANTIC_REVIEW_NEEDS_REPLAN: "request_replan",
        }.get(verdict, "review_manually")

    try:
        confidence = float(raw.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.5

    return {
        "verdict": verdict,
        "semantic_status": semantic_status,
        "confidence": max(0.0, min(confidence, 1.0)),
        "reason": _clip_plan_context(str(raw.get("reason") or fallback_reason), 500),
        "recommended_action": recommended_action,
    }


def _build_trace_summary(events: list[TraceEvent]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for event in events[:8]:
        summary.append(
            {
                "event_type": event.event_type,
                "event_name": event.event_name,
                "created_at": event.created_at.isoformat() if event.created_at else None,
                "data": copy.deepcopy(event.data or {}),
            }
        )
    return summary


def _deterministic_assessment(bundle: dict[str, Any]) -> tuple[list[str], dict[str, Any] | None]:
    flags: list[str] = []
    outcome = str(bundle["outcome"].get("outcome") or "")
    features = bundle["features"]

    if features["requested_replan"] and outcome not in {PLAN_PROGRESS_OUTCOME_BLOCKED, PLAN_PROGRESS_OUTCOME_NO_PROGRESS}:
        flags.append("requested_replan_conflicts_with_success_claim")
        return flags, {
            "verdict": PLAN_SEMANTIC_REVIEW_NEEDS_REPLAN,
            "semantic_status": PLAN_SEMANTIC_STATUS_NEEDS_REPLAN,
            "confidence": 0.97,
            "reason": "This turn indicates the plan needed replanning, which conflicts with the recorded successful outcome.",
            "recommended_action": "request_replan",
        }

    if features["all_tool_calls_failed"] and outcome in {
        PLAN_PROGRESS_OUTCOME_PROGRESS,
        PLAN_PROGRESS_OUTCOME_VERIFICATION,
        PLAN_PROGRESS_OUTCOME_STEP_DONE,
    }:
        flags.append("all_tools_failed")
        return flags, {
            "verdict": PLAN_SEMANTIC_REVIEW_UNSUPPORTED,
            "semantic_status": PLAN_SEMANTIC_STATUS_WARNING,
            "confidence": 0.96,
            "reason": "All relevant tool calls failed, so the claimed progress is not supported by the turn evidence.",
            "recommended_action": "repeat_step",
        }

    if not features["had_successful_tool"] and outcome in {
        PLAN_PROGRESS_OUTCOME_STEP_DONE,
        PLAN_PROGRESS_OUTCOME_VERIFICATION,
    }:
        flags.append("no_successful_supporting_action")
        return flags, {
            "verdict": PLAN_SEMANTIC_REVIEW_UNSUPPORTED,
            "semantic_status": PLAN_SEMANTIC_STATUS_WARNING,
            "confidence": 0.92,
            "reason": "The turn did not show a successful supporting action for the recorded completion or verification outcome.",
            "recommended_action": "repeat_step",
        }

    if outcome == PLAN_PROGRESS_OUTCOME_VERIFICATION and not features["had_verification_signal"]:
        flags.append("verification_without_verification_signal")
        return flags, {
            "verdict": PLAN_SEMANTIC_REVIEW_WEAK_SUPPORT,
            "semantic_status": PLAN_SEMANTIC_STATUS_WARNING,
            "confidence": 0.86,
            "reason": "The outcome claims verification, but the turn evidence does not show a clear verification action or command.",
            "recommended_action": "review_manually",
        }

    if outcome == PLAN_PROGRESS_OUTCOME_STEP_DONE and features["read_only_only"] and bundle["step"]["execution_oriented"]:
        flags.append("step_done_from_read_only_turn")
        return flags, {
            "verdict": PLAN_SEMANTIC_REVIEW_WEAK_SUPPORT,
            "semantic_status": PLAN_SEMANTIC_STATUS_WARNING,
            "confidence": 0.82,
            "reason": "The step looks execution-oriented, but this turn only shows read-only activity.",
            "recommended_action": "review_manually",
        }

    return flags, None


async def review_plan_adherence(
    db: AsyncSession,
    session: Session,
    *,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    plan = load_session_plan(session, required=False)
    if plan is None:
        raise HTTPException(status_code=404, detail="No active plan for this session.")

    adherence = _normalize_adherence((session.metadata_ or {}).get("plan_adherence"))
    outcomes = [item for item in adherence.get("outcomes", []) if isinstance(item, dict)]
    selected_outcome: dict[str, Any] | None = None
    if correlation_id:
        for item in reversed(outcomes):
            if str(item.get("correlation_id") or "") == correlation_id:
                selected_outcome = copy.deepcopy(item)
                break
        if selected_outcome is None:
            raise HTTPException(status_code=404, detail="No recorded plan outcome found for that correlation id.")
    else:
        latest = adherence.get("latest_outcome")
        if not isinstance(latest, dict):
            raise HTTPException(status_code=409, detail="No recorded plan outcome is available to review.")
        selected_outcome = copy.deepcopy(latest)

    outcome_correlation = str(selected_outcome.get("correlation_id") or "").strip()
    if not outcome_correlation:
        raise HTTPException(
            status_code=409,
            detail="This recorded outcome predates correlation-aware review and cannot be reviewed semantically.",
        )

    corr_uuid = _parse_uuid(outcome_correlation)
    if corr_uuid is None:
        raise HTTPException(status_code=409, detail="The recorded outcome has an invalid correlation id.")

    plan_revision = int(selected_outcome.get("accepted_revision") or selected_outcome.get("plan_revision") or plan.revision)
    review_plan = load_session_plan_revision(session, plan_revision, prefer_snapshot=False, required=False) or plan
    step_id = str(selected_outcome.get("step_id") or "").strip() or None
    step = next((item for item in review_plan.steps if item.id == step_id), None)

    message_result = await db.execute(
        select(Message)
        .where(Message.session_id == session.id, Message.correlation_id == corr_uuid, Message.role == "assistant")
        .order_by(Message.created_at.desc())
    )
    assistant_message = message_result.scalars().first()

    tool_result = await db.execute(
        select(ToolCall)
        .where(ToolCall.session_id == session.id, ToolCall.correlation_id == corr_uuid)
        .order_by(ToolCall.created_at.asc())
    )
    tool_calls = list(tool_result.scalars().all())

    trace_result = await db.execute(
        select(TraceEvent)
        .where(TraceEvent.session_id == session.id, TraceEvent.correlation_id == corr_uuid)
        .order_by(TraceEvent.created_at.asc())
    )
    trace_events = list(trace_result.scalars().all())

    tool_names = [tool.tool_name for tool in tool_calls]
    command_samples: list[str] = []
    touched_paths: list[str] = []
    had_successful_tool = False
    had_any_error = False
    had_mutation = False
    had_verification_signal = False
    tier_observations: list[str] = []

    for tool in tool_calls:
        arguments = copy.deepcopy(tool.arguments or {})
        command_samples.extend(item for item in _extract_commands(arguments) if item not in command_samples)
        touched_paths.extend(item for item in _extract_paths(arguments) if item not in touched_paths)
        tier = get_tool_safety_tier(tool.tool_name)
        if tier != "unknown":
            tier_observations.append(tier)
        if tier in {"mutating", "exec_capable", "control_plane"}:
            had_mutation = True
        if tool.status == "done" and not tool.error:
            had_successful_tool = True
        if tool.error or tool.status in {"error", "denied", "expired"}:
            had_any_error = True
        if _VERIFY_TOOL_RE.search(tool.tool_name):
            had_verification_signal = True
        if any(_VERIFY_COMMAND_RE.search(command) for command in _extract_commands(arguments)):
            had_verification_signal = True

    for event in trace_events:
        haystack = " ".join(filter(None, [event.event_type, event.event_name, _truncate_json(event.data, 300) or ""]))
        if _REPLAN_EVENT_RE.search(haystack):
            had_any_error = had_any_error or False

    requested_replan = any(
        tool.tool_name == "request_plan_replan" or _REPLAN_EVENT_RE.search(tool.tool_name or "")
        for tool in tool_calls
    ) or any(
        _REPLAN_EVENT_RE.search(" ".join(filter(None, [event.event_type, event.event_name])))
        for event in trace_events
    )

    read_only_only = bool(tool_calls) and bool(tier_observations) and all(tier == "readonly" for tier in tier_observations)
    all_tool_calls_failed = bool(tool_calls) and not had_successful_tool and had_any_error

    assistant_summary = _clip_plan_context(assistant_message.content, 500) if assistant_message and assistant_message.content else None
    bundle = {
        "plan_revision": plan_revision,
        "accepted_revision": selected_outcome.get("accepted_revision"),
        "step": {
            "id": step.id if step else step_id,
            "label": step.label if step else None,
            "note": step.note if step else None,
            "execution_oriented": _step_is_execution_oriented(step.label if step else None, step.note if step else None),
        },
        "plan": {
            "title": review_plan.title,
            "summary": review_plan.summary,
            "acceptance_criteria": list(review_plan.acceptance_criteria),
        },
        "outcome": selected_outcome,
        "assistant_message": {
            "id": str(assistant_message.id) if assistant_message else None,
            "content": assistant_summary,
            "created_at": assistant_message.created_at.isoformat() if assistant_message and assistant_message.created_at else None,
        },
        "tool_calls": [
            {
                "tool_name": tool.tool_name,
                "tool_type": tool.tool_type,
                "status": tool.status,
                "error": tool.error,
                "created_at": tool.created_at.isoformat() if tool.created_at else None,
                "summary": copy.deepcopy(tool.summary or {}),
                "arguments": copy.deepcopy(tool.arguments or {}),
            }
            for tool in tool_calls[:12]
        ],
        "trace_events": _build_trace_summary(trace_events),
        "features": {
            "had_successful_tool": had_successful_tool,
            "had_any_error": had_any_error,
            "all_tool_calls_failed": all_tool_calls_failed,
            "read_only_only": read_only_only,
            "had_mutation": had_mutation,
            "had_verification_signal": had_verification_signal,
            "requested_replan": requested_replan,
            "tool_names": tool_names[:10],
            "touched_paths": touched_paths[:8],
            "command_samples": command_samples[:5],
        },
    }

    deterministic_flags, deterministic_review = _deterministic_assessment(bundle)
    judge_raw: Any = None

    if deterministic_review is None:
        try:
            judge_raw = await judge_single_case(
                _JUDGE_RUBRIC,
                {
                    "plan": bundle["plan"],
                    "step": bundle["step"],
                    "outcome": bundle["outcome"],
                },
                {
                    "assistant_message": bundle["assistant_message"],
                    "tool_calls": bundle["tool_calls"],
                    "trace_events": bundle["trace_events"],
                    "features": bundle["features"],
                },
                {},
            )
            review = _normalize_review_payload(
                judge_raw,
                fallback_reason="The semantic reviewer returned an incomplete result; manual review is recommended.",
            )
        except Exception as exc:
            deterministic_flags.append("judge_error")
            judge_raw = {"error": str(exc)}
            review = {
                "verdict": PLAN_SEMANTIC_REVIEW_WEAK_SUPPORT,
                "semantic_status": PLAN_SEMANTIC_STATUS_WARNING,
                "confidence": 0.35,
                "reason": "The semantic judge was unavailable, so only deterministic evidence could be considered.",
                "recommended_action": "review_manually",
            }
    else:
        review = deterministic_review

    review_record = {
        "created_at": _utc_now_iso(),
        "plan_revision": bundle["plan_revision"],
        "accepted_revision": bundle["accepted_revision"],
        "step_id": bundle["step"]["id"],
        "turn_id": selected_outcome.get("turn_id"),
        "correlation_id": outcome_correlation,
        "outcome": selected_outcome.get("outcome"),
        "verdict": review["verdict"],
        "semantic_status": review["semantic_status"],
        "confidence": review["confidence"],
        "reason": _clip_plan_context(review["reason"], 500),
        "recommended_action": review["recommended_action"],
        "deterministic_flags": deterministic_flags,
        "evidence_snapshot": {
            "assistant_summary": assistant_summary,
            "tool_names": tool_names[:10],
            "touched_paths": touched_paths[:8],
            "command_samples": command_samples[:5],
            "had_successful_tool": had_successful_tool,
            "had_any_error": had_any_error,
            "read_only_only": read_only_only,
            "had_mutation": had_mutation,
            "had_verification_signal": had_verification_signal,
            "requested_replan": requested_replan,
            "trace_event_types": [event.event_type for event in trace_events[:8]],
        },
        "judge_raw": _truncate_json(judge_raw),
    }
    return record_plan_semantic_review(session, review_record, plan=plan)
