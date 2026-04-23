"""Widget template engine — renders tool results as interactive components.

Integrations declare `tool_widgets:` in their YAML, and core tools live
under ``app/tools/local/widgets/<tool_name>/template.yaml`` — one folder
per tool, the folder name IS the tool name, the YAML body is the widget
definition with fields (``template`` / ``html_template`` / ``state_poll``
/ etc.) at the top level. When a tool returns JSON, the engine checks for
a matching template, substitutes variables from the result data, and
produces a ToolResultEnvelope.

Template syntax:
  - {{key}}          — simple key lookup from the parsed tool result JSON
  - {{a.b.c}}        — nested dot-path lookup
  - {{a[0].b}}       — array index + dot-path
  - {{a == 'x'}}     — equality expression → boolean
  - {{a | map: {label: name, value: id}}} — array map transform
  - {{a | in: x,y,z}} — membership test → boolean
  - {{a | not_empty}} — truthy test → boolean
  - {{a | status_color}} — map status strings to color names

Component-level features:
  - when: "{{expr}}"   — conditionally include/exclude a component
  - each: "{{array}}"  — iterate over an array to produce rows/items
    template: [...]     — template applied per item (use {{_.field}})

Code extensions:
  - transform: "module.path:function_name" — post-substitution Python hook
    receives (data: dict, components: list[dict]) → list[dict]
"""
from __future__ import annotations

import copy
import importlib
import json
import logging
import re
from pathlib import Path
from typing import Any

import yaml

from app.agent.tool_dispatch import ToolResultEnvelope

logger = logging.getLogger(__name__)

# Global map: tool_name → { content_type, display, template, transform? }
_widget_templates: dict[str, dict] = {}

# Template variable pattern — matches {{...}}
_VAR_PATTERN = re.compile(r"\{\{(.+?)\}\}")

# Status → color mapping (used by the status_color transform)
_STATUS_COLORS: dict[str, str] = {
    "active": "accent",
    "running": "info",
    "complete": "success",
    "completed": "success",
    "done": "success",
    "failed": "danger",
    "error": "danger",
    "cancelled": "muted",
    "canceled": "muted",
    "pending": "warning",
    "skipped": "muted",
    "open": "success",
    "closed": "muted",
    "merged": "accent",
}


# ── Template loading ──

def _register_widgets(
    source: str, widgets: dict, *, base_dir: Path | None = None,
) -> int:
    """Register tool_widgets from a source (integration ID, file path, etc.).

    Returns the number of templates registered. Later registrations do NOT
    override earlier ones — first-registered wins (integration > core).

    ``base_dir`` — used to resolve ``html_template.path`` references against
    an integration directory (or the core tools dir for core widgets). When
    omitted, path-mode HTML widgets are rejected (body-only).
    """
    from app.services.widget_package_validation import _validate_parsed_definition

    count = 0
    for tool_name, widget_def in widgets.items():
        # Skip YAML anchors (keys starting with _) — not real tool names
        if tool_name.startswith("_"):
            continue
        if not isinstance(widget_def, dict) or (
            "template" not in widget_def and "html_template" not in widget_def
        ):
            logger.warning(
                "%s: tool_widgets[%s] missing 'template' or 'html_template', skipping",
                source, tool_name,
            )
            continue

        if tool_name in _widget_templates:
            logger.debug(
                "%s: tool_widgets[%s] already registered (from %s), skipping",
                source, tool_name, _widget_templates[tool_name].get("source", "?"),
            )
            continue

        # If html_template.path is set, resolve it against base_dir and
        # inline the HTML body so the rest of the pipeline sees a
        # self-contained widget_def.
        resolved_def, resolve_err = _resolve_html_template_paths(widget_def, base_dir)
        if resolve_err:
            logger.error("%s: tool_widgets[%s]: %s", source, tool_name, resolve_err)
            continue
        widget_def = resolved_def

        # Component-tree validation — fail fast on misauthored templates
        # rather than letting them surface as `Unknown: <type>` blocks or
        # silent runtime errors. Extended to accept html_template shape.
        errors, warnings = _validate_parsed_definition(widget_def)
        for w in warnings:
            logger.warning("%s: tool_widgets[%s]: %s", source, tool_name, w.message)
        if errors:
            for e in errors:
                logger.error("%s: tool_widgets[%s]: %s", source, tool_name, e.message)
            continue

        is_html_mode = "html_template" in widget_def
        html_body: str | None = None
        if is_html_mode:
            html_body = widget_def["html_template"].get("body")

        # Expand fragment references, then default state_poll.template to
        # template if the author omitted it. Expansion errors skip the
        # widget (like schema errors).
        from app.services.widget_fragments import resolve_fragments
        expanded, frag_errors = resolve_fragments(widget_def)
        if frag_errors:
            for msg in frag_errors:
                logger.error("%s: tool_widgets[%s]: %s", source, tool_name, msg)
            continue
        state_poll = expanded.get("state_poll")
        # For component mode, default state_poll.template to the main template.
        # HTML mode ignores state_poll.template — the HTML file re-renders from
        # fresh toolResult JSON pushed into the iframe, no sub-template needed.
        if (
            isinstance(state_poll, dict)
            and state_poll.get("template") is None
            and not is_html_mode
            and expanded.get("template") is not None
        ):
            state_poll = {**state_poll, "template": copy.deepcopy(expanded["template"])}
            expanded["state_poll"] = state_poll

        default_content_type = (
            "application/vnd.spindrel.html+interactive"
            if is_html_mode
            else "application/vnd.spindrel.components+json"
        )

        _widget_templates[tool_name] = {
            "content_type": expanded.get("content_type", default_content_type),
            "display": expanded.get("display", "inline"),
            "view_key": expanded.get("view_key"),
            "template": expanded.get("template"),
            "html_template_body": html_body,
            "transform": expanded.get("transform"),
            "display_label": expanded.get("display_label"),
            "state_poll": expanded.get("state_poll"),
            "default_config": expanded.get("default_config") or {},
            "config_schema": expanded.get("config_schema"),
            "source": source,
        }
        count += 1
    return count


def _resolve_html_template_paths(
    widget_def: dict, base_dir: Path | None,
) -> tuple[dict, str | None]:
    """Inline ``html_template.path`` into ``html_template.body`` in-place.

    Returns (resolved_widget_def, error_message_or_None). The widget_def
    is always returned unmodified on error so callers can log and skip.
    """
    html_template = widget_def.get("html_template")
    if not isinstance(html_template, dict):
        return widget_def, None
    # Already inlined? Nothing to do.
    if html_template.get("body") is not None:
        return widget_def, None
    rel_path = html_template.get("path")
    if not rel_path:
        return widget_def, None
    if base_dir is None:
        return widget_def, (
            "html_template.path set but no base_dir available to resolve — "
            "use html_template.body instead"
        )
    try:
        resolved = (base_dir / rel_path).resolve()
        base_resolved = base_dir.resolve()
        if base_resolved not in resolved.parents and resolved != base_resolved:
            return widget_def, (
                f"html_template.path '{rel_path}' escapes base directory"
            )
        if not resolved.is_file():
            return widget_def, f"html_template.path '{rel_path}' not found"
        body_text = resolved.read_text()
    except Exception as exc:
        return widget_def, f"html_template.path '{rel_path}' read failed: {exc}"

    new_html_template = {**html_template, "body": body_text}
    new_html_template.pop("path", None)
    return {**widget_def, "html_template": new_html_template}, None


def load_widget_templates_from_manifests() -> None:
    """Load widget templates from all sources.

    Priority order (first-registered wins):
    1. Integration manifests (tool_widgets in integration.yaml)
    2. Core tool templates (``widgets/<tool_name>/template.yaml``)
    """
    from app.services.integration_manifests import get_all_manifests

    _widget_templates.clear()
    total = 0

    # 1. Integration manifests — highest priority
    for integration_id, manifest in get_all_manifests().items():
        tool_widgets = manifest.get("tool_widgets")
        if tool_widgets and isinstance(tool_widgets, dict):
            src_path = manifest.get("source_path")
            base_dir = Path(src_path).parent if src_path else None
            total += _register_widgets(
                f"integration:{integration_id}", tool_widgets, base_dir=base_dir,
            )

    # 2. Core tool widget templates — ``widgets/<tool_name>/template.yaml``.
    # The folder name is the tool name; html_template.path resolves against
    # the widget folder itself.
    widgets_root = Path(__file__).parent.parent / "tools" / "local" / "widgets"
    if widgets_root.is_dir():
        for entry in sorted(widgets_root.iterdir()):
            if not entry.is_dir():
                continue
            tmpl_path = entry / "template.yaml"
            if not tmpl_path.is_file():
                continue
            try:
                widget_def = yaml.safe_load(tmpl_path.read_text())
            except Exception:
                logger.warning(
                    "Failed to load core widget template %s", tmpl_path, exc_info=True,
                )
                continue
            if not isinstance(widget_def, dict):
                continue
            total += _register_widgets(
                f"core:{entry.name}", {entry.name: widget_def}, base_dir=entry,
            )

    if total:
        logger.info("Loaded %d widget templates", total)


def get_widget_template(tool_name: str) -> dict | None:
    """Return the widget template for a tool name, or None."""
    return _widget_templates.get(tool_name)


# ── DB-backed registry ──

def _build_entry_from_package(row) -> dict | None:
    """Build a ``_widget_templates`` entry dict from a WidgetTemplatePackage row.

    Parses YAML, loads optional Python code into a synthetic module, and
    rewrites ``self:`` transform refs to the synthetic module path. Returns
    None on parse/exec failure (caller marks the row ``is_invalid``).
    """
    from app.services.widget_package_loader import (
        load_package_module,
        resolve_transform_ref,
    )

    try:
        widget_def = yaml.safe_load(row.yaml_template)
    except Exception as exc:
        logger.warning(
            "Widget package %s (tool=%s) YAML parse failed: %s",
            row.id, row.tool_name, exc,
        )
        return None
    if not isinstance(widget_def, dict) or (
        "template" not in widget_def and "html_template" not in widget_def
    ):
        logger.warning(
            "Widget package %s (tool=%s) YAML missing 'template' or 'html_template' key",
            row.id, row.tool_name,
        )
        return None

    try:
        load_package_module(row.id, row.version, row.python_code)
    except Exception as exc:
        logger.warning(
            "Widget package %s (tool=%s) Python exec failed: %s",
            row.id, row.tool_name, exc,
        )
        return None

    transform = resolve_transform_ref(widget_def.get("transform"), row.id)
    state_poll = widget_def.get("state_poll")
    if isinstance(state_poll, dict) and "transform" in state_poll:
        state_poll = {
            **state_poll,
            "transform": resolve_transform_ref(state_poll.get("transform"), row.id),
        }

    html_template = widget_def.get("html_template")
    html_body: str | None = None
    is_html_mode = isinstance(html_template, dict)
    if is_html_mode:
        html_body = html_template.get("body")
        if not isinstance(html_body, str):
            logger.warning(
                "Widget package %s (tool=%s) html_template missing inlined 'body'",
                row.id, row.tool_name,
            )
            return None

    default_content_type = (
        "application/vnd.spindrel.html+interactive"
        if is_html_mode
        else "application/vnd.spindrel.components+json"
    )

    return {
        "content_type": widget_def.get("content_type", default_content_type),
        "display": widget_def.get("display", "inline"),
        "view_key": widget_def.get("view_key"),
        "template": widget_def.get("template"),
        "html_template_body": html_body,
        "transform": transform,
        "display_label": widget_def.get("display_label"),
        "state_poll": state_poll,
        "default_config": widget_def.get("default_config") or {},
        "config_schema": widget_def.get("config_schema"),
        "source": f"package:{row.id}",
        "package_id": str(row.id),
        "package_version": row.version,
    }


async def load_widget_templates_from_db() -> None:
    """Rebuild ``_widget_templates`` from active DB packages.

    Invalid packages (YAML or Python fails to load) are flagged
    ``is_invalid=true`` in DB and the tool falls back to the newest
    non-orphan seed for the same tool_name.
    """
    from sqlalchemy import select
    from app.db.engine import async_session
    from app.db.models import WidgetTemplatePackage

    _widget_templates.clear()

    async with async_session() as db:
        actives = (
            await db.execute(
                select(WidgetTemplatePackage).where(
                    WidgetTemplatePackage.is_active.is_(True),
                )
            )
        ).scalars().all()

        loaded = 0
        fell_back = 0
        for row in actives:
            entry = _build_entry_from_package(row)
            if entry is None:
                row.is_invalid = True
                row.invalid_reason = "YAML or Python failed to load — see server logs"
                fallback = await _pick_fallback_seed(db, row.tool_name, skip_id=row.id)
                if fallback is not None:
                    fb_entry = _build_entry_from_package(fallback)
                    if fb_entry is not None:
                        _widget_templates[row.tool_name] = fb_entry
                        fell_back += 1
                continue
            _widget_templates[row.tool_name] = entry
            loaded += 1

        await db.commit()

    logger.info(
        "Loaded %d widget templates from DB (%d fell back to seed)",
        loaded, fell_back,
    )


async def _pick_fallback_seed(db, tool_name: str, skip_id=None):
    """Newest non-orphan seed for a tool, excluding a given id."""
    from sqlalchemy import select
    from app.db.models import WidgetTemplatePackage

    stmt = select(WidgetTemplatePackage).where(
        WidgetTemplatePackage.tool_name == tool_name,
        WidgetTemplatePackage.source == "seed",
        WidgetTemplatePackage.is_orphaned.is_(False),
        WidgetTemplatePackage.is_invalid.is_(False),
    ).order_by(WidgetTemplatePackage.updated_at.desc())
    if skip_id is not None:
        stmt = stmt.where(WidgetTemplatePackage.id != skip_id)
    return (await db.execute(stmt)).scalars().first()


async def reload_tool(tool_name: str) -> None:
    """Refresh the in-memory entry for one tool after an API mutation."""
    from sqlalchemy import select
    from app.db.engine import async_session
    from app.db.models import WidgetTemplatePackage

    async with async_session() as db:
        active = (
            await db.execute(
                select(WidgetTemplatePackage).where(
                    WidgetTemplatePackage.tool_name == tool_name,
                    WidgetTemplatePackage.is_active.is_(True),
                )
            )
        ).scalars().first()

        if active is None:
            _widget_templates.pop(tool_name, None)
            return

        entry = _build_entry_from_package(active)
        if entry is None:
            active.is_invalid = True
            active.invalid_reason = "YAML or Python failed to load — see server logs"
            fallback = await _pick_fallback_seed(db, tool_name, skip_id=active.id)
            await db.commit()
            if fallback is not None:
                fb_entry = _build_entry_from_package(fallback)
                if fb_entry is not None:
                    _widget_templates[tool_name] = fb_entry
                    return
            _widget_templates.pop(tool_name, None)
            return

        _widget_templates[tool_name] = entry


def substitute_vars(obj: Any, data: dict) -> Any:
    """Public helper: deep-substitute ``{{...}}`` expressions in a template/dict.

    Used by callers outside this module (e.g. state_poll args) to template
    widget_meta values into arbitrary YAML-loaded structures.
    """
    return _substitute(copy.deepcopy(obj), data)


def _build_widget_template_envelope(
    *,
    content_type: str,
    body: Any,
    plain_body: str,
    display: str,
    display_label: str | None = None,
    refreshable: bool = False,
    refresh_interval_seconds: int | None = None,
    source_bot_id: str | None = None,
    source_channel_id: str | None = None,
    view_key: str | None = None,
    data: Any | None = None,
    template_id: str | None = None,
) -> ToolResultEnvelope:
    if isinstance(body, str):
        body_text = body
    else:
        body_text = json.dumps(body, ensure_ascii=False)

    return ToolResultEnvelope(
        content_type=content_type,
        body=body_text,
        plain_body=plain_body,
        display=display,  # type: ignore[arg-type]
        byte_size=len(body_text.encode("utf-8")),
        display_label=display_label,
        refreshable=refreshable,
        refresh_interval_seconds=refresh_interval_seconds,
        source_bot_id=source_bot_id,
        source_channel_id=source_channel_id,
        view_key=view_key,
        data=data,
        template_id=template_id,
    )


def apply_widget_template(
    tool_name: str,
    raw_result: str,
    widget_config: dict | None = None,
) -> ToolResultEnvelope | None:
    """Apply a widget template to a raw tool result, returning an envelope or None.

    Returns None if no template exists or if the result can't be parsed as JSON.
    MCP tool names are often prefixed with the server name (e.g., "homeassistant-HassTurnOn"),
    so we try both the full name and the bare name (after stripping the server prefix).

    ``widget_config`` — per-pin config dict. Merged over the template's
    ``default_config`` and exposed as ``{{config.*}}`` during substitution so
    templates can gate components on user-toggled options (e.g. show_forecast).
    """
    tmpl = _widget_templates.get(tool_name)
    # Try stripping MCP server prefix: "server-ToolName" → "ToolName"
    if not tmpl and "-" in tool_name:
        bare_name = tool_name.split("-", 1)[1]
        tmpl = _widget_templates.get(bare_name)
    if not tmpl:
        return None

    # Parse the raw result as JSON for variable substitution
    try:
        data = json.loads(raw_result)
    except (json.JSONDecodeError, TypeError):
        logger.debug("Widget template for %s: result is not JSON, skipping", tool_name)
        return None

    if not isinstance(data, dict):
        logger.debug("Widget template for %s: result is not a dict, skipping", tool_name)
        return None

    # Shallow-merge default_config < widget_config → data["config"]
    merged_config = {**(tmpl.get("default_config") or {}), **(widget_config or {})}
    data_with_config = {**data, "config": merged_config}

    # Resolve display_label if declared in the template (shared across modes)
    display_label = None
    raw_label = tmpl.get("display_label")
    if raw_label and isinstance(raw_label, str):
        resolved = _substitute_string(raw_label, data_with_config)
        if resolved and isinstance(resolved, str) and resolved.strip():
            display_label = resolved.strip()

    state_poll = tmpl.get("state_poll") or {}
    interval = state_poll.get("refresh_interval_seconds")
    plain_body = f"Widget: {tool_name}"

    # HTML template mode: bake the tool's JSON result into a
    # `window.spindrel.toolResult` preamble, then concatenate the shipped
    # HTML body. The iframe renderer wraps in a `<!doctype>` + CSP shell.
    # Refreshes go through apply_state_poll (which reuses the preamble
    # pipeline with fresh data).
    if tmpl.get("html_template_body") is not None:
        # Capture current bot/channel context so the iframe can mint a
        # widget-auth token and call channel-scoped APIs. Matches the
        # stamping pattern in emit_html_widget.
        from app.agent.context import current_bot_id, current_channel_id
        bot_id = current_bot_id.get()
        channel_val = current_channel_id.get()
        channel_str = str(channel_val) if channel_val else None

        body = _build_html_widget_body(tmpl["html_template_body"], data_with_config)
        return _build_widget_template_envelope(
            content_type=tmpl.get(
                "content_type", "application/vnd.spindrel.html+interactive",
            ),
            body=body,
            plain_body=plain_body,
            display=tmpl.get("display", "inline"),
            display_label=display_label,
            refreshable=bool(tmpl.get("state_poll")),
            refresh_interval_seconds=int(interval) if interval else None,
            source_bot_id=bot_id if bot_id else None,
            source_channel_id=channel_str,
            view_key=tmpl.get("view_key"),
            data=data_with_config,
            template_id=f"{tmpl.get('source', 'template')}:{tool_name}",
        )

    # Component template mode (legacy/default)
    filled = _substitute(copy.deepcopy(tmpl["template"]), data_with_config)

    # Apply code extension if declared
    transform_ref = tmpl.get("transform")
    if transform_ref and isinstance(filled, dict):
        components = filled.get("components")
        if isinstance(components, list):
            filled["components"] = _apply_code_transform(transform_ref, data_with_config, components)

    body = json.dumps(filled)

    return _build_widget_template_envelope(
        content_type=tmpl["content_type"],
        body=body,
        plain_body=plain_body,
        display=tmpl["display"],
        display_label=display_label,
        refreshable=bool(tmpl.get("state_poll")),
        refresh_interval_seconds=int(interval) if interval else None,
        view_key=tmpl.get("view_key"),
        data=data_with_config,
        template_id=f"{tmpl.get('source', 'template')}:{tool_name}",
    )


def _build_html_widget_body(html_template_body: str, tool_result_json: dict) -> str:
    """Prepend a `window.spindrel.toolResult = {...}` preamble to the HTML body.

    The preamble runs before any user script in the body, so widget JS can
    synchronously read `window.spindrel.toolResult` at load time. Refresh
    pushes new values via `window.spindrel.__setToolResult(...)` (see the
    iframe renderer) without reloading srcDoc.

    Escapes `</script>` occurrences in the JSON to keep the preamble from
    closing early if a string literal in the tool result includes it.
    """
    json_payload = json.dumps(tool_result_json, ensure_ascii=False)
    # Break any `</script>` literal so the host <script> tag isn't terminated
    # mid-JSON. Browsers treat this as a pure escape on the JS side.
    # Also escape U+2028 / U+2029 — valid JSON, but JS treats them as line
    # terminators inside string literals, breaking the inline script with
    # `Invalid or unexpected token`. Common in scraped article/RSS content.
    safe_json = (
        json_payload
        .replace("</", "<\\/")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    # Mirrors `.scroll-subtle` in ui/global.css. The host flips
    # `documentElement.dataset.hoverScrollbars = "1"` on the iframe once it's
    # loaded when the dashboard has `grid_config.hover_scrollbars` on, so the
    # widget's own document-level scrollbar follows the same hover-reveal
    # behavior as the tile's outer scroll container.
    scrollbar_style = (
        "<style>"
        "html[data-hover-scrollbars=\"1\"],"
        "html[data-hover-scrollbars=\"1\"] body,"
        "html[data-hover-scrollbars=\"1\"] * {"
        " scrollbar-width: none;"
        " scrollbar-color: transparent transparent;"
        " transition: scrollbar-color 200ms ease;"
        "}"
        "html[data-hover-scrollbars=\"1\"]:hover,"
        "html[data-hover-scrollbars=\"1\"]:focus-within,"
        "html[data-hover-scrollbars=\"1\"]:hover body,"
        "html[data-hover-scrollbars=\"1\"]:focus-within body,"
        "html[data-hover-scrollbars=\"1\"]:hover *,"
        "html[data-hover-scrollbars=\"1\"]:focus-within * {"
        " scrollbar-width: thin;"
        " scrollbar-color: rgba(153,163,180,0.35) transparent;"
        "}"
        "html[data-hover-scrollbars=\"1\"]::-webkit-scrollbar,"
        "html[data-hover-scrollbars=\"1\"] body::-webkit-scrollbar,"
        "html[data-hover-scrollbars=\"1\"] *::-webkit-scrollbar {"
        " width: 0; height: 0;"
        "}"
        "html[data-hover-scrollbars=\"1\"]::-webkit-scrollbar-track {"
        " background: transparent;"
        "}"
        "html[data-hover-scrollbars=\"1\"]::-webkit-scrollbar-thumb,"
        "html[data-hover-scrollbars=\"1\"] body::-webkit-scrollbar-thumb,"
        "html[data-hover-scrollbars=\"1\"] *::-webkit-scrollbar-thumb {"
        " background: transparent;"
        " border-radius: 3px;"
        " transition: background-color 200ms ease;"
        "}"
        "html[data-hover-scrollbars=\"1\"]:hover::-webkit-scrollbar,"
        "html[data-hover-scrollbars=\"1\"]:focus-within::-webkit-scrollbar,"
        "html[data-hover-scrollbars=\"1\"]:hover body::-webkit-scrollbar,"
        "html[data-hover-scrollbars=\"1\"]:focus-within body::-webkit-scrollbar,"
        "html[data-hover-scrollbars=\"1\"]:hover *::-webkit-scrollbar,"
        "html[data-hover-scrollbars=\"1\"]:focus-within *::-webkit-scrollbar {"
        " width: 6px; height: 6px;"
        "}"
        "html[data-hover-scrollbars=\"1\"]:hover::-webkit-scrollbar-thumb,"
        "html[data-hover-scrollbars=\"1\"]:focus-within::-webkit-scrollbar-thumb,"
        "html[data-hover-scrollbars=\"1\"]:hover body::-webkit-scrollbar-thumb,"
        "html[data-hover-scrollbars=\"1\"]:focus-within body::-webkit-scrollbar-thumb,"
        "html[data-hover-scrollbars=\"1\"]:hover *::-webkit-scrollbar-thumb,"
        "html[data-hover-scrollbars=\"1\"]:focus-within *::-webkit-scrollbar-thumb {"
        " background: rgba(153,163,180,0.35);"
        "}"
        "</style>\n"
    )
    preamble = (
        "<script>"
        "window.spindrel = window.spindrel || {};"
        f"window.spindrel.toolResult = {safe_json};"
        "</script>\n"
    )
    return scrollbar_style + preamble + html_template_body


def get_state_poll_config(tool_name: str) -> dict | None:
    """Return the state_poll config for a tool, or None.

    Tries the full name first, then strips the MCP server prefix.
    """
    tmpl = _widget_templates.get(tool_name)
    if not tmpl and "-" in tool_name:
        tmpl = _widget_templates.get(tool_name.split("-", 1)[1])
    if not tmpl:
        return None
    return tmpl.get("state_poll")


def apply_state_poll(
    tool_name: str, raw_result: str, widget_meta: dict,
) -> ToolResultEnvelope | None:
    """Apply a state_poll template to a raw poll result.

    ``widget_meta`` carries pinned widget metadata (display_label, etc.)
    that the code transform can use to filter the poll result. For HTML
    widgets it should also carry ``source_bot_id`` and ``source_channel_id``
    so the refreshed envelope keeps iframe auth intact (otherwise
    ``window.spindrel.api()`` stops working on the next render).

    Flow: raw_result → code transform (optional) → template substitution → envelope.
    """
    poll_cfg = get_state_poll_config(tool_name)
    if not poll_cfg:
        return None

    # Resolve the owning widget template — it tells us whether to render as
    # components or as HTML with a fresh preamble.
    owner_tmpl = _widget_templates.get(tool_name) or (
        _widget_templates.get(tool_name.split("-", 1)[1])
        if "-" in tool_name else None
    ) or {}
    is_html_mode = owner_tmpl.get("html_template_body") is not None

    if not is_html_mode and "template" not in poll_cfg:
        # Component-mode widgets still require state_poll.template.
        return None

    # Run code transform if declared — reshape raw result for template
    transform_ref = poll_cfg.get("transform")
    if transform_ref:
        data = _apply_state_poll_transform(transform_ref, raw_result, widget_meta)
    else:
        try:
            data = json.loads(raw_result)
        except (json.JSONDecodeError, TypeError):
            return None

    if not isinstance(data, dict):
        return None

    merged_config = {
        **(owner_tmpl.get("default_config") or {}),
        **(widget_meta.get("config") or {}),
    }
    data_with_config = {**data, "config": merged_config}

    display_label = widget_meta.get("display_label")
    interval = poll_cfg.get("refresh_interval_seconds")

    # HTML mode: rebuild body with fresh toolResult preamble. The iframe
    # renderer extracts the new JSON and pushes it in via
    # window.spindrel.__setToolResult without reloading srcDoc. The merged
    # pin config rides along under ``toolResult.config`` so widgets can
    # gate rendering on user-toggled state (e.g. starred URLs, units).
    if is_html_mode:
        body = _build_html_widget_body(owner_tmpl["html_template_body"], data_with_config)
        return _build_widget_template_envelope(
            content_type="application/vnd.spindrel.html+interactive",
            body=body,
            plain_body=f"Widget: {tool_name}",
            display=owner_tmpl.get("display", "inline"),
            display_label=display_label,
            refreshable=True,
            refresh_interval_seconds=int(interval) if interval else None,
            source_bot_id=widget_meta.get("source_bot_id"),
            source_channel_id=widget_meta.get("source_channel_id"),
            view_key=owner_tmpl.get("view_key"),
            data=data_with_config,
            template_id=f"{owner_tmpl.get('source', 'template')}:{tool_name}",
        )

    # Component-template mode
    filled = _substitute(copy.deepcopy(poll_cfg["template"]), data_with_config)
    body = json.dumps(filled)

    return _build_widget_template_envelope(
        content_type="application/vnd.spindrel.components+json",
        body=body,
        plain_body=f"Widget: {tool_name}",
        display="inline",
        display_label=display_label,
        refreshable=True,
        refresh_interval_seconds=int(interval) if interval else None,
        view_key=owner_tmpl.get("view_key"),
        data=data_with_config,
        template_id=f"{owner_tmpl.get('source', 'template')}:{tool_name}",
    )


def _apply_state_poll_transform(ref: str, raw_result: str, widget_meta: dict) -> dict:
    """Call a state poll transform: 'module.path:function_name'.

    Receives (raw_result_str, widget_meta) and returns a dict for template substitution.
    """
    try:
        module_path, func_name = ref.rsplit(":", 1)
        module = importlib.import_module(module_path)
        func = getattr(module, func_name)
        return func(raw_result, widget_meta)
    except Exception:
        logger.warning("State poll transform '%s' failed", ref, exc_info=True)
        return {}


# ── Code extension hook ──

def _apply_code_transform(ref: str, data: dict, components: list[dict]) -> list[dict]:
    """Call a Python transform function: 'module.path:function_name'.

    The function receives (data, components) and returns a modified components list.
    """
    try:
        module_path, func_name = ref.rsplit(":", 1)
        module = importlib.import_module(module_path)
        func = getattr(module, func_name)
        return func(data, components)
    except Exception:
        logger.warning("Widget transform '%s' failed, using template as-is", ref, exc_info=True)
        return components


# ── Variable substitution ──

def _substitute(obj: Any, data: dict) -> Any:
    """Recursively substitute {{...}} expressions in a template structure."""
    if isinstance(obj, str):
        return _substitute_string(obj, data)
    elif isinstance(obj, dict):
        # Handle `each:` expansion before recursing
        if "each" in obj and "template" in obj:
            return _expand_each(obj, data)
        return {k: _substitute(v, data) for k, v in obj.items() if k != "when"}
    elif isinstance(obj, list):
        # Filter items with `when:` conditionals, then substitute
        result = []
        for item in obj:
            if isinstance(item, dict) and "when" in item:
                condition = _substitute_string(item["when"], data) if isinstance(item["when"], str) else item["when"]
                if not _is_truthy(condition):
                    continue
            result.append(_substitute(item, data))
        return result
    return obj


def _is_truthy(value: Any) -> bool:
    """Determine if a value is truthy for `when:` conditionals."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value not in ("", "false", "False", "null", "None", "0")
    if isinstance(value, (list, dict)):
        return len(value) > 0
    if isinstance(value, (int, float)):
        return value != 0
    return True


def _expand_each(obj: dict, data: dict) -> Any:
    """Expand an `each:` directive into a list of items.

    ```yaml
    each: "{{items}}"
    template: ["{{_.name}}", "{{_.value}}"]
    ```

    Iterates over the resolved array, substituting `_` as the current item.
    """
    array_expr = obj["each"]
    template = obj["template"]

    # Resolve the array
    if isinstance(array_expr, str):
        array = _substitute_string(array_expr, data)
    else:
        array = array_expr

    if not isinstance(array, list):
        return []

    result = []
    for item in array:
        # Create a data overlay with `_` as the current item
        item_data = {**data, "_": item}
        row = _substitute(copy.deepcopy(template), item_data)
        result.append(row)
    return result


def _substitute_string(s: str, data: dict) -> Any:
    """Substitute {{...}} in a string.

    If the ENTIRE string is a single {{...}} expression, the result can be
    any type (bool, list, dict). If the string contains mixed text and
    expressions, the result is always a string.
    """
    # Fast path: entire string is a single expression. Use prefix/suffix
    # checks (not fullmatch) because the non-greedy _VAR_PATTERN will happily
    # span across multiple {{...}} pairs under fullmatch's backtracking.
    stripped = s.strip()
    if (
        stripped.startswith("{{")
        and stripped.endswith("}}")
        and stripped.count("{{") == 1
        and stripped.count("}}") == 1
    ):
        return _evaluate_expression(stripped[2:-2].strip(), data)

    # Mixed content: substitute inline, convert results to strings
    def replacer(match: re.Match) -> str:
        result = _evaluate_expression(match.group(1).strip(), data)
        if isinstance(result, bool):
            return "true" if result else "false"
        if result is None:
            return ""
        return str(result)

    return _VAR_PATTERN.sub(replacer, s)


def _evaluate_expression(expr: str, data: dict) -> Any:
    """Evaluate a template expression.

    Supports:
      - key              → data["key"]
      - a.b.c            → data["a"]["b"]["c"]
      - a[0].b           → data["a"][0]["b"]
      - a == 'val'       → data["a"] == "val"  (returns bool)
      - a | map: {l: n}  → [{"l": item["n"]} for item in data["a"]]
    """
    # Pipe expressions: value | transform (preserve trailing whitespace in transforms
    # so separators like ", " in "join: , " aren't lost)
    if "|" in expr:
        parts = expr.split("|", 1)
        value = _resolve_path(parts[0].strip(), data)
        transform = parts[1].lstrip()  # only strip leading space, preserve trailing
        return _apply_transform(value, transform, data)

    # Equality expression: a == 'val' or a == "val"
    eq_match = re.match(r"(.+?)\s*==\s*['\"](.+?)['\"]", expr)
    if eq_match:
        left = _resolve_path(eq_match.group(1).strip(), data)
        right = eq_match.group(2)
        return left == right

    # Simple path lookup
    return _resolve_path(expr, data)


def _resolve_path(path: str, data: Any) -> Any:
    """Resolve a dot-path with optional array indices: a.b[0].c"""
    # Split on dots, handling array indices
    parts = re.split(r"\.(?![^\[]*\])", path)
    current = data

    for part in parts:
        if current is None:
            return None

        # Check for array index: key[0]
        idx_match = re.match(r"(.+?)\[(\d+)\]", part)
        if idx_match:
            key = idx_match.group(1)
            idx = int(idx_match.group(2))
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None
            if isinstance(current, list) and 0 <= idx < len(current):
                current = current[idx]
            else:
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None

    return current


def _format_date_relative(value: Any) -> str:
    """Format an ISO 8601 timestamp as a compact relative string.

    <60s      → "just now"
    <60m      → "Nm ago"
    <24h      → "Nh ago"
    <7d       → "Nd ago"
    otherwise → "Mon D" (month + day)

    Returns the original value on parse failure so authors don't end up
    with an empty string in the pinned card.
    """
    from datetime import datetime, timezone

    if not isinstance(value, str) or not value.strip():
        return str(value) if value is not None else ""
    try:
        # Python 3.11+ fromisoformat handles the `Z` suffix; older versions
        # need the manual swap.
        iso = value.strip().replace("Z", "+00:00")
        ts = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return value
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    delta = datetime.now(timezone.utc) - ts
    secs = int(delta.total_seconds())
    if secs < 0:
        return value  # future timestamp — echo raw
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    if secs < 7 * 86400:
        return f"{secs // 86400}d ago"
    return ts.strftime("%b %-d") if hasattr(ts, "strftime") else value


def _apply_transform(value: Any, transform: str, data: dict) -> Any:
    """Apply a pipe transform to a value.

    Supported transforms:
      - map: {label: name, value: id}  → map each item to a new dict
      - pluck: key                      → extract a single field from each item
      - join: separator                 → join list items with separator (default ", ")
      - where: key=value                → filter list items
      - first                           → take first item from list
      - default: fallback               → use fallback if value is None
      - in: val1,val2,val3              → returns true if value is in the set
      - not_empty                       → returns true if value is truthy
      - status_color                    → map status string to a color name
      - count                           → return length of a list
      - date_relative                   → ISO 8601 timestamp → "5m ago" / "2h ago" / "Apr 18"
    """
    # Chained transforms: "pluck: name | join: , "
    # Split on " | " (with spaces) to preserve separators like ", " in join
    if " | " in transform:
        idx = transform.index(" | ")
        left = transform[:idx]
        right = transform[idx + 3:]  # skip " | "
        intermediate = _apply_transform(value, left.strip(), data)
        return _apply_transform(intermediate, right, data)

    # in: val1,val2,val3 — membership test
    in_match = re.match(r"in:\s*(.+)", transform)
    if in_match:
        members = {m.strip() for m in in_match.group(1).split(",")}
        return str(value) in members if value is not None else False

    # not_empty — truthy test
    if transform.strip() == "not_empty":
        return _is_truthy(value)

    # not — boolean inverse (useful for gating "off-state" buttons on a flag)
    if transform.strip() == "not":
        return not _is_truthy(value)

    # status_color — map status strings to color names
    if transform.strip() == "status_color":
        if isinstance(value, str):
            return _STATUS_COLORS.get(value.lower(), "muted")
        return "muted"

    # date_relative — ISO 8601 timestamp to compact relative string
    if transform.strip() == "date_relative":
        return _format_date_relative(value)

    # count — length of a list
    if transform.strip() == "count":
        if isinstance(value, (list, dict)):
            return len(value)
        return 0

    # default: fallback_value — return fallback if value is None
    default_match = re.match(r"default:\s*(.*)", transform)
    if default_match:
        if value is None:
            fallback = default_match.group(1).strip()
            try:
                return int(fallback)
            except ValueError:
                try:
                    return float(fallback)
                except ValueError:
                    return fallback
        return value

    # join: separator
    join_match = re.match(r"join(?::\s*(.*))?", transform)
    if join_match and isinstance(value, list):
        sep = join_match.group(1) if join_match.group(1) is not None else ", "
        # Preserve the separator as-is (don't strip — ", " should stay ", ")
        return sep.join(str(item) for item in value if item)

    # pluck: key
    pluck_match = re.match(r"pluck:\s*(\w+)", transform)
    if pluck_match and isinstance(value, list):
        key = pluck_match.group(1)
        return [item.get(key, "") for item in value if isinstance(item, dict)]

    # where: key=value — filter list items where item[key] == value
    where_match = re.match(r"where:\s*(\w+)\s*=\s*(.+)", transform)
    if where_match and isinstance(value, list):
        key = where_match.group(1)
        target = where_match.group(2).strip().strip("'\"")
        return [item for item in value if isinstance(item, dict) and item.get(key) == target]

    # first — take the first item from a list
    if transform.strip() == "first":
        if isinstance(value, list) and len(value) > 0:
            return value[0]
        return value

    # map: {label: name, value: id}
    map_match = re.match(r"map:\s*\{(.+)\}", transform)
    if map_match and isinstance(value, list):
        mapping_str = map_match.group(1)
        mappings: dict[str, str] = {}
        for pair in mapping_str.split(","):
            pair = pair.strip()
            if ":" in pair:
                k, v = pair.split(":", 1)
                mappings[k.strip()] = v.strip()

        result = []
        for item in value:
            if isinstance(item, dict):
                mapped = {}
                for out_key, src_key in mappings.items():
                    mapped[out_key] = item.get(src_key, "")
                result.append(mapped)
        return result

    return value
