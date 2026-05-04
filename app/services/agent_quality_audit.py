"""Deterministic post-turn quality audit.

This module emits observation-only findings after a turn has already been
persisted. It does not change prompts, retry turns, or block user responses.
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.engine import async_session
from app.db.models import Message, ToolCall, TraceEvent

logger = logging.getLogger(__name__)

AGENT_QUALITY_AUDIT_EVENT = "agent_quality_audit"
AGENT_QUALITY_AUDIT_VERSION = 1

_VISION_REFUSAL_RE = re.compile(
    r"\b("
    r"can(?:not|'t)\s+(?:see|view|inspect|access)\s+(?:the\s+)?(?:image|photo|picture|attachment)"
    r"|no\s+(?:image|photo|picture|attachment)\s+(?:is\s+)?(?:attached|available|visible)"
    r"|i\s+don(?:'t|’t)\s+have\s+access\s+to\s+(?:the\s+)?(?:image|photo|picture|attachment)"
    r")\b",
    re.IGNORECASE,
)

_CURRENT_FACT_USER_RE = re.compile(
    r"\b("
    r"current|right now|today|latest|live|status|weather|temperature|temp|"
    r"look\s+up|search|check|now playing|due/wanted|missing|available"
    r")\b",
    re.IGNORECASE,
)

_CAPABILITY_REFUSAL_RE = re.compile(
    r"\b("
    r"tool .*?(?:not available|missing|not exposed|not found)|"
    r"(?:can(?:not|'t)|unable to)\s+(?:access|use|call|read|check)\b"
    r")",
    re.IGNORECASE,
)

_BENIGN_NO_LOOKUP_RE = re.compile(
    r"\b("
    r"i\s+can(?:not|'t)\s+(?:check|access|look up|verify|read)|"
    r"i\s+don(?:'t|’t)\s+have\s+(?:live|real[- ]time|access)|"
    r"would\s+need\s+(?:a|the)\s+tool|"
    r"not\s+available\s+in\s+this\s+session"
    r")\b",
    re.IGNORECASE,
)

_DISCOVERY_ONLY_TOOLS = {
    "get_tool_info",
    "search_tools",
    "get_skill",
    "get_skill_list",
    "list_tool_signatures",
    "list_agent_capabilities",
}


@dataclass(slots=True)
class QualityEvidence:
    correlation_id: uuid.UUID
    session_id: uuid.UUID | None
    bot_id: str | None
    client_id: str | None
    turn_kind: str
    user_text: str
    assistant_text: str
    had_inline_image: bool
    tool_calls: list[dict[str, Any]]
    trace_events: list[dict[str, Any]]
    exposed_tools: set[str]


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _message_text(message: Message | None) -> str:
    return _text(getattr(message, "content", None))


def _message_has_image(message: Message | None) -> bool:
    if message is None:
        return False
    if any(getattr(att, "type", None) == "image" for att in (message.attachments or [])):
        return True
    content = _message_text(message).lower()
    return "image_url" in content or "[image" in content or '"type": "image"' in content


def _extract_exposed_tools(trace_rows: list[TraceEvent]) -> set[str]:
    names: set[str] = set()
    for event in trace_rows:
        data = event.data or {}
        if event.event_type == "tool_surface_summary":
            for name in data.get("tools") or []:
                if isinstance(name, str):
                    names.add(name)
        if event.event_type == "discovery_summary":
            tools = data.get("tools") if isinstance(data.get("tools"), dict) else {}
            for key in ("included", "retrieved", "enrolled_working_set", "pinned"):
                for name in tools.get(key) or []:
                    if isinstance(name, str):
                        names.add(name)
    return names


def _trace_feature_had_image(trace_rows: list[TraceEvent]) -> bool:
    for event in trace_rows:
        data = event.data or {}
        if event.event_type == "attachment_vision_routing":
            keys = ("source_image_count", "admitted_image_count", "image_count")
        elif event.event_type == "recent_attachment_context":
            keys = ("admitted_count",)
        else:
            continue
        for key in keys:
            try:
                if int(data.get(key) or 0) > 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


async def build_quality_evidence(
    db: AsyncSession,
    correlation_id: uuid.UUID,
    *,
    turn_kind: str | None = None,
) -> QualityEvidence | None:
    messages = (await db.execute(
        select(Message)
        .options(selectinload(Message.attachments))
        .where(Message.correlation_id == correlation_id)
        .order_by(Message.created_at)
    )).scalars().all()
    trace_rows = (await db.execute(
        select(TraceEvent)
        .where(TraceEvent.correlation_id == correlation_id)
        .order_by(TraceEvent.created_at)
    )).scalars().all()
    tool_rows = (await db.execute(
        select(ToolCall)
        .where(ToolCall.correlation_id == correlation_id)
        .order_by(ToolCall.created_at)
    )).scalars().all()

    if not messages and not trace_rows and not tool_rows:
        return None

    first_user = next((m for m in messages if m.role == "user"), None)
    last_assistant = next((m for m in reversed(messages) if m.role == "assistant"), None)
    first_trace = trace_rows[0] if trace_rows else None
    first_tool = tool_rows[0] if tool_rows else None

    return QualityEvidence(
        correlation_id=correlation_id,
        session_id=getattr(first_trace, "session_id", None)
        or getattr(first_tool, "session_id", None)
        or getattr(first_user, "session_id", None),
        bot_id=getattr(first_trace, "bot_id", None) or getattr(first_tool, "bot_id", None),
        client_id=getattr(first_trace, "client_id", None) or getattr(first_tool, "client_id", None),
        turn_kind=turn_kind or "unknown",
        user_text=_message_text(first_user),
        assistant_text=_message_text(last_assistant),
        had_inline_image=_message_has_image(first_user) or _trace_feature_had_image(trace_rows),
        tool_calls=[
            {
                "tool_name": row.tool_name,
                "status": row.status,
                "error": row.error,
                "error_code": row.error_code,
                "error_kind": row.error_kind,
                "result": row.result,
                "summary": row.summary,
            }
            for row in tool_rows
        ],
        trace_events=[
            {
                "event_type": row.event_type,
                "event_name": row.event_name,
                "data": row.data or {},
            }
            for row in trace_rows
        ],
        exposed_tools=_extract_exposed_tools(trace_rows),
    )


def detect_quality_findings(evidence: QualityEvidence) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    assistant = evidence.assistant_text
    user = evidence.user_text

    if evidence.had_inline_image and _VISION_REFUSAL_RE.search(assistant):
        findings.append({
            "code": "current_inline_image_missed",
            "severity": "warning",
            "evidence": {
                "had_inline_image": True,
                "assistant_excerpt": assistant[:500],
            },
        })

    if (
        _CURRENT_FACT_USER_RE.search(user)
        and not _has_lookup_tool_call(evidence.tool_calls)
        and assistant.strip()
        and not _BENIGN_NO_LOOKUP_RE.search(assistant)
    ):
        findings.append({
            "code": "current_fact_without_lookup",
            "severity": "warning",
            "evidence": {
                "user_excerpt": user[:500],
                "assistant_excerpt": assistant[:500],
                "tool_calls": evidence.tool_calls[:10],
            },
        })

    findings.extend(_detect_tool_surface_mismatches(evidence))
    return findings


def _has_lookup_tool_call(tool_calls: list[dict[str, Any]]) -> bool:
    for call in tool_calls:
        name = _text(call.get("tool_name"))
        if not name or name in _DISCOVERY_ONLY_TOOLS:
            continue
        if call.get("status") == "error":
            continue
        return True
    return False


def _detect_tool_surface_mismatches(evidence: QualityEvidence) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    exposed = evidence.exposed_tools
    assistant = evidence.assistant_text

    for call in evidence.tool_calls:
        tool_name = _text(call.get("tool_name"))
        err = " ".join(
            _text(call.get(key))
            for key in ("error", "error_code", "error_kind", "result")
            if call.get(key)
        )
        if not tool_name or "not found" not in err.lower():
            continue
        missing_name = tool_name
        match = re.search(r"Tool ['\"]([^'\"]+)['\"] not found", err, re.IGNORECASE)
        if match:
            missing_name = match.group(1)
        suffix_matches = sorted(name for name in exposed if name.endswith(f"-{missing_name}"))
        findings.append({
            "code": "tool_surface_mismatch",
            "severity": "warning",
            "subkind": "referenced_unexposed",
            "evidence": {
                "tool_name": missing_name,
                "carrier_tool_name": tool_name,
                "error": err[:500],
                "prefixed_candidates": suffix_matches[:10],
            },
        })

    if _CAPABILITY_REFUSAL_RE.search(assistant) and exposed:
        lowered = assistant.lower()
        named = sorted(name for name in exposed if name.lower() in lowered)
        if named:
            findings.append({
                "code": "tool_surface_mismatch",
                "severity": "warning",
                "subkind": "claimed_missing",
                "evidence": {
                    "assistant_excerpt": assistant[:500],
                    "mentioned_exposed_tools": named[:10],
                },
            })

    return findings


def _features(evidence: QualityEvidence) -> dict[str, Any]:
    return {
        "had_inline_image": evidence.had_inline_image,
        "tool_call_count": len(evidence.tool_calls),
        "tool_calls": evidence.tool_calls[:50],
        "exposed_tools": sorted(evidence.exposed_tools)[:100],
        "turn_kind": evidence.turn_kind,
    }


async def audit_turn_quality(
    db: AsyncSession,
    correlation_id: uuid.UUID,
    *,
    turn_kind: str | None = None,
    audit_version: int = AGENT_QUALITY_AUDIT_VERSION,
    persist: bool = True,
) -> dict[str, Any]:
    existing_rows = (await db.execute(
        select(TraceEvent).where(
            TraceEvent.correlation_id == correlation_id,
            TraceEvent.event_type == AGENT_QUALITY_AUDIT_EVENT,
            # Auditor-emitted summary rows have ``event_name=NULL``. User
            # feedback rows share ``event_type`` for routing convenience but
            # carry their own ``event_name`` and a single-vote payload —
            # they must not satisfy the idempotency check.
            TraceEvent.event_name.is_(None),
        )
    )).scalars().all()
    for row in existing_rows:
        data = row.data or {}
        if data.get("audit_version") == audit_version:
            return data

    evidence = await build_quality_evidence(db, correlation_id, turn_kind=turn_kind)
    if evidence is None:
        return {
            "audit_version": audit_version,
            "findings": [],
            "features": {},
            "audited_count": 0,
            "message": "No evidence found for correlation_id.",
        }

    findings = detect_quality_findings(evidence)
    payload = {
        "audit_version": audit_version,
        "findings": findings,
        "features": _features(evidence),
        "audited_count": 1,
    }

    if persist:
        db.add(TraceEvent(
            correlation_id=correlation_id,
            session_id=evidence.session_id,
            bot_id=evidence.bot_id,
            client_id=evidence.client_id,
            event_type=AGENT_QUALITY_AUDIT_EVENT,
            event_name=None,
            count=len(findings),
            data=payload,
            created_at=datetime.now(timezone.utc),
        ))
        await db.commit()
    return payload


async def audit_turn_quality_background(
    correlation_id: uuid.UUID,
    *,
    turn_kind: str | None = None,
) -> None:
    try:
        async with async_session() as db:
            await audit_turn_quality(db, correlation_id, turn_kind=turn_kind, persist=True)
    except Exception:
        logger.exception("agent_quality_audit: failed for correlation_id=%s", correlation_id)
