"""Bot-facing widget health-check tools."""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.agent.context import current_channel_id
from app.db.engine import async_session
from app.services.widget_health import (
    check_dashboard_widgets as _check_dashboard_widgets,
    check_envelope_health,
    check_pin_health,
)
from app.tools.registry import register


_CHECK_WIDGET_SCHEMA = {
    "type": "function",
    "function": {
        "name": "check_widget",
        "description": (
            "Run a widget health check. Use pin_id for an already-pinned "
            "widget. For draft HTML/library widgets, pass the same one-of "
            "library_ref/html/path shape used by preview_widget; this catches "
            "static issues before pinning. Pinned checks persist the latest "
            "summary for dashboard/UI badges."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pin_id": {"type": "string", "description": "Dashboard pin UUID to check."},
                "library_ref": {"type": "string", "description": "Draft library widget ref, e.g. bot/status."},
                "html": {"type": "string", "description": "Draft inline HTML body."},
                "path": {"type": "string", "description": "Draft channel/workspace HTML path."},
                "js": {"type": "string", "description": "Optional inline JS for draft html mode."},
                "css": {"type": "string", "description": "Optional inline CSS for draft html mode."},
                "extra_csp": {"type": "object", "description": "Optional CSP extensions for draft widgets."},
                "display_label": {"type": "string"},
                "include_browser": {
                    "type": "boolean",
                    "description": "When true, try an opportunistic Playwright smoke check for pinned widgets.",
                },
            },
        },
    },
}


_CHECK_DASHBOARD_SCHEMA = {
    "type": "function",
    "function": {
        "name": "check_dashboard_widgets",
        "description": (
            "Run health checks for widgets on a dashboard and persist latest "
            "summaries. Omit dashboard_key in channel context to check the "
            "current channel dashboard."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "dashboard_key": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                "include_browser": {"type": "boolean"},
            },
        },
    },
}


_HEALTH_RETURNS = {
    "type": "object",
    "properties": {
        "status": {"type": "string"},
        "summary": {"type": "string"},
        "issues": {"type": "array"},
        "phases": {"type": "array"},
    },
    "additionalProperties": True,
}


def _one_of_draft_sources(*values: str | None) -> int:
    return sum(1 for value in values if isinstance(value, str) and value.strip())


async def _preview_draft_envelope(
    *,
    library_ref: str | None,
    html: str | None,
    path: str | None,
    js: str | None,
    css: str | None,
    extra_csp: dict[str, Any] | None,
    display_label: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    from app.tools.local.preview_widget import preview_widget

    raw = await preview_widget(
        library_ref=library_ref,
        html=html,
        path=path,
        js=js,
        css=css,
        display_label=display_label,
        extra_csp=extra_csp,
    )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None, {"error": "preview_widget returned invalid JSON", "raw": raw}
    if not parsed.get("ok"):
        return None, {
            "status": "failing",
            "summary": "preview_widget failed before health checks could run.",
            "preview": parsed,
        }
    envelope = parsed.get("envelope")
    if not isinstance(envelope, dict):
        return None, {"error": "preview_widget did not return an envelope", "preview": parsed}
    return envelope, None


@register(_CHECK_WIDGET_SCHEMA, safety_tier="readonly", requires_bot_context=True, requires_channel_context=False, returns=_HEALTH_RETURNS)
async def check_widget(
    pin_id: str | None = None,
    library_ref: str | None = None,
    html: str | None = None,
    path: str | None = None,
    js: str | None = None,
    css: str | None = None,
    extra_csp: dict[str, Any] | None = None,
    display_label: str | None = None,
    include_browser: bool = True,
) -> str:
    if pin_id and _one_of_draft_sources(library_ref, html, path):
        return json.dumps({"error": "Provide pin_id or one draft source, not both."})
    if pin_id:
        try:
            parsed_pin_id = uuid.UUID(pin_id)
        except (TypeError, ValueError):
            return json.dumps({"error": f"Invalid pin_id: {pin_id!r}"})
        async with async_session() as db:
            result = await check_pin_health(db, parsed_pin_id, include_browser=include_browser)
        return json.dumps(result, ensure_ascii=False, default=str)

    if _one_of_draft_sources(library_ref, html, path) != 1:
        return json.dumps({"error": "Provide exactly one of pin_id, library_ref, html, or path."})
    envelope, preview_error = await _preview_draft_envelope(
        library_ref=library_ref,
        html=html,
        path=path,
        js=js,
        css=css,
        extra_csp=extra_csp,
        display_label=display_label,
    )
    if preview_error:
        return json.dumps(preview_error, ensure_ascii=False, default=str)
    assert envelope is not None
    result = await check_envelope_health(
        envelope,
        target_ref=library_ref or path or "inline_html",
        include_browser=False,
    )
    return json.dumps(result, ensure_ascii=False, default=str)


@register(_CHECK_DASHBOARD_SCHEMA, safety_tier="readonly", requires_bot_context=True, requires_channel_context=False, returns=_HEALTH_RETURNS)
async def check_dashboard_widgets(
    dashboard_key: str | None = None,
    limit: int = 20,
    include_browser: bool = True,
) -> str:
    key = dashboard_key
    if not key:
        channel_id = current_channel_id.get()
        if not channel_id:
            return json.dumps({"error": "dashboard_key is required outside channel context."})
        key = f"channel:{channel_id}"
    async with async_session() as db:
        result = await _check_dashboard_widgets(
            db,
            key,
            limit=limit,
            include_browser=include_browser,
        )
    return json.dumps(result, ensure_ascii=False, default=str)
