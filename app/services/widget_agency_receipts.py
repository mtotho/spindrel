"""Durable receipts for bot-applied channel-dashboard widget changes."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Task, WidgetAgencyReceipt


def _clip_text(value: object, limit: int = 220) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "..."


def _clean_uuid(value: object) -> str | None:
    if not value:
        return None
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError):
        return None


def _pin_snapshot(pin: dict[str, Any]) -> dict[str, Any]:
    envelope = pin.get("envelope") if isinstance(pin.get("envelope"), dict) else {}
    label = (
        pin.get("display_label")
        or envelope.get("display_label")
        or pin.get("tool_name")
        or pin.get("id")
    )
    return {
        "id": _clean_uuid(pin.get("id")) or str(pin.get("id") or ""),
        "label": _clip_text(label, 120),
        "tool_name": pin.get("tool_name"),
        "zone": pin.get("zone") or "grid",
        "grid_layout": pin.get("grid_layout") if isinstance(pin.get("grid_layout"), dict) else {},
        "is_main_panel": bool(pin.get("is_main_panel")),
        "source_kind": pin.get("source_kind"),
        "widget_origin": pin.get("widget_origin") if isinstance(pin.get("widget_origin"), dict) else None,
    }


def _dashboard_snapshot(dashboard: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(dashboard, dict):
        return {}
    return {
        "slug": dashboard.get("slug"),
        "name": _clip_text(dashboard.get("name"), 120),
        "grid_config": dashboard.get("grid_config") if isinstance(dashboard.get("grid_config"), dict) else {},
    }


def build_widget_agency_state(
    *,
    dashboard: dict[str, Any] | None = None,
    pins: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    state: dict[str, Any] = {}
    if dashboard is not None:
        state["dashboard"] = _dashboard_snapshot(dashboard)
    if pins is not None:
        state["pins"] = [_pin_snapshot(pin) for pin in pins if isinstance(pin, dict)]
    return state


async def _infer_task_id(
    db: AsyncSession,
    correlation_id: uuid.UUID | None,
) -> uuid.UUID | None:
    if correlation_id is None:
        return None
    row = (
        await db.execute(
            select(Task.id)
            .where(Task.correlation_id == correlation_id)
            .order_by(Task.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return row


async def create_widget_agency_receipt(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID,
    dashboard_key: str,
    action: str,
    summary: str,
    reason: str | None = None,
    bot_id: str | None = None,
    session_id: uuid.UUID | None = None,
    correlation_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    affected_pin_ids: list[str] | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> WidgetAgencyReceipt:
    receipt = WidgetAgencyReceipt(
        channel_id=channel_id,
        dashboard_key=dashboard_key,
        action=action,
        summary=_clip_text(summary, 500) or action,
        reason=_clip_text(reason, 500),
        bot_id=bot_id,
        session_id=session_id,
        correlation_id=correlation_id,
        task_id=task_id or await _infer_task_id(db, correlation_id),
        affected_pin_ids=[
            pin_id for pin_id in (_clean_uuid(item) for item in (affected_pin_ids or [])) if pin_id
        ],
        before_state=before_state or {},
        after_state=after_state or {},
        metadata_=metadata or {},
    )
    db.add(receipt)
    await db.commit()
    await db.refresh(receipt)
    return receipt


def serialize_widget_agency_receipt(row: WidgetAgencyReceipt) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "channel_id": str(row.channel_id) if row.channel_id else None,
        "dashboard_key": row.dashboard_key,
        "action": row.action,
        "summary": row.summary,
        "reason": row.reason,
        "bot_id": row.bot_id,
        "session_id": str(row.session_id) if row.session_id else None,
        "correlation_id": str(row.correlation_id) if row.correlation_id else None,
        "task_id": str(row.task_id) if row.task_id else None,
        "affected_pin_ids": list(row.affected_pin_ids or []),
        "before_state": row.before_state or {},
        "after_state": row.after_state or {},
        "metadata": row.metadata_ or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def list_channel_widget_agency_receipts(
    db: AsyncSession,
    channel_id: uuid.UUID,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    bounded = max(1, min(int(limit or 20), 100))
    rows = (
        await db.execute(
            select(WidgetAgencyReceipt)
            .where(WidgetAgencyReceipt.channel_id == channel_id)
            .order_by(WidgetAgencyReceipt.created_at.desc())
            .limit(bounded)
        )
    ).scalars().all()
    return [serialize_widget_agency_receipt(row) for row in rows]
