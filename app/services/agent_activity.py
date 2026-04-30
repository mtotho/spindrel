"""Read-only agent activity/replay stream.

This is a normalized view over durable evidence.  It deliberately keeps each
source system authoritative instead of turning activity replay into the owner
of receipts or workflow state.
"""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ExecutionReceipt,
    ProjectRunReceipt,
    Session,
    ToolCall,
    WidgetAgencyReceipt,
    WorkspaceAttentionItem,
    WorkspaceMission,
    WorkspaceMissionUpdate,
)


AgentActivityKind = Literal[
    "tool_call",
    "attention",
    "mission_update",
    "project_receipt",
    "widget_receipt",
    "execution_receipt",
]

AGENT_ACTIVITY_KINDS: tuple[AgentActivityKind, ...] = (
    "tool_call",
    "attention",
    "mission_update",
    "project_receipt",
    "widget_receipt",
    "execution_receipt",
)


def _uuid_or_none(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None or isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _clip(value: object, *, limit: int = 500) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _first_string(values: Any) -> str | None:
    if isinstance(values, list):
        for value in values:
            if isinstance(value, dict):
                for key in ("label", "summary", "title", "action"):
                    text = _clip(value.get(key), limit=300)
                    if text:
                        return text
            text = _clip(value, limit=300)
            if text:
                return text
    return None


def _target(
    *,
    bot_id: str | None = None,
    channel_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    widget_pin_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "bot_id": bot_id,
        "channel_id": str(channel_id) if channel_id else None,
        "project_id": str(project_id) if project_id else None,
        "widget_pin_ids": list(widget_pin_ids or []),
    }


def _actor(
    *,
    bot_id: str | None = None,
    session_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    return {
        "bot_id": bot_id,
        "session_id": str(session_id) if session_id else None,
        "task_id": str(task_id) if task_id else None,
    }


def _trace(
    *,
    correlation_id: uuid.UUID | None = None,
    tool_call_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    return {
        "correlation_id": str(correlation_id) if correlation_id else None,
        "tool_call_id": str(tool_call_id) if tool_call_id else None,
    }


def _error(
    *,
    error_code: str | None = None,
    error_kind: str | None = None,
    retryable: bool | None = None,
) -> dict[str, Any]:
    return {
        "error_code": error_code,
        "error_kind": error_kind,
        "retryable": retryable,
    }


def _tool_status(row: ToolCall) -> str:
    status = (row.status or "").lower()
    if row.error or status in {"error", "denied", "expired"}:
        return "failed"
    if status == "done":
        return "succeeded"
    if status == "awaiting_approval":
        return "warning"
    return "unknown"


def _attention_status(row: WorkspaceAttentionItem) -> str:
    if row.status == "resolved":
        return "succeeded"
    if row.status in {"open", "acknowledged", "responded"}:
        return "needs_review"
    return "reported"


def _mission_status(row: WorkspaceMissionUpdate) -> str:
    if row.kind == "error":
        return "failed"
    if row.kind in {"result", "progress", "manual"}:
        return "reported"
    return "succeeded"


def _receipt_status(value: str | None) -> str:
    if value in {"failed", "blocked", "needs_review"}:
        return value
    if value == "completed":
        return "succeeded"
    if value == "reported":
        return "reported"
    return "unknown"


def _activity_item(
    *,
    id: str,
    kind: AgentActivityKind,
    actor: dict[str, Any],
    target: dict[str, Any],
    status: str,
    summary: str,
    next_action: str | None,
    trace: dict[str, Any],
    error: dict[str, Any],
    created_at: datetime | None,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": id,
        "kind": kind,
        "actor": actor,
        "target": target,
        "status": status,
        "summary": summary,
        "next_action": next_action,
        "trace": trace,
        "error": error,
        "created_at": _iso(created_at),
        "source": source or {},
    }


def _apply_time(stmt: Select[Any], column: Any, since: datetime | None) -> Select[Any]:
    return stmt.where(column >= since) if since else stmt


async def _tool_call_items(
    db: AsyncSession,
    *,
    bot_id: str | None,
    channel_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    correlation_id: uuid.UUID | None,
    since: datetime | None,
    limit: int,
) -> list[dict[str, Any]]:
    stmt = (
        select(ToolCall, Session.channel_id)
        .join(Session, Session.id == ToolCall.session_id, isouter=True)
        .order_by(ToolCall.created_at.desc())
        .limit(limit)
    )
    if bot_id:
        stmt = stmt.where(ToolCall.bot_id == bot_id)
    if channel_id:
        stmt = stmt.where(Session.channel_id == channel_id)
    if session_id:
        stmt = stmt.where(ToolCall.session_id == session_id)
    if correlation_id:
        stmt = stmt.where(ToolCall.correlation_id == correlation_id)
    stmt = _apply_time(stmt, ToolCall.created_at, since)

    rows = (await db.execute(stmt)).all()
    items: list[dict[str, Any]] = []
    for row, row_channel_id in rows:
        summary = f"{row.tool_name} {row.status or 'called'}"
        if row.error:
            summary = f"{row.tool_name} failed: {_clip(row.error, limit=180)}"
        items.append(_activity_item(
            id=f"tool_call:{row.id}",
            kind="tool_call",
            actor=_actor(bot_id=row.bot_id, session_id=row.session_id),
            target=_target(channel_id=row_channel_id),
            status=_tool_status(row),
            summary=summary,
            next_action=row.fallback,
            trace=_trace(correlation_id=row.correlation_id, tool_call_id=row.id),
            error=_error(error_code=row.error_code, error_kind=row.error_kind, retryable=row.retryable),
            created_at=row.created_at,
            source={"tool_name": row.tool_name, "tool_type": row.tool_type},
        ))
    return items


async def _attention_items(
    db: AsyncSession,
    *,
    bot_id: str | None,
    channel_id: uuid.UUID | None,
    task_id: uuid.UUID | None,
    correlation_id: uuid.UUID | None,
    since: datetime | None,
    limit: int,
) -> list[dict[str, Any]]:
    stmt = (
        select(WorkspaceAttentionItem)
        .order_by(WorkspaceAttentionItem.last_seen_at.desc())
        .limit(limit)
    )
    if bot_id:
        stmt = stmt.where(or_(
            WorkspaceAttentionItem.source_id == bot_id,
            WorkspaceAttentionItem.assigned_bot_id == bot_id,
        ))
    if channel_id:
        stmt = stmt.where(WorkspaceAttentionItem.channel_id == channel_id)
    if task_id:
        stmt = stmt.where(WorkspaceAttentionItem.assignment_task_id == task_id)
    if correlation_id:
        stmt = stmt.where(WorkspaceAttentionItem.latest_correlation_id == correlation_id)
    stmt = _apply_time(stmt, WorkspaceAttentionItem.last_seen_at, since)

    rows = (await db.execute(stmt)).scalars().all()
    items: list[dict[str, Any]] = []
    for row in rows:
        evidence = row.evidence or {}
        fallback = evidence.get("fallback") if isinstance(evidence.get("fallback"), str) else None
        items.append(_activity_item(
            id=f"attention:{row.id}",
            kind="attention",
            actor=_actor(
                bot_id=row.assigned_bot_id or (row.source_id if row.source_type == "bot" else None),
                task_id=row.assignment_task_id,
            ),
            target=_target(channel_id=row.channel_id),
            status=_attention_status(row),
            summary=row.title,
            next_action=_first_string(row.next_steps) or fallback,
            trace=_trace(correlation_id=row.latest_correlation_id),
            error=_error(
                error_code=evidence.get("error_code") if isinstance(evidence.get("error_code"), str) else None,
                error_kind=evidence.get("error_kind") if isinstance(evidence.get("error_kind"), str) else None,
                retryable=evidence.get("retryable") if isinstance(evidence.get("retryable"), bool) else None,
            ),
            created_at=row.last_seen_at,
            source={"severity": row.severity, "status": row.status},
        ))
    return items


async def _mission_update_items(
    db: AsyncSession,
    *,
    bot_id: str | None,
    channel_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    task_id: uuid.UUID | None,
    correlation_id: uuid.UUID | None,
    since: datetime | None,
    limit: int,
) -> list[dict[str, Any]]:
    stmt = (
        select(WorkspaceMissionUpdate, WorkspaceMission)
        .join(WorkspaceMission, WorkspaceMission.id == WorkspaceMissionUpdate.mission_id)
        .order_by(WorkspaceMissionUpdate.created_at.desc())
        .limit(limit)
    )
    if bot_id:
        stmt = stmt.where(WorkspaceMissionUpdate.bot_id == bot_id)
    if channel_id:
        stmt = stmt.where(WorkspaceMission.channel_id == channel_id)
    if session_id:
        stmt = stmt.where(WorkspaceMissionUpdate.session_id == session_id)
    if task_id:
        stmt = stmt.where(WorkspaceMissionUpdate.task_id == task_id)
    if correlation_id:
        stmt = stmt.where(WorkspaceMissionUpdate.correlation_id == correlation_id)
    stmt = _apply_time(stmt, WorkspaceMissionUpdate.created_at, since)

    rows = (await db.execute(stmt)).all()
    items: list[dict[str, Any]] = []
    for row, mission in rows:
        items.append(_activity_item(
            id=f"mission_update:{row.id}",
            kind="mission_update",
            actor=_actor(bot_id=row.bot_id, session_id=row.session_id, task_id=row.task_id),
            target=_target(channel_id=mission.channel_id),
            status=_mission_status(row),
            summary=row.summary,
            next_action=_first_string(row.next_actions),
            trace=_trace(correlation_id=row.correlation_id),
            error=_error(error_kind="internal" if row.kind == "error" else None),
            created_at=row.created_at,
            source={"mission_id": str(row.mission_id), "mission_title": mission.title, "kind": row.kind},
        ))
    return items


async def _project_receipt_items(
    db: AsyncSession,
    *,
    bot_id: str | None,
    channel_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    task_id: uuid.UUID | None,
    since: datetime | None,
    limit: int,
) -> list[dict[str, Any]]:
    stmt = (
        select(ProjectRunReceipt, Session.channel_id)
        .join(Session, Session.id == ProjectRunReceipt.session_id, isouter=True)
        .order_by(ProjectRunReceipt.created_at.desc())
        .limit(limit)
    )
    if bot_id:
        stmt = stmt.where(ProjectRunReceipt.bot_id == bot_id)
    if channel_id:
        stmt = stmt.where(Session.channel_id == channel_id)
    if session_id:
        stmt = stmt.where(ProjectRunReceipt.session_id == session_id)
    if task_id:
        stmt = stmt.where(ProjectRunReceipt.task_id == task_id)
    stmt = _apply_time(stmt, ProjectRunReceipt.created_at, since)

    rows = (await db.execute(stmt)).all()
    items: list[dict[str, Any]] = []
    for row, row_channel_id in rows:
        items.append(_activity_item(
            id=f"project_receipt:{row.id}",
            kind="project_receipt",
            actor=_actor(bot_id=row.bot_id, session_id=row.session_id, task_id=row.task_id),
            target=_target(channel_id=row_channel_id, project_id=row.project_id),
            status=_receipt_status(row.status),
            summary=row.summary,
            next_action=row.handoff_url,
            trace=_trace(),
            error=_error(error_kind="internal" if row.status == "failed" else None),
            created_at=row.created_at,
            source={
                "status": row.status,
                "handoff_type": row.handoff_type,
                "changed_files": list(row.changed_files or [])[:20],
            },
        ))
    return items


async def _widget_receipt_items(
    db: AsyncSession,
    *,
    bot_id: str | None,
    channel_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    task_id: uuid.UUID | None,
    correlation_id: uuid.UUID | None,
    since: datetime | None,
    limit: int,
) -> list[dict[str, Any]]:
    stmt = (
        select(WidgetAgencyReceipt)
        .order_by(WidgetAgencyReceipt.created_at.desc())
        .limit(limit)
    )
    if bot_id:
        stmt = stmt.where(WidgetAgencyReceipt.bot_id == bot_id)
    if channel_id:
        stmt = stmt.where(WidgetAgencyReceipt.channel_id == channel_id)
    if session_id:
        stmt = stmt.where(WidgetAgencyReceipt.session_id == session_id)
    if task_id:
        stmt = stmt.where(WidgetAgencyReceipt.task_id == task_id)
    if correlation_id:
        stmt = stmt.where(WidgetAgencyReceipt.correlation_id == correlation_id)
    stmt = _apply_time(stmt, WidgetAgencyReceipt.created_at, since)

    rows = (await db.execute(stmt)).scalars().all()
    items: list[dict[str, Any]] = []
    for row in rows:
        metadata = row.metadata_ or {}
        next_actions = metadata.get("next_actions") if isinstance(metadata, dict) else None
        items.append(_activity_item(
            id=f"widget_receipt:{row.id}",
            kind="widget_receipt",
            actor=_actor(bot_id=row.bot_id, session_id=row.session_id, task_id=row.task_id),
            target=_target(channel_id=row.channel_id, widget_pin_ids=list(row.affected_pin_ids or [])),
            status="reported",
            summary=row.summary,
            next_action=_first_string(next_actions),
            trace=_trace(correlation_id=row.correlation_id),
            error=_error(),
            created_at=row.created_at,
            source={"action": row.action, "dashboard_key": row.dashboard_key, "kind": metadata.get("kind")},
        ))
    return items


async def _execution_receipt_items(
    db: AsyncSession,
    *,
    bot_id: str | None,
    channel_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    task_id: uuid.UUID | None,
    correlation_id: uuid.UUID | None,
    since: datetime | None,
    limit: int,
) -> list[dict[str, Any]]:
    stmt = (
        select(ExecutionReceipt)
        .order_by(ExecutionReceipt.created_at.desc())
        .limit(limit)
    )
    if bot_id:
        stmt = stmt.where(ExecutionReceipt.bot_id == bot_id)
    if channel_id:
        stmt = stmt.where(ExecutionReceipt.channel_id == channel_id)
    if session_id:
        stmt = stmt.where(ExecutionReceipt.session_id == session_id)
    if task_id:
        stmt = stmt.where(ExecutionReceipt.task_id == task_id)
    if correlation_id:
        stmt = stmt.where(ExecutionReceipt.correlation_id == correlation_id)
    stmt = _apply_time(stmt, ExecutionReceipt.created_at, since)

    rows = (await db.execute(stmt)).scalars().all()
    items: list[dict[str, Any]] = []
    for row in rows:
        target = row.target or {}
        target_bot_id = target.get("bot_id") if isinstance(target.get("bot_id"), str) else row.bot_id
        items.append(_activity_item(
            id=f"execution_receipt:{row.id}",
            kind="execution_receipt",
            actor=_actor(bot_id=row.bot_id, session_id=row.session_id, task_id=row.task_id),
            target=_target(bot_id=target_bot_id, channel_id=row.channel_id),
            status=_receipt_status(row.status),
            summary=row.summary,
            next_action=row.rollback_hint if row.status in {"failed", "blocked", "needs_review"} else None,
            trace=_trace(correlation_id=row.correlation_id),
            error=_error(error_kind="internal" if row.status == "failed" else None),
            created_at=row.created_at,
            source={
                "scope": row.scope,
                "action_type": row.action_type,
                "approval_required": bool(row.approval_required),
                "approval_ref": row.approval_ref,
                "before_summary": row.before_summary,
                "after_summary": row.after_summary,
                "result": dict(row.result or {}),
            },
        ))
    return items


async def list_agent_activity(
    db: AsyncSession,
    *,
    bot_id: str | None = None,
    channel_id: str | uuid.UUID | None = None,
    session_id: str | uuid.UUID | None = None,
    task_id: str | uuid.UUID | None = None,
    correlation_id: str | uuid.UUID | None = None,
    kind: str | None = None,
    since: datetime | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return newest-first normalized agent activity items."""
    bounded = max(1, min(int(limit or 50), 200))
    selected_kinds = [kind] if kind in AGENT_ACTIVITY_KINDS else list(AGENT_ACTIVITY_KINDS)
    channel_uuid = _uuid_or_none(channel_id)
    session_uuid = _uuid_or_none(session_id)
    task_uuid = _uuid_or_none(task_id)
    correlation_uuid = _uuid_or_none(correlation_id)

    per_source_limit = bounded
    items: list[dict[str, Any]] = []
    if "tool_call" in selected_kinds:
        items.extend(await _tool_call_items(
            db,
            bot_id=bot_id,
            channel_id=channel_uuid,
            session_id=session_uuid,
            correlation_id=correlation_uuid,
            since=since,
            limit=per_source_limit,
        ))
    if "attention" in selected_kinds:
        items.extend(await _attention_items(
            db,
            bot_id=bot_id,
            channel_id=channel_uuid,
            task_id=task_uuid,
            correlation_id=correlation_uuid,
            since=since,
            limit=per_source_limit,
        ))
    if "mission_update" in selected_kinds:
        items.extend(await _mission_update_items(
            db,
            bot_id=bot_id,
            channel_id=channel_uuid,
            session_id=session_uuid,
            task_id=task_uuid,
            correlation_id=correlation_uuid,
            since=since,
            limit=per_source_limit,
        ))
    if "project_receipt" in selected_kinds and correlation_uuid is None:
        items.extend(await _project_receipt_items(
            db,
            bot_id=bot_id,
            channel_id=channel_uuid,
            session_id=session_uuid,
            task_id=task_uuid,
            since=since,
            limit=per_source_limit,
        ))
    if "widget_receipt" in selected_kinds:
        items.extend(await _widget_receipt_items(
            db,
            bot_id=bot_id,
            channel_id=channel_uuid,
            session_id=session_uuid,
            task_id=task_uuid,
            correlation_id=correlation_uuid,
            since=since,
            limit=per_source_limit,
        ))
    if "execution_receipt" in selected_kinds:
        items.extend(await _execution_receipt_items(
            db,
            bot_id=bot_id,
            channel_id=channel_uuid,
            session_id=session_uuid,
            task_id=task_uuid,
            correlation_id=correlation_uuid,
            since=since,
            limit=per_source_limit,
        ))

    items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return items[:bounded]


async def agent_activity_summary(
    db: AsyncSession,
    *,
    bot_id: str | None = None,
    channel_id: str | uuid.UUID | None = None,
    session_id: str | uuid.UUID | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    items = await list_agent_activity(
        db,
        bot_id=bot_id,
        channel_id=channel_id,
        session_id=session_id,
        limit=limit,
    )
    counts = Counter(item["kind"] for item in items)
    return {
        "available": True,
        "supported_kinds": list(AGENT_ACTIVITY_KINDS),
        "supported_filters": [
            "bot_id",
            "channel_id",
            "session_id",
            "task_id",
            "correlation_id",
            "kind",
            "since",
            "limit",
        ],
        "recent_count": len(items),
        "recent_counts": dict(sorted(counts.items())),
        "recent": items[:5],
    }


async def count_agent_activity(
    db: AsyncSession,
    *,
    bot_id: str | None = None,
    channel_id: str | uuid.UUID | None = None,
    session_id: str | uuid.UUID | None = None,
    limit: int = 200,
) -> int:
    """Cheap-enough count for readiness displays.

    This intentionally counts the bounded normalized replay stream rather than
    exact table cardinality, so the number matches what the agent can replay.
    """
    return len(await list_agent_activity(
        db,
        bot_id=bot_id,
        channel_id=channel_id,
        session_id=session_id,
        limit=limit,
    ))
