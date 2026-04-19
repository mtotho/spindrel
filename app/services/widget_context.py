"""Pinned-widget state injection for the assembled LLM context.

Produces a single plain-text system message summarizing the current state of
every widget pinned to the channel. Positioned right after the temporal block
in `context_assembly.py` so it stays out of the cacheable prefix.

Pins now live in ``widget_dashboard_pins`` under the reserved slug
``channel:<uuid>``. :func:`fetch_channel_pin_dicts` pulls them and shapes
them into the dict form :func:`build_widget_context_block` consumes, so the
renderer stays pure / I/O-free.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


_MAX_PINS = 12
_MAX_LINE_CHARS = 250
_MAX_TOTAL_CHARS = 2000
_HEADER = (
    "The user has these widgets pinned in this channel — "
    "treat their state as current reference data:"
)


def _parse_iso(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        # fromisoformat handles "2026-04-17T14:30:00+00:00" and the trailing-Z
        # variant once we normalize.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _relative_age(pinned_at: str | None, now: datetime) -> str | None:
    dt = _parse_iso(pinned_at)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    total = int((now - dt).total_seconds())
    if total < 0:
        return None
    if total < 60:
        return "just now"
    minutes = total // 60
    if minutes < 60:
        return f"~{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"~{hours}h ago"
    days = hours // 24
    return f"~{days}d ago"


async def fetch_channel_pin_dicts(
    db: "AsyncSession",
    channel_id: uuid.UUID | str,
) -> list[dict]:
    """Return channel pins as plain dicts sized for this module's renderer.

    Reads from ``widget_dashboard_pins`` at slug ``channel:<channel_id>``
    and shapes each row into the legacy ``channel.config.pinned_widgets``
    entry shape — ``envelope``, ``display_name``, ``tool_name``,
    ``bot_id``, ``pinned_at``, ``position``, ``config`` — so callers that
    previously read from JSONB keep working with a single swap.
    """
    from sqlalchemy import select
    from app.db.models import WidgetDashboardPin

    slug = f"channel:{channel_id}"
    rows = (await db.execute(
        select(WidgetDashboardPin)
        .where(WidgetDashboardPin.dashboard_key == slug)
        .order_by(WidgetDashboardPin.position.asc())
    )).scalars().all()

    out: list[dict] = []
    for r in rows:
        out.append({
            "id": str(r.id),
            "tool_name": r.tool_name,
            "display_name": r.display_label or r.tool_name,
            "bot_id": r.source_bot_id or "",
            "envelope": r.envelope or {},
            "position": r.position,
            "pinned_at": r.pinned_at.isoformat() if r.pinned_at else "",
            "config": r.widget_config or {},
        })
    return out


def build_widget_context_block(
    pins: list[dict] | None,
    *,
    bot_id: str,
    now: datetime | None = None,
) -> str | None:
    """Render pinned widgets as a plain-text system message.

    ``pins`` is the shape returned by :func:`fetch_channel_pin_dicts`.
    Returns None when there are no pins or none of them have usable
    ``plain_body`` state.
    """
    if not pins:
        return None
    now = now or datetime.now(timezone.utc)

    lines: list[str] = []
    for pin in pins[:_MAX_PINS]:
        if not isinstance(pin, dict):
            continue
        env = pin.get("envelope") or {}
        label = (
            env.get("display_label")
            or pin.get("display_name")
            or pin.get("tool_name")
            or "widget"
        )
        body = (env.get("plain_body") or "").strip()
        if not body:
            continue
        if len(body) > _MAX_LINE_CHARS:
            body = body[: _MAX_LINE_CHARS - 1].rstrip() + "…"

        suffix_bits: list[str] = []
        pin_bot = pin.get("bot_id")
        if pin_bot and pin_bot != bot_id:
            suffix_bits.append(f"pinned by {pin_bot}")
        age = _relative_age(pin.get("pinned_at"), now)
        if age:
            suffix_bits.append(f"updated {age}")
        suffix = f" ({'; '.join(suffix_bits)})" if suffix_bits else ""

        lines.append(f"- {label}: {body}{suffix}")

    if not lines:
        return None

    block = _HEADER + "\n" + "\n".join(lines)
    while len(block) > _MAX_TOTAL_CHARS and len(lines) > 1:
        lines.pop()
        block = _HEADER + "\n" + "\n".join(lines)
    return block
