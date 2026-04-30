"""Bot-facing widget authoring diagnostics."""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

from app.agent.context import (
    current_bot_id,
    current_channel_id,
    current_correlation_id,
    current_session_id,
    current_task_id,
)
from app.db.engine import async_session
from app.services.agent_capabilities import build_agent_capability_manifest
from app.services.html_widget_authoring_check import run_html_widget_authoring_check
from app.services.widget_agency_receipts import (
    create_widget_authoring_receipt,
    serialize_widget_agency_receipt,
)
from app.services.widget_authoring_check import run_widget_authoring_check
from app.tools.registry import register
from app.tools.registry import _tools as _local_tools


_SCHEMA = {
    "type": "function",
    "function": {
        "name": "check_widget_authoring",
        "description": (
            "Run the full authoring feedback loop for a draft tool-widget YAML "
            "template before saving, pinning, or asking the user to rely on it. "
            "Checks YAML/Python/schema validation, preview rendering, static "
            "widget health, and optionally a Playwright runtime smoke check in "
            "the real widget host. Use this for tool-widget authoring; use "
            "preview_widget/check_widget for standalone HTML widgets."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "yaml_template": {"type": "string", "description": "Tool-widget YAML template body."},
                "python_code": {"type": "string", "description": "Optional transform code referenced by self:* hooks."},
                "sample_payload": {"type": "object", "description": "Representative tool result JSON used for preview."},
                "widget_config": {"type": "object", "description": "Optional runtime widget_config used during substitution."},
                "tool_name": {"type": "string", "description": "Tool name this renderer targets."},
                "include_runtime": {
                    "type": "boolean",
                    "description": "When true, run Playwright against the real widget preview host.",
                },
                "include_screenshot": {
                    "type": "boolean",
                    "description": "When true and runtime smoke runs, include a PNG data URL for visual inspection.",
                },
            },
            "required": ["yaml_template"],
        },
    },
}


_RETURNS = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "readiness": {"type": "string"},
        "summary": {"type": "string"},
        "phases": {"type": "array"},
        "issues": {"type": "array"},
        "envelope": {"type": ["object", "null"]},
        "artifacts": {"type": "object"},
    },
    "additionalProperties": True,
}


_RECEIPT_RETURNS = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "receipt_id": {"type": ["string", "null"]},
        "summary": {"type": "string"},
        "dashboard_key": {"type": ["string", "null"]},
        "affected_pin_ids": {"type": "array", "items": {"type": "string"}},
        "metadata": {"type": "object"},
        "warning": {"type": ["string", "null"]},
        "error": {"type": "string"},
    },
    "additionalProperties": True,
}


_AUTHORING_TOOLS = (
    "get_skill",
    "widget_library_list",
    "file",
    "preview_widget",
    "check_html_widget_authoring",
    "check_widget_authoring",
    "emit_html_widget",
    "pin_widget",
    "check_widget",
    "publish_widget_authoring_receipt",
    "inspect_widget_pin",
    "describe_dashboard",
    "list_api_endpoints",
    "call_api",
)

_AUTHORING_SKILLS = (
    "widgets",
    "widgets/html",
    "widgets/sdk",
    "widgets/styling",
    "widgets/errors",
    "widgets/channel_dashboards",
    "widgets/authoring_runs",
)


def _slug_from_goal(goal: str) -> str:
    words = re.findall(r"[a-z0-9]+", goal.lower())
    if not words:
        return "custom-widget"
    stop = {"a", "an", "the", "for", "with", "widget", "dashboard", "please", "make", "build", "create"}
    picked = [word for word in words if word not in stop][:4]
    return "-".join(picked or words[:4])[:48].strip("-") or "custom-widget"


def _lane_for_goal(goal: str, data_sources: list[str] | None) -> str:
    text = " ".join([goal, *(data_sources or [])]).lower()
    if any(token in text for token in ("native", "built-in", "builtin", "first-party")):
        return "native_widget_if_catalog_match"
    if any(token in text for token in ("tool result", "tool-widget", "tool widget", "yaml", "template", "preset")):
        return "tool_widget"
    return "html_widget"


def _scope_for_request(preferred_scope: str, goal: str) -> str:
    value = (preferred_scope or "auto").strip().lower()
    if value in {"bot", "workspace", "inline"}:
        return value
    text = goal.lower()
    if any(token in text for token in ("team", "workspace", "shared", "everyone")):
        return "workspace"
    return "bot"


def _tool_presence() -> tuple[list[str], list[str]]:
    available = [name for name in _AUTHORING_TOOLS if name in _local_tools]
    missing = [name for name in _AUTHORING_TOOLS if name not in _local_tools]
    return available, missing


def _skill_presence(manifest: dict[str, Any]) -> tuple[list[str], list[str]]:
    enrolled = {
        row.get("id")
        for row in (manifest.get("skills", {}).get("bot_enrolled") or [])
        + (manifest.get("skills", {}).get("channel_enrolled") or [])
        if isinstance(row, dict)
    }
    available = [skill for skill in _AUTHORING_SKILLS if skill in enrolled]
    missing = [skill for skill in _AUTHORING_SKILLS if skill not in enrolled]
    return available, missing


_PREPARE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "prepare_widget_authoring",
        "description": (
            "Prepare a concrete bot authoring brief for creating or improving a "
            "widget. This is the first tool to call when the user asks for a "
            "custom widget and the bot needs to know which widget lane, skills, "
            "tools, bundle path, validation checks, and post-pin evidence loop "
            "to use. It does not mutate files or dashboards."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "What the widget should help the user do."},
                "target_surface": {
                    "type": "string",
                    "enum": ["chat", "channel_dashboard", "spatial_canvas", "dashboard", "unknown"],
                    "description": "Where the widget should appear first. Default unknown.",
                },
                "preferred_scope": {
                    "type": "string",
                    "enum": ["auto", "bot", "workspace", "inline"],
                    "description": "Where reusable HTML bundles should live. Default auto.",
                },
                "data_sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Known tools/APIs/files the widget may use.",
                },
            },
            "required": ["goal"],
        },
    },
}


@register(_PREPARE_SCHEMA, safety_tier="readonly", requires_bot_context=True, requires_channel_context=False, returns={
    "type": "object",
    "properties": {
        "goal": {"type": "string"},
        "lane": {"type": "string"},
        "target_surface": {"type": "string"},
        "bundle": {"type": "object"},
        "required_skills": {"type": "array", "items": {"type": "string"}},
        "missing_skills": {"type": "array", "items": {"type": "string"}},
        "required_tools": {"type": "array", "items": {"type": "string"}},
        "missing_tools": {"type": "array", "items": {"type": "string"}},
        "api": {"type": "object"},
        "validation_sequence": {"type": "array", "items": {"type": "object"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "next_calls": {"type": "array", "items": {"type": "object"}},
    },
    "required": ["goal", "lane", "bundle", "required_tools", "validation_sequence"],
})
async def prepare_widget_authoring(
    goal: str,
    target_surface: str = "unknown",
    preferred_scope: str = "auto",
    data_sources: list[str] | None = None,
) -> str:
    bot_id = current_bot_id.get()
    channel_id = current_channel_id.get()
    async with async_session() as db:
        manifest = await build_agent_capability_manifest(
            db,
            bot_id=bot_id,
            channel_id=channel_id,
            session_id=current_session_id.get(),
            include_schemas=False,
            include_endpoints=False,
            max_tools=80,
        )

    lane = _lane_for_goal(goal, data_sources)
    scope = _scope_for_request(preferred_scope, goal)
    slug = _slug_from_goal(goal)
    if scope == "inline":
        bundle = {
            "scope": "inline",
            "library_ref": None,
            "recommended_files": [],
            "note": "Inline is acceptable for one-off chat output; use bot/workspace scope for anything reusable.",
        }
    else:
        bundle = {
            "scope": scope,
            "library_ref": f"{scope}/{slug}",
            "recommended_files": [
                f"widget://{scope}/{slug}/index.html",
                f"widget://{scope}/{slug}/widget.yaml",
            ],
        }

    available_tools, missing_tools = _tool_presence()
    available_skills, missing_skills = _skill_presence(manifest)
    scopes = manifest.get("api", {}).get("scopes") or []
    risks: list[str] = []
    if not channel_id and target_surface in {"channel_dashboard", "dashboard", "spatial_canvas"}:
        risks.append("No channel context is active; dashboard pinning may need an explicit dashboard/channel target.")
    if not scopes:
        risks.append("The bot has no API scopes, so widget JS cannot call authenticated app APIs until scopes are granted.")
    if data_sources and not any(scope_name.startswith("tools:") for scope_name in scopes):
        risks.append("Data sources mention tools/APIs, but this bot may lack tools/API execution scopes.")
    if lane == "tool_widget":
        risks.append("Tool widgets need a representative sample payload; call the source tool or inspect a recent trace before authoring YAML.")

    if lane == "tool_widget":
        validation_sequence = [
            {"tool": "get_skill", "args": {"skill_id": "widgets"}, "why": "Load the widget taxonomy and tool-widget lane rules."},
            {"tool": "check_widget_authoring", "args": {"include_runtime": True, "include_screenshot": True}, "why": "Validate YAML/Python, render a draft envelope, and smoke-test the real host."},
            {"tool": "pin_widget", "args": {"source_kind": "library"}, "why": "Pin only after full check passes, if this should live on a dashboard."},
            {"tool": "check_widget", "why": "Verify the created pin and use inspect_widget_pin only if health reports issues."},
            {"tool": "publish_widget_authoring_receipt", "args": {"action": "checked"}, "why": "Record the work and validation evidence where widget owners can see it."},
        ]
    else:
        validation_sequence = [
            {"tool": "get_skill", "args": {"skill_id": "widgets"}, "why": "Load the start-here widget decision tree."},
            {"tool": "get_skill", "args": {"skill_id": "widgets/html"}, "why": "Load bundle/path/runtime rules before writing files."},
            {"tool": "widget_library_list", "args": {"scope": "all"}, "why": "Reuse or extend an existing widget before creating a new bundle."},
            {"tool": "file", "args": {"path": bundle["recommended_files"][0] if bundle["recommended_files"] else None}, "why": "Create or update the HTML bundle source."},
            {"tool": "check_html_widget_authoring", "args": {"library_ref": bundle["library_ref"], "include_runtime": True, "include_screenshot": True}, "why": "Validate preview, static health, and runtime host behavior before emit/pin."},
            {"tool": "emit_html_widget" if target_surface == "chat" else "pin_widget", "args": {"library_ref": bundle["library_ref"]} if target_surface == "chat" else {"widget": bundle["library_ref"], "source_kind": "library"}, "why": "Place the checked widget on the requested surface."},
            {"tool": "check_widget", "why": "Verify the created pin and use inspect_widget_pin only if health reports issues."},
            {"tool": "publish_widget_authoring_receipt", "args": {"library_ref": bundle["library_ref"], "action": "checked"}, "why": "Record the work and validation evidence where widget owners can see it."},
        ]

    payload = {
        "goal": goal,
        "lane": lane,
        "target_surface": target_surface,
        "bundle": bundle,
        "required_skills": list(_AUTHORING_SKILLS),
        "available_skills": available_skills,
        "missing_skills": missing_skills,
        "available_tools": available_tools,
        "required_tools": list(_AUTHORING_TOOLS),
        "missing_tools": missing_tools,
        "api": {
            "scopes": scopes,
            "endpoint_count": manifest.get("api", {}).get("endpoint_count", 0),
            "use_list_api_endpoints_before_fetching": True,
        },
        "validation_sequence": validation_sequence,
        "risks": risks,
        "next_calls": validation_sequence[:3],
    }
    return json.dumps(payload, ensure_ascii=False)


_HTML_SCHEMA = {
    "type": "function",
    "function": {
        "name": "check_html_widget_authoring",
        "description": (
            "Run the full authoring feedback loop for a standalone HTML widget "
            "before emitting, pinning, or asking the user to rely on it. Accepts "
            "the same source modes as preview_widget/emit_html_widget: exactly "
            "one of `library_ref`, `html`, or `path`. Checks previewability, "
            "manifest/CSP/path errors, static widget health, and optionally a "
            "Playwright runtime smoke check in the real widget host. Use this "
            "for bot-authored library/path/inline HTML widgets; use "
            "check_widget_authoring for tool-widget YAML."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "library_ref": {"type": "string", "description": "Library widget ref such as bot/project_status or workspace/team_board."},
                "html": {"type": "string", "description": "Inline HTML body. Mutually exclusive with path/library_ref."},
                "path": {"type": "string", "description": "Workspace HTML path. Mutually exclusive with html/library_ref."},
                "js": {"type": "string", "description": "Optional inline JS for html mode."},
                "css": {"type": "string", "description": "Optional inline CSS for html mode."},
                "display_label": {"type": "string", "description": "Short widget label used in the preview envelope."},
                "display_mode": {"type": "string", "enum": ["inline", "panel"], "description": "Space hint for the eventual dashboard pin."},
                "runtime": {"type": "string", "enum": ["html", "react"], "description": "HTML runtime flavor. Use react for JSX widgets."},
                "extra_csp": {"type": "object", "description": "Per-widget CSP extensions, same shape as emit_html_widget.extra_csp."},
                "include_runtime": {"type": "boolean", "description": "When true, run Playwright against the real widget preview host."},
                "include_screenshot": {"type": "boolean", "description": "When true and runtime smoke runs, include a PNG data URL."},
            },
        },
    },
}


_PUBLISH_RECEIPT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "publish_widget_authoring_receipt",
        "description": (
            "Publish a durable in-context receipt after creating, updating, "
            "debugging, checking, or improving a widget. This records what "
            "the bot touched and what evidence it collected; it does not edit "
            "files, pins, or dashboards. Use this after the authoring/check "
            "loop so users can see bot widget activity where the widget lives."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "dashboard_key": {
                    "type": "string",
                    "description": "Dashboard key that owns the work, e.g. channel:<uuid>. Defaults from channel context when omitted.",
                },
                "channel_id": {
                    "type": "string",
                    "description": "Channel UUID for channel-dashboard receipts. Defaults to current channel context.",
                },
                "pin_id": {"type": "string", "description": "Primary widget dashboard pin id affected by this work."},
                "affected_pin_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Additional affected pin ids.",
                },
                "library_ref": {"type": "string", "description": "Library ref or widget:// bundle ref that was authored or checked."},
                "action": {
                    "type": "string",
                    "enum": ["created", "updated", "debugged", "checked", "improved"],
                    "description": "Kind of authoring activity. Stored as authoring_<action>.",
                },
                "summary": {"type": "string", "description": "One-sentence user-facing summary of the widget work."},
                "reason": {"type": "string", "description": "Why this work was done."},
                "touched_files": {"type": "array", "items": {"type": "string"}},
                "health_status": {"type": "string"},
                "health_summary": {"type": "string"},
                "check_phases": {"type": "array", "items": {"type": "object"}},
                "screenshot_data_url": {
                    "type": "string",
                    "description": "Optional PNG data URL from check_html_widget_authoring/check_widget_authoring include_screenshot.",
                },
                "next_actions": {"type": "array", "items": {"type": "object"}},
                "metadata": {"type": "object", "description": "Small extra structured evidence."},
            },
            "required": ["action", "summary"],
        },
    },
}


def _uuid_or_none(value: object) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


@register(_SCHEMA, safety_tier="readonly", requires_bot_context=True, requires_channel_context=False, returns=_RETURNS)
async def check_widget_authoring(
    yaml_template: str,
    python_code: str | None = None,
    sample_payload: dict[str, Any] | None = None,
    widget_config: dict[str, Any] | None = None,
    tool_name: str | None = None,
    include_runtime: bool = True,
    include_screenshot: bool = False,
) -> str:
    channel_id = current_channel_id.get()
    result = await run_widget_authoring_check(
        yaml_template=yaml_template,
        python_code=python_code,
        sample_payload=sample_payload,
        widget_config=widget_config,
        tool_name=tool_name,
        source_bot_id=current_bot_id.get(),
        source_channel_id=str(channel_id) if channel_id else None,
        include_runtime=include_runtime,
        include_screenshot=include_screenshot,
    )
    return json.dumps(result, ensure_ascii=False, default=str)


@register(_HTML_SCHEMA, safety_tier="readonly", requires_bot_context=True, requires_channel_context=False, returns={
    **_RETURNS,
    "properties": {
        **_RETURNS["properties"],
        "next_actions": {"type": "array", "items": {"type": "object"}},
    },
})
async def check_html_widget_authoring(
    html: str | None = None,
    path: str | None = None,
    library_ref: str | None = None,
    js: str = "",
    css: str = "",
    display_label: str = "",
    extra_csp: dict | None = None,
    display_mode: str = "inline",
    runtime: str | None = None,
    include_runtime: bool = True,
    include_screenshot: bool = False,
) -> str:
    result = await run_html_widget_authoring_check(
        html=html,
        path=path,
        library_ref=library_ref,
        js=js,
        css=css,
        display_label=display_label,
        extra_csp=extra_csp,
        display_mode=display_mode,
        runtime=runtime,
        include_runtime=include_runtime,
        include_screenshot=include_screenshot,
    )
    return json.dumps(result, ensure_ascii=False, default=str)


@register(
    _PUBLISH_RECEIPT_SCHEMA,
    safety_tier="mutating",
    requires_bot_context=True,
    requires_channel_context=False,
    returns=_RECEIPT_RETURNS,
)
async def publish_widget_authoring_receipt(
    action: str,
    summary: str,
    dashboard_key: str | None = None,
    channel_id: str | None = None,
    pin_id: str | None = None,
    affected_pin_ids: list[str] | None = None,
    library_ref: str | None = None,
    reason: str | None = None,
    touched_files: list[str] | None = None,
    health_status: str | None = None,
    health_summary: str | None = None,
    check_phases: list[dict[str, Any]] | None = None,
    screenshot_data_url: str | None = None,
    next_actions: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Record widget authoring evidence after the bot has checked or changed a widget."""

    cid = _uuid_or_none(channel_id) or current_channel_id.get()
    normalized_dashboard_key = (dashboard_key or "").strip()
    if not normalized_dashboard_key and cid:
        normalized_dashboard_key = f"channel:{cid}"
    if not normalized_dashboard_key:
        return json.dumps({
            "ok": False,
            "receipt_id": None,
            "summary": summary,
            "dashboard_key": None,
            "affected_pin_ids": [],
            "metadata": {},
            "warning": None,
            "error": "dashboard_key is required when no channel context is active.",
        }, ensure_ascii=False)

    async with async_session() as db:
        receipt, warning = await create_widget_authoring_receipt(
            db,
            channel_id=cid,
            dashboard_key=normalized_dashboard_key,
            action=action,
            summary=summary,
            reason=reason,
            bot_id=current_bot_id.get(),
            session_id=current_session_id.get(),
            correlation_id=current_correlation_id.get(),
            task_id=current_task_id.get(),
            pin_id=pin_id,
            affected_pin_ids=affected_pin_ids,
            library_ref=library_ref,
            touched_files=touched_files,
            health_status=health_status,
            health_summary=health_summary,
            check_phases=check_phases,
            screenshot_data_url=screenshot_data_url,
            next_actions=next_actions,
            metadata=metadata,
        )
        serialized = serialize_widget_agency_receipt(receipt)

    return json.dumps({
        "ok": True,
        "receipt_id": serialized["id"],
        "summary": serialized["summary"],
        "dashboard_key": serialized["dashboard_key"],
        "affected_pin_ids": serialized["affected_pin_ids"],
        "metadata": serialized["metadata"],
        "warning": warning,
        "receipt": serialized,
    }, ensure_ascii=False, default=str)
