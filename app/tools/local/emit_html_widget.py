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

from app.agent.context import current_bot_id, current_channel_id
from app.tools.registry import register

logger = logging.getLogger(__name__)

INTERACTIVE_HTML_CONTENT_TYPE = "application/vnd.spindrel.html+interactive"

_SCHEMA = {
    "type": "function",
    "function": {
        "name": "emit_html_widget",
        "description": (
            "Emit an interactive HTML widget as the tool result. Renders in "
            "a sandboxed iframe that CAN run JavaScript and call this app's "
            "own API via same-origin fetch to /api/v1/... Cross-origin "
            "network is blocked by CSP. Pin the result to the dashboard "
            "for a persistent interactive card.\n\n"
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
                        "Workspace-relative path to an HTML file (e.g. "
                        "'dashboards/cpu.html'). Path mode — widget re-"
                        "fetches the file so updates to it propagate. "
                        "Mutually exclusive with `html`."
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


@register(_SCHEMA, safety_tier="readonly")
async def emit_html_widget(
    html: str | None = None,
    path: str | None = None,
    js: str = "",
    css: str = "",
    display_label: str = "",
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
        return json.dumps(
            {"_envelope": envelope, "llm": f"Emitted HTML widget ({len(body)} chars)."},
            ensure_ascii=False,
        )

    # Path mode — validate the file resolves + exists under the current
    # channel's workspace so the renderer won't 404.
    channel_id = emit_channel
    bot_id = current_bot_id.get()
    if not channel_id or not bot_id:
        return _error(
            "Path mode requires channel + bot context — none available."
        )

    from app.agent.bots import get_bot
    from app.services.channel_workspace import read_workspace_file

    bot = get_bot(bot_id)
    if bot is None:
        return _error(f"Bot {bot_id} not found")

    content = read_workspace_file(str(channel_id), bot, path)
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
        "source_path": path,
        "source_channel_id": str(channel_id),
        "source_bot_id": bot_id,
        "plain_body": _derive_plain_body(
            display_label=label, path=path, body_len=0
        ),
        "display": "inline",
    }
    if label:
        envelope["display_label"] = label
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
