"""Pinned-widget context export for chat-profile prompt assembly."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

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


def _normalize_line(value: str) -> str:
    return " ".join(value.split())


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def is_pinned_widget_context_enabled(channel_config: object) -> bool:
    if not isinstance(channel_config, dict):
        return True
    value = channel_config.get("pinned_widget_context_enabled")
    return True if value is None else bool(value)


def _display_label_for_pin(pin: dict[str, Any]) -> str:
    env = pin.get("envelope") or {}
    return (
        env.get("display_label")
        or pin.get("display_label")
        or pin.get("display_name")
        or pin.get("tool_name")
        or "widget"
    )


def _pin_actions(pin: dict[str, Any]) -> list[dict[str, Any]]:
    actions = pin.get("available_actions")
    if isinstance(actions, list) and actions:
        return [action for action in actions if isinstance(action, dict)]
    contract = pin.get("widget_contract") or {}
    raw_actions = contract.get("actions")
    if not isinstance(raw_actions, list):
        return []
    return [action for action in raw_actions if isinstance(action, dict)]


def _resolve_channel_id_from_pins(pins: list[dict[str, Any]] | None) -> str | None:
    if not pins:
        return None
    for pin in pins:
        if not isinstance(pin, dict):
            continue
        source_channel_id = pin.get("source_channel_id")
        if isinstance(source_channel_id, str) and source_channel_id.strip():
            return source_channel_id.strip()
        dashboard_key = pin.get("dashboard_key")
        if isinstance(dashboard_key, str) and dashboard_key.startswith("channel:"):
            return dashboard_key.split(":", 1)[1].strip() or None
    return None


def _context_export_contract(pin: dict[str, Any]) -> dict[str, Any] | None:
    contract = pin.get("widget_contract")
    if not isinstance(contract, dict):
        return None
    context_export = contract.get("context_export")
    if not isinstance(context_export, dict):
        return None
    if context_export.get("enabled") is not True:
        return None
    return context_export


def _summarize_plain_body(pin: dict[str, Any]) -> str | None:
    env = pin.get("envelope") or {}
    body = env.get("plain_body")
    if not isinstance(body, str):
        return None
    cleaned = _normalize_line(body.strip())
    return cleaned or None


def _snippet(text: str | None, *, limit: int = 90) -> str | None:
    if not isinstance(text, str):
        return None
    cleaned = _normalize_line(text.strip())
    if not cleaned:
        return None
    return _clip(cleaned, limit)


def _native_state(pin: dict[str, Any]) -> dict[str, Any]:
    env = pin.get("envelope") or {}
    body = env.get("body") or {}
    state = body.get("state")
    return state if isinstance(state, dict) else {}


def _native_widget_ref(pin: dict[str, Any]) -> str | None:
    env = pin.get("envelope") or {}
    body = env.get("body") or {}
    widget_ref = body.get("widget_ref")
    if isinstance(widget_ref, str) and widget_ref.strip():
        return widget_ref.strip()
    return None


def _summarize_notes_state(pin: dict[str, Any], *, now: datetime) -> str | None:
    state = _native_state(pin)
    snippet = _snippet(state.get("body"))
    updated = _relative_age(state.get("updated_at"), now)
    if snippet and updated:
        return f"{snippet} ({updated})"
    if snippet:
        return snippet
    if updated:
        return f"Empty note ({updated})"
    return "Empty note"


def _summarize_todo_state(pin: dict[str, Any]) -> str | None:
    state = _native_state(pin)
    items = state.get("items")
    if not isinstance(items, list):
        return None
    open_titles = [
        _normalize_line(str(item.get("title") or "").strip())
        for item in items
        if isinstance(item, dict) and not bool(item.get("done")) and str(item.get("title") or "").strip()
    ]
    done_count = sum(1 for item in items if isinstance(item, dict) and bool(item.get("done")))
    open_count = len(open_titles)
    summary = f"{open_count} open, {done_count} done"
    if open_titles:
        summary += f"; next: {', '.join(open_titles[:2])}"
    return summary


def _summarize_pinned_files_state(pin: dict[str, Any]) -> str | None:
    state = _native_state(pin)
    items = state.get("pinned_files")
    if not isinstance(items, list):
        return None
    active_path = state.get("active_path")
    active_name = None
    if isinstance(active_path, str) and active_path.strip():
        active_name = PurePosixPath(active_path.strip()).name or active_path.strip()
    count = len([item for item in items if isinstance(item, dict)])
    if active_name:
        return f"{count} pinned; active {active_name}"
    return f"{count} pinned"


def _summarize_standing_order_state(pin: dict[str, Any], *, now: datetime) -> str | None:
    state = _native_state(pin)
    goal = _snippet(state.get("goal"), limit=80) or "(no goal)"
    status = str(state.get("status") or "running")
    iterations = state.get("iterations")
    bits: list[str] = [status]
    if isinstance(iterations, int) and iterations:
        bits.append(f"{iterations} tick{'s' if iterations != 1 else ''}")
    if status in ("done", "failed", "cancelled"):
        reason = _snippet(state.get("terminal_reason"), limit=80)
        if reason:
            bits.append(reason)
    else:
        log = state.get("log")
        if isinstance(log, list) and log:
            last = log[-1]
            if isinstance(last, dict):
                text = _snippet(last.get("text"), limit=80)
                age = _relative_age(last.get("at"), now)
                if text and age:
                    bits.append(f"last: {text} ({age})")
                elif text:
                    bits.append(f"last: {text}")
    return f"\"{goal}\" — {'; '.join(bits)}"


def _summarize_native_state(pin: dict[str, Any], *, now: datetime) -> str | None:
    widget_ref = _native_widget_ref(pin)
    if widget_ref == "core/notes_native":
        return _summarize_notes_state(pin, now=now)
    if widget_ref == "core/todo_native":
        return _summarize_todo_state(pin)
    if widget_ref == "core/pinned_files_native":
        return _summarize_pinned_files_state(pin)
    if widget_ref == "core/standing_order_native":
        return _summarize_standing_order_state(pin, now=now)
    return None


async def _summarize_context_tracker(
    db: "AsyncSession",
    *,
    channel_id: str,
) -> str | None:
    from app.services.context_breakdown import fetch_latest_context_budget

    budget = await fetch_latest_context_budget(channel_id, db)
    if not isinstance(budget, dict):
        return None
    utilization = budget.get("utilization")
    current = budget.get("current_prompt_tokens")
    total = budget.get("total_tokens")
    parts: list[str] = []
    if isinstance(utilization, (int, float)):
        parts.append(f"{round(float(utilization) * 100)}% used")
    if isinstance(current, int) and isinstance(total, int) and total > 0:
        parts.append(f"{current:,} / {total:,} tokens")
    profile = budget.get("context_profile")
    if isinstance(profile, str) and profile.strip() and profile.strip() != "unknown":
        parts.append(f"profile {profile.strip()}")
    source = budget.get("source")
    if isinstance(source, str) and source.strip() == "estimate":
        parts.append("estimate")
    return "; ".join(parts) or None


async def _summarize_usage_forecast(db: "AsyncSession") -> str | None:
    from app.routers.api_v1_admin.usage import usage_forecast

    forecast = await usage_forecast(db)
    if hasattr(forecast, "model_dump"):
        forecast = forecast.model_dump()
    if not isinstance(forecast, dict):
        return None
    projected_daily = forecast.get("projected_daily")
    projected_monthly = forecast.get("projected_monthly")
    limits = forecast.get("limits") or []
    parts: list[str] = []
    if isinstance(projected_daily, (int, float)):
        parts.append(f"proj ${float(projected_daily):.2f}/day")
    if isinstance(projected_monthly, (int, float)):
        parts.append(f"${float(projected_monthly):.2f}/mo")
    worst_limit = None
    if isinstance(limits, list):
        for limit in limits:
            if not isinstance(limit, dict):
                continue
            projected_pct = limit.get("projected_percentage")
            if isinstance(projected_pct, (int, float)) and (
                worst_limit is None or float(projected_pct) > worst_limit
            ):
                worst_limit = float(projected_pct)
    if worst_limit is not None:
        parts.append(f"worst limit {round(worst_limit)}%")
    return "; ".join(parts) or None


async def _summarize_upcoming_activity(db: "AsyncSession") -> str | None:
    from app.routers.api_v1_admin.upcoming import upcoming_activity

    payload = await upcoming_activity(limit=3, db=db)
    if not isinstance(payload, dict):
        return None
    items = payload.get("items")
    if not isinstance(items, list):
        return None
    count = len(items)
    next_item = items[0] if items else None
    next_title = None
    if isinstance(next_item, dict):
        next_title = _snippet(str(next_item.get("title") or next_item.get("type") or ""))
    if count and next_title:
        return f"{count} upcoming; next: {next_title}"
    if count:
        return f"{count} upcoming"
    return "No upcoming activity"


async def _summarize_server_provider(
    db: "AsyncSession",
    pin: dict[str, Any],
    *,
    channel_id: str | None,
) -> str | None:
    widget_ref = _native_widget_ref(pin)
    if widget_ref == "core/context_tracker":
        if not channel_id:
            return None
        return await _summarize_context_tracker(db, channel_id=channel_id)
    if widget_ref == "core/usage_forecast_native":
        return await _summarize_usage_forecast(db)
    if widget_ref == "core/upcoming_activity_native":
        return await _summarize_upcoming_activity(db)
    return None


def _build_invoke_widget_action_hint(pin: dict[str, Any]) -> str | None:
    actions = [action.get("id") for action in _pin_actions(pin) if isinstance(action.get("id"), str)]
    if not actions:
        return None
    action_preview = ", ".join(actions[:4])
    return (
        f"Use invoke_widget_action(pin_id='{pin.get('id')}', action=...) "
        f"for actions like {action_preview}."
    )


def _build_handler_tools_hint(pin: dict[str, Any]) -> str | None:
    actions = [action.get("id") for action in _pin_actions(pin) if isinstance(action.get("id"), str)]
    if not actions:
        return None
    action_preview = ", ".join(actions[:4])
    return f"Bot-callable widget handler tools are available for actions like {action_preview}."


def _build_context_hint(pin: dict[str, Any], context_export: dict[str, Any]) -> str | None:
    hint_kind = context_export.get("hint_kind")
    if hint_kind == "invoke_widget_action":
        return _build_invoke_widget_action_hint(pin)
    if hint_kind == "handler_tools":
        return _build_handler_tools_hint(pin)
    if hint_kind == "custom":
        hint_text = context_export.get("hint_text")
        if isinstance(hint_text, str) and hint_text.strip():
            return hint_text.strip()
    return None


async def enrich_pins_for_context_export(
    db: "AsyncSession",
    pins: list[dict] | None,
    *,
    bot_id: str,
    now: datetime | None = None,
    channel_id: str | None = None,
) -> list[dict]:
    if not pins:
        return []
    now = now or datetime.now(timezone.utc)
    resolved_channel_id = channel_id or _resolve_channel_id_from_pins(pins)
    enriched: list[dict] = []
    for raw_pin in pins:
        if not isinstance(raw_pin, dict):
            continue
        pin = dict(raw_pin)
        context_export = _context_export_contract(pin)
        if context_export is None:
            enriched.append(pin)
            continue
        summary_kind = context_export.get("summary_kind")
        summary: str | None = None
        if summary_kind == "plain_body":
            summary = _summarize_plain_body(pin)
        elif summary_kind == "native_state":
            summary = _summarize_native_state(pin, now=now)
        elif summary_kind == "server_provider":
            summary = await _summarize_server_provider(
                db,
                pin,
                channel_id=resolved_channel_id,
            )
        if summary:
            pin["context_summary"] = _clip(summary, _MAX_LINE_CHARS)
            context_hint = _build_context_hint(pin, context_export)
            if context_hint:
                pin["context_hint"] = _clip(_normalize_line(context_hint), _MAX_LINE_CHARS)
        enriched.append(pin)
    return enriched


def _build_context_row_from_pin(
    pin: dict[str, Any],
    *,
    bot_id: str,
    now: datetime,
) -> dict[str, Any] | None:
    summary = pin.get("context_summary")
    if not isinstance(summary, str) or not summary.strip():
        context_export = _context_export_contract(pin)
        if context_export is None:
            return None
        if context_export.get("summary_kind") != "plain_body":
            return None
        summary = _summarize_plain_body(pin)
    if not isinstance(summary, str) or not summary.strip():
        return None

    label = _display_label_for_pin(pin)
    line = f"- {label}: {_normalize_line(summary.strip())}"

    context_hint = pin.get("context_hint")
    hint_value = None
    if isinstance(context_hint, str) and context_hint.strip():
        hint_value = _normalize_line(context_hint.strip())
        line += f" Hint: {hint_value}"

    suffix_bits: list[str] = []
    pin_bot = pin.get("bot_id") or pin.get("source_bot_id")
    if isinstance(pin_bot, str) and pin_bot and pin_bot != bot_id:
        suffix_bits.append(f"pinned by {pin_bot}")
    age = _relative_age(pin.get("pinned_at"), now)
    if age:
        suffix_bits.append(f"updated {age}")
    if suffix_bits:
        line += f" ({'; '.join(suffix_bits)})"

    line = _clip(line, _MAX_LINE_CHARS + 96)
    return {
        "pin_id": str(pin.get("id") or ""),
        "label": label,
        "summary": _normalize_line(summary.strip()),
        "hint": hint_value,
        "line": line,
        "chars": len(line),
    }


async def build_pinned_widget_context_snapshot(
    db: "AsyncSession",
    pins: list[dict] | None,
    *,
    bot_id: str,
    now: datetime | None = None,
    channel_id: str | None = None,
    enabled: bool = True,
    disabled_reason: str = "channel_disabled",
) -> dict[str, Any]:
    raw_pins = [dict(pin) for pin in (pins or []) if isinstance(pin, dict)]
    if not enabled:
        skipped = [
            {
                "pin_id": str(pin.get("id") or ""),
                "label": _display_label_for_pin(pin),
                "reason": disabled_reason,
            }
            for pin in raw_pins
        ]
        return {
            "enabled": False,
            "total_pins": len(raw_pins),
            "exported_count": 0,
            "skipped_count": len(skipped),
            "total_chars": 0,
            "truncated": False,
            "rows": [],
            "skipped": skipped,
            "block_text": None,
        }

    now = now or datetime.now(timezone.utc)
    enriched = await enrich_pins_for_context_export(
        db,
        raw_pins,
        bot_id=bot_id,
        now=now,
        channel_id=channel_id,
    )

    candidate_rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for pin in enriched:
        context_export = _context_export_contract(pin)
        if context_export is None:
            skipped.append({
                "pin_id": str(pin.get("id") or ""),
                "label": _display_label_for_pin(pin),
                "reason": "export_disabled",
            })
            continue
        row = _build_context_row_from_pin(pin, bot_id=bot_id, now=now)
        if row is None:
            skipped.append({
                "pin_id": str(pin.get("id") or ""),
                "label": _display_label_for_pin(pin),
                "reason": "no_summary",
            })
            continue
        candidate_rows.append(row)

    kept_rows = list(candidate_rows[:_MAX_PINS])
    if len(candidate_rows) > _MAX_PINS:
        for row in candidate_rows[_MAX_PINS:]:
            skipped.append({
                "pin_id": row["pin_id"],
                "label": row["label"],
                "reason": "trimmed",
            })

    block_text = None
    truncated = False
    if kept_rows:
        block_text = _HEADER + "\n" + "\n".join(str(row["line"]) for row in kept_rows)
        while len(block_text) > _MAX_TOTAL_CHARS and len(kept_rows) > 1:
            trimmed = kept_rows.pop()
            skipped.append({
                "pin_id": trimmed["pin_id"],
                "label": trimmed["label"],
                "reason": "trimmed",
            })
            truncated = True
            block_text = _HEADER + "\n" + "\n".join(str(row["line"]) for row in kept_rows)

    return {
        "enabled": True,
        "total_pins": len(raw_pins),
        "exported_count": len(kept_rows),
        "skipped_count": len(skipped),
        "total_chars": len(block_text) if block_text else 0,
        "truncated": truncated or len(candidate_rows) > len(kept_rows),
        "rows": kept_rows,
        "skipped": skipped,
        "block_text": block_text,
    }


async def fetch_channel_pin_dicts(
    db: "AsyncSession",
    channel_id: uuid.UUID | str,
) -> list[dict]:
    from app.services.dashboard_pins import list_pins, serialize_pin

    rows = await list_pins(db, dashboard_key=f"channel:{channel_id}")
    out: list[dict] = []
    for row in rows:
        pin = serialize_pin(row)
        pin["display_name"] = pin.get("display_label") or pin.get("tool_name")
        pin["bot_id"] = pin.get("source_bot_id") or ""
        pin["config"] = pin.get("widget_config") or {}
        out.append(pin)
    return out


def build_widget_context_block(
    pins: list[dict] | None,
    *,
    bot_id: str,
    now: datetime | None = None,
) -> str | None:
    if not pins:
        return None
    now = now or datetime.now(timezone.utc)

    lines: list[str] = []
    for pin in pins[:_MAX_PINS]:
        if not isinstance(pin, dict):
            continue
        row = _build_context_row_from_pin(pin, bot_id=bot_id, now=now)
        if row is None:
            continue
        lines.append(str(row["line"]))

    if not lines:
        return None

    block = _HEADER + "\n" + "\n".join(lines)
    while len(block) > _MAX_TOTAL_CHARS and len(lines) > 1:
        lines.pop()
        block = _HEADER + "\n" + "\n".join(lines)
    return block
