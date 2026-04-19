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

from app.agent.context import current_bot_id, current_channel_id
from app.tools.registry import register

logger = logging.getLogger(__name__)

INTERACTIVE_HTML_CONTENT_TYPE = "application/vnd.spindrel.html+interactive"

# Match /workspace/channels/<uuid>/... for absolute-path overrides.  Lets a
# bot emit a widget pointing at any channel workspace it has access to —
# including from outside a channel context (e.g., cron-triggered tasks).
_CHANNEL_PATH_RE = re.compile(
    r"^/workspace/channels/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(/.*)?$"
)

_SCHEMA = {
    "type": "function",
    "function": {
        "name": "emit_html_widget",
        "description": (
            "Emit an interactive HTML widget as the tool result. Renders in "
            "a sandboxed iframe that CAN run JavaScript and call this app's "
            "own API. Cross-origin network is blocked by CSP. Pin the "
            "result to the dashboard for a persistent interactive card.\n\n"
            "Widget JS authenticates as THIS bot (not the viewing user) via "
            "a short-lived bearer token scoped to this bot's API key. Use "
            "`window.spindrel.api(path, options?)` for every API call — "
            "it attaches the bearer. Raw `fetch()` is unauthenticated. "
            "Call `list_api_endpoints()` first to see what paths your bot "
            "can hit; widgets inherit the same scopes as `call_api`.\n\n"
            "Provide EITHER `html` (one-off inline HTML) OR `path` (points "
            "at an existing workspace file; the widget re-renders when the "
            "file changes — good for iterative work). Exactly one is "
            "required. In inline mode, optional `js` and `css` are wrapped "
            "into the document for you; in path mode the file should "
            "contain the complete HTML document and js/css are ignored."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "html": {
                    "type": "string",
                    "description": (
                        "Raw HTML body content. Inline mode — snapshot at "
                        "emit time. Mutually exclusive with `path`."
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
)
async def emit_html_widget(
    html: str | None = None,
    path: str | None = None,
    js: str = "",
    css: str = "",
    display_label: str = "",
    extra_csp: dict | None = None,
) -> str:
    # Exactly-one validation. Reject both-set and neither-set.
    html_set = bool(html and html.strip())
    path_set = bool(path and path.strip())
    if html_set == path_set:  # both True or both False
        return _error(
            "Provide exactly one of `html` (inline mode) or `path` "
            "(workspace file mode)."
        )

    label = display_label.strip() or None

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
