"""widget_library_list — inventory of widget bundles available to the bot.

The tool walks three scopes:

- ``core`` — shipped with the server under ``app/tools/local/widgets/``
  (read-only to bots at runtime).
- ``bot`` — per-bot authored library under ``<ws_root>/.widget_library/``.
- ``workspace`` — shared library under ``<shared_root>/.widget_library/``
  (requires a shared workspace; standalone bots see nothing there).

Bots author entries in the writable scopes via the existing file tool over
``widget://bot/<name>/...`` / ``widget://workspace/<name>/...`` virtual
paths — this tool is the metadata-rich inventory surface.

See ``vault/Projects/agent-server/Track - Widget Library.md`` for the full arc.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from app.agent.context import current_bot_id
from app.services.native_app_widgets import list_native_widget_catalog_entries
from app.services.widget_manifest import parse_manifest
from app.services.widget_paths import scope_root
from app.tools.registry import register

logger = logging.getLogger(__name__)

_WIDGETS_DIR = Path(__file__).parent / "widgets"

_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

# Subdirectories under widgets/ that aren't themselves widgets — skip during
# the scan. ``examples/`` is a QA corpus. Phase 2 flattened the previous
# ``suites/`` directory up one level; suites now surface via the presence of
# a ``suite.yaml`` inside a widget folder, alongside template/html bundles.
_SKIP_NAMES = frozenset({"examples"})

_METADATA_KEYS = (
    "display_label",
    "panel_title",
    "show_panel_title",
    "description",
    "version",
    "tags",
    "icon",
    "suite",
    "package",
)


def _manifest_actions(widget_dir: Path) -> list[dict]:
    yaml_path = widget_dir / "widget.yaml"
    if not yaml_path.is_file():
        return []
    try:
        manifest = parse_manifest(yaml_path)
    except Exception:
        logger.debug("Failed parsing action manifest from %s", yaml_path, exc_info=True)
        return []
    out: list[dict] = []
    for spec in manifest.handlers:
        if not spec.bot_callable:
            continue
        props = spec.args or {}
        required = [name for name, cfg in props.items() if isinstance(cfg, dict) and cfg.get("required")]
        out.append({
            "id": spec.name,
            "description": spec.description,
            "args_schema": {
                "type": "object",
                "properties": props,
                "required": required,
            },
            "returns_schema": spec.returns,
        })
    return out


def _read_widget_meta(widget_dir: Path, scope: str) -> dict | None:
    """Introspect a widget bundle folder; return metadata or None if invalid."""
    name = widget_dir.name
    if not _NAME_RE.match(name) or name in _SKIP_NAMES:
        return None

    has_index = (widget_dir / "index.html").is_file()
    has_suite = (widget_dir / "suite.yaml").is_file()
    has_template = (widget_dir / "template.yaml").is_file()

    if not (has_index or has_suite or has_template):
        return None

    if has_suite:
        fmt = "suite"
        yaml_path = widget_dir / "suite.yaml"
    elif has_template:
        fmt = "template"
        yaml_path = widget_dir / "template.yaml"
    else:
        fmt = "html"
        yaml_path = widget_dir / "widget.yaml"

    meta: dict = {"name": name, "scope": scope, "format": fmt}

    if yaml_path.is_file():
        try:
            import yaml  # lazy — not every call site uses it
            raw = yaml_path.read_text()
            # Some widget.yaml files include a trailing "---" frontmatter-style
            # separator followed by extra notes; slice at that if present.
            if "\n---" in raw:
                raw = raw.split("\n---", 1)[0]
            parsed = yaml.safe_load(raw) or {}
            if isinstance(parsed, dict):
                # Folder name wins as the machine identifier; a ``name:`` field
                # in the YAML acts as a display label fallback.
                yaml_name = parsed.get("name")
                if yaml_name and not parsed.get("display_label"):
                    meta["display_label"] = str(yaml_name)
                for key in _METADATA_KEYS:
                    value = parsed.get(key)
                    if value is not None:
                        meta[key] = value
        except Exception:  # noqa: BLE001 — YAML parse errors shouldn't block listing
            logger.debug("Failed parsing %s", yaml_path, exc_info=True)

    try:
        meta["updated_at"] = int(widget_dir.stat().st_mtime)
    except OSError:
        pass

    meta["widget_kind"] = "template" if fmt == "template" else "html"
    meta["widget_binding"] = "tool_bound" if fmt == "template" else "standalone"
    meta["theme_support"] = "html" if fmt in {"html", "suite"} else "none"
    if fmt in {"html", "suite"}:
        actions = _manifest_actions(widget_dir)
        if actions:
            meta["actions"] = actions
    suite = meta.get("suite")
    package = meta.get("package")
    if isinstance(suite, str) and suite.strip():
        meta["group_kind"] = "suite"
        meta["group_ref"] = suite.strip()
    elif isinstance(package, str) and package.strip():
        meta["group_kind"] = "package"
        meta["group_ref"] = package.strip()
    elif fmt == "suite":
        meta["group_kind"] = "suite"
        meta["group_ref"] = name

    return meta


def _iter_core_widgets() -> list[dict]:
    """Walk the in-repo core widget directory and return metadata per bundle."""
    if not _WIDGETS_DIR.is_dir():
        return []
    out: list[dict] = []
    for entry in sorted(_WIDGETS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        meta = _read_widget_meta(entry, "core")
        if meta is not None:
            out.append(meta)
    return out


def _iter_scope_dir(base_dir: str | None, scope: str) -> list[dict]:
    """Walk a writable scope's on-disk library directory.

    Missing directories are treated as empty — authoring doesn't require a
    pre-existing ``.widget_library/`` dir; it materializes on first write.
    """
    if not base_dir:
        return []
    root = Path(base_dir)
    if not root.is_dir():
        return []
    out: list[dict] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        meta = _read_widget_meta(entry, scope)
        if meta is not None:
            out.append(meta)
    return out


def _resolve_scope_roots() -> tuple[str | None, str | None]:
    """Resolve (ws_root, shared_root) for the current bot context.

    Returns ``(None, None)`` when no bot context is active — the caller then
    sees empty bot/workspace scopes rather than an error, which matches the
    behavior of the file tool (non-channel contexts can still list core
    widgets).
    """
    bot_id = current_bot_id.get()
    if not bot_id:
        return None, None
    try:
        from app.agent.bots import get_bot
        bot = get_bot(bot_id)
    except Exception:  # noqa: BLE001 — unknown bot id = no writable scopes
        return None, None
    if not bot:
        return None, None
    from app.services.workspace import workspace_service
    ws_root = workspace_service.get_workspace_root(bot_id, bot)
    shared_root: str | None = None
    if bot.shared_workspace_id:
        from app.services.shared_workspace import shared_workspace_service
        shared_root = os.path.realpath(
            shared_workspace_service.get_host_root(bot.shared_workspace_id)
        )
    return ws_root, shared_root


@register(
    {
        "type": "function",
        "function": {
            "name": "widget_library_list",
            "description": (
                "List widget bundles available to the bot across the core, bot, "
                "and workspace libraries. Returns name, scope, format, display "
                "metadata, declared bot action schemas when available, and "
                "grouping/theme capabilities per entry. Use this "
                "before composing a new widget so you can reuse or extend an "
                "existing bundle instead of creating another one from scratch. "
                "HTML entries can be emitted via `emit_html_widget(library_ref=...)` "
                "or pinned with `pin_widget`; native app entries are "
                "first-party built-ins that can be pinned through the same "
                "library flow; template entries can be "
                "instantiated by calling `pin_widget(source_kind='library', "
                "widget='<tool_name>', tool_args={...})`. Filter "
                "by `scope`, `format`, or free-text `q` (matches name + "
                "display_label + description)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": ["core", "bot", "workspace", "all"],
                        "description": (
                            "Filter by origin. `core` = shipped with the "
                            "server (read-only). `bot` = widgets you've "
                            "authored under `widget://bot/<name>/...`. "
                            "`workspace` = widgets shared across this "
                            "workspace (requires a shared workspace). "
                            "Default: `all`."
                        ),
                    },
                    "format": {
                        "type": "string",
                        "enum": ["html", "template", "suite"],
                        "description": (
                            "Filter by bundle format. `html` = iframe-backed "
                            "HTML + SDK. `template` = YAML-declared component "
                            "tree/tool renderer. `suite` = grouped HTML bundle "
                            "family, typically sharing state or DB."
                        ),
                    },
                    "q": {
                        "type": "string",
                        "description": (
                            "Case-insensitive substring filter applied to "
                            "name + display_label + description."
                        ),
                    },
                },
            },
        },
    },
    safety_tier="readonly",
    returns={
        "type": "object",
        "properties": {
            "widgets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "scope": {"type": "string"},
                        "format": {"type": "string"},
                        "display_label": {"type": "string"},
                        "description": {"type": "string"},
                        "version": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "icon": {"type": "string"},
                        "updated_at": {"type": "integer"},
                    },
                    "required": ["name", "scope", "format"],
                },
            },
            "count": {"type": "integer"},
            "_envelope": {"type": "object"},
        },
        "required": ["widgets", "count"],
    },
)
async def widget_library_list(
    scope: str = "all",
    format: str | None = None,
    q: str | None = None,
) -> str:
    wanted_scopes = {"core", "bot", "workspace"} if scope == "all" else {scope}

    widgets: list[dict] = []
    if "core" in wanted_scopes:
        widgets.extend(_iter_core_widgets())
        widgets.extend(list_native_widget_catalog_entries())
    if wanted_scopes & {"bot", "workspace"}:
        ws_root, shared_root = _resolve_scope_roots()
        if "bot" in wanted_scopes:
            widgets.extend(_iter_scope_dir(
                scope_root("bot", ws_root=ws_root, shared_root=shared_root),
                "bot",
            ))
        if "workspace" in wanted_scopes:
            widgets.extend(_iter_scope_dir(
                scope_root("workspace", ws_root=ws_root, shared_root=shared_root),
                "workspace",
            ))

    # Tool-renderer ``template.yaml`` entries need runtime tool arguments
    # (``{{id}}``, etc.) to render — surfacing them as pinnable library
    # bundles doesn't make sense. The admin dev panel's Tools and Recent
    # calls tabs are the right surface for those. Skip unless the caller
    # explicitly asked for ``format="template"`` (inspection use-case).
    if format != "template":
        widgets = [w for w in widgets if w.get("format") != "template"]

    if format:
        widgets = [w for w in widgets if w.get("format") == format]
    if q:
        needle = q.lower()
        widgets = [
            w for w in widgets
            if needle in w.get("name", "").lower()
            or needle in str(w.get("display_label", "")).lower()
            or needle in str(w.get("description", "")).lower()
        ]

    summary_lines = [f"**Widget library** — {len(widgets)} entries"]
    for w in widgets[:50]:
        bits = [f"`{w['name']}`", f"[{w.get('format', '?')}]"]
        if w.get("display_label"):
            bits.append(str(w["display_label"]))
        if w.get("description"):
            desc = str(w["description"]).strip().replace("\n", " ")
            if len(desc) > 120:
                desc = desc[:117] + "..."
            bits.append(desc)
        summary_lines.append("- " + " — ".join(bits))
    if len(widgets) > 50:
        summary_lines.append(
            f"_…and {len(widgets) - 50} more — narrow with `q` or `format`._"
        )

    return json.dumps(
        {
            "widgets": widgets,
            "count": len(widgets),
            "_envelope": {
                "content_type": "text/markdown",
                "body": "\n".join(summary_lines),
                "plain_body": f"Listed {len(widgets)} library widget(s)",
                "display": "inline",
            },
        },
        ensure_ascii=False,
    )
