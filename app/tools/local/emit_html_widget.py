"""Bot tool: emit_html_widget — render HTML (+ optional JS/CSS) as an
interactive widget.

Two input modes:

- **Inline** (``html=...``): bot supplies the raw HTML string; the server
  wraps it with optional ``<style>`` and ``<script>`` blocks and returns
  the assembled document as the envelope body. One-off snapshot.
- **Path** (``path=...``): bot supplies a workspace-relative path. The
  backend confirms the file exists under the current channel's
  workspace; the envelope body is empty but carries ``source_path`` (and
  ``source_channel_id``) so the renderer fetches fresh content via
  ``/api/v1/channels/{cid}/workspace/files/content`` and re-polls as the
  file changes.

Exactly one of ``html`` / ``path`` must be provided.

The envelope uses ``content_type:
"application/vnd.spindrel.html+interactive"`` — the frontend renders it
under ``InteractiveHtmlRenderer`` (permissive sandbox allowing scripts +
same-origin fetch to ``/api/v1/*``). The strict ``text/html`` path is
unchanged and still used for pinned ``.html`` workspace file previews.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from app.agent.context import current_bot_id, current_channel_id
from app.services.widget_paths import scope_root
from app.tools.registry import register

logger = logging.getLogger(__name__)

INTERACTIVE_HTML_CONTENT_TYPE = "application/vnd.spindrel.html+interactive"

# Match /workspace/channels/<uuid>/... for absolute-path overrides.  Lets a
# bot emit a widget pointing at any channel workspace it has access to —
# including from outside a channel context (e.g., cron-triggered tasks).
_CHANNEL_PATH_RE = re.compile(
    r"^/workspace/channels/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(/.*)?$"
)

# Library widgets live alongside this module.  Core bundles ship with the
# server; bot- and workspace-scoped bundles live under the corresponding
# workspace's ``.widget_library/`` directory (see ``app/services/widget_paths.py``).
_CORE_WIDGETS_DIR = Path(__file__).parent / "widgets"
_LIBRARY_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _resolve_scope_roots() -> tuple[str | None, str | None]:
    """Resolve (ws_root, shared_root) for the current bot context.

    Returns ``(None, None)`` when no bot context is active — callers then see
    only the core scope, matching ``widget_library_list`` semantics.
    """
    bot_id = current_bot_id.get()
    if not bot_id:
        return None, None
    try:
        from app.agent.bots import get_bot
        bot = get_bot(bot_id)
    except Exception:  # noqa: BLE001 — unknown bot id = no writable scopes
        return None, None
    if bot is None:
        return None, None
    from app.services.workspace import workspace_service
    ws_root = workspace_service.get_workspace_root(bot_id, bot)
    shared_root: str | None = None
    if bot.shared_workspace_id:
        import os
        from app.services.shared_workspace import shared_workspace_service
        shared_root = os.path.realpath(
            shared_workspace_service.get_host_root(bot.shared_workspace_id)
        )
    return ws_root, shared_root


def _load_library_widget(
    ref: str,
    *,
    ws_root: str | None,
    shared_root: str | None,
) -> tuple[str, dict]:
    """Resolve a ``library_ref`` to (body_html, metadata).

    Accepts ``"name"`` (defaults to core scope) or ``"<scope>/<name>"`` where
    scope is ``core`` / ``bot`` / ``workspace``. Bot- and workspace-scoped
    refs resolve against the same ``widget://bot|workspace/<name>/`` virtual
    path the file tool writes to — so a widget authored with
    ``file(op="create", path="widget://bot/foo/index.html", ...)`` is
    immediately renderable via ``library_ref="bot/foo"`` (or just ``"foo"``
    if no core widget shadows the name).

    Callers supply ``ws_root`` / ``shared_root`` explicitly; ``_resolve_scope_roots``
    derives them from the current bot context var for agent-runtime callers,
    and the widget content API resolves them from the pin's source bot.
    """
    ref = ref.strip().strip("/")
    if "/" in ref:
        scope, _, name = ref.partition("/")
        if scope not in {"core", "bot", "workspace"}:
            raise ValueError(
                f"Invalid library_ref scope '{scope}'. Use 'core', 'bot', or 'workspace'."
            )
    else:
        scope, name = None, ref  # implicit — try bot, workspace, then core.

    if not _LIBRARY_NAME_RE.match(name):
        raise ValueError(
            f"Invalid library widget name '{name}'. "
            f"Names must contain only letters, digits, '_', or '-'."
        )

    # Resolve the on-disk directory for the requested scope.  For implicit
    # refs, walk bot → workspace → core in that order so bot-authored widgets
    # naturally shadow core names (matches the editor's override semantics).
    widget_dir: Path | None = None
    resolved_scope: str | None = None
    search: list[str] = [scope] if scope else ["bot", "workspace", "core"]
    for candidate in search:
        if candidate == "core":
            root_dir = str(_CORE_WIDGETS_DIR)
        else:
            root_dir = scope_root(candidate, ws_root=ws_root, shared_root=shared_root)
        if not root_dir:
            continue
        dir_candidate = Path(root_dir) / name
        if dir_candidate.is_dir():
            widget_dir = dir_candidate
            resolved_scope = candidate
            break

    if widget_dir is None:
        # Explicit scope that simply had no match — surface a scope-specific
        # hint; for implicit refs fall back to the generic not-found message.
        if scope:
            raise LookupError(
                f"Library widget not found: '{scope}/{name}'. Call "
                f"`widget_library_list(scope=\"{scope}\")` to see what's "
                f"available."
            )
        raise LookupError(
            f"Library widget not found: '{name}'. Call `widget_library_list()` "
            f"to see available names across scopes."
        )

    index_path = widget_dir / "index.html"
    if not index_path.is_file():
        raise LookupError(
            f"Library widget '{ref}' has no index.html — it may be a template "
            f"or suite bundle, which this tool cannot emit directly."
        )

    body = index_path.read_text()
    meta: dict = {"name": name, "scope": resolved_scope or "core"}
    yaml_path = widget_dir / "widget.yaml"
    if yaml_path.is_file():
        try:
            import yaml
            raw = yaml_path.read_text()
            if "\n---" in raw:
                raw = raw.split("\n---", 1)[0]
            parsed = yaml.safe_load(raw) or {}
            if isinstance(parsed, dict):
                yaml_name = parsed.get("name")
                if yaml_name and not parsed.get("display_label"):
                    meta["display_label"] = str(yaml_name)
                for key in ("display_label", "panel_title", "show_panel_title", "description", "version"):
                    value = parsed.get(key)
                    if value is not None and key not in meta:
                        meta[key] = value
        except Exception:  # noqa: BLE001
            logger.debug("Failed parsing %s", yaml_path, exc_info=True)
    return body, meta

_SCHEMA = {
    "type": "function",
    "function": {
        "name": "emit_html_widget",
        "description": (
            "Emit an interactive HTML widget as the tool result. This is the "
            "HTML-widget path: use it for free-form layouts, charts, mini-apps, "
            "and richer client-side behavior. If the request already fits a "
            "tool-renderer/template widget, prefer that system instead of "
            "wrapping it in HTML. Renders in a sandboxed iframe that CAN run "
            "JavaScript and call this app's own API. Cross-origin network is "
            "blocked by CSP. The user can pin the result to a dashboard via the "
            "Pin button; to place a library widget onto a dashboard yourself, "
            "use `pin_widget`.\n\n"
            "Widget JS authenticates as THIS bot (not the viewing user) via "
            "a short-lived bearer token scoped to this bot's API key. Use "
            "`window.spindrel.api(path, options?)` for every API call — "
            "it attaches the bearer. Raw `fetch()` is unauthenticated. "
            "Call `list_api_endpoints()` first to see what paths your bot "
            "can hit; widgets inherit the same scopes as `call_api`.\n\n"
            "To display attachment images use `window.spindrel.loadAttachment(id)` "
            "(async, returns a blob URL): `const url = await window.spindrel.loadAttachment(id); "
            "img.src = url;`. Do NOT use `/api/v1/attachments/<id>` directly in "
            "<img src> — that endpoint requires an Authorization header the browser "
            "won't send. Always use loadAttachment() for attachment images.\n\n"
            "Provide EXACTLY ONE of: `library_ref` (render a named widget "
            "from the library — prefer this for reusable widgets; call "
            "`widget_library_list` to see what's available), `html` (one-off "
            "inline HTML — snapshot at emit time), or `path` (workspace file "
            "— re-renders when the file changes). In inline mode, optional "
            "`js` and `css` are wrapped into the document for you; in path "
            "and library modes the bundle should contain the complete HTML "
            "and js/css are ignored.\n\n"
            "Reusable bundles should usually be authored under "
            "`widget://bot/<name>/...` or `widget://workspace/<name>/...` with "
            "`index.html` plus optional `widget.yaml`. To group related widgets, "
            "set exactly one of `suite:` or `package:` in the bundle metadata. "
            "Widget themes currently apply to HTML widgets; template widgets do "
            "not have theme parity yet."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "library_ref": {
                    "type": "string",
                    "description": (
                        "Name of a library widget to render, e.g. `notes`, "
                        "`core/notes`, `bot/my_toggle`, or `workspace/team_board`. "
                        "Implicit refs (no scope prefix) resolve in the order "
                        "bot → workspace → core, so bot-authored widgets "
                        "naturally shadow core names. Use `widget_library_list` "
                        "to discover what's available. Bot/workspace widgets "
                        "are authored via the file tool against "
                        "`widget://bot/<name>/...` or `widget://workspace/<name>/...` "
                        "(write `index.html` + optional `widget.yaml`, then emit "
                        "by ref). Add `suite:` or `package:` metadata when the "
                        "widget belongs to a related group. "
                        "Preferred emission path — library widgets are reusable "
                        "and editable in place. Mutually exclusive with `html` "
                        "and `path`."
                    ),
                },
                "html": {
                    "type": "string",
                    "description": (
                        "Raw HTML body content. Inline mode — snapshot at "
                        "emit time, not reusable. Prefer `library_ref` for "
                        "anything you might want to update. Mutually "
                        "exclusive with `path` and `library_ref`."
                    ),
                },
                "path": {
                    "type": "string",
                    "description": (
                        "Path to an HTML file. Accepts two forms: "
                        "(1) channel-workspace-relative (e.g. "
                        "'data/widgets/project-status/index.html') — "
                        "resolves against your current channel's workspace; "
                        "(2) absolute channel path (e.g. "
                        "'/workspace/channels/<channel_id>/data/widgets/foo/index.html') "
                        "— targets a specific channel's workspace, works even "
                        "from outside a channel context. Path mode — widget "
                        "re-fetches the file so updates propagate. Mutually "
                        "exclusive with `html`."
                    ),
                },
                "js": {
                    "type": "string",
                    "description": (
                        "Optional JavaScript to inject inside a <script> "
                        "tag. Inline mode only — ignored when `path` is "
                        "set. Runs same-origin; may fetch /api/v1/... "
                        "endpoints."
                    ),
                },
                "css": {
                    "type": "string",
                    "description": (
                        "Optional CSS to inject inside a <style> tag. "
                        "Inline mode only — ignored when `path` is set."
                    ),
                },
                "display_label": {
                    "type": "string",
                    "description": (
                        "Short label shown on the widget card (e.g. "
                        "'Server stats', 'Task timeline'). Surfaces in "
                        "dashboard pins + pinned-widget context injection."
                    ),
                },
                "display_mode": {
                    "type": "string",
                    "enum": ["inline", "panel"],
                    "description": (
                        "How the widget should claim space when pinned to a "
                        "dashboard. `inline` (default) renders inside a "
                        "normal grid tile sized by the user. `panel` is a "
                        "hint to the pinning UI that this widget wants to "
                        "fill the dashboard's main area — only one pin per "
                        "dashboard can be the panel pin. The user still "
                        "decides via the EditPinDrawer; the hint just "
                        "pre-checks the 'Promote to panel' option."
                    ),
                },
                "extra_csp": {
                    "type": "object",
                    "description": (
                        "Per-widget CSP extensions — opt in to third-party "
                        "origins the iframe needs to load (Google Maps, "
                        "Mapbox, Stripe Elements, Chart.js CDN, etc.). "
                        "Shape: `{\"script_src\": [\"https://maps.googleapis.com\", "
                        "\"https://maps.gstatic.com\"], \"connect_src\": "
                        "[\"https://maps.googleapis.com\"], \"img_src\": "
                        "[\"https://maps.gstatic.com\"], \"style_src\": "
                        "[\"https://fonts.googleapis.com\"], \"font_src\": "
                        "[\"https://fonts.gstatic.com\"]}`. Values must be "
                        "concrete `https://host[:port]` origins — wildcards, "
                        "non-https schemes, and CSP keywords (`'self'`, "
                        "`'unsafe-*'`, `data:`, `blob:`) are rejected. "
                        "Max 10 origins per directive. Supported directives: "
                        "script_src, connect_src, img_src, style_src, "
                        "font_src, media_src, frame_src, worker_src."
                    ),
                    "properties": {
                        "script_src": {"type": "array", "items": {"type": "string"}},
                        "connect_src": {"type": "array", "items": {"type": "string"}},
                        "img_src": {"type": "array", "items": {"type": "string"}},
                        "style_src": {"type": "array", "items": {"type": "string"}},
                        "font_src": {"type": "array", "items": {"type": "string"}},
                        "media_src": {"type": "array", "items": {"type": "string"}},
                        "frame_src": {"type": "array", "items": {"type": "string"}},
                        "worker_src": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
    },
}


def _error(msg: str) -> str:
    return json.dumps({"error": msg}, ensure_ascii=False)


def _assemble_inline_body(html: str, js: str, css: str) -> str:
    """Stitch html + optional css/js into a complete HTML fragment.

    The renderer wraps this in a full <!doctype html> document inside the
    iframe srcdoc, so we only return the body-level content.
    """
    parts: list[str] = []
    if css:
        parts.append(f"<style>\n{css}\n</style>")
    parts.append(html)
    if js:
        parts.append(f"<script>\n{js}\n</script>")
    return "\n".join(parts)


def _derive_plain_body(
    *, display_label: str | None, path: str | None, body_len: int
) -> str:
    if display_label:
        return f"HTML widget: {display_label}"
    if path:
        return f"HTML widget backed by {path}"
    return f"HTML widget ({body_len} chars)"


@register(
    _SCHEMA,
    safety_tier="readonly",
    requires_bot_context=True,
    requires_channel_context=True,
    returns={
        "type": "object",
        "properties": {
            "llm": {"type": "string"},
            "_envelope": {"type": "object"},
            "error": {"type": "string"},
        },
    },
)
async def emit_html_widget(
    html: str | None = None,
    path: str | None = None,
    library_ref: str | None = None,
    js: str = "",
    css: str = "",
    display_label: str = "",
    extra_csp: dict | None = None,
    display_mode: str = "inline",
) -> str:
    # Exactly-one validation across html / path / library_ref.
    html_set = bool(html and html.strip())
    path_set = bool(path and path.strip())
    library_ref_set = bool(library_ref and library_ref.strip())
    modes_set = sum([html_set, path_set, library_ref_set])
    if modes_set != 1:
        return _error(
            "Provide exactly one of `library_ref` (preferred — named library "
            "widget), `html` (inline), or `path` (workspace file)."
        )

    label = display_label.strip() or None

    mode = (display_mode or "inline").strip().lower()
    if mode not in ("inline", "panel"):
        return _error("display_mode must be one of 'inline', 'panel'.")

    # Validate + normalize the CSP extension before we build the envelope so a
    # misspecified payload surfaces as a tool error (visible to the bot and
    # testable) instead of silently dropping. Sanitizer rejects wildcards,
    # non-https schemes, CSP keywords, and full-URL values.
    validated_csp: dict[str, list[str]] | None = None
    if extra_csp is not None:
        from app.agent.tool_dispatch import _sanitize_extra_csp
        try:
            validated_csp = _sanitize_extra_csp(extra_csp)
        except ValueError as exc:
            return _error(str(exc))

    # Channel + bot context at emit time. Persisted on the envelope so the
    # widget's JS can keep calling channel-scoped APIs after the pin is
    # rendered on the dashboard (where the host page has no channel
    # context of its own). ``source_bot_id`` drives the widget-auth mint:
    # the iframe authenticates as THIS bot, with THIS bot's scopes — not
    # as the viewing user. Best-effort — inline-mode still works without
    # it, the widget's `window.spindrel` just can't authenticate.
    emit_channel = current_channel_id.get()
    emit_channel_id = str(emit_channel) if emit_channel else None
    emit_bot_id = current_bot_id.get()

    if library_ref_set:
        ws_root, shared_root = _resolve_scope_roots()
        try:
            body, ref_meta = _load_library_widget(
                library_ref, ws_root=ws_root, shared_root=shared_root,
            )
        except LookupError as exc:
            return _error(str(exc))
        except ValueError as exc:
            return _error(str(exc))

        resolved_label = label or ref_meta.get("display_label") or ref_meta.get("name")
        envelope = {
            "content_type": INTERACTIVE_HTML_CONTENT_TYPE,
            "body": body,
            "plain_body": _derive_plain_body(
                display_label=resolved_label, path=None, body_len=len(body)
            ),
            "display": "inline",
            "source_kind": "library",
            "source_library_ref": f"{ref_meta['scope']}/{ref_meta['name']}",
        }
        if emit_channel_id:
            envelope["source_channel_id"] = emit_channel_id
        if emit_bot_id:
            envelope["source_bot_id"] = emit_bot_id
        if resolved_label:
            envelope["display_label"] = resolved_label
        panel_title = ref_meta.get("panel_title")
        if isinstance(panel_title, str) and panel_title.strip():
            envelope["panel_title"] = panel_title.strip()
        if isinstance(ref_meta.get("show_panel_title"), bool):
            envelope["show_panel_title"] = ref_meta["show_panel_title"]
        if validated_csp:
            envelope["extra_csp"] = validated_csp
        if mode == "panel":
            envelope["display_mode"] = "panel"
        return json.dumps(
            {
                "_envelope": envelope,
                "llm": (
                    f"Emitted library widget '{ref_meta['scope']}/"
                    f"{ref_meta['name']}' ({len(body)} chars)."
                ),
            },
            ensure_ascii=False,
        )

    if html_set:
        body = _assemble_inline_body(html, js or "", css or "")
        envelope = {
            "content_type": INTERACTIVE_HTML_CONTENT_TYPE,
            "body": body,
            "plain_body": _derive_plain_body(
                display_label=label, path=None, body_len=len(body)
            ),
            "display": "inline",
        }
        if emit_channel_id:
            envelope["source_channel_id"] = emit_channel_id
        if emit_bot_id:
            envelope["source_bot_id"] = emit_bot_id
        if label:
            envelope["display_label"] = label
        if validated_csp:
            envelope["extra_csp"] = validated_csp
        if mode == "panel":
            envelope["display_mode"] = "panel"
        return json.dumps(
            {"_envelope": envelope, "llm": f"Emitted HTML widget ({len(body)} chars)."},
            ensure_ascii=False,
        )

    # Path mode — resolve the target channel + relative path, then validate
    # the file exists so the renderer won't 404.
    #
    # Two grammars accepted:
    #   - Absolute: "/workspace/channels/<uuid>/<path>" — targets a specific
    #     channel, works even when current_channel_id is unset (e.g. cron,
    #     autoresearch). Path is parsed and the parsed channel drives both
    #     file resolution and the envelope's source_channel_id.
    #   - Relative: "<path>" — resolves against the emitting channel's
    #     workspace (original behavior). Requires current_channel_id.
    bot_id = current_bot_id.get()
    if not bot_id:
        return _error("Path mode requires bot context — none available.")

    stripped = path.strip()
    target_channel_id: str | None = None
    resolved_path = stripped

    m = _CHANNEL_PATH_RE.match(stripped)
    if m:
        target_channel_id = m.group(1)
        # Group 2 is "/rest/of/path" or None. Strip the leading slash so the
        # channel-workspace resolver (which os.path.joins with the root) treats
        # it as relative.
        rest = m.group(2) or ""
        resolved_path = rest.lstrip("/")
        if not resolved_path:
            return _error(
                "Path must point at a file, not a channel root: " + stripped
            )
    elif stripped.startswith("/workspace/"):
        # Non-channel absolute paths are reserved for DX-5b (non-channel
        # workspace root). Reject with a clear pointer instead of silently
        # resolving against the channel workspace.
        return _error(
            "Absolute /workspace/... paths must be of the form "
            "/workspace/channels/<channel_id>/... (non-channel workspace "
            "roots are not yet supported — use channel-workspace paths)."
        )
    else:
        # Relative — need an emitting channel to scope against.
        if emit_channel is None:
            return _error(
                "Relative paths require channel context. Either run inside a "
                "channel, or pass an absolute path: "
                "/workspace/channels/<channel_id>/<path>"
            )
        target_channel_id = str(emit_channel)

    from app.agent.bots import get_bot
    from app.services.channel_workspace import read_workspace_file

    bot = get_bot(bot_id)
    if bot is None:
        return _error(f"Bot {bot_id} not found")

    content = read_workspace_file(target_channel_id, bot, resolved_path)
    if content is None:
        return _error(
            f"Workspace file not found (or path escapes workspace): {path}"
        )

    # NOTE: deliberately do NOT set `refreshable: True`. That flag drives the
    # WidgetCard state_poll machinery (tool re-invoke → new envelope). For
    # HTML widgets, freshness is owned by the renderer's own useQuery poll
    # against the workspace file — re-calling the emit tool wouldn't help.
    envelope = {
        "content_type": INTERACTIVE_HTML_CONTENT_TYPE,
        "body": "",
        "source_path": resolved_path,
        "source_channel_id": target_channel_id,
        "source_bot_id": bot_id,
        "plain_body": _derive_plain_body(
            display_label=label, path=path, body_len=0
        ),
        "display": "inline",
    }
    if label:
        envelope["display_label"] = label
    if validated_csp:
        envelope["extra_csp"] = validated_csp
    if mode == "panel":
        envelope["display_mode"] = "panel"
    return json.dumps(
        {
            "_envelope": envelope,
            "llm": (
                f"Emitted HTML widget backed by {path} "
                f"({len(content)} chars in file)."
            ),
        },
        ensure_ascii=False,
    )
