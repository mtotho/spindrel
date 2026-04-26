"""Workspace Attention Items.

Attention Items are shared work-intake/domain state. The Spatial Canvas
renders active items as Beacons, but dedupe, lifecycle, evidence, and future
assignment semantics stay here.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.engine import async_session
from app.db.models import (
    Channel,
    ChannelHeartbeat,
    HeartbeatRun,
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


logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("open", "acknowledged", "responded")
VALID_SEVERITIES = {"info", "warning", "error", "critical"}
VALID_TARGET_KINDS = {"channel", "bot", "widget", "system"}
VALID_ASSIGNMENT_MODES = {"next_heartbeat", "run_now"}
STRUCTURED_ERROR_DETECTOR_ID = "system:structured-errors"


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


def _merge_evidence(old: dict | None, new: dict | None) -> dict:
    merged = dict(old or {})
    if new:
        merged.update(new)
        history = list(merged.get("recent") or [])
        history.append(new)
        merged["recent"] = history[-10:]
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
            WorkspaceAttentionItem.status.in_(ACTIVE_STATUSES),
        )
    )).scalar_one_or_none()
    if existing is not None:
        existing.title = title
        existing.message = message or ""
        existing.severity = severity
        existing.requires_response = bool(requires_response)
        existing.next_steps = list(next_steps or [])
        existing.evidence = _merge_evidence(existing.evidence, evidence)
        existing.latest_correlation_id = latest_correlation_id or existing.latest_correlation_id
        existing.occurrence_count = int(existing.occurrence_count or 0) + 1
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
        evidence=evidence or {},
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
    if item.status == "open":
        item.status = "acknowledged"
        item.updated_at = _now()
        await db.commit()
        await db.refresh(item)
    return item


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
) -> WorkspaceAttentionItem:
    item = await get_attention_item(db, item_id)
    if source_bot_id and not (item.source_type == "bot" and item.source_id == source_bot_id):
        raise ValidationError("Bots can only resolve attention items they created.")
    now = _now()
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
        channel = await db.get(Channel, item.channel_id) if item.channel_id else None
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
            WorkspaceAttentionItem.status.in_(ACTIVE_STATUSES),
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
        clauses.append(WorkspaceAttentionItem.status.in_(ACTIVE_STATUSES))
    if channel_id:
        clauses.append(WorkspaceAttentionItem.channel_id == channel_id)
    if not _is_admin_auth(auth):
        clauses.append(WorkspaceAttentionItem.source_type.in_(("bot", "user")))
    stmt = select(WorkspaceAttentionItem).where(*clauses).order_by(
        desc(WorkspaceAttentionItem.status == "open"),
        desc(WorkspaceAttentionItem.last_seen_at),
    )
    return list((await db.execute(stmt)).scalars().all())


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
            WorkspaceAttentionItem.status.in_(ACTIVE_STATUSES),
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
            WorkspaceAttentionItem.status.in_(ACTIVE_STATUSES),
        ).order_by(desc(WorkspaceAttentionItem.assigned_at)).limit(5)
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
    for call in tool_calls:
        channel_id = await _channel_for_session(db, call.session_id)
        target_kind = "channel" if channel_id else ("bot" if call.bot_id else "system")
        target_id = str(channel_id) if channel_id else (call.bot_id or "structured-errors")
        text = call.error or call.result or "tool call failed"
        signature = derive_dedupe_key("tool", str(channel_id), call.bot_id, call.tool_name, _error_signature(text))
        item = await place_attention_item(
            db,
            source_type="system",
            source_id=STRUCTURED_ERROR_DETECTOR_ID,
            channel_id=channel_id,
            target_kind=target_kind,
            target_id=target_id,
            title=f"{call.tool_name} failed",
            message=str(text)[:1000],
            severity="critical" if (call.error and "timeout" not in call.error.lower()) else "error",
            requires_response=False,
            dedupe_key=signature,
            evidence={
                "kind": "tool_call",
                "tool_call_id": str(call.id),
                "tool_name": call.tool_name,
                "correlation_id": str(call.correlation_id) if call.correlation_id else None,
            },
            latest_correlation_id=call.correlation_id,
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
            evidence={
                "kind": "trace_event",
                "trace_event_id": str(event.id),
                "event_type": event.event_type,
                "event_name": event.event_name,
                "correlation_id": str(event.correlation_id) if event.correlation_id else None,
            },
            latest_correlation_id=event.correlation_id,
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
            evidence={
                "kind": "heartbeat_run",
                "heartbeat_run_id": str(run.id),
                "heartbeat_id": str(hb.id),
                "correlation_id": str(run.correlation_id) if run.correlation_id else None,
            },
            latest_correlation_id=run.correlation_id,
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
