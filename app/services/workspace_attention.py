"""Workspace Attention Items.

Attention Items are shared work-intake/domain state. The Spatial Canvas
renders active items as Beacons, but dedupe, lifecycle, evidence, and future
assignment semantics stay here.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.engine import async_session
from app.db.models import (
    Channel,
    ChannelHeartbeat,
    HeartbeatRun,
    IssueWorkPack,
    Project,
    Session,
    Task,
    ToolCall,
    TraceEvent,
    WidgetDashboardPin,
    WorkspaceAttentionItem,
    WorkspaceSpatialNode,
)
from app.dependencies import ApiKeyAuth
from app.domain.errors import NotFoundError, ValidationError
from app.services.tool_error_contract import (
    BENIGN_REVIEW_ERROR_KINDS,
    RETRYABLE_ERROR_KINDS,
)


logger = logging.getLogger(__name__)

DEDUPE_STATUSES = ("open", "acknowledged", "responded")
VISIBLE_STATUSES = ("open", "responded")
VALID_SEVERITIES = {"info", "warning", "error", "critical"}
VALID_TARGET_KINDS = {"channel", "bot", "widget", "system"}
VALID_ASSIGNMENT_MODES = {"next_heartbeat", "run_now"}
VALID_RESOLUTIONS = {
    "fixed",
    "benign",
    "duplicate",
    "not_reproducible",
    "external",
    "stale",
    "already_recovered",
    "other",
}
STRUCTURED_ERROR_DETECTOR_ID = "system:structured-errors"
OPERATOR_TRIAGE_BOT_ID = "orchestrator"
OPERATOR_TRIAGE_TOOL_NAME = "report_attention_triage_batch"
REPORT_ISSUE_TOOL_NAME = "report_issue"
ISSUE_WORK_PACK_TOOL_NAME = "report_issue_work_packs"
AUTO_SIGNAL_REOPEN_COOLDOWN = timedelta(hours=24)
SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2, "critical": 3}
BOT_REPORT_CATEGORIES = {
    "needs_review",
    "needs_fix",
    "blocked",
    "missing_permission",
    "system_issue",
    "setup_issue",
    "user_decision",
}
OPERATOR_TRIAGE_PROCESSED_CLASSIFICATIONS = {
    "benign",
    "noise",
    "duplicate",
    "expected",
    "already_recovered",
    "informational",
}
OPERATOR_TRIAGE_ALLOWED_TOOLS = {
    "get_system_status",
    "list_tasks",
    "get_trace",
    "search_memory",
    "get_memory_file",
    "search_bot_memory",
    OPERATOR_TRIAGE_TOOL_NAME,
}
ISSUE_TRIAGE_ALLOWED_TOOLS = {
    "read_conversation_history",
    "search_history",
    "search_memory",
    "get_memory_file",
    "list_tasks",
    "get_trace",
    ISSUE_WORK_PACK_TOOL_NAME,
}
ISSUE_INTAKE_CATEGORIES = {
    "bug",
    "regression",
    "quality",
    "feature",
    "test_failure",
    "config_issue",
    "environment_issue",
    "user_decision",
    "other",
}
ISSUE_WORK_PACK_CATEGORIES = {
    "code_bug",
    "test_failure",
    "config_issue",
    "environment_issue",
    "user_decision",
    "not_code_work",
    "needs_info",
    "other",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_admin_auth(auth: Any) -> bool:
    if isinstance(auth, ApiKeyAuth):
        return "admin" in (auth.scopes or [])
    return bool(getattr(auth, "is_admin", False))


def actor_label(auth: Any | None) -> str | None:
    if auth is None:
        return None
    if isinstance(auth, ApiKeyAuth):
        return f"api_key:{auth.name}"
    user_id = getattr(auth, "id", None)
    if user_id:
        return f"user:{user_id}"
    return None


def normalize_dedupe_key(value: str) -> str:
    text = re.sub(r"\s+", " ", (value or "").strip().lower())
    text = re.sub(r"[^a-z0-9:._/-]+", "-", text)
    return text.strip("-")[:160] or "attention"


def derive_dedupe_key(*parts: str | None) -> str:
    raw = "|".join((p or "").strip().lower() for p in parts)
    if len(raw) <= 160:
        return normalize_dedupe_key(raw)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"{normalize_dedupe_key(raw[:120])}-{digest}"


def _severity_rank(value: str | None) -> int:
    return SEVERITY_RANK.get(value or "warning", 1)


def _auto_signal_signature(
    *,
    kind: str,
    channel_id: uuid.UUID | None,
    target_kind: str,
    target_id: str,
    name: str | None = None,
    error_kind: str | None = None,
    text: str | None = None,
) -> str:
    return derive_dedupe_key(
        "auto-signal",
        kind,
        str(channel_id) if channel_id else None,
        target_kind,
        target_id,
        name,
        error_kind,
        _error_signature(text or ""),
    )


def _extract_signal_signature(evidence: dict | None) -> str | None:
    if not isinstance(evidence, dict):
        return None
    auto_signal = evidence.get("auto_signal")
    if isinstance(auto_signal, dict) and auto_signal.get("signature"):
        return str(auto_signal["signature"])
    report = evidence.get("report_issue")
    if isinstance(report, dict) and report.get("signal_signature"):
        return str(report["signal_signature"])
    value = evidence.get("signal_signature") or evidence.get("signature")
    return str(value) if value else None


def _merge_evidence(old: dict | None, new: dict | None) -> dict:
    merged = dict(old or {})
    if new:
        merged.update(new)
        history = list(merged.get("recent") or [])
        history.append(new)
        merged["recent"] = history[-10:]
    return merged


def _source_event_seen(evidence: dict | None, source_event_key: str | None) -> bool:
    if not source_event_key:
        return False
    keys = (evidence or {}).get("source_event_keys") or []
    return str(source_event_key) in {str(key) for key in keys}


def _record_source_event(evidence: dict | None, source_event_key: str | None) -> dict:
    if not source_event_key:
        return dict(evidence or {})
    merged = dict(evidence or {})
    keys = [str(key) for key in (merged.get("source_event_keys") or [])]
    key = str(source_event_key)
    if key not in keys:
        keys.append(key)
    merged["source_event_keys"] = keys[-25:]
    return merged


async def _resolve_target_channel(
    db: AsyncSession,
    *,
    target_kind: str,
    target_id: str,
    fallback_channel_id: uuid.UUID | None,
) -> uuid.UUID | None:
    if target_kind == "channel":
        try:
            return uuid.UUID(target_id)
        except (TypeError, ValueError):
            raise ValidationError("channel target_id must be a UUID")
    if target_kind == "widget":
        try:
            pin = await db.get(WidgetDashboardPin, uuid.UUID(target_id))
        except (TypeError, ValueError):
            raise ValidationError("widget target_id must be a dashboard pin UUID")
        if pin and pin.source_channel_id:
            return pin.source_channel_id
    return fallback_channel_id


async def place_attention_item(
    db: AsyncSession,
    *,
    source_type: str,
    source_id: str,
    channel_id: uuid.UUID | None,
    target_kind: str,
    target_id: str,
    title: str,
    message: str = "",
    severity: str = "warning",
    requires_response: bool = False,
    next_steps: list[str] | None = None,
    dedupe_key: str | None = None,
    evidence: dict | None = None,
    latest_correlation_id: uuid.UUID | None = None,
    source_event_key: str | None = None,
    reopen_after: timedelta | None = None,
) -> WorkspaceAttentionItem:
    if source_type not in {"bot", "system", "user"}:
        raise ValidationError("source_type must be 'bot', 'system', or 'user'")
    if target_kind not in VALID_TARGET_KINDS:
        raise ValidationError(f"target_kind must be one of {sorted(VALID_TARGET_KINDS)}")
    if severity not in VALID_SEVERITIES:
        raise ValidationError(f"severity must be one of {sorted(VALID_SEVERITIES)}")
    title = (title or "").strip()
    if not title:
        raise ValidationError("title is required")
    target_id = str(target_id or "").strip()
    if not target_id:
        raise ValidationError("target_id is required")
    channel_id = await _resolve_target_channel(
        db,
        target_kind=target_kind,
        target_id=target_id,
        fallback_channel_id=channel_id,
    )
    key = normalize_dedupe_key(dedupe_key or derive_dedupe_key(source_type, source_id, target_kind, target_id, title))
    now = _now()
    existing = (await db.execute(
        select(WorkspaceAttentionItem).where(
            WorkspaceAttentionItem.source_type == source_type,
            WorkspaceAttentionItem.source_id == source_id,
            WorkspaceAttentionItem.channel_id == channel_id,
            WorkspaceAttentionItem.target_kind == target_kind,
            WorkspaceAttentionItem.target_id == target_id,
            WorkspaceAttentionItem.dedupe_key == key,
            WorkspaceAttentionItem.status.in_(DEDUPE_STATUSES),
        )
    )).scalar_one_or_none()
    if existing is not None:
        if _source_event_seen(existing.evidence, source_event_key):
            return existing
        existing.title = title
        existing.message = message or ""
        existing.severity = severity
        existing.requires_response = bool(requires_response)
        existing.next_steps = list(next_steps or [])
        existing.evidence = _record_source_event(_merge_evidence(existing.evidence, evidence), source_event_key)
        existing.latest_correlation_id = latest_correlation_id or existing.latest_correlation_id
        existing.occurrence_count = int(existing.occurrence_count or 0) + 1
        if existing.status in {"acknowledged", "responded"}:
            should_reopen = True
            if reopen_after is not None:
                last_seen = existing.last_seen_at or existing.updated_at or existing.first_seen_at or now
                cooled_down = now - last_seen >= reopen_after
                escalated = _severity_rank(severity) > _severity_rank(existing.severity)
                should_reopen = cooled_down or escalated
            if should_reopen:
                existing.status = "open"
        existing.last_seen_at = now
        existing.updated_at = now
        flag_modified(existing, "next_steps")
        flag_modified(existing, "evidence")
        await db.commit()
        await db.refresh(existing)
        return existing

    item = WorkspaceAttentionItem(
        source_type=source_type,
        source_id=source_id,
        channel_id=channel_id,
        target_kind=target_kind,
        target_id=target_id,
        dedupe_key=key,
        severity=severity,
        title=title,
        message=message or "",
        next_steps=list(next_steps or []),
        requires_response=bool(requires_response),
        status="open",
        evidence=_record_source_event(evidence or {}, source_event_key),
        latest_correlation_id=latest_correlation_id,
        first_seen_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def get_attention_item(db: AsyncSession, item_id: uuid.UUID) -> WorkspaceAttentionItem:
    item = await db.get(WorkspaceAttentionItem, item_id)
    if item is None:
        raise NotFoundError("Attention item not found.")
    return item


async def acknowledge_attention_item(db: AsyncSession, item_id: uuid.UUID) -> WorkspaceAttentionItem:
    item = await get_attention_item(db, item_id)
    if item.status != "resolved":
        now = _now()
        item.status = "acknowledged"
        item.occurrence_count = max(1, int(item.occurrence_count or 1))
        item.updated_at = now
        await db.commit()
        await db.refresh(item)
    return item


async def acknowledge_attention_items_bulk(
    db: AsyncSession,
    *,
    auth: Any,
    scope: str,
    target_kind: str | None = None,
    target_id: str | None = None,
    channel_id: uuid.UUID | None = None,
) -> list[WorkspaceAttentionItem]:
    if scope not in {"target", "workspace_visible"}:
        raise ValidationError("scope must be 'target' or 'workspace_visible'")
    clauses = [WorkspaceAttentionItem.status.in_(VISIBLE_STATUSES)]
    if scope == "target":
        if not target_kind or not target_id:
            raise ValidationError("target_kind and target_id are required for target scope.")
        clauses.extend([
            WorkspaceAttentionItem.target_kind == target_kind,
            WorkspaceAttentionItem.target_id == str(target_id),
        ])
        if channel_id:
            clauses.append(WorkspaceAttentionItem.channel_id == channel_id)
    if not _is_admin_auth(auth):
        clauses.append(WorkspaceAttentionItem.source_type.in_(("bot", "user")))
    items = list((await db.execute(
        select(WorkspaceAttentionItem).where(*clauses).order_by(desc(WorkspaceAttentionItem.last_seen_at))
    )).scalars().all())
    if not items:
        return []
    now = _now()
    for item in items:
        item.status = "acknowledged"
        item.occurrence_count = max(1, int(item.occurrence_count or 1))
        item.updated_at = now
    await db.commit()
    for item in items:
        await db.refresh(item)
    return items


async def mark_attention_responded(
    db: AsyncSession,
    item_id: uuid.UUID,
    *,
    response_message_id: uuid.UUID | None = None,
    responded_by: str | None = None,
) -> WorkspaceAttentionItem:
    item = await get_attention_item(db, item_id)
    if item.status != "resolved":
        now = _now()
        item.status = "responded"
        item.responded_at = item.responded_at or now
        item.response_message_id = response_message_id or item.response_message_id
        item.responded_by = responded_by or item.responded_by
        item.updated_at = now
        await db.commit()
        await db.refresh(item)
    return item


async def resolve_attention_item(
    db: AsyncSession,
    item_id: uuid.UUID,
    *,
    resolved_by: str | None = None,
    source_bot_id: str | None = None,
    resolution: str | None = None,
    note: str | None = None,
    duplicate_of: uuid.UUID | str | None = None,
) -> WorkspaceAttentionItem:
    item = await get_attention_item(db, item_id)
    if source_bot_id and not (item.source_type == "bot" and item.source_id == source_bot_id):
        raise ValidationError("Bots can only resolve attention items they created.")
    now = _now()
    resolution_value = (resolution or "").strip().lower() or None
    if resolution_value and resolution_value not in VALID_RESOLUTIONS:
        raise ValidationError(f"resolution must be one of {sorted(VALID_RESOLUTIONS)}")
    duplicate_of_value = str(duplicate_of) if duplicate_of else None
    if duplicate_of_value and resolution_value != "duplicate":
        raise ValidationError("duplicate_of can only be set when resolution is duplicate")
    if duplicate_of_value and duplicate_of_value == str(item.id):
        raise ValidationError("duplicate_of cannot reference the resolved item")
    note_value = (note or "").strip()[:2000] or None
    if resolution_value or note_value or duplicate_of_value:
        evidence = dict(item.evidence or {})
        history = list(evidence.get("resolution_history") or [])
        resolution_record = {
            "resolution": resolution_value or "other",
            "note": note_value,
            "duplicate_of": duplicate_of_value,
            "resolved_by": resolved_by or source_bot_id or item.resolved_by,
            "resolved_at": now.isoformat(),
        }
        evidence["resolution"] = resolution_record
        history.append(resolution_record)
        evidence["resolution_history"] = history[-10:]
        item.evidence = evidence
        flag_modified(item, "evidence")
    item.status = "resolved"
    item.resolved_at = now
    item.resolved_by = resolved_by or source_bot_id or item.resolved_by
    item.updated_at = now
    await db.commit()
    await db.refresh(item)
    return item


async def create_user_attention_item(
    db: AsyncSession,
    *,
    actor: str,
    channel_id: uuid.UUID | None,
    target_kind: str,
    target_id: str,
    title: str,
    message: str = "",
    severity: str = "warning",
    requires_response: bool = True,
    next_steps: list[str] | None = None,
) -> WorkspaceAttentionItem:
    return await place_attention_item(
        db,
        source_type="user",
        source_id=actor,
        channel_id=channel_id,
        target_kind=target_kind,
        target_id=target_id,
        title=title,
        message=message,
        severity=severity,
        requires_response=requires_response,
        next_steps=next_steps or [],
        dedupe_key=f"user:{uuid.uuid4()}",
    )


async def publish_issue_intake(
    db: AsyncSession,
    *,
    bot_id: str,
    channel_id: uuid.UUID | None,
    title: str,
    summary: str,
    observed_behavior: str | None = None,
    expected_behavior: str | None = None,
    steps: list[str] | None = None,
    severity: str = "warning",
    category_hint: str = "bug",
    project_hint: str | None = None,
    tags: list[str] | None = None,
    latest_correlation_id: uuid.UUID | None = None,
) -> WorkspaceAttentionItem:
    clean_title = (title or "").strip()
    clean_summary = (summary or "").strip()
    if not clean_title:
        raise ValidationError("title is required.")
    if not clean_summary:
        raise ValidationError("summary is required.")
    if severity not in VALID_SEVERITIES:
        severity = "warning"
    category = normalize_dedupe_key(category_hint or "bug").replace("-", "_")
    if category not in ISSUE_INTAKE_CATEGORIES:
        category = "other"
    target_kind = "channel" if channel_id else "bot"
    target_id = str(channel_id) if channel_id else bot_id
    clean_steps = [str(step).strip() for step in (steps or []) if str(step).strip()]
    evidence = {
        "issue_intake": {
            "reported_by": bot_id,
            "reported_at": _now().isoformat(),
            "category_hint": category,
            "project_hint": (project_hint or "").strip() or None,
            "tags": [str(tag).strip() for tag in (tags or []) if str(tag).strip()][:12],
            "observed_behavior": (observed_behavior or "").strip() or None,
            "expected_behavior": (expected_behavior or "").strip() or None,
            "steps": clean_steps[:20],
            "source": "conversation",
        },
    }
    next_steps = ["Triage this issue into a work pack before launching implementation."]
    return await place_attention_item(
        db,
        source_type="bot",
        source_id=bot_id,
        channel_id=channel_id,
        target_kind=target_kind,
        target_id=target_id,
        title=clean_title[:500],
        message=clean_summary[:8000],
        severity=severity,
        requires_response=True,
        next_steps=next_steps,
        dedupe_key=f"issue-intake:{uuid.uuid4()}",
        evidence=evidence,
        latest_correlation_id=latest_correlation_id,
    )


async def create_issue_intake_note(
    db: AsyncSession,
    *,
    actor: str,
    channel_id: uuid.UUID | None,
    title: str,
    summary: str,
    observed_behavior: str | None = None,
    expected_behavior: str | None = None,
    steps: list[str] | None = None,
    severity: str = "warning",
    category_hint: str = "bug",
    project_hint: str | None = None,
    tags: list[str] | None = None,
) -> WorkspaceAttentionItem:
    """Create a user/admin-authored issue intake item without requiring a bot turn."""
    clean_title = (title or "").strip()
    clean_summary = (summary or "").strip()
    if not clean_title:
        raise ValidationError("title is required.")
    if not clean_summary:
        raise ValidationError("summary is required.")
    if severity not in VALID_SEVERITIES:
        severity = "warning"
    category = normalize_dedupe_key(category_hint or "bug").replace("-", "_")
    if category not in ISSUE_INTAKE_CATEGORIES:
        category = "other"
    target_kind = "channel" if channel_id else "system"
    target_id = str(channel_id) if channel_id else "workspace"
    clean_steps = [str(step).strip() for step in (steps or []) if str(step).strip()]
    evidence = {
        "issue_intake": {
            "reported_by": actor,
            "reported_at": _now().isoformat(),
            "category_hint": category,
            "project_hint": (project_hint or "").strip() or None,
            "tags": [str(tag).strip() for tag in (tags or []) if str(tag).strip()][:12],
            "observed_behavior": (observed_behavior or "").strip() or None,
            "expected_behavior": (expected_behavior or "").strip() or None,
            "steps": clean_steps[:20],
            "source": "user",
        },
    }
    return await place_attention_item(
        db,
        source_type="user",
        source_id=actor or "user",
        channel_id=channel_id,
        target_kind=target_kind,
        target_id=target_id,
        title=clean_title[:500],
        message=clean_summary[:8000],
        severity=severity,
        requires_response=True,
        next_steps=["Triage this issue into a work pack before launching implementation."],
        dedupe_key=f"issue-intake:{uuid.uuid4()}",
        evidence=evidence,
    )


async def _fold_system_signal_into_bot_report(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID | None,
    target_kind: str,
    target_id: str,
    signal_signature: str | None,
    evidence: dict,
    latest_correlation_id: uuid.UUID | None = None,
) -> WorkspaceAttentionItem | None:
    if not signal_signature:
        return None
    items = list((await db.execute(
        select(WorkspaceAttentionItem).where(
            WorkspaceAttentionItem.source_type == "bot",
            WorkspaceAttentionItem.channel_id == channel_id,
            WorkspaceAttentionItem.target_kind == target_kind,
            WorkspaceAttentionItem.target_id == target_id,
            WorkspaceAttentionItem.status.in_(DEDUPE_STATUSES),
        ).order_by(desc(WorkspaceAttentionItem.last_seen_at)).limit(25)
    )).scalars().all())
    now = _now()
    for item in items:
        item_evidence = dict(item.evidence or {})
        report = item_evidence.get("report_issue")
        if not isinstance(report, dict) or report.get("signal_signature") != signal_signature:
            continue
        collapsed = list(item_evidence.get("collapsed_system_signals") or [])
        collapsed.append({
            "at": now.isoformat(),
            "signal_signature": signal_signature,
            "evidence": evidence,
            "correlation_id": str(latest_correlation_id) if latest_correlation_id else None,
        })
        item_evidence["collapsed_system_signals"] = collapsed[-10:]
        item.evidence = item_evidence
        item.occurrence_count = int(item.occurrence_count or 0) + 1
        item.last_seen_at = now
        item.updated_at = now
        item.latest_correlation_id = latest_correlation_id or item.latest_correlation_id
        if item.status == "acknowledged":
            item.status = "open"
        flag_modified(item, "evidence")
        await db.commit()
        await db.refresh(item)
        return item
    return None


async def _collapse_existing_system_signals_for_report(
    db: AsyncSession,
    *,
    report_item: WorkspaceAttentionItem,
    signal_signature: str | None,
) -> None:
    if not signal_signature:
        return
    system_items = list((await db.execute(
        select(WorkspaceAttentionItem).where(
            WorkspaceAttentionItem.source_type == "system",
            WorkspaceAttentionItem.channel_id == report_item.channel_id,
            WorkspaceAttentionItem.target_kind == report_item.target_kind,
            WorkspaceAttentionItem.target_id == report_item.target_id,
            WorkspaceAttentionItem.status.in_(VISIBLE_STATUSES),
        )
    )).scalars().all())
    now = _now()
    report_evidence = dict(report_item.evidence or {})
    collapsed = list(report_evidence.get("collapsed_system_signals") or [])
    changed = False
    for item in system_items:
        if _extract_signal_signature(item.evidence) != signal_signature:
            continue
        collapsed.append({
            "at": now.isoformat(),
            "signal_signature": signal_signature,
            "collapsed_item_id": str(item.id),
            "title": item.title,
            "message": item.message,
            "count": item.occurrence_count,
        })
        item.status = "acknowledged"
        item.updated_at = now
        changed = True
    if changed:
        report_evidence["collapsed_system_signals"] = collapsed[-10:]
        report_item.evidence = report_evidence
        report_item.updated_at = now
        report_item.last_seen_at = now
        flag_modified(report_item, "evidence")
        await db.commit()
        await db.refresh(report_item)


async def report_bot_issue(
    db: AsyncSession,
    *,
    bot_id: str,
    channel_id: uuid.UUID | None,
    title: str,
    summary: str,
    category: str = "needs_review",
    suggested_action: str | None = None,
    severity: str = "warning",
    target_kind: str | None = None,
    target_id: str | None = None,
    dedupe_key: str | None = None,
    evidence: dict | None = None,
    task_id: uuid.UUID | None = None,
    run_origin: str | None = None,
    latest_correlation_id: uuid.UUID | None = None,
) -> WorkspaceAttentionItem:
    category = normalize_dedupe_key(category or "needs_review").replace("-", "_")
    if category not in BOT_REPORT_CATEGORIES:
        category = "needs_review"
    if severity not in VALID_SEVERITIES:
        severity = "warning"
    resolved_target_kind = target_kind or ("channel" if channel_id else "bot")
    resolved_target_id = target_id or (str(channel_id) if channel_id else bot_id)
    if resolved_target_kind not in VALID_TARGET_KINDS:
        raise ValidationError(f"target_kind must be one of {sorted(VALID_TARGET_KINDS)}")
    raw_evidence = dict(evidence or {})
    signal_signature = _extract_signal_signature(raw_evidence)
    if not signal_signature and raw_evidence.get("tool_name"):
        signal_signature = _auto_signal_signature(
            kind=str(raw_evidence.get("kind") or "tool_call"),
            channel_id=channel_id,
            target_kind=resolved_target_kind,
            target_id=str(resolved_target_id),
            name=str(raw_evidence.get("tool_name") or ""),
            error_kind=str(raw_evidence.get("error_kind") or ""),
            text=str(raw_evidence.get("error") or raw_evidence.get("message") or summary),
        )
    report_evidence = {
        **raw_evidence,
        "report_issue": {
            "category": category,
            "suggested_action": suggested_action or "",
            "reported_by": bot_id,
            "reported_at": _now().isoformat(),
            "task_id": str(task_id) if task_id else None,
            "origin": run_origin,
            "signal_signature": signal_signature,
        },
    }
    item = await place_attention_item(
        db,
        source_type="bot",
        source_id=bot_id,
        channel_id=channel_id,
        target_kind=resolved_target_kind,
        target_id=str(resolved_target_id),
        title=title,
        message=summary,
        severity=severity,
        requires_response=True,
        next_steps=[suggested_action] if suggested_action else [],
        dedupe_key=dedupe_key or derive_dedupe_key("report_issue", bot_id, category, resolved_target_kind, str(resolved_target_id), signal_signature, title),
        evidence=report_evidence,
        latest_correlation_id=latest_correlation_id,
    )
    await _collapse_existing_system_signals_for_report(db, report_item=item, signal_signature=signal_signature)
    return item


def _assignment_prompt(item: WorkspaceAttentionItem, instructions: str | None) -> str:
    steps = "\n".join(f"- {step}" for step in (item.next_steps or [])) or "- Investigate the item and report concise findings."
    extra = (instructions or "").strip()
    return (
        "[ATTENTION ASSIGNMENT]\n"
        f"Attention item id: {item.id}\n"
        f"Title: {item.title}\n"
        f"Severity: {item.severity}\n"
        f"Target: {item.target_kind}:{item.target_id}\n\n"
        f"Message:\n{item.message or '(none)'}\n\n"
        f"Requested next steps:\n{steps}\n\n"
        f"Assignment instructions:\n{extra or 'Investigate and report findings only. Do not execute fixes as part of this assignment.'}\n\n"
        "Use report_attention_assignment with this attention item id and your findings. "
        "Your final response should be the same concise findings for channel visibility."
    )


async def assign_attention_item(
    db: AsyncSession,
    item_id: uuid.UUID,
    *,
    bot_id: str,
    mode: str,
    instructions: str | None = None,
    assigned_by: str | None = None,
) -> WorkspaceAttentionItem:
    if mode not in VALID_ASSIGNMENT_MODES:
        raise ValidationError("assignment mode must be 'next_heartbeat' or 'run_now'")
    item = await get_attention_item(db, item_id)
    if item.status == "resolved":
        raise ValidationError("Cannot assign a resolved attention item.")
    channel = await db.get(Channel, item.channel_id) if item.channel_id else None
    if mode == "next_heartbeat":
        if channel is None:
            raise ValidationError("Next-heartbeat assignments require a channel target.")
        if channel.bot_id != bot_id:
            raise ValidationError("Next-heartbeat assignments must target the channel heartbeat bot. Use run_now for other bots.")
    try:
        from app.agent.bots import get_bot
        get_bot(bot_id)
    except Exception as exc:  # noqa: BLE001 - normalize registry errors for API callers
        raise ValidationError(f"Unknown bot: {bot_id}") from exc

    now = _now()
    item.assigned_bot_id = bot_id
    item.assignment_mode = mode
    item.assignment_status = "assigned"
    item.assignment_instructions = (instructions or "").strip() or None
    item.assigned_by = assigned_by
    item.assigned_at = now
    item.assignment_report = None
    item.assignment_reported_by = None
    item.assignment_reported_at = None
    item.updated_at = now
    item.requires_response = True

    if mode == "run_now":
        task = Task(
            bot_id=bot_id,
            client_id=channel.client_id if channel else None,
            session_id=channel.active_session_id if channel else None,
            channel_id=item.channel_id,
            prompt=_assignment_prompt(item, instructions),
            title=f"Attention: {item.title}",
            status="pending",
            task_type="attention_assignment",
            dispatch_type="none",
            dispatch_config={},
            callback_config={"attention_assignment": True, "attention_item_id": str(item.id)},
            execution_config={
                "history_mode": "none",
                "tools": ["report_attention_assignment"],
                "system_preamble": "You are handling an Attention assignment. Investigate and report findings only; do not execute fixes as assignment semantics.",
            },
            created_at=now,
        )
        db.add(task)
        await db.flush()
        item.assignment_task_id = task.id
        item.assignment_status = "running"

    await db.commit()
    await db.refresh(item)
    return item


async def unassign_attention_item(
    db: AsyncSession,
    item_id: uuid.UUID,
    *,
    actor: str | None = None,
) -> WorkspaceAttentionItem:
    item = await get_attention_item(db, item_id)
    item.assigned_bot_id = None
    item.assignment_mode = None
    item.assignment_status = None
    item.assignment_instructions = None
    item.assignment_task_id = None
    item.assigned_by = actor
    item.updated_at = _now()
    await db.commit()
    await db.refresh(item)
    return item


async def report_attention_assignment(
    db: AsyncSession,
    item_id: uuid.UUID,
    *,
    bot_id: str,
    findings: str,
    task_id: uuid.UUID | None = None,
) -> WorkspaceAttentionItem:
    item = await get_attention_item(db, item_id)
    if item.assigned_bot_id != bot_id:
        raise ValidationError("Only the assigned bot can report on this Attention Item.")
    findings = (findings or "").strip()
    if not findings:
        raise ValidationError("findings are required.")
    now = _now()
    item.assignment_report = findings[:8000]
    item.assignment_reported_by = bot_id
    item.assignment_reported_at = now
    item.assignment_status = "reported"
    item.assignment_task_id = task_id or item.assignment_task_id
    if item.status != "resolved":
        item.status = "responded"
        item.responded_at = item.responded_at or now
        item.responded_by = f"bot:{bot_id}"
    item.updated_at = now
    await db.commit()
    await db.refresh(item)
    return item


def _triage_item_payload(item: WorkspaceAttentionItem, channel_name: str | None = None) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "title": item.title,
        "severity": item.severity,
        "status": item.status,
        "source_type": item.source_type,
        "source_id": item.source_id,
        "channel_id": str(item.channel_id) if item.channel_id else None,
        "channel_name": channel_name,
        "target_kind": item.target_kind,
        "target_id": item.target_id,
        "message": item.message[:1600],
        "occurrence_count": item.occurrence_count,
        "next_steps": list(item.next_steps or [])[:8],
        "latest_correlation_id": str(item.latest_correlation_id) if item.latest_correlation_id else None,
        "first_seen_at": item.first_seen_at.isoformat() if item.first_seen_at else None,
        "last_seen_at": item.last_seen_at.isoformat() if item.last_seen_at else None,
        "evidence": item.evidence or {},
    }


def _operator_triage_prompt(items: list[WorkspaceAttentionItem], channel_names: dict[uuid.UUID, str]) -> str:
    payload = [
        _triage_item_payload(item, channel_names.get(item.channel_id) if item.channel_id else None)
        for item in items
    ]
    return (
        "[OPERATOR ATTENTION TRIAGE]\n"
        "You are the workspace operator triaging active Attention items. "
        "Your job is to reduce noise without hiding real work.\n\n"
        "Rules:\n"
        "- Treat Attention items as weak signals until evidence supports them.\n"
        "- Use read-only tools to inspect traces, tasks, recent runs, channel context, and memory when useful.\n"
        "- Do not modify code, configuration, channels, bots, tasks, widgets, or files during this run.\n"
        "- Classify every item exactly once.\n"
        "- Use report_attention_triage_batch before your final response.\n"
        "- Put benign, duplicate, expected, already_recovered, informational, or noise items in processed state.\n"
        "- Put true defects, unknown risks, user decisions, and likely Spindrel code issues in ready_for_review.\n"
        "- Include route recommendations when useful, for example developer_channel, owner_channel, automation, or acknowledge.\n"
        "- Treat route as internal metadata. Do not write phrases like 'route to developer channel' or 'route to development' in summary or suggested_action.\n"
        "- If route is developer_channel, suggested_action should name the concrete code path or behavior to fix and the regression coverage to add.\n"
        "- Before classifying, search your memory for prior Attention triage routing lessons.\n\n"
        "Output expectations for report_attention_triage_batch outcomes:\n"
        "- classification: benign | noise | duplicate | expected | already_recovered | informational | needs_review | needs_fix | likely_spindrel_code_issue | user_decision\n"
        "- review_required: true for anything the human should inspect or route onward.\n"
        "- confidence: low | medium | high.\n"
        "- summary: concise evidence-backed finding.\n"
        "- suggested_action: what the human should do next.\n"
        "- route: optional routing hint.\n\n"
        f"Attention items JSON:\n{json.dumps(payload, indent=2, default=str)}"
    )


def _reuse_active_operator_triage_run(
    items: list[WorkspaceAttentionItem],
    *,
    operator_model: str | None,
) -> dict[str, Any] | None:
    runs: dict[str, dict[str, Any]] = {}
    for item in items:
        triage = (item.evidence or {}).get("operator_triage")
        if not isinstance(triage, dict):
            continue
        if triage.get("state") not in {"queued", "running"}:
            continue
        session_id = str(triage.get("session_id") or "").strip()
        parent_channel_id = str(triage.get("parent_channel_id") or "").strip()
        if not session_id or not parent_channel_id:
            continue
        run = runs.setdefault(session_id, {
            "task_id": str(triage.get("task_id") or ""),
            "session_id": session_id,
            "parent_channel_id": parent_channel_id,
            "bot_id": str(triage.get("operator_bot_id") or OPERATOR_TRIAGE_BOT_ID),
            "status": "running",
            "item_count": 0,
            "model_override": None,
            "model_provider_id_override": None,
            "effective_model": operator_model,
            "created_at": triage.get("started_at"),
            "completed_at": None,
            "error": None,
            "_started_at": str(triage.get("started_at") or ""),
        })
        run["item_count"] += 1
        if str(triage.get("started_at") or "") > str(run.get("_started_at") or ""):
            run["_started_at"] = str(triage.get("started_at") or "")

    if not runs:
        return None

    selected = max(runs.values(), key=lambda run: (int(run.get("item_count") or 0), str(run.get("_started_at") or "")))
    return {key: value for key, value in selected.items() if not key.startswith("_")}


def _operator_triage_state(item: WorkspaceAttentionItem) -> str:
    triage = (item.evidence or {}).get("operator_triage")
    if not isinstance(triage, dict):
        return ""
    return str(triage.get("state") or "").strip()


def _is_operator_triage_sweep_candidate(item: WorkspaceAttentionItem) -> bool:
    if item.status not in VISIBLE_STATUSES:
        return False
    state = _operator_triage_state(item)
    return state in {"", "failed"}


async def _operator_channel(db: AsyncSession) -> Channel:
    from app.services.channels import ensure_orchestrator_channel

    await ensure_orchestrator_channel()
    channel = (await db.execute(
        select(Channel).where(Channel.client_id == "orchestrator:home").limit(1)
    )).scalar_one_or_none()
    if channel is None:
        raise ValidationError("Operator channel is unavailable.")
    return channel


async def create_attention_triage_run(
    db: AsyncSession,
    *,
    auth: Any,
    actor: str | None,
    model_override: str | None = None,
    model_provider_id_override: str | None = None,
) -> dict[str, Any]:
    items = await list_attention_items(db, auth=auth, include_resolved=False)
    visible = [item for item in items if item.status in VISIBLE_STATUSES]
    if not visible:
        raise ValidationError("No active Attention items to triage.")

    try:
        from app.agent.bots import get_bot
        operator_bot = get_bot(OPERATOR_TRIAGE_BOT_ID)
    except Exception as exc:  # noqa: BLE001
        raise ValidationError("Operator bot is unavailable.") from exc

    existing_run = _reuse_active_operator_triage_run(visible, operator_model=operator_bot.model)
    if existing_run is not None:
        return existing_run

    active = [item for item in visible if _is_operator_triage_sweep_candidate(item)]
    if not active:
        raise ValidationError("No untriaged Attention items to sweep.")

    operator_channel = await _operator_channel(db)
    from app.services.sub_sessions import spawn_ephemeral_session
    session = await spawn_ephemeral_session(
        db,
        bot_id=OPERATOR_TRIAGE_BOT_ID,
        parent_channel_id=operator_channel.id,
        context={
            "page_name": "Attention operator triage",
            "tags": ["attention", "operator-triage"],
            "payload": {
                "item_count": len(active),
                "actor": actor,
            },
            "tool_hints": [
                "search_memory",
                "get_trace",
                "list_tasks",
                OPERATOR_TRIAGE_TOOL_NAME,
            ],
        },
    )

    channel_ids = {item.channel_id for item in active if item.channel_id}
    channel_names: dict[uuid.UUID, str] = {}
    if channel_ids:
        rows = (await db.execute(select(Channel).where(Channel.id.in_(channel_ids)))).scalars().all()
        channel_names = {row.id: row.name for row in rows}

    clean_model_override = (model_override or "").strip() or None
    clean_provider_id_override = (model_provider_id_override or "").strip() or None
    if not clean_model_override:
        clean_provider_id_override = None

    task = Task(
        bot_id=OPERATOR_TRIAGE_BOT_ID,
        client_id=operator_channel.client_id,
        session_id=session.id,
        channel_id=operator_channel.id,
        prompt=_operator_triage_prompt(active, channel_names),
        title=f"Operator triage: {len(active)} Attention items",
        status="pending",
        task_type="attention_triage",
        dispatch_type="none",
        dispatch_config={},
        callback_config={
            "attention_triage": True,
            "attention_item_ids": [str(item.id) for item in active],
        },
        execution_config={
            "session_scoped": True,
            "external_delivery": "none",
            "history_mode": "none",
            "tools": [
                *sorted(OPERATOR_TRIAGE_ALLOWED_TOOLS - {OPERATOR_TRIAGE_TOOL_NAME}),
                OPERATOR_TRIAGE_TOOL_NAME,
            ],
            "exclude_tools": [
                tool_name
                for tool_name in (operator_bot.local_tools or [])
                if tool_name not in OPERATOR_TRIAGE_ALLOWED_TOOLS
            ],
            "system_preamble": (
                "You are running a read-only Attention triage sweep. "
                "Classify and report outcomes only. Do not mutate workspace state "
                "except by calling report_attention_triage_batch."
            ),
            "model_override": clean_model_override,
            "model_provider_id_override": clean_provider_id_override,
            "effective_model": clean_model_override or operator_bot.model,
        },
        created_at=_now(),
    )
    db.add(task)
    await db.flush()
    session.source_task_id = task.id
    session.title = task.title
    if isinstance(getattr(session, "metadata_", None), dict):
        session.metadata_ = {
            **(session.metadata_ or {}),
            "attention_triage_task_id": str(task.id),
            "attention_triage_item_count": len(active),
        }
        flag_modified(session, "metadata_")

    now = _now()
    for item in active:
        evidence = dict(item.evidence or {})
        triage = dict(evidence.get("operator_triage") or {})
        triage.update({
            "state": "running",
            "task_id": str(task.id),
            "session_id": str(session.id),
            "parent_channel_id": str(operator_channel.id),
            "operator_bot_id": OPERATOR_TRIAGE_BOT_ID,
            "started_by": actor,
            "started_at": now.isoformat(),
        })
        evidence["operator_triage"] = triage
        item.evidence = evidence
        item.assigned_bot_id = OPERATOR_TRIAGE_BOT_ID
        item.assignment_mode = "run_now"
        item.assignment_status = "running"
        item.assignment_task_id = task.id
        item.assigned_by = actor
        item.assigned_at = now
        item.updated_at = now
        flag_modified(item, "evidence")

    await db.commit()
    await db.refresh(task)
    return {
        "task_id": str(task.id),
        "session_id": str(session.id),
        "parent_channel_id": str(operator_channel.id),
        "bot_id": OPERATOR_TRIAGE_BOT_ID,
        "status": task.status,
        "item_count": len(active),
        "model_override": clean_model_override,
        "model_provider_id_override": clean_provider_id_override,
        "effective_model": clean_model_override or operator_bot.model,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "error": task.error,
    }


def _is_issue_intake_candidate(item: WorkspaceAttentionItem) -> bool:
    if item.status not in VISIBLE_STATUSES:
        return False
    evidence = item.evidence or {}
    if not isinstance(evidence, dict):
        return False
    if not (isinstance(evidence.get("issue_intake"), dict) or isinstance(evidence.get("report_issue"), dict)):
        return False
    triage = evidence.get("issue_triage")
    if isinstance(triage, dict) and triage.get("state") in {"packed", "dismissed", "needs_info"}:
        return False
    return True


def _issue_triage_payload(item: WorkspaceAttentionItem, channel_name: str | None = None) -> dict[str, Any]:
    evidence = item.evidence or {}
    return {
        "id": str(item.id),
        "source_type": item.source_type,
        "source_id": item.source_id,
        "channel_id": str(item.channel_id) if item.channel_id else None,
        "channel_name": channel_name,
        "target": f"{item.target_kind}:{item.target_id}",
        "severity": item.severity,
        "title": item.title,
        "message": item.message,
        "issue_intake": evidence.get("issue_intake") if isinstance(evidence, dict) else None,
        "agent_report": evidence.get("report_issue") if isinstance(evidence, dict) else None,
        "occurrence_count": item.occurrence_count,
        "last_seen_at": item.last_seen_at.isoformat() if item.last_seen_at else None,
    }


def _issue_intake_triage_prompt(items: list[WorkspaceAttentionItem], channel_names: dict[uuid.UUID, str]) -> str:
    payload = [
        _issue_triage_payload(item, channel_names.get(item.channel_id) if item.channel_id else None)
        for item in items
    ]
    return (
        "You are the workspace operator triaging raw issue intake into implementation-ready work packs.\n"
        "Inputs may include conversational issue dumps from users and autonomous agent blocker reports.\n\n"
        "Rules:\n"
        "- Group related items into the smallest useful work packs.\n"
        "- Create code work packs only when the evidence points to concrete implementation work.\n"
        "- Put config/setup/environment/user-decision/non-code items into non-code categories instead of forcing them into Project runs.\n"
        "- If an item is too vague, mark it needs_info and say what is missing.\n"
        "- Use report_issue_work_packs before your final response.\n"
        "- Do not launch Project coding runs. Humans approve launches later.\n\n"
        "Work pack categories: code_bug, test_failure, config_issue, environment_issue, user_decision, not_code_work, needs_info, other.\n"
        "Confidence: low, medium, high.\n\n"
        "Raw intake:\n"
        f"{json.dumps(payload, indent=2, default=str)}"
    )


async def create_issue_intake_triage_run(
    db: AsyncSession,
    *,
    auth: Any,
    actor: str | None,
    model_override: str | None = None,
    model_provider_id_override: str | None = None,
) -> dict[str, Any]:
    items = await list_attention_items(db, auth=auth, include_resolved=False)
    active = [item for item in items if _is_issue_intake_candidate(item)]
    if not active:
        raise ValidationError("No raw issue intake is ready to triage.")
    try:
        from app.agent.bots import get_bot
        operator_bot = get_bot(OPERATOR_TRIAGE_BOT_ID)
    except Exception as exc:  # noqa: BLE001
        raise ValidationError("Operator bot is unavailable.") from exc

    operator_channel = await _operator_channel(db)
    from app.services.sub_sessions import spawn_ephemeral_session
    session = await spawn_ephemeral_session(
        db,
        bot_id=OPERATOR_TRIAGE_BOT_ID,
        parent_channel_id=operator_channel.id,
        context={
            "page_name": "Issue intake triage",
            "tags": ["attention", "issue-intake", "work-packs"],
            "payload": {"item_count": len(active), "actor": actor},
            "tool_hints": ["read_conversation_history", "search_history", ISSUE_WORK_PACK_TOOL_NAME],
        },
    )

    channel_ids = {item.channel_id for item in active if item.channel_id}
    channel_names: dict[uuid.UUID, str] = {}
    if channel_ids:
        rows = (await db.execute(select(Channel).where(Channel.id.in_(channel_ids)))).scalars().all()
        channel_names = {row.id: row.name for row in rows}

    clean_model_override = (model_override or "").strip() or None
    clean_provider_id_override = (model_provider_id_override or "").strip() or None
    if not clean_model_override:
        clean_provider_id_override = None

    task = Task(
        bot_id=OPERATOR_TRIAGE_BOT_ID,
        client_id=operator_channel.client_id,
        session_id=session.id,
        channel_id=operator_channel.id,
        prompt=_issue_intake_triage_prompt(active, channel_names),
        title=f"Issue intake triage: {len(active)} items",
        status="pending",
        task_type="issue_intake_triage",
        dispatch_type="none",
        dispatch_config={},
        callback_config={
            "issue_intake_triage": True,
            "attention_item_ids": [str(item.id) for item in active],
        },
        execution_config={
            "session_scoped": True,
            "external_delivery": "none",
            "history_mode": "none",
            "tools": sorted(ISSUE_TRIAGE_ALLOWED_TOOLS),
            "exclude_tools": [
                tool_name
                for tool_name in (operator_bot.local_tools or [])
                if tool_name not in ISSUE_TRIAGE_ALLOWED_TOOLS
            ],
            "system_preamble": (
                "You are running a read-only issue-intake triage pass. "
                "Group, classify, and report work packs only. Do not mutate workspace state "
                "except by calling report_issue_work_packs."
            ),
            "model_override": clean_model_override,
            "model_provider_id_override": clean_provider_id_override,
            "effective_model": clean_model_override or operator_bot.model,
        },
        created_at=_now(),
    )
    db.add(task)
    await db.flush()
    session.source_task_id = task.id
    session.title = task.title
    if isinstance(getattr(session, "metadata_", None), dict):
        session.metadata_ = {
            **(session.metadata_ or {}),
            "issue_intake_triage_task_id": str(task.id),
            "issue_intake_item_count": len(active),
        }
        flag_modified(session, "metadata_")

    now = _now()
    for item in active:
        evidence = dict(item.evidence or {})
        triage = dict(evidence.get("issue_triage") or {})
        triage.update({
            "state": "running",
            "task_id": str(task.id),
            "session_id": str(session.id),
            "parent_channel_id": str(operator_channel.id),
            "operator_bot_id": OPERATOR_TRIAGE_BOT_ID,
            "started_by": actor,
            "started_at": now.isoformat(),
        })
        evidence["issue_triage"] = triage
        item.evidence = evidence
        item.assigned_bot_id = OPERATOR_TRIAGE_BOT_ID
        item.assignment_mode = "run_now"
        item.assignment_status = "running"
        item.assignment_task_id = task.id
        item.assigned_by = actor
        item.assigned_at = now
        item.updated_at = now
        flag_modified(item, "evidence")

    await db.commit()
    await db.refresh(task)
    return {
        "task_id": str(task.id),
        "session_id": str(session.id),
        "parent_channel_id": str(operator_channel.id),
        "bot_id": OPERATOR_TRIAGE_BOT_ID,
        "status": task.status,
        "item_count": len(active),
        "model_override": clean_model_override,
        "model_provider_id_override": clean_provider_id_override,
        "effective_model": clean_model_override or operator_bot.model,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "error": task.error,
    }


def _operator_triage_from_item(item: WorkspaceAttentionItem) -> dict[str, Any]:
    triage = (item.evidence or {}).get("operator_triage")
    return triage if isinstance(triage, dict) else {}


def _serialized_operator_triage(item: dict[str, Any]) -> dict[str, Any]:
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    triage = evidence.get("operator_triage") if isinstance(evidence, dict) else None
    return triage if isinstance(triage, dict) else {}


def _serialized_bot_report(item: dict[str, Any]) -> dict[str, Any]:
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    report = evidence.get("report_issue") if isinstance(evidence, dict) else None
    return report if isinstance(report, dict) else {}


def _serialized_target_label(item: dict[str, Any]) -> str:
    return str(item.get("channel_name") or item.get("target_id") or item.get("target_kind") or "workspace")


def _brief_item_ref(item: dict[str, Any]) -> dict[str, Any]:
    triage = _serialized_operator_triage(item)
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "severity": item.get("severity"),
        "target_kind": item.get("target_kind"),
        "target_id": item.get("target_id"),
        "target_label": _serialized_target_label(item),
        "channel_id": item.get("channel_id"),
        "channel_name": item.get("channel_name"),
        "route": triage.get("route"),
        "classification": triage.get("classification"),
        "summary": triage.get("summary") or item.get("assignment_report") or item.get("message"),
    }


def _brief_code_pack_key(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "attention").lower()
    title = re.sub(r"\s+failed$", "", title)
    title = re.sub(r"\s+error$", "", title)
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    error_kind = evidence.get("error_kind") if isinstance(evidence, dict) else None
    return normalize_dedupe_key(str(error_kind or title or item.get("dedupe_key") or "code-fix"))


def _brief_category(item: dict[str, Any]) -> str:
    triage = _serialized_operator_triage(item)
    report = _serialized_bot_report(item)
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    text = " ".join(
        str(value or "")
        for value in (
            item.get("title"),
            item.get("message"),
            item.get("assignment_report"),
            triage.get("classification"),
            triage.get("route"),
            triage.get("summary"),
            triage.get("suggested_action"),
            report.get("category"),
            report.get("summary"),
            report.get("suggested_action"),
            evidence.get("classification") if isinstance(evidence, dict) else None,
            evidence.get("error_kind") if isinstance(evidence, dict) else None,
        )
    ).lower()
    route = str(triage.get("route") or "").lower()
    classification = str(triage.get("classification") or "").lower()
    triage_state = str(triage.get("state") or "").lower()
    report_category = str(report.get("category") or "").lower()

    if triage_state in {"running", "queued"}:
        return "running"
    if triage_state == "processed":
        return "cleared"
    if report_category in {"missing_permission", "user_decision", "setup_issue"}:
        return "decision"
    if report_category in {"blocked", "system_issue"}:
        return "blocker"
    if route in {"owner_channel", "user_decision"} or classification == "user_decision":
        return "decision"
    if "permission" in text or "grant scopes" in text:
        return "decision"
    if (
        route == "developer_channel"
        or classification in {"likely_spindrel_code_issue", "needs_fix"}
        or "code fix" in text
        or "platform_contract" in text
        or "server-side" in text
    ):
        return "fix_pack"
    if triage_state == "ready_for_review" or triage.get("review_required") is True:
        return "blocker"
    if item.get("severity") in {"critical", "error"} and int(item.get("occurrence_count") or 0) >= 3:
        return "fix_pack"
    return "quiet"


def _make_attention_brief_card(item: dict[str, Any], *, kind: str) -> dict[str, Any]:
    triage = _serialized_operator_triage(item)
    report = _serialized_bot_report(item)
    summary = (
        triage.get("summary")
        or report.get("summary")
        or item.get("assignment_report")
        or item.get("message")
        or "Review the evidence before taking action."
    )
    action_label = "Review finding"
    if kind == "decision":
        action_label = "Make decision"
    elif kind == "fix_pack":
        action_label = "Open fix pack"
    elif kind == "blocker":
        action_label = "Inspect blocker"
    return {
        "id": item.get("id"),
        "kind": kind,
        "title": item.get("title"),
        "summary": str(summary)[:700],
        "severity": item.get("severity"),
        "target_label": _serialized_target_label(item),
        "item_ids": [item.get("id")],
        "action_label": action_label,
        "action": {"type": "open_item", "item_id": item.get("id")},
    }


def _make_fix_pack(pack_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    refs = [_brief_item_ref(item) for item in items]
    primary = refs[0]
    target_counts: dict[str, int] = {}
    for ref in refs:
        target = str(ref.get("target_label") or "workspace")
        target_counts[target] = target_counts.get(target, 0) + 1
    target_summary = ", ".join(
        f"{label} ({count})" if count > 1 else label
        for label, count in sorted(target_counts.items(), key=lambda row: (-row[1], row[0]))[:4]
    )
    summary = str(primary.get("summary") or "Related operator findings point to the same fix area.").strip()
    prompt = (
        f"Fix the Attention issue group '{primary.get('title')}'. "
        f"Targets: {target_summary or primary.get('target_label')}. "
        f"Evidence: {summary[:900]} "
        "Start with a regression test, fix the root cause, and keep unrelated changes out."
    )
    return {
        "id": pack_id,
        "title": str(primary.get("title") or "Code fix"),
        "summary": summary[:700],
        "count": len(items),
        "severity": max((str(item.get("severity") or "warning") for item in items), key=lambda value: _severity_rank(value)),
        "target_summary": target_summary,
        "item_ids": [item.get("id") for item in items],
        "items": refs,
        "prompt": prompt,
        "action_label": "Copy fix prompt",
        "action": {"type": "copy_prompt", "prompt": prompt},
    }


def build_attention_brief_from_serialized(
    items: list[dict[str, Any]],
    *,
    autofix_queue: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a read-only operator brief from serialized Attention items."""
    blockers: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    quiet: list[dict[str, Any]] = []
    running: list[dict[str, Any]] = []
    cleared: list[dict[str, Any]] = []
    fix_pack_groups: dict[str, list[dict[str, Any]]] = {}
    autofix_queue = autofix_queue or []

    for item in items:
        category = _brief_category(item)
        if category == "fix_pack":
            fix_pack_groups.setdefault(_brief_code_pack_key(item), []).append(item)
        elif category == "decision":
            decisions.append(_make_attention_brief_card(item, kind="decision"))
        elif category == "blocker":
            blockers.append(_make_attention_brief_card(item, kind="blocker"))
        elif category == "running":
            running.append(_brief_item_ref(item))
        elif category == "cleared":
            cleared.append(_brief_item_ref(item))
        else:
            quiet.append(_brief_item_ref(item))

    fix_packs = [
        _make_fix_pack(pack_id, sorted(group, key=lambda item: -int(item.get("occurrence_count") or 0)))
        for pack_id, group in sorted(fix_pack_groups.items(), key=lambda row: (-len(row[1]), row[0]))
    ]
    next_action: dict[str, Any]
    if decisions:
        first = decisions[0]
        next_action = {
            "kind": "decision",
            "title": "Make the first owner decision",
            "description": first["summary"],
            "action_label": first["action_label"],
            "item_id": first["id"],
        }
    elif autofix_queue:
        first_request = autofix_queue[0]
        next_action = {
            "kind": "autofix",
            "title": "Review the first agent repair",
            "description": first_request.get("summary") or "A queued readiness repair is waiting for approval.",
            "action_label": "Review autofix",
            "item_id": None,
            "receipt_id": first_request.get("receipt_id"),
            "action_id": first_request.get("action_id"),
        }
    elif fix_packs:
        first_pack = fix_packs[0]
        next_action = {
            "kind": "fix_pack",
            "title": "Open the first fix pack",
            "description": first_pack["summary"],
            "action_label": "Open evidence",
            "item_id": first_pack["item_ids"][0] if first_pack["item_ids"] else None,
            "fix_pack_id": first_pack["id"],
        }
    elif blockers:
        first = blockers[0]
        next_action = {
            "kind": "blocker",
            "title": "Inspect the first blocker",
            "description": first["summary"],
            "action_label": first["action_label"],
            "item_id": first["id"],
        }
    elif quiet:
        next_action = {
            "kind": "quiet_digest",
            "title": "No high-signal action",
            "description": f"{len(quiet)} lower-priority item{'s' if len(quiet) != 1 else ''} are available as evidence.",
            "action_label": "Review evidence",
            "item_id": quiet[0].get("id") if quiet else None,
        }
    else:
        next_action = {
            "kind": "empty",
            "title": "Nothing needs review",
            "description": "No active Attention items are waiting.",
            "action_label": None,
            "item_id": None,
        }

    quiet_groups: dict[str, int] = {}
    for item in quiet:
        label = str(item.get("classification") or item.get("severity") or "other")
        quiet_groups[label] = quiet_groups.get(label, 0) + 1
    return {
        "generated_at": _now().isoformat(),
        "summary": {
            "autofix": len(autofix_queue),
            "blockers": len(blockers),
            "fix_packs": len(fix_packs),
            "decisions": len(decisions),
            "quiet": len(quiet),
            "running": len(running),
            "cleared": len(cleared),
            "total": len(items),
        },
        "next_action": next_action,
        "blockers": blockers[:6],
        "fix_packs": fix_packs[:8],
        "decisions": decisions[:8],
        "autofix_queue": autofix_queue[:10],
        "quiet_digest": {
            "count": len(quiet),
            "groups": [
                {"label": label.replace("_", " "), "count": count}
                for label, count in sorted(quiet_groups.items(), key=lambda row: (-row[1], row[0]))[:8]
            ],
        },
        "running": running[:8],
        "cleared": cleared[:8],
    }


async def get_attention_brief(
    db: AsyncSession,
    *,
    auth: Any,
    channel_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    items = await list_attention_items(db, auth=auth, channel_id=channel_id, include_resolved=False)
    serialized = await serialize_attention_items(db, items)
    from app.services.agent_capabilities import agent_readiness_autofix_queue_payload

    autofix_queue = await agent_readiness_autofix_queue_payload(
        db,
        channel_id=channel_id,
        limit=10,
    )
    return build_attention_brief_from_serialized(serialized, autofix_queue=autofix_queue)


async def serialize_issue_work_pack(db: AsyncSession, pack: IssueWorkPack) -> dict[str, Any]:
    project = await db.get(Project, pack.project_id) if pack.project_id else None
    channel = await db.get(Channel, pack.channel_id) if pack.channel_id else None
    launched_task = await db.get(Task, pack.launched_task_id) if pack.launched_task_id else None
    return {
        "id": str(pack.id),
        "title": pack.title,
        "summary": pack.summary,
        "category": pack.category,
        "confidence": pack.confidence,
        "status": pack.status,
        "source_item_ids": [str(item_id) for item_id in (pack.source_item_ids or [])],
        "launch_prompt": pack.launch_prompt,
        "triage_task_id": str(pack.triage_task_id) if pack.triage_task_id else None,
        "project_id": str(pack.project_id) if pack.project_id else None,
        "project_name": project.name if project else None,
        "channel_id": str(pack.channel_id) if pack.channel_id else None,
        "channel_name": channel.name if channel else None,
        "launched_task_id": str(pack.launched_task_id) if pack.launched_task_id else None,
        "launched_task_status": launched_task.status if launched_task else None,
        "metadata": pack.metadata_ or {},
        "created_at": pack.created_at.isoformat() if pack.created_at else None,
        "updated_at": pack.updated_at.isoformat() if pack.updated_at else None,
    }


async def list_issue_work_packs(
    db: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    clauses = []
    if status:
        clauses.append(IssueWorkPack.status == status)
    stmt = select(IssueWorkPack)
    if clauses:
        stmt = stmt.where(*clauses)
    stmt = stmt.order_by(desc(IssueWorkPack.updated_at), desc(IssueWorkPack.created_at)).limit(max(1, min(limit, 100)))
    packs = list((await db.execute(stmt)).scalars().all())
    return [await serialize_issue_work_pack(db, pack) for pack in packs]


async def get_issue_work_pack(db: AsyncSession, pack_id: uuid.UUID) -> IssueWorkPack:
    pack = await db.get(IssueWorkPack, pack_id)
    if pack is None:
        raise NotFoundError("Issue work pack not found.")
    return pack


async def launch_issue_work_pack_project_run(
    db: AsyncSession,
    *,
    pack_id: uuid.UUID,
    project_id: uuid.UUID,
    channel_id: uuid.UUID,
    actor: str | None = None,
) -> dict[str, Any]:
    pack = await get_issue_work_pack(db, pack_id)
    if pack.status == "dismissed":
        raise ValidationError("Dismissed work packs cannot be launched.")
    if pack.status == "needs_info":
        raise ValidationError("Work packs that need more information cannot be launched.")
    project = await db.get(Project, project_id)
    if project is None:
        raise NotFoundError("Project not found.")
    from app.services.project_coding_runs import ProjectCodingRunCreate, create_project_coding_run, get_project_coding_run

    request = (
        f"{pack.launch_prompt.strip()}\n\n"
        f"[Issue work pack]\n"
        f"- Work pack id: {pack.id}\n"
        f"- Category: {pack.category}\n"
        f"- Confidence: {pack.confidence}\n"
        f"- Source Attention items: {', '.join(str(item_id) for item_id in (pack.source_item_ids or []))}\n"
    )
    task = await create_project_coding_run(
        db,
        project,
        ProjectCodingRunCreate(
            channel_id=channel_id,
            request=request,
            source_work_pack_id=pack.id,
        ),
    )
    pack.status = "launched"
    pack.project_id = project.id
    pack.channel_id = channel_id
    pack.launched_task_id = task.id
    pack.updated_at = _now()
    metadata = dict(pack.metadata_ or {})
    metadata["launched_by"] = actor
    metadata["launched_at"] = pack.updated_at.isoformat()
    pack.metadata_ = metadata
    flag_modified(pack, "metadata_")
    await db.commit()
    await db.refresh(pack)
    return {
        "work_pack": await serialize_issue_work_pack(db, pack),
        "run": await get_project_coding_run(db, project, task.id),
    }


def _attention_item_visible_to_auth(item: WorkspaceAttentionItem, auth: Any) -> bool:
    return _is_admin_auth(auth) or item.source_type in {"bot", "user"}


def _triage_run_counts(items: list[WorkspaceAttentionItem]) -> dict[str, int]:
    counts = {
        "total": len(items),
        "running": 0,
        "processed": 0,
        "ready_for_review": 0,
        "failed": 0,
        "unreported": 0,
    }
    for item in items:
        triage = _operator_triage_from_item(item)
        state = str(triage.get("state") or "").strip()
        if state in {"running", "queued"}:
            counts["running"] += 1
        elif state == "processed":
            counts["processed"] += 1
        elif state == "ready_for_review" or triage.get("review_required") is True:
            counts["ready_for_review"] += 1
        elif state == "failed":
            counts["failed"] += 1
        else:
            counts["unreported"] += 1
    return counts


def _triage_run_status(task: Task, items: list[WorkspaceAttentionItem]) -> str:
    if task.status in {"pending", "queued"}:
        return "queued"
    if task.status == "running":
        return "running"
    if task.status in {"failed", "cancelled", "error"}:
        return "failed"
    if any(_operator_triage_from_item(item).get("state") in {"running", "queued"} for item in items):
        return "running"
    if any(_operator_triage_from_item(item).get("state") == "failed" for item in items):
        return "failed"
    return "complete" if task.status == "complete" else task.status


async def _attention_items_for_triage_task(
    db: AsyncSession,
    task: Task,
    *,
    auth: Any,
) -> list[WorkspaceAttentionItem]:
    raw_ids = (task.callback_config or {}).get("attention_item_ids") or []
    parsed_ids: list[uuid.UUID] = []
    for raw_id in raw_ids:
        try:
            parsed_ids.append(uuid.UUID(str(raw_id)))
        except (TypeError, ValueError):
            continue
    if not parsed_ids:
        return []
    rows = list((await db.execute(
        select(WorkspaceAttentionItem).where(WorkspaceAttentionItem.id.in_(parsed_ids))
    )).scalars().all())
    by_id = {row.id: row for row in rows if _attention_item_visible_to_auth(row, auth)}
    return [by_id[item_id] for item_id in parsed_ids if item_id in by_id]


async def serialize_attention_triage_run(
    db: AsyncSession,
    task: Task,
    *,
    auth: Any,
) -> dict[str, Any]:
    items = await _attention_items_for_triage_task(db, task, auth=auth)
    serialized_items = await serialize_attention_items(db, items)
    execution_config = task.execution_config or {}
    return {
        "task_id": str(task.id),
        "session_id": str(task.session_id) if task.session_id else None,
        "parent_channel_id": str(task.channel_id) if task.channel_id else None,
        "bot_id": task.bot_id,
        "status": _triage_run_status(task, items),
        "task_status": task.status,
        "item_count": len(items),
        "counts": _triage_run_counts(items),
        "items": serialized_items,
        "model_override": execution_config.get("model_override"),
        "model_provider_id_override": execution_config.get("model_provider_id_override"),
        "effective_model": execution_config.get("effective_model") or execution_config.get("model_override") or None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "error": task.error,
    }


async def list_attention_triage_runs(
    db: AsyncSession,
    *,
    auth: Any,
    limit: int = 20,
) -> list[dict[str, Any]]:
    capped_limit = max(1, min(int(limit or 20), 50))
    tasks = list((await db.execute(
        select(Task)
        .where(Task.task_type == "attention_triage")
        .order_by(desc(Task.created_at))
        .limit(capped_limit)
    )).scalars().all())
    return [await serialize_attention_triage_run(db, task, auth=auth) for task in tasks]


async def get_attention_triage_run(
    db: AsyncSession,
    *,
    auth: Any,
    task_id: uuid.UUID,
) -> dict[str, Any]:
    task = await db.get(Task, task_id)
    if task is None or task.task_type != "attention_triage":
        raise NotFoundError("Operator triage run not found.")
    return await serialize_attention_triage_run(db, task, auth=auth)


def _normalize_triage_classification(value: Any) -> str:
    text = normalize_dedupe_key(str(value or "needs_review")).replace("-", "_")
    return text or "needs_review"


def _triage_review_required(outcome: dict[str, Any], classification: str) -> bool:
    raw = outcome.get("review_required")
    if isinstance(raw, bool):
        return raw
    return classification not in OPERATOR_TRIAGE_PROCESSED_CLASSIFICATIONS


def _normalize_triage_suggested_action(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\b[Rr]oute to (the )?developer channel\b", "Open a code fix", text)
    text = re.sub(r"\b[Rr]oute to development\b", "Open a code fix", text)
    text = re.sub(r"\b[Rr]oute to dev\b", "Open a code fix", text)
    text = re.sub(r"\bdeveloper channel\b", "code fix", text, flags=re.IGNORECASE)
    return text.strip()


async def report_attention_triage_batch(
    db: AsyncSession,
    *,
    bot_id: str,
    outcomes: list[dict[str, Any]],
) -> list[WorkspaceAttentionItem]:
    if not outcomes:
        raise ValidationError("outcomes are required.")
    now = _now()
    updated: list[WorkspaceAttentionItem] = []
    for outcome in outcomes:
        raw_id = outcome.get("item_id") or outcome.get("id")
        try:
            item_id = uuid.UUID(str(raw_id))
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"Invalid Attention item id: {raw_id!r}") from exc
        item = await get_attention_item(db, item_id)
        if item.assigned_bot_id != bot_id:
            raise ValidationError("Only the assigned operator can report triage outcomes.")
        classification = _normalize_triage_classification(outcome.get("classification"))
        review_required = _triage_review_required(outcome, classification)
        confidence = str(outcome.get("confidence") or "medium").lower()
        if confidence not in {"low", "medium", "high"}:
            confidence = "medium"
        summary = str(outcome.get("summary") or outcome.get("findings") or "").strip()
        suggested_action = _normalize_triage_suggested_action(outcome.get("suggested_action") or outcome.get("action"))
        route = str(outcome.get("route") or "").strip() or None

        evidence = dict(item.evidence or {})
        previous = dict(evidence.get("operator_triage") or {})
        triage = {
            **previous,
            "state": "ready_for_review" if review_required else "processed",
            "classification": classification,
            "confidence": confidence,
            "summary": summary[:4000],
            "suggested_action": suggested_action[:2000],
            "route": route[:200] if route else None,
            "review_required": review_required,
            "reported_by": bot_id,
            "reported_at": now.isoformat(),
        }
        evidence["operator_triage"] = triage
        item.evidence = evidence
        item.assignment_report = summary[:8000] or suggested_action[:8000] or classification
        item.assignment_reported_by = bot_id
        item.assignment_reported_at = now
        item.assignment_status = "reported"
        item.responded_at = item.responded_at or now
        item.responded_by = f"bot:{bot_id}"
        item.status = "responded" if review_required else "acknowledged"
        item.updated_at = now
        flag_modified(item, "evidence")
        updated.append(item)
    await db.commit()
    for item in updated:
        await db.refresh(item)
    return updated


def _normalize_work_pack_category(value: Any) -> str:
    category = normalize_dedupe_key(str(value or "code_bug")).replace("-", "_")
    return category if category in ISSUE_WORK_PACK_CATEGORIES else "other"


def _normalize_confidence(value: Any) -> str:
    confidence = str(value or "medium").strip().lower()
    return confidence if confidence in {"low", "medium", "high"} else "medium"


async def create_manual_issue_work_pack(
    db: AsyncSession,
    *,
    actor: str | None,
    title: str,
    summary: str,
    category: str,
    confidence: str,
    source_item_ids: list[str],
    launch_prompt: str = "",
    project_id: uuid.UUID | None = None,
    channel_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> IssueWorkPack:
    clean_title = str(title or "").strip()
    clean_summary = str(summary or "").strip()
    if not clean_title:
        raise ValidationError("title is required.")
    parsed_item_ids: list[str] = []
    for raw in source_item_ids or []:
        try:
            item_id = str(uuid.UUID(str(raw)))
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"Invalid source item id: {raw!r}") from exc
        item = await db.get(WorkspaceAttentionItem, uuid.UUID(item_id))
        if item is None:
            raise ValidationError(f"Source attention item not found: {item_id}")
        if item_id not in parsed_item_ids:
            parsed_item_ids.append(item_id)
    if not parsed_item_ids:
        raise ValidationError("At least one source item id is required.")
    if project_id and await db.get(Project, project_id) is None:
        raise ValidationError("Project not found.")
    if channel_id and await db.get(Channel, channel_id) is None:
        raise ValidationError("Channel not found.")

    normalized_category = _normalize_work_pack_category(category)
    normalized_confidence = _normalize_confidence(confidence)
    prompt = str(launch_prompt or "").strip() or (
        f"{clean_title}\n\n"
        f"{clean_summary}\n\n"
        "Use the linked issue intake as evidence. Start with a regression test where applicable, "
        "fix the root cause, run focused verification, and publish a Project run receipt."
    )
    now = _now()
    pack = IssueWorkPack(
        title=clean_title[:500],
        summary=clean_summary[:8000],
        category=normalized_category,
        confidence=normalized_confidence,
        status="needs_info" if normalized_category == "needs_info" else "proposed",
        source_item_ids=parsed_item_ids,
        launch_prompt=prompt[:12000],
        project_id=project_id,
        channel_id=channel_id,
        metadata_={
            **(metadata or {}),
            "created_by": actor,
            "created_at": now.isoformat(),
            "source": "manual",
        },
        created_at=now,
        updated_at=now,
    )
    db.add(pack)
    await db.flush()
    for item_id in parsed_item_ids:
        item = await db.get(WorkspaceAttentionItem, uuid.UUID(item_id))
        if item is None:
            continue
        evidence = dict(item.evidence or {})
        triage = dict(evidence.get("issue_triage") or {})
        pack_ids = list(triage.get("work_pack_ids") or [])
        if str(pack.id) not in pack_ids:
            pack_ids.append(str(pack.id))
        triage.update({
            "state": "packed" if pack.status == "proposed" else pack.status,
            "work_pack_ids": pack_ids,
            "manual": True,
            "actor": actor,
            "updated_at": now.isoformat(),
        })
        evidence["issue_triage"] = triage
        item.evidence = evidence
        item.updated_at = now
        flag_modified(item, "evidence")
    await db.commit()
    await db.refresh(pack)
    return pack


async def report_issue_work_packs(
    db: AsyncSession,
    *,
    bot_id: str,
    triage_task_id: uuid.UUID | None,
    packs: list[dict[str, Any]],
    item_outcomes: list[dict[str, Any]] | None = None,
) -> list[IssueWorkPack]:
    if not triage_task_id:
        raise ValidationError("Issue work-pack reporting requires a triage task context.")
    task = await db.get(Task, triage_task_id)
    if task is None or task.task_type != "issue_intake_triage":
        raise ValidationError("Issue work packs can only be reported from an issue-intake triage task.")
    if task.bot_id != bot_id:
        raise ValidationError("Only the assigned operator can report issue work packs.")
    if not packs:
        raise ValidationError("At least one work pack is required.")

    allowed_item_ids = {
        str(raw_id)
        for raw_id in ((task.callback_config or {}).get("attention_item_ids") or [])
    }
    now = _now()
    created: list[IssueWorkPack] = []
    item_pack_ids: dict[str, list[str]] = {}

    for pack in packs:
        title = str(pack.get("title") or "").strip()
        summary = str(pack.get("summary") or "").strip()
        launch_prompt = str(pack.get("launch_prompt") or pack.get("prompt") or "").strip()
        if not title:
            raise ValidationError("Each work pack needs a title.")
        source_ids: list[str] = []
        for raw in pack.get("source_item_ids") or pack.get("item_ids") or []:
            try:
                item_id = str(uuid.UUID(str(raw)))
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"Invalid source item id: {raw!r}") from exc
            if item_id not in allowed_item_ids:
                raise ValidationError("Work pack references an item outside this triage run.")
            if item_id not in source_ids:
                source_ids.append(item_id)
        if not source_ids:
            raise ValidationError("Each work pack needs at least one source item id.")
        category = _normalize_work_pack_category(pack.get("category"))
        confidence = _normalize_confidence(pack.get("confidence"))
        if not launch_prompt:
            launch_prompt = (
                f"{title}\n\n"
                f"{summary}\n\n"
                "Use the linked issue intake as evidence. Start with a regression test where applicable, "
                "fix the root cause, run focused verification, and publish a Project run receipt."
            )
        work_pack = IssueWorkPack(
            title=title[:500],
            summary=summary[:8000],
            category=category,
            confidence=confidence,
            status="needs_info" if category == "needs_info" else "proposed",
            source_item_ids=source_ids,
            launch_prompt=launch_prompt[:12000],
            triage_task_id=task.id,
            metadata_={
                "rationale": str(pack.get("rationale") or "").strip()[:4000] or None,
                "target_project_hint": str(pack.get("target_project_hint") or pack.get("project_hint") or "").strip()[:300] or None,
                "target_channel_hint": str(pack.get("target_channel_hint") or pack.get("channel_hint") or "").strip()[:300] or None,
                "non_code_reason": str(pack.get("non_code_reason") or "").strip()[:2000] or None,
                "reported_by": bot_id,
                "reported_at": now.isoformat(),
            },
            created_at=now,
            updated_at=now,
        )
        db.add(work_pack)
        await db.flush()
        created.append(work_pack)
        for item_id in source_ids:
            item_pack_ids.setdefault(item_id, []).append(str(work_pack.id))

    outcomes_by_id: dict[str, dict[str, Any]] = {}
    for outcome in item_outcomes or []:
        raw_id = outcome.get("item_id") or outcome.get("id")
        try:
            item_id = str(uuid.UUID(str(raw_id)))
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"Invalid outcome item id: {raw_id!r}") from exc
        if item_id not in allowed_item_ids:
            raise ValidationError("Item outcome references an item outside this triage run.")
        outcomes_by_id[item_id] = outcome

    for raw_id in allowed_item_ids:
        item = await db.get(WorkspaceAttentionItem, uuid.UUID(raw_id))
        if item is None:
            continue
        outcome = outcomes_by_id.get(raw_id, {})
        pack_ids = item_pack_ids.get(raw_id, [])
        disposition = str(outcome.get("disposition") or ("packed" if pack_ids else "dismissed")).strip().lower()
        if disposition not in {"packed", "dismissed", "needs_info"}:
            disposition = "packed" if pack_ids else "dismissed"
        evidence = dict(item.evidence or {})
        triage = dict(evidence.get("issue_triage") or {})
        triage.update({
            "state": disposition,
            "task_id": str(task.id),
            "session_id": str(task.session_id) if task.session_id else triage.get("session_id"),
            "operator_bot_id": bot_id,
            "work_pack_ids": pack_ids,
            "summary": str(outcome.get("summary") or "").strip()[:4000] or triage.get("summary"),
            "reported_by": bot_id,
            "reported_at": now.isoformat(),
        })
        evidence["issue_triage"] = triage
        item.evidence = evidence
        item.assignment_status = "reported"
        item.assignment_report = triage.get("summary") or ("Grouped into work pack." if pack_ids else "Dismissed during issue triage.")
        item.assignment_reported_by = bot_id
        item.assignment_reported_at = now
        item.responded_at = item.responded_at or now
        item.responded_by = f"bot:{bot_id}"
        item.status = "responded" if disposition in {"packed", "needs_info"} else "acknowledged"
        item.updated_at = now
        flag_modified(item, "evidence")

    await db.commit()
    for pack in created:
        await db.refresh(pack)
    return created


def _feedback_memory_line(item: WorkspaceAttentionItem, verdict: str, note: str | None, route: str | None) -> str:
    triage = (item.evidence or {}).get("operator_triage") or {}
    return (
        f"- {datetime.now(timezone.utc).date().isoformat()} "
        f"verdict={verdict} route={route or triage.get('route') or 'none'} "
        f"classification={triage.get('classification') or 'unknown'} "
        f"title={item.title!r}"
        + (f" note={note.strip()!r}" if note and note.strip() else "")
    )


def _append_operator_triage_memory(item: WorkspaceAttentionItem, verdict: str, note: str | None, route: str | None) -> None:
    try:
        from app.agent.bots import get_bot
        from app.services.memory_scheme import get_memory_root
        from app.services.workspace import workspace_service

        bot = get_bot(OPERATOR_TRIAGE_BOT_ID)
        ws_root = workspace_service.get_workspace_root(OPERATOR_TRIAGE_BOT_ID, bot)
        memory_root = Path(get_memory_root(bot, ws_root=ws_root))
        memory_root.mkdir(parents=True, exist_ok=True)
        reference_dir = memory_root / "reference"
        reference_dir.mkdir(parents=True, exist_ok=True)
        path = reference_dir / "attention-triage-routing.md"
        if not path.exists():
            path.write_text(
                "# Attention triage routing\n\n"
                "Operator review feedback. Read this before future bulk Attention triage runs.\n\n",
                encoding="utf-8",
            )
        with path.open("a", encoding="utf-8") as fh:
            fh.write(_feedback_memory_line(item, verdict, note, route) + "\n")
    except Exception:
        logger.debug("Failed to append operator triage memory for item %s", item.id, exc_info=True)


async def record_attention_triage_feedback(
    db: AsyncSession,
    item_id: uuid.UUID,
    *,
    verdict: str,
    actor: str | None,
    note: str | None = None,
    route: str | None = None,
) -> WorkspaceAttentionItem:
    verdict = str(verdict or "").strip().lower()
    if verdict not in {"confirmed", "wrong", "rerouted"}:
        raise ValidationError("verdict must be confirmed, wrong, or rerouted.")
    item = await get_attention_item(db, item_id)
    evidence = dict(item.evidence or {})
    triage = dict(evidence.get("operator_triage") or {})
    review = {
        "verdict": verdict,
        "reviewed_by": actor,
        "reviewed_at": _now().isoformat(),
        "note": (note or "").strip()[:2000] or None,
        "route": (route or "").strip()[:200] or triage.get("route"),
    }
    triage["review"] = review
    if verdict == "rerouted" and route:
        triage["route"] = route.strip()[:200]
    if verdict in {"wrong", "rerouted"}:
        triage["state"] = "ready_for_review"
        triage["review_required"] = True
    evidence["operator_triage"] = triage
    item.evidence = evidence
    if verdict in {"wrong", "rerouted"} and item.status == "acknowledged":
        item.status = "responded"
        item.responded_at = item.responded_at or _now()
        item.responded_by = actor or item.responded_by
    item.updated_at = _now()
    flag_modified(item, "evidence")
    await db.commit()
    await db.refresh(item)
    _append_operator_triage_memory(item, verdict, note, route)
    return item


async def on_attention_triage_task_complete(task_id: uuid.UUID, status: str) -> None:
    async with async_session() as db:
        task = await db.get(Task, task_id)
        if task is None:
            return
        cb = task.callback_config or {}
        if not cb.get("attention_triage"):
            return
        raw_ids = cb.get("attention_item_ids") or []
        now = _now()
        for raw_id in raw_ids:
            try:
                item = await db.get(WorkspaceAttentionItem, uuid.UUID(str(raw_id)))
            except (TypeError, ValueError):
                continue
            if item is None:
                continue
            evidence = dict(item.evidence or {})
            triage = dict(evidence.get("operator_triage") or {})
            if triage.get("state") not in {"running", "queued"}:
                continue
            if status == "complete":
                message = "Operator triage completed without a structured outcome. Review manually."
                triage.update({
                    "state": "ready_for_review",
                    "classification": "needs_review",
                    "confidence": "low",
                    "summary": message,
                    "suggested_action": "Review this item directly or rerun operator triage.",
                    "review_required": True,
                    "reported_by": f"task:{task.id}",
                    "reported_at": now.isoformat(),
                })
                item.assignment_status = "reported"
                item.status = "responded" if item.status != "resolved" else item.status
                item.responded_at = item.responded_at or now
                item.responded_by = f"task:{task.id}"
            else:
                message = task.error or f"Operator triage ended with status {status}."
                triage.update({
                    "state": "failed",
                    "error": message,
                    "reported_at": now.isoformat(),
                })
                item.assignment_status = "cancelled"
            evidence["operator_triage"] = triage
            item.evidence = evidence
            item.assignment_report = message
            item.assignment_reported_by = f"task:{task.id}"
            item.assignment_reported_at = now
            item.updated_at = now
            flag_modified(item, "evidence")
        await db.commit()


async def on_issue_intake_triage_task_complete(task_id: uuid.UUID, status: str) -> None:
    async with async_session() as db:
        task = await db.get(Task, task_id)
        if task is None:
            return
        cb = task.callback_config or {}
        if not cb.get("issue_intake_triage"):
            return
        raw_ids = cb.get("attention_item_ids") or []
        now = _now()
        for raw_id in raw_ids:
            try:
                item = await db.get(WorkspaceAttentionItem, uuid.UUID(str(raw_id)))
            except (TypeError, ValueError):
                continue
            if item is None:
                continue
            evidence = dict(item.evidence or {})
            triage = dict(evidence.get("issue_triage") or {})
            if triage.get("state") not in {"running", "queued"}:
                continue
            if status == "complete":
                message = "Issue triage completed without structured work packs. Review manually."
                triage.update({
                    "state": "needs_info",
                    "summary": message,
                    "reported_by": f"task:{task.id}",
                    "reported_at": now.isoformat(),
                })
                item.assignment_status = "reported"
                item.status = "responded" if item.status != "resolved" else item.status
                item.responded_at = item.responded_at or now
                item.responded_by = f"task:{task.id}"
            else:
                message = task.error or f"Issue triage ended with status {status}."
                triage.update({
                    "state": "failed",
                    "error": message,
                    "reported_at": now.isoformat(),
                })
                item.assignment_status = "cancelled"
            evidence["issue_triage"] = triage
            item.evidence = evidence
            item.assignment_report = message
            item.assignment_reported_by = f"task:{task.id}"
            item.assignment_reported_at = now
            item.updated_at = now
            flag_modified(item, "evidence")
        await db.commit()


async def on_attention_assignment_task_complete(task_id: uuid.UUID, status: str) -> None:
    async with async_session() as db:
        task = await db.get(Task, task_id)
        if task is None:
            return
        cb = task.callback_config or {}
        if not cb.get("attention_assignment"):
            return
        item_id = cb.get("attention_item_id")
        if not item_id:
            return
        try:
            parsed = uuid.UUID(str(item_id))
        except (TypeError, ValueError):
            return
        item = await db.get(WorkspaceAttentionItem, parsed)
        if item is None or item.assignment_status == "reported":
            return
        if status == "complete" and task.result:
            await report_attention_assignment(db, parsed, bot_id=task.bot_id, findings=task.result, task_id=task.id)
        elif status != "complete":
            item.assignment_status = "assigned" if item.assignment_mode == "next_heartbeat" else "cancelled"
            item.assignment_report = task.error or f"Assignment task ended with status {status}."
            item.assignment_reported_at = _now()
            item.assignment_reported_by = f"task:{task.id}"
            item.updated_at = _now()
            await db.commit()


async def resolve_attention_item_by_bot_key(
    db: AsyncSession,
    *,
    bot_id: str,
    channel_id: uuid.UUID,
    item_id: uuid.UUID | None = None,
    dedupe_key: str | None = None,
) -> WorkspaceAttentionItem:
    if item_id is not None:
        return await resolve_attention_item(db, item_id, source_bot_id=bot_id)
    if not dedupe_key:
        raise ValidationError("item_id or dedupe_key is required.")
    item = (await db.execute(
        select(WorkspaceAttentionItem).where(
            WorkspaceAttentionItem.source_type == "bot",
            WorkspaceAttentionItem.source_id == bot_id,
            WorkspaceAttentionItem.channel_id == channel_id,
            WorkspaceAttentionItem.dedupe_key == normalize_dedupe_key(dedupe_key),
            WorkspaceAttentionItem.status.in_(DEDUPE_STATUSES),
        ).order_by(desc(WorkspaceAttentionItem.last_seen_at))
    )).scalar_one_or_none()
    if item is None:
        raise NotFoundError("Attention item not found.")
    return await resolve_attention_item(db, item.id, source_bot_id=bot_id)


async def list_attention_items(
    db: AsyncSession,
    *,
    auth: Any,
    status: str | None = None,
    channel_id: uuid.UUID | None = None,
    include_resolved: bool = False,
) -> list[WorkspaceAttentionItem]:
    clauses = []
    if status:
        clauses.append(WorkspaceAttentionItem.status == status)
    elif not include_resolved:
        clauses.append(WorkspaceAttentionItem.status.in_(VISIBLE_STATUSES))
    if channel_id:
        clauses.append(WorkspaceAttentionItem.channel_id == channel_id)
    if not _is_admin_auth(auth):
        clauses.append(WorkspaceAttentionItem.source_type.in_(("bot", "user")))
    stmt = select(WorkspaceAttentionItem).where(*clauses).order_by(
        desc(WorkspaceAttentionItem.status == "open"),
        desc(WorkspaceAttentionItem.last_seen_at),
    )
    items = list((await db.execute(stmt)).scalars().all())

    def _priority(item: WorkspaceAttentionItem) -> tuple[int, int, float]:
        evidence = item.evidence or {}
        report = evidence.get("report_issue") if isinstance(evidence, dict) else None
        triage = evidence.get("operator_triage") if isinstance(evidence, dict) else None
        if isinstance(report, dict):
            bucket = 0
        elif isinstance(triage, dict) and triage.get("state") == "ready_for_review":
            bucket = 1
        elif item.status == "open" and item.source_type in {"bot", "user"}:
            bucket = 2
        elif item.status == "open":
            bucket = 3
        else:
            bucket = 4
        ts = item.last_seen_at or item.first_seen_at or datetime.min.replace(tzinfo=timezone.utc)
        return (bucket, -_severity_rank(item.severity), -ts.timestamp())

    return sorted(items, key=_priority)


async def _target_node_id(db: AsyncSession, item: WorkspaceAttentionItem) -> str | None:
    try:
        if item.target_kind == "channel":
            node = (await db.execute(
                select(WorkspaceSpatialNode.id).where(WorkspaceSpatialNode.channel_id == uuid.UUID(item.target_id))
            )).scalar_one_or_none()
            return str(node) if node else None
        if item.target_kind == "widget":
            node = (await db.execute(
                select(WorkspaceSpatialNode.id).where(WorkspaceSpatialNode.widget_pin_id == uuid.UUID(item.target_id))
            )).scalar_one_or_none()
            return str(node) if node else None
        if item.target_kind == "bot":
            node = (await db.execute(
                select(WorkspaceSpatialNode.id).where(WorkspaceSpatialNode.bot_id == item.target_id)
            )).scalar_one_or_none()
            return str(node) if node else None
    except (TypeError, ValueError):
        return None
    return None


async def serialize_attention_item(db: AsyncSession, item: WorkspaceAttentionItem) -> dict[str, Any]:
    channel_name = None
    if item.channel_id:
        channel = await db.get(Channel, item.channel_id)
        channel_name = channel.name if channel else None
    return {
        "id": str(item.id),
        "source_type": item.source_type,
        "source_id": item.source_id,
        "channel_id": str(item.channel_id) if item.channel_id else None,
        "channel_name": channel_name,
        "target_kind": item.target_kind,
        "target_id": item.target_id,
        "target_node_id": await _target_node_id(db, item),
        "dedupe_key": item.dedupe_key,
        "severity": item.severity,
        "title": item.title,
        "message": item.message,
        "next_steps": list(item.next_steps or []),
        "requires_response": item.requires_response,
        "status": item.status,
        "occurrence_count": item.occurrence_count,
        "evidence": item.evidence or {},
        "latest_correlation_id": str(item.latest_correlation_id) if item.latest_correlation_id else None,
        "response_message_id": str(item.response_message_id) if item.response_message_id else None,
        "assigned_bot_id": item.assigned_bot_id,
        "assignment_mode": item.assignment_mode,
        "assignment_status": item.assignment_status,
        "assignment_instructions": item.assignment_instructions,
        "assigned_by": item.assigned_by,
        "assigned_at": item.assigned_at.isoformat() if item.assigned_at else None,
        "assignment_task_id": str(item.assignment_task_id) if item.assignment_task_id else None,
        "assignment_report": item.assignment_report,
        "assignment_reported_by": item.assignment_reported_by,
        "assignment_reported_at": item.assignment_reported_at.isoformat() if item.assignment_reported_at else None,
        "first_seen_at": item.first_seen_at.isoformat() if item.first_seen_at else None,
        "last_seen_at": item.last_seen_at.isoformat() if item.last_seen_at else None,
        "responded_at": item.responded_at.isoformat() if item.responded_at else None,
        "resolved_at": item.resolved_at.isoformat() if item.resolved_at else None,
    }


async def serialize_attention_items(db: AsyncSession, items: Iterable[WorkspaceAttentionItem]) -> list[dict[str, Any]]:
    return [await serialize_attention_item(db, item) for item in items]


async def list_bot_neighborhood_attention(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID,
    bot_id: str,
) -> list[dict[str, Any]]:
    items = (await db.execute(
        select(WorkspaceAttentionItem).where(
            WorkspaceAttentionItem.source_type == "bot",
            WorkspaceAttentionItem.status.in_(VISIBLE_STATUSES),
            or_(
                WorkspaceAttentionItem.channel_id == channel_id,
                WorkspaceAttentionItem.source_id == bot_id,
            ),
        ).order_by(desc(WorkspaceAttentionItem.last_seen_at)).limit(12)
    )).scalars().all()
    return [
        {
            "id": str(item.id),
            "source_id": item.source_id,
            "target_kind": item.target_kind,
            "target_id": item.target_id,
            "severity": item.severity,
            "status": item.status,
            "title": item.title,
            "requires_response": item.requires_response,
            "occurrence_count": item.occurrence_count,
            "last_seen_at": item.last_seen_at.isoformat() if item.last_seen_at else None,
            "own": item.source_id == bot_id,
        }
        for item in items
    ]


async def build_attention_assignment_block(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID,
    bot_id: str,
) -> str | None:
    items = (await db.execute(
        select(WorkspaceAttentionItem).where(
            WorkspaceAttentionItem.channel_id == channel_id,
            WorkspaceAttentionItem.assigned_bot_id == bot_id,
            WorkspaceAttentionItem.assignment_mode == "next_heartbeat",
            WorkspaceAttentionItem.assignment_status.in_(("assigned", "running")),
            WorkspaceAttentionItem.status.in_(VISIBLE_STATUSES),
        ).order_by(
            desc(WorkspaceAttentionItem.severity == "critical"),
            desc(WorkspaceAttentionItem.severity == "error"),
            desc(WorkspaceAttentionItem.severity == "warning"),
            WorkspaceAttentionItem.assigned_at.asc(),
        ).limit(1)
    )).scalars().all()
    if not items:
        return None
    lines = [
        "[attention assignments]",
        "You have Attention Items assigned to investigate. Report findings only; do not execute fixes as assignment semantics.",
        "Use report_attention_assignment with the item id and findings.",
    ]
    for item in items:
        steps = "; ".join(item.next_steps or [])
        lines.append(
            f"- id={item.id} severity={item.severity} title={item.title!r} "
            f"target={item.target_kind}:{item.target_id} message={item.message!r}"
        )
        if item.assignment_instructions:
            lines.append(f"  instructions: {item.assignment_instructions}")
        if steps:
            lines.append(f"  next_steps: {steps}")
    return "\n".join(lines)


def _error_signature(text: str) -> str:
    cleaned = re.sub(r"[0-9a-f]{8,}", "<id>", text.lower())
    cleaned = re.sub(r"\b\d+\b", "<n>", cleaned)
    return normalize_dedupe_key(cleaned[:180])


_NOISY_FILE_TOOL_PARTS = (
    "file",
    "workspace",
)
_NOISY_FILE_TOOL_NAMES = {
    "read_file",
    "list_files",
    "glob_files",
    "grep_files",
    "search_files",
    "get_memory_file",
}
_SEVERE_TOOL_ERROR_RE = re.compile(
    r"permission|denied|timeout|timed out|traceback|exception|crash|failed to write|"
    r"write failed|delete|remove|move|overwrite|missing required|workspace root",
    re.IGNORECASE,
)

def _tool_attention_classification(
    tool_name: str | None,
    error_text: str,
    repeated_count: int,
    *,
    error_kind: str | None = None,
    retryable: bool | None = None,
) -> tuple[bool, str, str]:
    """Decide whether to surface a failed tool call to attention, and at
    what severity.

    Returns ``(should_surface, classification, severity)``. Severity is one
    of ``"info"``, ``"warning"``, ``"critical"`` matching the
    ``workspace_attention_items.severity`` constraint.
    """
    name = (tool_name or "").lower()
    text = error_text or ""
    kind = (error_kind or "").lower() or None
    if kind in BENIGN_REVIEW_ERROR_KINDS:
        if repeated_count >= 3:
            return True, "repeated_benign_contract", "warning"
        return False, "benign_contract", "info"
    if retryable is True or kind in RETRYABLE_ERROR_KINDS:
        return True, "retryable_contract", "warning"
    if kind == "internal":
        return True, "platform_contract", "critical"
    if _SEVERE_TOOL_ERROR_RE.search(text):
        return True, "severe", "critical"
    if repeated_count >= 3:
        return True, "repeated", "critical"
    if name in _NOISY_FILE_TOOL_NAMES or any(part in name for part in _NOISY_FILE_TOOL_PARTS):
        return False, "suppressed_noisy_file_tool", "info"
    return True, "default", "critical"


async def _channel_for_session(db: AsyncSession, session_id: uuid.UUID | None) -> uuid.UUID | None:
    if not session_id:
        return None
    session = await db.get(Session, session_id)
    return session.channel_id if session else None


async def detect_structured_attention_once(db: AsyncSession, *, since: datetime | None = None) -> int:
    since = since or (_now() - timedelta(minutes=10))
    created = 0
    tool_calls = (await db.execute(
        select(ToolCall).where(
            ToolCall.created_at >= since,
            or_(ToolCall.status == "error", ToolCall.error.isnot(None)),
        ).order_by(ToolCall.created_at.desc()).limit(50)
    )).scalars().all()
    tool_signature_counts: dict[str, int] = {}
    tool_call_signatures: dict[uuid.UUID, str] = {}
    for call in tool_calls:
        channel_id = await _channel_for_session(db, call.session_id)
        text = str(call.error or call.result or "tool call failed")
        signature = derive_dedupe_key("tool", str(channel_id), call.bot_id, call.tool_name, _error_signature(text))
        tool_call_signatures[call.id] = signature
        tool_signature_counts[signature] = tool_signature_counts.get(signature, 0) + 1
    for call in tool_calls:
        channel_id = await _channel_for_session(db, call.session_id)
        target_kind = "channel" if channel_id else ("bot" if call.bot_id else "system")
        target_id = str(channel_id) if channel_id else (call.bot_id or "structured-errors")
        text = call.error or call.result or "tool call failed"
        signature = tool_call_signatures[call.id]
        should_surface, classification, severity = _tool_attention_classification(
            call.tool_name,
            str(text),
            tool_signature_counts.get(signature, 1),
            error_kind=call.error_kind,
            retryable=call.retryable,
        )
        if not should_surface:
            continue
        auto_signature = _auto_signal_signature(
            kind="tool_call",
            channel_id=channel_id,
            target_kind=target_kind,
            target_id=target_id,
            name=call.tool_name,
            error_kind=call.error_kind,
            text=str(text),
        )
        evidence = {
            "kind": "tool_call",
            "tool_call_id": str(call.id),
            "tool_name": call.tool_name,
            "classification": classification,
            "error_code": call.error_code,
            "error_kind": call.error_kind,
            "retryable": call.retryable,
            "retry_after_seconds": call.retry_after_seconds,
            "fallback": call.fallback,
            "correlation_id": str(call.correlation_id) if call.correlation_id else None,
            "auto_signal": {
                "signature": auto_signature,
                "kind": "tool_call",
                "tool_name": call.tool_name,
                "error_code": call.error_code,
                "error_kind": call.error_kind,
                "retryable": call.retryable,
            },
        }
        folded = await _fold_system_signal_into_bot_report(
            db,
            channel_id=channel_id,
            target_kind=target_kind,
            target_id=target_id,
            signal_signature=auto_signature,
            evidence=evidence,
            latest_correlation_id=call.correlation_id,
        )
        if folded is not None:
            continue
        item = await place_attention_item(
            db,
            source_type="system",
            source_id=STRUCTURED_ERROR_DETECTOR_ID,
            channel_id=channel_id,
            target_kind=target_kind,
            target_id=target_id,
            title=f"{call.tool_name} failed",
            message=str(text)[:1000],
            severity=severity,
            requires_response=False,
            next_steps=[call.fallback] if call.fallback else None,
            dedupe_key=signature,
            evidence=evidence,
            latest_correlation_id=call.correlation_id,
            source_event_key=f"tool_call:{call.id}",
            reopen_after=AUTO_SIGNAL_REOPEN_COOLDOWN,
        )
        if item.occurrence_count == 1:
            created += 1

    trace_events = (await db.execute(
        select(TraceEvent).where(
            TraceEvent.created_at >= since,
            TraceEvent.event_type.in_(("error", "llm_error")),
        ).order_by(TraceEvent.created_at.desc()).limit(50)
    )).scalars().all()
    for event in trace_events:
        channel_id = await _channel_for_session(db, event.session_id)
        target_kind = "channel" if channel_id else ("bot" if event.bot_id else "system")
        target_id = str(channel_id) if channel_id else (event.bot_id or "structured-errors")
        data = event.data or {}
        text = str(data.get("error") or data.get("message") or event.event_name or event.event_type)
        signature = derive_dedupe_key("trace", str(channel_id), event.bot_id, event.event_type, _error_signature(text))
        auto_signature = _auto_signal_signature(
            kind="trace_event",
            channel_id=channel_id,
            target_kind=target_kind,
            target_id=target_id,
            name=event.event_type,
            error_kind=event.event_name,
            text=text,
        )
        evidence = {
            "kind": "trace_event",
            "trace_event_id": str(event.id),
            "event_type": event.event_type,
            "event_name": event.event_name,
            "correlation_id": str(event.correlation_id) if event.correlation_id else None,
            "auto_signal": {
                "signature": auto_signature,
                "kind": "trace_event",
                "event_type": event.event_type,
                "event_name": event.event_name,
            },
        }
        folded = await _fold_system_signal_into_bot_report(
            db,
            channel_id=channel_id,
            target_kind=target_kind,
            target_id=target_id,
            signal_signature=auto_signature,
            evidence=evidence,
            latest_correlation_id=event.correlation_id,
        )
        if folded is not None:
            continue
        item = await place_attention_item(
            db,
            source_type="system",
            source_id=STRUCTURED_ERROR_DETECTOR_ID,
            channel_id=channel_id,
            target_kind=target_kind,
            target_id=target_id,
            title=f"Trace {event.event_type}",
            message=text[:1000],
            severity="error",
            dedupe_key=signature,
            evidence=evidence,
            latest_correlation_id=event.correlation_id,
            source_event_key=f"trace_event:{event.id}",
            reopen_after=AUTO_SIGNAL_REOPEN_COOLDOWN,
        )
        if item.occurrence_count == 1:
            created += 1

    runs = (await db.execute(
        select(HeartbeatRun, ChannelHeartbeat).join(
            ChannelHeartbeat, HeartbeatRun.heartbeat_id == ChannelHeartbeat.id,
        ).where(
            HeartbeatRun.run_at >= since,
            or_(HeartbeatRun.status == "error", HeartbeatRun.error.isnot(None)),
        ).order_by(HeartbeatRun.run_at.desc()).limit(50)
    )).all()
    for run, hb in runs:
        text = run.error or "Heartbeat run failed"
        signature = derive_dedupe_key("heartbeat", str(hb.channel_id), _error_signature(text))
        auto_signature = _auto_signal_signature(
            kind="heartbeat_run",
            channel_id=hb.channel_id,
            target_kind="channel",
            target_id=str(hb.channel_id),
            name="heartbeat",
            error_kind=run.status,
            text=text,
        )
        evidence = {
            "kind": "heartbeat_run",
            "heartbeat_run_id": str(run.id),
            "heartbeat_id": str(hb.id),
            "correlation_id": str(run.correlation_id) if run.correlation_id else None,
            "auto_signal": {
                "signature": auto_signature,
                "kind": "heartbeat_run",
                "heartbeat_id": str(hb.id),
                "status": run.status,
            },
        }
        folded = await _fold_system_signal_into_bot_report(
            db,
            channel_id=hb.channel_id,
            target_kind="channel",
            target_id=str(hb.channel_id),
            signal_signature=auto_signature,
            evidence=evidence,
            latest_correlation_id=run.correlation_id,
        )
        if folded is not None:
            continue
        item = await place_attention_item(
            db,
            source_type="system",
            source_id=STRUCTURED_ERROR_DETECTOR_ID,
            channel_id=hb.channel_id,
            target_kind="channel",
            target_id=str(hb.channel_id),
            title="Heartbeat failed",
            message=text[:1000],
            severity="warning",
            dedupe_key=signature,
            evidence=evidence,
            latest_correlation_id=run.correlation_id,
            source_event_key=f"heartbeat_run:{run.id}",
            reopen_after=AUTO_SIGNAL_REOPEN_COOLDOWN,
        )
        if item.occurrence_count == 1:
            created += 1
    return created


async def structured_attention_worker(interval_seconds: int = 60) -> None:
    while True:
        try:
            async with async_session() as db:
                await detect_structured_attention_once(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("workspace_attention: structured detector failed")
        await asyncio.sleep(interval_seconds)
