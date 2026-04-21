"""Bot tool: preview_widget — dry-run a widget emission.

Closes the AI feedback loop: bots call ``preview_widget`` before
``emit_html_widget`` (or before pinning a library widget) to surface
manifest, CSP, path-resolution, and library-ref errors in the same turn
— no user pin required.

Same input shape as ``emit_html_widget`` (``library_ref`` / ``html`` /
``path`` plus optional ``js`` / ``css`` / ``extra_csp`` /
``display_label`` / ``display_mode``). Returns a structured JSON result
with ``ok``, an ``envelope`` (what would have been emitted), and an
``errors`` list with ``phase`` / ``message`` / ``severity``. On success
``errors`` is empty and the envelope is populated; on any failure the
envelope is omitted and ``errors`` names the phase that rejected the
input so the bot can iterate without emitting a broken widget to chat.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.agent.context import current_bot_id, current_channel_id
from app.services.widget_manifest import ManifestError, parse_manifest
from app.services.widget_paths import scope_root
from app.tools.local import emit_html_widget as _ehw
from app.tools.local.emit_html_widget import (
    INTERACTIVE_HTML_CONTENT_TYPE,
    _CHANNEL_PATH_RE,
    _CORE_WIDGETS_DIR,
    _LIBRARY_NAME_RE,
    _assemble_inline_body,
    _derive_plain_body,
)
from app.tools.registry import register

logger = logging.getLogger(__name__)


_SCHEMA = {
    "type": "function",
    "function": {
        "name": "preview_widget",
        "description": (
            "Dry-run a widget emission and report errors without rendering "
            "the widget in chat. Call this BEFORE `emit_html_widget` (or "
            "before pinning a newly-authored library widget) to catch "
            "manifest, CSP, path-resolution, and library-ref errors in the "
            "same turn, without forcing the user to pin a broken widget "
            "first. Accepts exactly one of `library_ref`, `html`, or `path` "
            "— the same shape as `emit_html_widget`. Returns "
            "`{ok, envelope, errors}`: `ok` is true when the widget would "
            "render; `envelope` is the same envelope `emit_html_widget` "
            "would have produced; `errors` is a structured list "
            "(`[{phase, message, severity}]`). When `library_ref` points at "
            "a bundle with a `widget.yaml` manifest, the manifest is parsed "
            "and `ManifestError` lines surface as errors in the `manifest` "
            "phase."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "library_ref": {
                    "type": "string",
                    "description": (
                        "Name of a library widget to preview, e.g. `notes`, "
                        "`core/notes`, `bot/my_toggle`, or "
                        "`workspace/team_board`. Same resolution order as "
                        "`emit_html_widget`. Mutually exclusive with `html` "
                        "and `path`."
                    ),
                },
                "html": {
                    "type": "string",
                    "description": (
                        "Raw HTML body content. Same inline mode as "
                        "`emit_html_widget(html=...)`. Mutually exclusive "
                        "with `path` and `library_ref`."
                    ),
                },
                "path": {
                    "type": "string",
                    "description": (
                        "Path to an HTML file — channel-workspace-relative "
                        "or absolute `/workspace/channels/<uuid>/...`. Same "
                        "grammar as `emit_html_widget(path=...)`. Mutually "
                        "exclusive with `html` and `library_ref`."
                    ),
                },
                "js": {
                    "type": "string",
                    "description": (
                        "Optional JS injected inside a <script> tag. Inline "
                        "mode only; ignored when `path` or `library_ref` is "
                        "set."
                    ),
                },
                "css": {
                    "type": "string",
                    "description": (
                        "Optional CSS injected inside a <style> tag. Inline "
                        "mode only; ignored when `path` or `library_ref` is "
                        "set."
                    ),
                },
                "display_label": {
                    "type": "string",
                    "description": (
                        "Short label that would appear on the widget card."
                    ),
                },
                "display_mode": {
                    "type": "string",
                    "enum": ["inline", "panel"],
                    "description": (
                        "Hint for the pin flow — `inline` (default) or "
                        "`panel`. Does not affect validation; included so "
                        "the returned envelope round-trips the same shape "
                        "as `emit_html_widget`."
                    ),
                },
                "extra_csp": {
                    "type": "object",
                    "description": (
                        "Per-widget CSP extensions — same validation as "
                        "`emit_html_widget.extra_csp`. CSP errors surface "
                        "in the `csp` phase."
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


def _ok(envelope: dict, notes: list[dict] | None = None) -> str:
    return json.dumps(
        {"ok": True, "envelope": envelope, "errors": notes or []},
        ensure_ascii=False,
    )


def _fail(phase: str, message: str) -> str:
    return json.dumps(
        {
            "ok": False,
            "envelope": None,
            "errors": [{"phase": phase, "message": message, "severity": "error"}],
        },
        ensure_ascii=False,
    )


def _resolve_library_bundle_dir(ref: str) -> Path | None:
    """Mirror ``_load_library_widget``'s directory resolution so the manifest
    parse can run against the same bundle that emit_html_widget would have
    used. Returns None if the name is invalid or nothing resolves.
    """
    ref = ref.strip().strip("/")
    if "/" in ref:
        scope, _, name = ref.partition("/")
        if scope not in {"core", "bot", "workspace"}:
            return None
    else:
        scope, name = None, ref
    if not _LIBRARY_NAME_RE.match(name):
        return None

    ws_root, shared_root = _ehw._resolve_scope_roots()
    search = [scope] if scope else ["bot", "workspace", "core"]
    for candidate in search:
        if candidate == "core":
            root_dir = str(_CORE_WIDGETS_DIR)
        else:
            root_dir = scope_root(candidate, ws_root=ws_root, shared_root=shared_root)
        if not root_dir:
            continue
        dir_candidate = Path(root_dir) / name
        if dir_candidate.is_dir():
            return dir_candidate
    return None


@register(
    _SCHEMA,
    safety_tier="readonly",
    requires_bot_context=True,
    requires_channel_context=False,
    returns={
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "envelope": {"type": ["object", "null"]},
            "errors": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "phase": {"type": "string"},
                        "message": {"type": "string"},
                        "severity": {"type": "string"},
                    },
                },
            },
        },
    },
)
async def preview_widget(
    html: str | None = None,
    path: str | None = None,
    library_ref: str | None = None,
    js: str = "",
    css: str = "",
    display_label: str = "",
    extra_csp: dict | None = None,
    display_mode: str = "inline",
) -> str:
    html_set = bool(html and html.strip())
    path_set = bool(path and path.strip())
    library_ref_set = bool(library_ref and library_ref.strip())
    modes_set = sum([html_set, path_set, library_ref_set])
    if modes_set != 1:
        return _fail(
            "input",
            "Provide exactly one of `library_ref`, `html`, or `path`.",
        )

    label = display_label.strip() or None

    mode = (display_mode or "inline").strip().lower()
    if mode not in ("inline", "panel"):
        return _fail("input", "display_mode must be one of 'inline', 'panel'.")

    validated_csp: dict[str, list[str]] | None = None
    if extra_csp is not None:
        from app.agent.tool_dispatch import _sanitize_extra_csp
        try:
            validated_csp = _sanitize_extra_csp(extra_csp)
        except ValueError as exc:
            return _fail("csp", str(exc))

    emit_channel = current_channel_id.get()
    emit_channel_id = str(emit_channel) if emit_channel else None
    emit_bot_id = current_bot_id.get()

    notes: list[dict] = []

    if library_ref_set:
        ws_root, shared_root = _ehw._resolve_scope_roots()
        try:
            body, ref_meta = _ehw._load_library_widget(
                library_ref, ws_root=ws_root, shared_root=shared_root,
            )
        except (LookupError, ValueError) as exc:
            return _fail("library_ref", str(exc))

        bundle_dir = _resolve_library_bundle_dir(library_ref)
        if bundle_dir is not None:
            manifest_path = bundle_dir / "widget.yaml"
            if manifest_path.is_file():
                try:
                    parse_manifest(manifest_path)
                except ManifestError as exc:
                    return _fail("manifest", str(exc))
                except Exception as exc:  # noqa: BLE001 — yaml/OSError surfaced as preview failure
                    return _fail("manifest", f"widget.yaml unreadable: {exc}")

        resolved_label = label or ref_meta.get("display_label") or ref_meta.get("name")
        envelope: dict = {
            "content_type": INTERACTIVE_HTML_CONTENT_TYPE,
            "body": body,
            "plain_body": _derive_plain_body(
                display_label=resolved_label, path=None, body_len=len(body)
            ),
            "display": "inline",
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
        return _ok(envelope, notes)

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
        return _ok(envelope, notes)

    # Path mode — resolve the workspace file the same way emit_html_widget
    # does, but only validate that it exists (no content read back to the
    # caller; the renderer fetches it at render time).
    bot_id = current_bot_id.get()
    if not bot_id:
        return _fail("input", "Path mode requires bot context — none available.")

    stripped = path.strip()
    target_channel_id: str | None = None
    resolved_path = stripped

    m = _CHANNEL_PATH_RE.match(stripped)
    if m:
        target_channel_id = m.group(1)
        rest = m.group(2) or ""
        resolved_path = rest.lstrip("/")
        if not resolved_path:
            return _fail(
                "path",
                "Path must point at a file, not a channel root: " + stripped,
            )
    elif stripped.startswith("/workspace/"):
        return _fail(
            "path",
            "Absolute /workspace/... paths must be of the form "
            "/workspace/channels/<channel_id>/...",
        )
    else:
        if emit_channel is None:
            return _fail(
                "path",
                "Relative paths require channel context. Either run inside "
                "a channel, or pass an absolute path: "
                "/workspace/channels/<channel_id>/<path>",
            )
        target_channel_id = str(emit_channel)

    from app.agent.bots import get_bot
    from app.services.channel_workspace import read_workspace_file

    bot = get_bot(bot_id)
    if bot is None:
        return _fail("path", f"Bot {bot_id} not found")

    content = read_workspace_file(target_channel_id, bot, resolved_path)
    if content is None:
        return _fail(
            "path",
            f"Workspace file not found (or path escapes workspace): {path}",
        )

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
    return _ok(envelope, notes)
