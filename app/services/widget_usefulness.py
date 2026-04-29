"""Deterministic widget usefulness analysis for channel dashboards."""
from __future__ import annotations

import json
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Project
from app.services.dashboard_pins import list_pins, serialize_pin
from app.services.widget_context import build_pinned_widget_context_snapshot
from app.services.widget_health import latest_health_for_pins


_CHAT_VISIBLE_ZONES = {"rail", "header", "dock"}
_LAYOUT_VISIBLE_ZONES = {
    "full": {"rail", "header", "dock"},
    "rail-header-chat": {"rail", "header"},
    "rail-chat": {"rail"},
    "dashboard-only": set(),
}
_SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3}


def _label(pin: dict[str, Any]) -> str:
    env = pin.get("envelope") if isinstance(pin.get("envelope"), dict) else {}
    return str(
        env.get("display_label")
        or pin.get("display_label")
        or pin.get("tool_name")
        or pin.get("id")
        or "widget"
    )


def _pin_id(pin: dict[str, Any]) -> str | None:
    raw = pin.get("id")
    return str(raw) if raw else None


def _zone(pin: dict[str, Any]) -> str:
    zone = pin.get("zone")
    return zone if zone in {"rail", "header", "dock", "grid"} else "grid"


def _context_export_enabled(pin: dict[str, Any]) -> bool:
    contract = pin.get("widget_contract")
    if not isinstance(contract, dict):
        return False
    context_export = contract.get("context_export")
    return isinstance(context_export, dict) and context_export.get("enabled") is True


def _available_actions(pin: dict[str, Any]) -> list[dict[str, Any]]:
    actions = pin.get("available_actions")
    if isinstance(actions, list):
        return [item for item in actions if isinstance(item, dict)]
    contract = pin.get("widget_contract")
    if not isinstance(contract, dict):
        return []
    raw = contract.get("actions")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _native_ref(pin: dict[str, Any]) -> str | None:
    env = pin.get("envelope") if isinstance(pin.get("envelope"), dict) else {}
    body = env.get("body") if isinstance(env.get("body"), dict) else {}
    ref = body.get("widget_ref")
    return ref.strip() if isinstance(ref, str) and ref.strip() else None


def _source_signature(pin: dict[str, Any]) -> str:
    native_ref = _native_ref(pin)
    if native_ref:
        return f"native:{native_ref}"

    origin = pin.get("widget_origin")
    if isinstance(origin, dict):
        origin_bits = [
            origin.get("definition_kind"),
            origin.get("instantiation_kind"),
            origin.get("source_ref"),
            origin.get("library_ref"),
            origin.get("widget_ref"),
        ]
        compact = [str(bit) for bit in origin_bits if isinstance(bit, str) and bit.strip()]
        if compact:
            return "origin:" + "|".join(compact)

    tool_name = pin.get("tool_name")
    if isinstance(tool_name, str) and tool_name.strip():
        config = pin.get("widget_config") if isinstance(pin.get("widget_config"), dict) else {}
        args = pin.get("tool_args") if isinstance(pin.get("tool_args"), dict) else {}
        payload = json.dumps({"config": config, "args": args}, sort_keys=True, default=str)
        return f"tool:{tool_name.strip()}:{payload}"

    source_kind = pin.get("source_kind")
    label = _label(pin).strip().lower()
    return f"{source_kind or 'unknown'}:{label}"


def _recommendation(
    *,
    type: str,
    severity: str,
    surface: str,
    reason: str,
    suggested_next_action: str,
    pin: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    requires_policy_decision: bool = False,
) -> dict[str, Any]:
    return {
        "type": type,
        "severity": severity,
        "surface": surface,
        "pin_id": _pin_id(pin) if pin else None,
        "label": _label(pin) if pin else None,
        "reason": reason,
        "evidence": evidence or {},
        "suggested_next_action": suggested_next_action,
        "requires_policy_decision": requires_policy_decision,
    }


def _overall_recommendation_status(recommendations: list[dict[str, Any]]) -> str:
    if not recommendations:
        return "healthy"
    worst = max((_SEVERITY_RANK.get(str(item.get("severity")), 0) for item in recommendations), default=0)
    if worst >= _SEVERITY_RANK["high"]:
        return "action_required"
    if worst >= _SEVERITY_RANK["medium"]:
        return "needs_attention"
    return "has_suggestions"


def _chat_visible_zones(layout_mode: str) -> set[str]:
    return set(_LAYOUT_VISIBLE_ZONES.get(layout_mode, _LAYOUT_VISIBLE_ZONES["full"]))


def assess_widget_usefulness_from_data(
    *,
    channel_id: str,
    channel_name: str | None,
    channel_config: dict[str, Any] | None,
    pins: list[dict[str, Any]],
    widget_health: dict[str, dict[str, Any]] | None = None,
    context_snapshot: dict[str, Any] | None = None,
    project: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Analyze already-loaded dashboard data.

    This stays pure so recommendation rules can be tested without DB fixtures.
    """
    cfg = channel_config or {}
    layout_mode = str(cfg.get("layout_mode") or "full")
    visible_zones = _chat_visible_zones(layout_mode)
    health_by_pin = widget_health or {}
    recommendations: list[dict[str, Any]] = []

    if not pins:
        if project:
            action = "Consider starter Project widgets such as files, todo/standing-order, or a Project status panel."
            reason = "This Project-bound channel has no pinned widgets yet."
        else:
            action = "Consider starter widgets for the channel's main work: notes, todo, files, or an integration-specific status widget."
            reason = "This channel has no pinned widgets yet."
        recommendations.append(_recommendation(
            type="missing_coverage",
            severity="medium",
            surface="dashboard",
            reason=reason,
            suggested_next_action=action,
            evidence={"project_bound": bool(project)},
        ))

    for pin in pins:
        pid = _pin_id(pin)
        health = health_by_pin.get(str(pid)) if pid else None
        status = health.get("status") if isinstance(health, dict) else None
        if status in {"failing", "warning"}:
            severity = "high" if status == "failing" else "medium"
            recommendations.append(_recommendation(
                type="health",
                severity=severity,
                surface="dashboard",
                pin=pin,
                reason=f"Latest widget health is {status}: {health.get('summary') or 'no summary'}",
                suggested_next_action="Run check_widget for this pin, then inspect_widget_pin if the health issue needs raw browser evidence.",
                evidence={"health": health},
            ))

    by_signature: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pin in pins:
        by_signature[_source_signature(pin)].append(pin)
        by_label[_label(pin).strip().lower()].append(pin)
    seen_duplicate_pins: set[str] = set()
    for group in list(by_signature.values()) + list(by_label.values()):
        if len(group) < 2:
            continue
        ids = [str(_pin_id(pin) or "") for pin in group]
        key = "|".join(sorted(ids))
        if key in seen_duplicate_pins:
            continue
        seen_duplicate_pins.add(key)
        recommendations.append(_recommendation(
            type="duplicate",
            severity="medium",
            surface="dashboard",
            pin=group[0],
            reason=f"{len(group)} pinned widgets appear to overlap in purpose.",
            suggested_next_action="Review these pins and consolidate, rename, or resize them if they serve the same job.",
            evidence={"pin_ids": ids, "labels": [_label(pin) for pin in group]},
            requires_policy_decision=True,
        ))

    chat_visible_count = 0
    hidden_chat_pins: list[dict[str, Any]] = []
    for pin in pins:
        zone = _zone(pin)
        if zone in visible_zones:
            chat_visible_count += 1
        elif zone in _CHAT_VISIBLE_ZONES:
            hidden_chat_pins.append(pin)
    for pin in hidden_chat_pins:
        recommendations.append(_recommendation(
            type="visibility",
            severity="medium",
            surface="chat",
            pin=pin,
            reason=f"Pin is in the { _zone(pin) } zone, but channel layout mode {layout_mode!r} hides that zone in chat.",
            suggested_next_action="Move the pin to a visible zone or change the channel presentation mode if this widget should be visible while chatting.",
            evidence={"layout_mode": layout_mode, "zone": _zone(pin), "visible_zones": sorted(visible_zones)},
            requires_policy_decision=True,
        ))
    if pins and chat_visible_count == 0 and layout_mode != "dashboard-only":
        recommendations.append(_recommendation(
            type="missing_coverage",
            severity="low",
            surface="chat",
            reason="No pinned widgets are currently visible in the chat-side surfaces.",
            suggested_next_action="Promote one high-signal widget to rail, header, or dock if it should stay visible during conversation.",
            evidence={"layout_mode": layout_mode, "visible_zones": sorted(visible_zones)},
            requires_policy_decision=True,
        ))

    exported_count = (
        int(context_snapshot.get("exported_count") or 0)
        if isinstance(context_snapshot, dict)
        else sum(1 for pin in pins if pin.get("context_summary"))
    )
    export_enabled_count = sum(1 for pin in pins if _context_export_enabled(pin))
    if pins and exported_count == 0:
        severity = "medium" if export_enabled_count else "low"
        recommendations.append(_recommendation(
            type="context",
            severity=severity,
            surface="chat",
            reason="No pinned widgets currently export useful context into the channel prompt.",
            suggested_next_action="Enable context_export on widgets whose state should guide future chat turns, or leave disabled for purely visual widgets.",
            evidence={"export_enabled_count": export_enabled_count, "exported_count": exported_count},
            requires_policy_decision=True,
        ))

    for pin in pins:
        actions = _available_actions(pin)
        if actions and not pin.get("context_hint"):
            recommendations.append(_recommendation(
                type="actionability",
                severity="low",
                surface="chat",
                pin=pin,
                reason="Widget declares bot-callable actions, but no action hint is exported for chat turns.",
                suggested_next_action="Add or enable a context_export hint if bots should naturally operate this widget from chat.",
                evidence={"action_ids": [action.get("id") or action.get("name") for action in actions[:6]]},
                requires_policy_decision=True,
            ))

    recommendations.sort(
        key=lambda item: (
            -_SEVERITY_RANK.get(str(item.get("severity")), 0),
            str(item.get("type") or ""),
            str(item.get("label") or ""),
        )
    )
    status = _overall_recommendation_status(recommendations)
    project_scope_available = bool(project)
    summary = (
        "No actionable widget findings."
        if not recommendations
        else f"{len(recommendations)} widget usefulness finding(s): {recommendations[0]['reason']}"
    )
    return {
        "channel_id": channel_id,
        "channel_name": channel_name,
        "dashboard_key": f"channel:{channel_id}",
        "status": status,
        "summary": summary,
        "pin_count": len(pins),
        "chat_visible_pin_count": chat_visible_count,
        "layout_mode": layout_mode,
        "project_scope_available": project_scope_available,
        "project": project,
        "context_export": context_snapshot or {
            "exported_count": exported_count,
            "export_enabled_count": export_enabled_count,
        },
        "recommendations": recommendations,
    }


async def assess_channel_widget_usefulness(
    db: AsyncSession,
    channel_id: uuid.UUID | str,
    *,
    bot_id: str | None = None,
) -> dict[str, Any]:
    parsed_channel_id = channel_id if isinstance(channel_id, uuid.UUID) else uuid.UUID(str(channel_id))
    channel = await db.get(Channel, parsed_channel_id)
    if channel is None:
        raise ValueError(f"Channel not found: {channel_id}")

    pin_rows = await list_pins(db, dashboard_key=f"channel:{channel.id}")
    pins = [serialize_pin(row) for row in pin_rows]
    health = await latest_health_for_pins(db, [pin.get("id") for pin in pins if pin.get("id")])
    context_snapshot = await build_pinned_widget_context_snapshot(
        db,
        pins,
        bot_id=bot_id or channel.bot_id,
        channel_id=str(channel.id),
    )

    project_payload: dict[str, Any] | None = None
    if channel.project_id:
        project = await db.get(Project, channel.project_id)
        if project is not None:
            attached_count = (await db.execute(
                select(func.count()).select_from(Channel).where(Channel.project_id == project.id)
            )).scalar_one()
            project_payload = {
                "id": str(project.id),
                "name": project.name,
                "slug": project.slug,
                "root_path": project.root_path,
                "workspace_id": str(project.workspace_id),
                "attached_channel_count": int(attached_count or 0),
            }

    return assess_widget_usefulness_from_data(
        channel_id=str(channel.id),
        channel_name=channel.name,
        channel_config=channel.config if isinstance(channel.config, dict) else {},
        pins=pins,
        widget_health=health,
        context_snapshot=context_snapshot,
        project=project_payload,
    )
