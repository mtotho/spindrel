"""Pinned-widget state injection for the assembled LLM context.

Produces a single plain-text system message summarizing the current state of
every widget pinned to the channel. Positioned right after the temporal block
in `context_assembly.py` so it stays out of the cacheable prefix.

The caller is responsible for sourcing the pins (from `channel.config`). This
module has no I/O and no awareness of the DB.
"""
from __future__ import annotations

from datetime import datetime, timezone


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


def build_widget_context_block(
    pins: list[dict] | None,
    *,
    bot_id: str,
    now: datetime | None = None,
) -> str | None:
    """Render pinned widgets as a plain-text system message.

    `pins` is `channel.config["pinned_widgets"]` verbatim. Returns None when
    there are no pins or none of them have usable `plain_body` state.
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
