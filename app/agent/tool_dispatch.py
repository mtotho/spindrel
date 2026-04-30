"""Tool call routing, execution, recording, and result processing."""

import asyncio
import json
import logging
import time
import uuid

from app.utils import safe_create_task
from dataclasses import dataclass, field
from typing import Any, Literal

from app.agent.llm import _summarize_tool_result
from app.agent.recording import (
    _complete_tool_call,
    _record_tool_call,
    _record_trace_event,
    _start_tool_call,
)
from app.agent.tracing import _trace
from app.agent.pending import CLIENT_TOOL_TIMEOUT, create_pending, expire_pending
from app.config import settings
from app.tools.client_tools import is_client_tool
from app.tools.mcp import call_mcp_tool, get_mcp_server_for_tool, is_mcp_tool, resolve_mcp_tool_name
from app.tools.registry import call_local_tool, is_local_tool
from app.tools.local.persona import call_persona_tool
from app.db.engine import async_session
from app.db.models import Session
from app.services.widget_handler_tools import (
    is_widget_handler_tool_name,
    resolve_widget_handler,
)

logger = logging.getLogger(__name__)


# Maximum bytes of envelope body that travel inline on SSE / Message metadata.
# Bodies larger than this are dropped from the inline envelope, the envelope is
# marked truncated, and the UI fetches the full body lazily via the
# session-scoped tool-call result endpoint. Tunable via settings.
INLINE_BODY_CAP_BYTES = 4096

# Default short summary length for envelope.plain_body.
PLAIN_BODY_CAP_CHARS = 200


async def _load_session_for_plan_mode(session_id: uuid.UUID | None) -> Session | None:
    if session_id is None:
        return None
    async with async_session() as db:
        return await db.get(Session, session_id)


async def _record_plan_tool_evidence(
    *,
    session_id: uuid.UUID | None,
    tool_name: str,
    tool_kind: str,
    status: str,
    error: str | None,
    error_kind: str | None,
    error_code: str | None,
    retryable: bool | None,
    retry_after_seconds: int | None,
    fallback: str | None,
    tool_call_id: str | None,
    record_id: uuid.UUID | None,
    arguments: dict[str, Any],
    result_summary: str | None,
    turn_id: str | None,
    correlation_id: str | None,
) -> None:
    if session_id is None:
        return
    try:
        from app.services.session_plan_mode import (
            publish_session_plan_event,
            record_plan_execution_evidence,
            record_plan_tool_feedback,
        )

        async with async_session() as db:
            session = await db.get(Session, session_id)
            if session is None:
                return
            changed = record_plan_execution_evidence(
                session,
                tool_name=tool_name,
                tool_kind=tool_kind,
                status=status,
                error=error,
                tool_call_id=tool_call_id,
                record_id=str(record_id) if record_id else None,
                arguments=arguments,
                result_summary=result_summary,
                turn_id=turn_id,
                correlation_id=correlation_id,
            )
            reason = "tool_evidence"
            if changed is None:
                changed = record_plan_tool_feedback(
                    session,
                    tool_name=tool_name,
                    tool_kind=tool_kind,
                    status=status,
                    error=error,
                    error_kind=error_kind,
                    error_code=error_code,
                    retryable=retryable,
                    retry_after_seconds=retry_after_seconds,
                    fallback=fallback,
                    tool_call_id=tool_call_id,
                    record_id=str(record_id) if record_id else None,
                    arguments=arguments,
                    result_summary=result_summary,
                    turn_id=turn_id,
                    correlation_id=correlation_id,
                )
                reason = "tool_feedback"
            if changed is not None:
                await db.commit()
                publish_session_plan_event(session, reason)
    except Exception:
        logger.warning("Failed to record plan execution evidence for %s", tool_name, exc_info=True)


@dataclass
class ToolResultEnvelope:
    """Structured envelope for the user-visible rendering of a tool result.

    Decoupled from ``ToolCallResult.result`` (which is the persisted +
    redacted raw text the LLM consumes). The envelope is what the web UI
    renders — keyed off ``content_type`` so the renderer dispatcher can
    pick markdown / json-tree / diff / file-listing / sandboxed-html
    components without per-tool knowledge.

    Tools opt in by returning a JSON dict containing an ``_envelope`` key
    in their result string. Tools that don't opt in get a default
    text/plain envelope built from their raw result, so legacy tools keep
    working byte-identically (the renderer just falls back to the
    plain-text component).

    Truncation rule: ``body`` is capped at ``INLINE_BODY_CAP_BYTES``. When
    the underlying result exceeds the cap, ``body`` is set to None,
    ``truncated`` is True, and ``record_id`` points to the persisted
    ``tool_calls`` row so the UI can lazy-fetch the full content via
    ``GET /api/v1/sessions/{sid}/tool-calls/{id}/result``.
    """

    content_type: str = "text/plain"
    body: str | None = None
    plain_body: str = ""
    display: Literal["badge", "inline", "panel"] = "badge"
    truncated: bool = False
    record_id: uuid.UUID | None = None
    byte_size: int = 0
    display_label: str | None = None
    refreshable: bool = False
    refresh_interval_seconds: int | None = None
    tool_name: str = ""
    # File-backed widgets: when set, the renderer fetches body content from
    # ``/api/v1/channels/{source_channel_id}/workspace/files/content?path={source_path}``
    # and re-polls so workspace edits propagate to the rendered widget.
    source_path: str | None = None
    source_channel_id: str | None = None
    # Bot that emitted this envelope. Persisted so interactive HTML widgets
    # can mint a short-lived bearer token scoped to the bot's own API key
    # (see ``POST /api/v1/widget-auth/mint``) instead of piggy-backing on the
    # viewing user's session — an admin looking at a pinned widget should
    # not be unwittingly lending their credentials to bot-authored JS.
    source_bot_id: str | None = None
    # Per-widget CSP extensions. Interactive-HTML widgets that need to load
    # third-party scripts/tiles/fonts (Google Maps, Mapbox, Stripe Elements)
    # declare the extra origins here; the renderer merges them into the
    # iframe CSP at srcDoc-generation time. Shape:
    #   {"script_src": ["https://maps.googleapis.com", ...],
    #    "connect_src": [...], "img_src": [...], "style_src": [...],
    #    "font_src": [...], "media_src": [...], "frame_src": [...],
    #    "worker_src": [...]}
    # Values must be https:// origins — no wildcards, no scheme keywords
    # (`data:`, `blob:`, `'self'`, `'unsafe-*'`). Validated at emit time.
    extra_csp: dict[str, list[str]] | None = None
    # Pinning hint for HTML widgets — `"panel"` tells the dashboard pinning
    # UI that this widget would prefer to claim the dashboard's main area
    # instead of a normal grid tile. Surfaced via emit_html_widget's
    # display_mode kwarg; the user still confirms via the EditPinDrawer
    # promote action. Defaults to None (== "inline") so existing widgets
    # behave identically.
    display_mode: Literal["inline", "panel"] | None = None
    # Host-owned title for panel surfaces. Distinct from ``display_label``,
    # which remains the generic widget/card/library label.
    panel_title: str | None = None
    show_panel_title: bool | None = None
    tool_call_id: str | None = None
    # Stable presentation identity and structured payload for mode-aware UI
    # renderers. ``body`` remains the default-mode rendered artifact; ``data``
    # is the shared input for terminal/compact/dashboard variants.
    view_key: str | None = None
    data: Any | None = None
    template_id: str | None = None
    # HTML-widget runtime flavor. ``"react"`` flips the renderer to inject the
    # vendored React + ReactDOM + Babel-standalone preamble and treat
    # ``<script type="text/spindrel-react">`` blocks as JSX/TSX. Defaults to
    # ``None`` (== plain HTML lane). Frontmatter ``runtime: react`` in a body
    # is also honored as a fallback for path-mode widgets where the body
    # parser has access to the file's prelude.
    runtime: Literal["html", "react"] | None = None

    def compact_dict(self) -> dict[str, Any]:
        """Serialize for SSE bus + Message.metadata.tool_results storage.

        ``record_id`` is stringified so the dict round-trips through JSONB.
        Empty/default fields are kept (the UI uses ``content_type`` as the
        renderer dispatch key, so it must always be present).
        """
        d: dict[str, Any] = {
            "content_type": self.content_type,
            "body": self.body,
            "plain_body": self.plain_body,
            "display": self.display,
            "truncated": self.truncated,
            "record_id": str(self.record_id) if self.record_id else None,
            "byte_size": self.byte_size,
        }
        if self.display_label:
            d["display_label"] = self.display_label
        if self.refreshable:
            d["refreshable"] = True
        if self.refresh_interval_seconds:
            d["refresh_interval_seconds"] = self.refresh_interval_seconds
        if self.tool_name:
            d["tool_name"] = self.tool_name
        if self.source_path:
            d["source_path"] = self.source_path
        if self.source_channel_id:
            d["source_channel_id"] = self.source_channel_id
        if self.source_bot_id:
            d["source_bot_id"] = self.source_bot_id
        if self.extra_csp:
            d["extra_csp"] = self.extra_csp
        if self.display_mode and self.display_mode != "inline":
            d["display_mode"] = self.display_mode
        if self.panel_title:
            d["panel_title"] = self.panel_title
        if self.show_panel_title is not None:
            d["show_panel_title"] = self.show_panel_title
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.view_key:
            d["view_key"] = self.view_key
        if self.data is not None:
            d["data"] = self.data
        if self.template_id:
            d["template_id"] = self.template_id
        if self.runtime:
            d["runtime"] = self.runtime
        return d


@dataclass
class ToolCallResult:
    """Result of dispatching a single tool call."""
    result: str = ""
    result_for_llm: str = ""
    was_summarized: bool = False
    record_id: uuid.UUID | None = None
    embedded_client_action: dict | None = None
    injected_images: list[dict] | None = None  # [{"mime_type": str, "base64": str}]
    tool_event: dict[str, Any] = field(default_factory=dict)
    envelope: ToolResultEnvelope = field(default_factory=ToolResultEnvelope)
    pre_events: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: int = 0
    # Approval fields (Phase 3)
    needs_approval: bool = False
    approval_id: str | None = None
    approval_timeout: int = 300
    approval_reason: str | None = None


def _build_default_envelope(text: str, *, cap_body: bool = True) -> ToolResultEnvelope:
    """Build a default envelope from raw tool result text.

    Used for tools that don't opt into the structured envelope. Detects
    content type from the text shape:

    - Markdown (headings, links, lists, emphasis) → ``text/markdown`` + inline
    - JSON (valid parse) → ``application/json`` + badge
    - Plain text fallback → ``text/plain`` + badge

    When ``cap_body`` is True (the default, used by the LLM turn loop) the
    body is capped at INLINE_BODY_CAP_BYTES. Widget-actions dispatch passes
    ``cap_body=False`` because the envelope is returned directly to widget
    JS that needs to parse the full payload — truncation would deliver a
    null ``body`` and break any ``JSON.parse(env.body)`` consumer.
    """
    text = text or ""
    content_type, display = _detect_content_type(text)
    byte_size = len(text.encode("utf-8"))
    truncated = cap_body and len(text) > INLINE_BODY_CAP_BYTES
    return ToolResultEnvelope(
        content_type=content_type,
        body=None if truncated else text,
        plain_body=text[:PLAIN_BODY_CAP_CHARS],
        display=display if not truncated else "badge",
        truncated=truncated,
        byte_size=byte_size,
    )


import re as _re

# Markdown heuristics — must match at least 2 of these to qualify.
_MD_HEADING = _re.compile(r"^#{1,3}\s+\S", _re.MULTILINE)
_MD_LINK = _re.compile(r"\[.+?\]\(.+?\)")
_MD_LIST = _re.compile(r"^[\-\*]\s+\S", _re.MULTILINE)
_MD_EMPHASIS = _re.compile(r"(\*\*|__).+?\1")
_MD_CODE_FENCE = _re.compile(r"^```", _re.MULTILINE)


def _detect_content_type(text: str) -> tuple[str, str]:
    """Sniff text content to pick a better MIME type and display hint.

    Returns ``(content_type, display)`` — callers use these to populate
    the envelope. Conservative: only promotes to markdown when at least
    2 signals are present, to avoid false positives on plain text that
    happens to contain ``#`` or ``*``.
    """
    stripped = text.strip()
    if not stripped:
        return "text/plain", "badge"

    # JSON detection — valid object/array, OR one that was tail-truncated
    # by a caller (e.g. ``_run_tool_step`` appends ``"... [truncated]"``
    # past its cap). Recognizing the truncated form keeps the JSON
    # renderer on the happy path instead of falling through to markdown,
    # where ``---`` separators and ``**bold**`` inside embedded string
    # values get rendered as formatting.
    if stripped[0] in "{[":
        try:
            json.loads(stripped)
            return "application/json", "badge"
        except (json.JSONDecodeError, ValueError):
            if stripped.rstrip().endswith("[truncated]"):
                return "application/json", "badge"

    # Markdown detection — count signals, require ≥ 2.
    md_signals = sum([
        bool(_MD_HEADING.search(stripped)),
        bool(_MD_LINK.search(stripped)),
        bool(_MD_LIST.search(stripped)),
        bool(_MD_EMPHASIS.search(stripped)),
        bool(_MD_CODE_FENCE.search(stripped)),
    ])
    if md_signals >= 2:
        return "text/markdown", "inline"

    return "text/plain", "badge"


def _build_envelope_from_optin(
    envelope_data: dict, raw_text: str, *, cap_body: bool = True,
) -> ToolResultEnvelope:
    """Build an envelope from a tool's ``_envelope`` opt-in payload.

    Truncates ``body`` if it exceeds the inline cap and sets truncated/byte_size
    accordingly. ``raw_text`` is the redacted full result string that lives on
    the persisted ``tool_calls`` row — used to compute byte_size when the
    envelope omits its own ``body``.

    ``cap_body`` — when False, the inline cap is skipped and ``body`` always
    carries the full serialized payload. Widget-actions dispatch sets this to
    False so ``callTool`` returns a fully parseable envelope to widget JS.
    The ``application/vnd.spindrel.html+interactive`` exemption is orthogonal
    and applies regardless of caller.
    """
    content_type = str(envelope_data.get("content_type") or "text/plain")
    body = envelope_data.get("body")
    plain_body = str(envelope_data.get("plain_body") or "")[:PLAIN_BODY_CAP_CHARS * 4]
    display = envelope_data.get("display") or "badge"
    if display not in ("badge", "inline", "panel"):
        display = "badge"

    if isinstance(body, str):
        body_str = body
    elif body is None:
        body_str = ""
    else:
        # Tool sent a non-string body (e.g. dict for json content) — JSON-encode
        # it so the wire format is consistent and the renderer can re-parse.
        try:
            body_str = json.dumps(body, ensure_ascii=False)
        except (TypeError, ValueError):
            body_str = str(body)

    byte_size = len(body_str.encode("utf-8")) if body_str else len((raw_text or "").encode("utf-8"))
    truncated = False
    # Interactive HTML widgets ship fixed-at-author-time markup (either from
    # emit_html_widget's inline mode or an integration's declarative
    # html_template). The 4KB cap was designed for unbounded tool output;
    # HTML markup blows past it trivially, and the UI renderer has no
    # fall-back to lazy-fetch a truncated HTML body — truncation renders as
    # an empty iframe. Exempt only this content_type.
    if (
        cap_body
        and len(body_str) > INLINE_BODY_CAP_BYTES
        and content_type != "application/vnd.spindrel.html+interactive"
    ):
        body_str = None
        truncated = True

    source_path = envelope_data.get("source_path")
    source_channel_id = envelope_data.get("source_channel_id")
    source_bot_id = envelope_data.get("source_bot_id")
    display_label = envelope_data.get("display_label")
    refreshable = bool(envelope_data.get("refreshable"))
    refresh_interval_seconds = envelope_data.get("refresh_interval_seconds")
    extra_csp_raw = envelope_data.get("extra_csp")
    extra_csp = _sanitize_extra_csp(extra_csp_raw) if extra_csp_raw else None
    raw_display_mode = envelope_data.get("display_mode")
    display_mode = (
        raw_display_mode if raw_display_mode in ("inline", "panel") else None
    )
    view_key = envelope_data.get("view_key")
    data = envelope_data.get("data")
    template_id = envelope_data.get("template_id")
    raw_runtime = envelope_data.get("runtime")
    runtime = raw_runtime if raw_runtime in ("html", "react") else None

    return ToolResultEnvelope(
        content_type=content_type,
        body=body_str,
        plain_body=plain_body,
        display=display,  # type: ignore[arg-type]
        truncated=truncated,
        byte_size=byte_size,
        display_label=str(display_label) if display_label else None,
        refreshable=refreshable,
        refresh_interval_seconds=int(refresh_interval_seconds) if refresh_interval_seconds else None,
        source_path=str(source_path) if source_path else None,
        source_channel_id=str(source_channel_id) if source_channel_id else None,
        source_bot_id=str(source_bot_id) if source_bot_id else None,
        extra_csp=extra_csp,
        display_mode=display_mode,
        view_key=str(view_key) if view_key else None,
        data=data,
        template_id=str(template_id) if template_id else None,
        runtime=runtime,
    )


# Whitelist of CSP directives a widget may extend. Keys are snake_case as the
# tool accepts them; values are the CSP directive name used on the wire.
_CSP_DIRECTIVE_MAP = {
    "script_src": "script-src",
    "connect_src": "connect-src",
    "img_src": "img-src",
    "style_src": "style-src",
    "font_src": "font-src",
    "media_src": "media-src",
    "frame_src": "frame-src",
    "worker_src": "worker-src",
}

# Per-directive cap. A widget needing more than this for a single directive is
# almost certainly overreaching — Google Maps' kitchen-sink setup lands at ~6.
_CSP_ORIGINS_PER_DIRECTIVE = 10

# Reject any entry that tries to relax the policy beyond adding named origins.
# These are the CSP keywords/schemes the renderer's default CSP controls; we
# don't want a widget turning on `'unsafe-eval'` or `data:` for a directive
# that doesn't already have it.
_CSP_FORBIDDEN_TOKENS = {
    "*",
    "'self'",
    "'unsafe-inline'",
    "'unsafe-eval'",
    "'unsafe-hashes'",
    "'strict-dynamic'",
    "data:",
    "blob:",
    "http:",
    "https:",
    "ws:",
    "wss:",
}


def _sanitize_extra_csp(raw: Any) -> dict[str, list[str]] | None:
    """Validate + normalize a widget's ``extra_csp`` payload.

    Returns a clean ``{directive_snake: [origin, ...]}`` dict with duplicates
    removed, or raises ValueError with a user-facing message on any violation.
    Accepts list-shape inputs and normalizes to lists; skips unknown directive
    keys silently (forward-compat for future directive additions on the
    renderer side without requiring a concurrent backend bump).
    """
    if not isinstance(raw, dict):
        raise ValueError("extra_csp must be an object keyed by directive")
    out: dict[str, list[str]] = {}
    for key, value in raw.items():
        if key not in _CSP_DIRECTIVE_MAP:
            continue
        if isinstance(value, str):
            origins = [value]
        elif isinstance(value, (list, tuple)):
            origins = list(value)
        else:
            raise ValueError(
                f"extra_csp.{key} must be a list of https:// origins"
            )
        if len(origins) > _CSP_ORIGINS_PER_DIRECTIVE:
            raise ValueError(
                f"extra_csp.{key}: max {_CSP_ORIGINS_PER_DIRECTIVE} origins "
                f"per directive (got {len(origins)})"
            )
        seen: set[str] = set()
        clean: list[str] = []
        for origin in origins:
            if not isinstance(origin, str):
                raise ValueError(f"extra_csp.{key}: non-string entry")
            o = origin.strip()
            if not o:
                continue
            if o in _CSP_FORBIDDEN_TOKENS or o.lower() in _CSP_FORBIDDEN_TOKENS:
                raise ValueError(
                    f"extra_csp.{key}: {o!r} is not allowed — pass a concrete "
                    "https://host origin, not a scheme keyword or wildcard"
                )
            if not o.startswith("https://"):
                raise ValueError(
                    f"extra_csp.{key}: {o!r} must start with https:// "
                    "(http, data, blob, ws not permitted)"
                )
            # Reject path/query/fragment — CSP source expressions are origins,
            # not URLs. "https://maps.googleapis.com/maps/api/js" is a category
            # error: CSP matches the origin only.
            rest = o[len("https://"):]
            if "/" in rest or "?" in rest or "#" in rest:
                raise ValueError(
                    f"extra_csp.{key}: {o!r} should be an origin "
                    "(https://host[:port]), not a full URL"
                )
            if not rest:
                raise ValueError(f"extra_csp.{key}: empty host in {o!r}")
            if o in seen:
                continue
            seen.add(o)
            clean.append(o)
        if clean:
            out[key] = clean
    return out or None


# ---------------------------------------------------------------------------
# Dispatch helpers — extracted from ``dispatch_tool_call`` so the main
# function reads as a linear pre-guard → execute → post-process pipeline.
# ---------------------------------------------------------------------------


def _apply_error_payload(
    result_obj: "ToolCallResult",
    *,
    tool_name: str,
    tool_call_id: str,
    error_message: str,
    raw_result: str | None = None,
    error_code: str | None = None,
    error_kind: str | None = None,
    retryable: bool | None = None,
    retry_after_seconds: int | None = None,
    fallback: str | None = None,
) -> None:
    """Populate ``result_obj`` for an error / denial return path.

    ``raw_result`` — when the tool result should carry more than the default
    ``{"error": ...}`` envelope (e.g. the machine-access-required denial wraps
    a structured ``local_control_required`` payload), caller passes the
    pre-serialized JSON string. Otherwise a ``{"error": error_message}`` JSON
    body is used for both the user-visible and LLM-visible result strings.
    """
    if raw_result is not None:
        try:
            parsed = json.loads(raw_result)
            if isinstance(parsed, dict) and parsed.get("error"):
                from app.services.tool_error_contract import enrich_tool_error_payload
                parsed = enrich_tool_error_payload(
                    parsed,
                    default_code=error_code or "tool_error",
                    default_kind=error_kind,
                    retryable=retryable,
                    retry_after_seconds=retry_after_seconds,
                    fallback=fallback,
                    tool_name=tool_name,
                )
                payload = json.dumps(parsed, ensure_ascii=False)
            else:
                payload = raw_result
        except (json.JSONDecodeError, TypeError, ValueError):
            payload = raw_result
    else:
        from app.services.tool_error_contract import build_tool_error
        payload = json.dumps(
            build_tool_error(
                message=error_message,
                error_code=error_code or "tool_error",
                error_kind=error_kind,
                retryable=retryable,
                retry_after_seconds=retry_after_seconds,
                fallback=fallback,
                tool_name=tool_name,
            ),
            ensure_ascii=False,
        )
    result_obj.result = payload
    result_obj.result_for_llm = payload
    result_obj.tool_event = {
        "type": "tool_result",
        "tool": tool_name,
        "tool_call_id": tool_call_id,
        "error": error_message,
    }
    try:
        parsed_payload = json.loads(payload)
        if isinstance(parsed_payload, dict):
            for key in ("error_code", "error_kind", "retryable", "retry_after_seconds", "fallback"):
                if key in parsed_payload:
                    result_obj.tool_event[key] = parsed_payload[key]
    except (json.JSONDecodeError, TypeError, ValueError):
        pass


def _enqueue_denial_record(
    *,
    session_id: uuid.UUID | None,
    client_id: str | None,
    bot_id: str,
    tool_name: str,
    tool_type: str,
    iteration: int,
    arguments: dict,
    result: str,
    error: str,
    correlation_id: uuid.UUID | None,
    envelope: dict | None = None,
    error_code: str | None = None,
    error_kind: str | None = None,
    retryable: bool | None = None,
    retry_after_seconds: int | None = None,
    fallback: str | None = None,
) -> None:
    """Enqueue a ``_record_tool_call`` insert with ``status='denied'``.

    Fire-and-forget — uses ``safe_create_task`` so the dispatcher can return
    the deny ``ToolCallResult`` immediately without awaiting the DB write.
    """
    kwargs = dict(
        session_id=session_id,
        client_id=client_id,
        bot_id=bot_id,
        tool_name=tool_name,
        tool_type=tool_type,
        server_name=None,
        iteration=iteration,
        arguments=arguments,
        result=result,
        error=error,
        duration_ms=0,
        correlation_id=correlation_id,
        status="denied",
        error_code=error_code,
        error_kind=error_kind,
        retryable=retryable,
        retry_after_seconds=retry_after_seconds,
        fallback=fallback,
    )
    if envelope is not None:
        kwargs["envelope"] = envelope
    safe_create_task(_record_tool_call(**kwargs))


def _parse_args_dict(args: str | None) -> dict:
    """Parse a JSON arguments string into a dict, returning ``{}`` on any
    failure. Used by the deny paths to populate the ``arguments`` column on
    the recorded denial row without crashing on malformed input.
    """
    if not args:
        return {}
    try:
        parsed = json.loads(args)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def _authorization_guard(
    result_obj: "ToolCallResult",
    *,
    name: str,
    tool_call_id: str,
    bot_id: str,
    client_id: str | None,
    session_id: uuid.UUID | None,
    correlation_id: uuid.UUID | None,
    iteration: int,
    arguments: dict,
    allowed_tool_names: set[str] | None,
) -> "ToolCallResult | None":
    """Early-deny when ``allowed_tool_names`` is set and ``name`` is absent.

    Returns the populated ``result_obj`` to signal the caller should return
    immediately; returns None when the tool is authorized (or no allowlist
    constraint is in effect).
    """
    if allowed_tool_names is None or name in allowed_tool_names:
        return None
    _trace("✗ %s not authorized for bot %s", name, bot_id)
    err = f"Tool '{name}' is not available. It must be explicitly assigned to this bot."
    _apply_error_payload(
        result_obj, tool_name=name, tool_call_id=tool_call_id, error_message=err,
        error_code="tool_not_assigned", error_kind="forbidden",
    )
    _enqueue_denial_record(
        session_id=session_id, client_id=client_id, bot_id=bot_id,
        tool_name=name, tool_type="unknown", iteration=iteration,
        arguments=arguments, result=result_obj.result,
        error=err, correlation_id=correlation_id,
        error_code="tool_not_assigned", error_kind="forbidden", retryable=False,
        fallback="Ask an admin to assign the tool or choose an assigned alternative.",
    )
    return result_obj


async def _execution_policy_guard(
    result_obj: "ToolCallResult",
    *,
    name: str,
    tool_call_id: str,
    bot_id: str,
    client_id: str | None,
    session_id: uuid.UUID | None,
    correlation_id: uuid.UUID | None,
    iteration: int,
    arguments: dict,
) -> tuple["ToolCallResult | None", str]:
    """Machine-control execution-policy gate for local tools.

    Returns ``(denial_or_None, execution_policy)``. ``execution_policy`` is
    one of ``"normal" | "interactive_user" | "live_target_lease"``; the
    downstream policy guard short-circuits ``require_approval`` for the
    latter two when the rule is the default (no explicit rule_id).
    """
    if not is_local_tool(name):
        return None, "normal"
    from app.tools.registry import get_tool_execution_policy
    execution_policy = get_tool_execution_policy(name)
    if execution_policy == "normal":
        return None, "normal"
    try:
        from app.services.machine_control import (
            build_machine_access_required_payload,
            validate_current_execution_policy,
        )
        resolution = await validate_current_execution_policy(execution_policy)
    except Exception:
        logger.exception("Execution-policy validation failed for %s", name)
        err = "Tool call denied: unable to validate the machine-control policy. Please retry."
        _apply_error_payload(
            result_obj, tool_name=name, tool_call_id=tool_call_id, error_message=err,
            error_code="execution_policy_validation_failed", error_kind="unavailable",
            retryable=True,
        )
        return result_obj, execution_policy
    if resolution is None or resolution.allowed:
        return None, execution_policy

    exec_err = resolution.reason or "Tool call denied by execution policy."
    from app.services.tool_error_contract import build_tool_error
    deny_payload_error = build_tool_error(
        message=exec_err,
        error_code="local_control_required",
        error_kind="approval_required",
        retryable=False,
        tool_name=name,
        extra={"message": exec_err},
    )
    deny_result = json.dumps(deny_payload_error, ensure_ascii=False)
    deny_payload: dict = {
        "reason": exec_err,
        "execution_policy": execution_policy,
        "requested_tool": name,
        "session_id": str(session_id) if session_id else None,
        "lease": None,
        "targets": [],
        "connected_targets": [],
        "connected_target_count": 0,
        "admin_machines_href": "/admin/machines",
        "integration_admin_href": "/admin/machines",
    }
    try:
        async with async_session() as db:
            deny_payload = await build_machine_access_required_payload(
                db,
                session_id=session_id,
                reason=exec_err,
                execution_policy=execution_policy,
                requested_tool=name,
            )
    except Exception:
        logger.debug("Failed to build machine-control denial payload for %s", name, exc_info=True)
    result_obj.result = deny_result
    result_obj.result_for_llm = deny_result
    result_obj.envelope = _build_envelope_from_optin(
        {
            "content_type": "application/vnd.spindrel.components+json",
            "display": "inline",
            "plain_body": exec_err,
            "body": {
                "v": 1,
                "components": [
                    {"type": "heading", "text": "Machine access required", "level": 3},
                ],
            },
            "view_key": "core.machine_access_required",
            "data": deny_payload,
        },
        deny_result,
    )
    result_obj.envelope.tool_name = name
    result_obj.envelope.tool_call_id = tool_call_id
    result_obj.tool_event = {
        "type": "tool_result", "tool": name, "tool_call_id": tool_call_id,
        "error": exec_err,
        "error_code": "local_control_required",
        "error_kind": "approval_required",
        "retryable": False,
        "retry_after_seconds": None,
        "fallback": deny_payload_error.get("fallback"),
    }
    _enqueue_denial_record(
        session_id=session_id, client_id=client_id, bot_id=bot_id,
        tool_name=name, tool_type="local", iteration=iteration,
        arguments=arguments, result=result_obj.result,
        error=exec_err, correlation_id=correlation_id,
        envelope=result_obj.envelope.compact_dict(),
        error_code="local_control_required", error_kind="approval_required",
        retryable=False, retry_after_seconds=None,
        fallback=deny_payload_error.get("fallback"),
    )
    return result_obj, execution_policy


async def _policy_and_approval_guard(
    result_obj: "ToolCallResult",
    *,
    name: str,
    tool_call_id: str,
    bot_id: str,
    client_id: str | None,
    session_id: uuid.UUID | None,
    channel_id: uuid.UUID | None,
    correlation_id: uuid.UUID | None,
    iteration: int,
    arguments: dict,
    execution_policy: str,
    skip_policy: bool,
) -> "ToolCallResult | None":
    """Tool-policy evaluation + approval creation.

    Three terminal outcomes:
    - policy deny → populated ``result_obj`` with ``"denied by policy"`` error.
    - require_approval → populated ``result_obj`` with ``needs_approval=True``,
      ``approval_id``, ``record_id``.
    - eval error → populated ``result_obj`` with generic policy error.

    Returns None when the policy allows the tool or ``skip_policy`` is set.
    """
    if skip_policy:
        return None
    try:
        decision = await _check_tool_policy(
            bot_id, name, arguments,
            correlation_id=str(correlation_id) if correlation_id else None,
        )
        if decision is None:
            return None
        if (
            execution_policy in {"interactive_user", "live_target_lease"}
            and decision.action == "require_approval"
            and decision.rule_id is None
        ):
            return None
        if decision.action == "deny":
            err = f"Tool call denied by policy: {decision.reason or 'no reason'}"
            _apply_error_payload(
                result_obj, tool_name=name, tool_call_id=tool_call_id, error_message=err,
                error_code="tool_policy_denied", error_kind="forbidden",
            )
            # Preserve legacy ``"Denied by policy: ..."`` phrasing on tool_event.error
            # for renderers / tests that match on it.
            result_obj.tool_event["error"] = f"Denied by policy: {decision.reason or 'no reason'}"
            _trace("✗ %s denied by policy (rule %s)", name, decision.rule_id)
            _enqueue_denial_record(
                session_id=session_id, client_id=client_id, bot_id=bot_id,
                tool_name=name, tool_type="unknown", iteration=iteration,
                arguments=arguments, result=result_obj.result,
                error=err, correlation_id=correlation_id,
                error_code="tool_policy_denied", error_kind="forbidden", retryable=False,
                fallback="Ask for approval/config changes or choose an allowed tool.",
            )
            return result_obj
        if decision.action == "require_approval":
            if is_client_tool(name):
                ap_type = "client"
            elif is_mcp_tool(name):
                ap_type = "mcp"
            else:
                ap_type = "local"
            approval_reason = decision.reason
            if decision.tier:
                approval_reason = f"[{decision.tier}] {decision.reason}"
            try:
                pending_id, approval_id = await _create_approval_state(
                    session_id=session_id, channel_id=channel_id, bot_id=bot_id,
                    client_id=client_id, correlation_id=correlation_id,
                    tool_name=name, tool_type=ap_type, arguments=arguments,
                    iteration=iteration, policy_rule_id=decision.rule_id,
                    reason=approval_reason, timeout=decision.timeout,
                )
            except Exception:
                logger.exception("Failed to create approval state for %s", name)
                err = "Tool call denied: approval state could not be created. Please retry."
                _apply_error_payload(
                    result_obj, tool_name=name, tool_call_id=tool_call_id, error_message=err,
                    error_code="approval_state_create_failed", error_kind="unavailable",
                    retryable=True,
                )
                return result_obj
            result_obj.needs_approval = True
            result_obj.approval_id = approval_id
            result_obj.approval_timeout = decision.timeout
            result_obj.approval_reason = approval_reason
            result_obj.record_id = pending_id
            result_obj.result_for_llm = json.dumps({
                "status": "pending_approval", "reason": approval_reason,
            })
            result_obj.tool_event = {
                "type": "tool_result", "tool": name, "tool_call_id": tool_call_id,
                "pending_approval": True,
            }
            _trace("⏳ %s requires approval (%s)", name,
                   f"tier={decision.tier}" if decision.tier else f"rule {decision.rule_id}")
            return result_obj
    except Exception:
        logger.exception("Policy check failed for %s — denying by default", name)
        err = "Tool call denied: policy evaluation error. Please retry."
        _apply_error_payload(
            result_obj, tool_name=name, tool_call_id=tool_call_id, error_message=err,
            error_code="policy_evaluation_error", error_kind="unavailable",
            retryable=True,
        )
        return result_obj
    return None


async def _plan_mode_guard(
    result_obj: "ToolCallResult",
    *,
    name: str,
    tool_call_id: str,
    bot_id: str,
    client_id: str | None,
    session_id: uuid.UUID | None,
    correlation_id: uuid.UUID | None,
    iteration: int,
    arguments: dict,
    pre_hook_type: str,
    safety_tier: str | None,
) -> "ToolCallResult | None":
    """Plan-mode tool-kind allowlist check.

    Sessions in plan mode restrict the set of tool kinds that can run —
    evidence-gathering local tools only, no network / write / approval paths.
    Returns a populated deny ``result_obj`` when the current session blocks
    the tool, or None when plan mode allows it (or the session isn't in
    plan mode, or no ``session_id`` was passed).
    """
    if session_id is None:
        return None
    try:
        from app.services.session_plan_mode import plan_mode_tool_denial_reason
        session = await _load_session_for_plan_mode(session_id)
        if session is None:
            return None
        err = plan_mode_tool_denial_reason(
            session,
            tool_name=name,
            tool_kind=pre_hook_type,
            safety_tier=safety_tier,
        )
        if not err:
            return None
        _apply_error_payload(
            result_obj, tool_name=name, tool_call_id=tool_call_id, error_message=err,
            error_code="plan_mode_denied", error_kind="forbidden",
        )
        _enqueue_denial_record(
            session_id=session_id, client_id=client_id, bot_id=bot_id,
            tool_name=name, tool_type=pre_hook_type, iteration=iteration,
            arguments=arguments, result=result_obj.result,
            error=err, correlation_id=correlation_id,
            error_code="plan_mode_denied", error_kind="forbidden", retryable=False,
        )
        return result_obj
    except Exception:
        logger.exception("Plan-mode guard failed for %s — denying by default", name)
        err = "Tool call denied: unable to validate plan-mode restrictions. Please retry."
        _apply_error_payload(
            result_obj, tool_name=name, tool_call_id=tool_call_id, error_message=err,
            error_code="plan_mode_validation_failed", error_kind="unavailable",
            retryable=True,
        )
        return result_obj


def _classify_pre_hook_type(name: str) -> str:
    """Map a tool ``name`` to its broad ``tool_type`` category used by
    hooks, plan-mode, DB recording."""
    if is_client_tool(name):
        return "client"
    if is_mcp_tool(name):
        return "mcp"
    if is_widget_handler_tool_name(name):
        return "widget"
    return "local"


def _extract_embedded_payloads(
    raw_result: str,
) -> tuple[str, dict | None, dict | None, list[dict] | None]:
    """Parse ``raw_result`` JSON (when possible) and extract the three
    structured extension points tools can embed alongside plain output:

    - ``_envelope`` — a user-visible rendering hint lifted onto the final
      envelope (content_type, body, display, plain_body, …).
    - ``client_action`` — browser-side action the UI performs (navigation,
      file open, etc.). Paired with a short ``message`` used as LLM text.
    - ``injected_images`` — images injected into the LLM's context.

    Returns ``(result_for_llm, envelope_optin, embedded_client_action,
    injected_images)``. ``result_for_llm`` is the raw JSON when no
    extension is present, or the extracted ``message`` / ``llm`` / default
    string when one is. Callers still need to run ``_redact_secrets`` on
    the returned ``result_for_llm`` — this helper is parse-only.
    """
    try:
        parsed = json.loads(raw_result)
    except (json.JSONDecodeError, TypeError):
        return raw_result, None, None, None
    if not isinstance(parsed, dict):
        return raw_result, None, None, None

    envelope_optin: dict | None = None
    if isinstance(parsed.get("_envelope"), dict):
        envelope_optin = parsed["_envelope"]

    if "client_action" in parsed:
        return parsed.get("message", "Done."), envelope_optin, parsed["client_action"], None
    if "injected_images" in parsed:
        return (
            parsed.get("message", "Image loaded for analysis."),
            envelope_optin,
            None,
            parsed["injected_images"],
        )
    if envelope_optin is not None:
        # Tool only sent an envelope — surface its ``llm`` text (if any) so
        # the bot has a short, readable hand-off without the full rendered
        # body bloating the context window.
        llm_text = parsed.get("llm")
        if isinstance(llm_text, str) and llm_text:
            return llm_text, envelope_optin, None, None
    return raw_result, envelope_optin, None, None


def _select_result_envelope(
    *,
    name: str,
    tool_call_id: str,
    redacted_result: str,
    envelope_optin: dict | None,
    redact: Any,
) -> "ToolResultEnvelope":
    """Build the final ``ToolResultEnvelope`` for a successful tool call.

    Precedence: ``_envelope`` opt-in from the tool → declared widget
    template → auto-detected default (markdown / json / plain text).
    Also invalidates the widget poll cache for tools that declare
    ``state_poll_config`` so the next refresh hits the real service
    instead of serving a stale payload.

    ``redact`` is injected so the caller controls which secret-registry
    function is used (avoids a module-level import dance).
    """
    from app.services.widget_templates import apply_widget_template, get_state_poll_config

    if envelope_optin is not None:
        scrubbed = dict(envelope_optin)
        if isinstance(scrubbed.get("body"), str):
            scrubbed["body"] = redact(scrubbed["body"])
        if isinstance(scrubbed.get("plain_body"), str):
            scrubbed["plain_body"] = redact(scrubbed["plain_body"])
        envelope = _build_envelope_from_optin(scrubbed, redacted_result)
    else:
        widget_envelope = apply_widget_template(name, redacted_result)
        if widget_envelope is not None:
            envelope = widget_envelope
        else:
            envelope = _build_default_envelope(redacted_result)
        # Widget-template tools and default tools may have mutated external
        # state a pinned widget is tracking. Drop the cached poll result so
        # the next refresh reads fresh data.
        poll_cfg = get_state_poll_config(name)
        if poll_cfg:
            try:
                from app.services.widget_action_state_poll import invalidate_poll_cache_for
                invalidate_poll_cache_for(poll_cfg)
            except Exception:
                logger.debug("poll-cache invalidation skipped", exc_info=True)

    envelope.tool_name = name
    envelope.tool_call_id = tool_call_id
    return envelope


def _build_tool_event(
    *,
    name: str,
    tool_call_id: str,
    args: str,
    redacted_result: str,
    result_for_llm: str,
    envelope: "ToolResultEnvelope",
    was_summarized: bool,
) -> dict[str, Any]:
    """Assemble the ``tool_result`` SSE event: envelope + presentation
    (surface / summary) + error hoist when the tool returned ``{"error": …}``.
    """
    from app.services.tool_presentation import derive_tool_presentation

    event: dict[str, Any] = {"type": "tool_result", "tool": name, "tool_call_id": tool_call_id}
    if was_summarized:
        event["summarized"] = True
    try:
        parsed = json.loads(redacted_result)
        if isinstance(parsed, dict) and "error" in parsed:
            err = parsed["error"]
            logger.warning("Tool %s returned error: %s", name, err)
            event["error"] = err
            for key in ("error_code", "error_kind", "retryable", "retry_after_seconds", "fallback"):
                if key in parsed:
                    event[key] = parsed[key]
            _trace("← %s error: %s", name, str(err)[:80])
        else:
            _trace("← %s (%d chars)", name, len(result_for_llm))
    except (json.JSONDecodeError, TypeError):
        _trace("← %s (%d chars)", name, len(result_for_llm))

    event["envelope"] = envelope.compact_dict()
    try:
        tool_args = json.loads(args) if args else {}
    except (json.JSONDecodeError, TypeError):
        tool_args = {}
    surface, summary = derive_tool_presentation(
        tool_name=name,
        arguments=tool_args,
        result=redacted_result,
        envelope=event["envelope"],
        error=event.get("error"),
    )
    event["surface"] = surface
    event["summary"] = summary
    return event


async def _execute_tool_call(
    result_obj: "ToolCallResult",
    *,
    name: str,
    args: str,
    bot_id: str,
    session_id: uuid.UUID | None,
    client_id: str | None,
    correlation_id: uuid.UUID | None,
    channel_id: uuid.UUID | None,
    iteration: int,
    pre_hook_type: str,
    compaction: bool,
) -> tuple[str, str, str | None]:
    """Fire the ``before_tool_execution`` hook, select the per-kind tool
    coroutine (client/local/mcp/widget), run it under the shared wall-clock
    guard, and return ``(raw_result_json, tc_type, tc_server)``.

    Side effects on ``result_obj``:
    - ``pre_events`` appended with a ``tool_request`` event for client tools.
    - ``duration_ms`` populated from the monotonic stopwatch.

    ``tc_type`` is normally identical to ``pre_hook_type`` except for local
    tools that dispatch through ``call_persona_tool`` — those still report
    ``"local"`` since the downstream audit/summarize logic keys on it.
    """
    from app.agent.message_utils import _event_with_compaction_tag
    from app.agent.hooks import fire_hook, HookContext

    safe_create_task(fire_hook("before_tool_execution", HookContext(
        bot_id=bot_id, session_id=session_id, channel_id=channel_id,
        client_id=client_id, correlation_id=correlation_id,
        extra={
            "tool_name": name,
            "tool_type": pre_hook_type,
            "args": args,
            "iteration": iteration + 1,
        },
    )))

    t0 = time.monotonic()
    tc_type = "local"
    tc_server: str | None = None
    tool_coro = None
    result: str = ""

    if is_client_tool(name):
        tc_type = "client"
        request_id = str(uuid.uuid4())
        try:
            tool_args = json.loads(args) if args else {}
        except (json.JSONDecodeError, TypeError):
            tool_args = {}
        result_obj.pre_events.append(_event_with_compaction_tag({
            "type": "tool_request",
            "request_id": request_id,
            "tool": name,
            "arguments": tool_args,
        }, compaction))
        future = create_pending(request_id)
        try:
            result = await asyncio.wait_for(future, timeout=CLIENT_TOOL_TIMEOUT)
        except asyncio.TimeoutError:
            expire_pending(request_id)
            logger.warning("Client tool %s timed out (request %s)", name, request_id)
            from app.services.tool_error_contract import build_tool_error
            result = json.dumps(
                build_tool_error(
                    message="Client did not respond in time",
                    error_code="client_tool_timeout",
                    error_kind="timeout",
                    retryable=True,
                    retry_after_seconds=1,
                    tool_name=name,
                ),
                ensure_ascii=False,
            )
    elif is_local_tool(name):
        tc_type = "local"
        if name in ("update_persona", "append_to_persona", "edit_persona"):
            tool_coro = call_persona_tool(name, args or "{}", bot_id)
        else:
            tool_coro = call_local_tool(name, args)
    elif is_mcp_tool(name):
        tc_type = "mcp"
        tc_server = get_mcp_server_for_tool(name)
        tool_coro = call_mcp_tool(name, args)
    elif is_widget_handler_tool_name(name):
        tc_type = "widget"
        tool_coro = _call_widget_handler_tool(name, args, bot_id, channel_id)
    else:
        from app.services.tool_error_contract import build_tool_error
        result = json.dumps(
            build_tool_error(
                message=f"Unknown tool: {name}",
                error_code="unknown_tool",
                error_kind="not_found",
                tool_name=name,
            ),
            ensure_ascii=False,
        )

    if tool_coro is not None:
        try:
            result = await asyncio.wait_for(
                tool_coro, timeout=settings.TOOL_DISPATCH_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Tool %s exceeded %.0fs wall-clock — cancelled by dispatch guard",
                name, settings.TOOL_DISPATCH_TIMEOUT,
            )
            from app.services.tool_error_contract import build_tool_error
            result = json.dumps(
                build_tool_error(
                    message=(
                        f"Tool {name} exceeded {settings.TOOL_DISPATCH_TIMEOUT:.0f}s "
                        "wall-clock and was cancelled. Try a different approach."
                    ),
                    error_code="tool_dispatch_timeout",
                    error_kind="timeout",
                    retryable=True,
                    retry_after_seconds=1,
                    tool_name=name,
                ),
                ensure_ascii=False,
            )

    result_obj.duration_ms = int((time.monotonic() - t0) * 1000)
    return result, tc_type, tc_server


async def dispatch_tool_call(
    *,
    name: str,
    args: str,
    tool_call_id: str,
    bot_id: str,
    bot_memory: Any,
    session_id: uuid.UUID | None,
    client_id: str | None,
    correlation_id: uuid.UUID | None,
    channel_id: uuid.UUID | None,
    iteration: int,
    provider_id: str | None,
    # Summarization config
    summarize_enabled: bool,
    summarize_threshold: int,
    summarize_model: str,
    summarize_max_tokens: int,
    summarize_exclude: set[str],
    # Compaction flag for event tagging
    compaction: bool,
    # Policy override — skip check when re-dispatching after approval
    skip_policy: bool = False,
    # Authorization — if set, only these tool names are allowed
    allowed_tool_names: set[str] | None = None,
    # Re-dispatch after approval: reuse the existing 'awaiting_approval' row
    # instead of inserting a new one. Set by ``app/agent/loop.py`` from the
    # ``record_id`` returned on the first (gated) dispatch.
    existing_record_id: uuid.UUID | None = None,
) -> ToolCallResult:
    """Route a single tool call to the appropriate handler, record it, and build the result event."""
    from app.agent.message_utils import _event_with_compaction_tag

    result_obj = ToolCallResult()

    # --- Forgiving MCP name resolution ---
    # LiteLLM's MCP gateway namespaces tools as "<server>-<tool>". Small models
    # (e.g. Gemini 2.5 Flash) frequently drop the prefix. If the name isn't a
    # known tool of any kind, try the prefixed MCP variant before failing so
    # the call lands instead of forcing a get_tool_info round-trip.
    if (
        not is_client_tool(name)
        and not is_local_tool(name)
        and not is_mcp_tool(name)
        and not is_widget_handler_tool_name(name)
    ):
        _resolved = resolve_mcp_tool_name(name)
        if _resolved is not None and _resolved != name:
            logger.info(
                "dispatch_tool_call: resolved bare name %r -> %r",
                name, _resolved,
            )
            name = _resolved

    args_dict = _parse_args_dict(args)

    # --- Pre-execution guards — each returns a populated ``result_obj`` to
    # short-circuit, or None to continue. Ordering matters: authorization
    # (cheap) → execution-policy (machine-control) → tool-policy + approval
    # (external config) → plan-mode (session state). The execution_policy
    # result flows into the policy guard so ``interactive_user`` /
    # ``live_target_lease`` tools skip default ``require_approval``.
    if (deny := await _authorization_guard(
        result_obj, name=name, tool_call_id=tool_call_id, bot_id=bot_id,
        client_id=client_id, session_id=session_id, correlation_id=correlation_id,
        iteration=iteration, arguments=args_dict, allowed_tool_names=allowed_tool_names,
    )) is not None:
        return deny

    deny, _execution_policy = await _execution_policy_guard(
        result_obj, name=name, tool_call_id=tool_call_id, bot_id=bot_id,
        client_id=client_id, session_id=session_id, correlation_id=correlation_id,
        iteration=iteration, arguments=args_dict,
    )
    if deny is not None:
        return deny

    if (deny := await _policy_and_approval_guard(
        result_obj, name=name, tool_call_id=tool_call_id, bot_id=bot_id,
        client_id=client_id, session_id=session_id, channel_id=channel_id,
        correlation_id=correlation_id, iteration=iteration, arguments=args_dict,
        execution_policy=_execution_policy, skip_policy=skip_policy,
    )) is not None:
        return deny

    _pre_hook_type = _classify_pre_hook_type(name)

    _safety_tier = None
    if _pre_hook_type == "local":
        from app.tools.registry import get_tool_safety_tier
        _safety_tier = get_tool_safety_tier(name)

    if (deny := await _plan_mode_guard(
        result_obj, name=name, tool_call_id=tool_call_id, bot_id=bot_id,
        client_id=client_id, session_id=session_id, correlation_id=correlation_id,
        iteration=iteration, arguments=args_dict,
        pre_hook_type=_pre_hook_type, safety_tier=_safety_tier,
    )) is not None:
        return deny

    # Tool call row id — pre-allocated so the row exists in 'running' state
    # before completion. Re-dispatch after approval reuses the existing row
    # via ``existing_record_id``; first dispatch inserts a new one.
    try:
        _tc_args_pre: dict = json.loads(args or "{}") if args else {}
        if not isinstance(_tc_args_pre, dict):
            _tc_args_pre = {}
    except Exception:
        _tc_args_pre = {}
    if existing_record_id is not None:
        _tc_record_id = existing_record_id
    else:
        _tc_record_id = uuid.uuid4()
        await _start_tool_call(
            id=_tc_record_id,
            session_id=session_id,
            client_id=client_id,
            bot_id=bot_id,
            tool_name=name,
            tool_type=_pre_hook_type,
            server_name=None,
            iteration=iteration,
            arguments=_tc_args_pre,
            correlation_id=correlation_id,
            status="running",
            strict=True,
        )

    result, _tc_type, _tc_server = await _execute_tool_call(
        result_obj,
        name=name, args=args, bot_id=bot_id,
        session_id=session_id, client_id=client_id,
        correlation_id=correlation_id, channel_id=channel_id,
        iteration=iteration, pre_hook_type=_pre_hook_type,
        compaction=compaction,
    )
    _tc_duration = result_obj.duration_ms

    # Detect tool-reported errors so the row gets status='error' on UPDATE.
    # Tools can also tag their failure with ``error_kind`` (validation,
    # not_found, conflict, forbidden, internal, ...) so downstream observers
    # can tell a benign 4xx-shaped domain rejection from a real crash.
    _tc_error: str | None = None
    _tc_error_kind: str | None = None
    _tc_error_code: str | None = None
    _tc_retryable: bool | None = None
    _tc_retry_after_seconds: int | None = None
    _tc_fallback: str | None = None
    try:
        _parsed_r = json.loads(result)
        if isinstance(_parsed_r, dict):
            if "error" in _parsed_r and _parsed_r["error"]:
                from app.services.tool_error_contract import enrich_tool_error_payload
                _parsed_r = enrich_tool_error_payload(
                    _parsed_r,
                    default_code=f"{_tc_type}_tool_error",
                    tool_name=name,
                )
                result = json.dumps(_parsed_r, ensure_ascii=False)
                _tc_error = str(_parsed_r["error"])
                _tc_error_kind = str(_parsed_r.get("error_kind") or "") or None
                _tc_error_code = str(_parsed_r.get("error_code") or "") or None
                _tc_retryable = bool(_parsed_r.get("retryable"))
                retry_after_raw = _parsed_r.get("retry_after_seconds")
                _tc_retry_after_seconds = int(retry_after_raw) if retry_after_raw is not None else None
                _tc_fallback = str(_parsed_r.get("fallback") or "") or None
            elif "error_kind" in _parsed_r and _parsed_r["error_kind"]:
                _tc_error_kind = str(_parsed_r["error_kind"])
    except Exception:
        pass

    # Redact known secrets from the raw result before storage
    from app.services.secret_registry import redact as _redact_secrets
    result_obj.result = _redact_secrets(result)

    # Extract embedded ``_envelope`` / ``client_action`` / ``injected_images``
    # from the raw (pre-redacted) JSON parse. The LLM-visible ``result_for_llm``
    # is re-redacted below; the envelope body is redacted inside
    # ``_select_result_envelope``.
    result_for_llm, _envelope_optin, _client_action, _injected_images = (
        _extract_embedded_payloads(result)
    )
    if _client_action is not None:
        result_obj.embedded_client_action = _client_action
    if _injected_images is not None:
        result_obj.injected_images = _injected_images

    # Redact known secrets before summarization or LLM consumption
    result_for_llm = _redact_secrets(result_for_llm)

    # Wrap MCP results in untrusted-data tags (injection boundary)
    if _tc_type == "mcp":
        from app.security.prompt_sanitize import wrap_untrusted_content
        result_for_llm = wrap_untrusted_content(
            result_for_llm, f"mcp:{_tc_server or name}"
        )

    # Audit log for exec_capable / control_plane tools
    if _safety_tier is None:
        from app.tools.registry import get_tool_safety_tier

        _safety_tier = get_tool_safety_tier(name)
    if _safety_tier in ("exec_capable", "control_plane"):
        from app.security.audit import log_tool_execution
        _args_summary = (args or "")[:200]
        log_tool_execution(
            tool_name=name,
            safety_tier=_safety_tier,
            bot_id=bot_id,
            channel_id=str(channel_id) if channel_id else None,
            arguments_summary=_args_summary,
        )

    # Hard-cap: truncate very large results before they enter the context window.
    # Full result is stored in DB (below) so the bot can retrieve on demand.
    _hard_cap = settings.TOOL_RESULT_HARD_CAP
    if _hard_cap and len(result_for_llm) > _hard_cap:
        result_for_llm = (
            result_for_llm[:_hard_cap]
            + f"\n\n[Truncated at {_hard_cap:,} chars — full output stored]"
        )

    # Summarize if needed
    _orig_len = len(result_for_llm)
    _was_summarized = False
    _will_summarize = (
        summarize_enabled
        and name not in summarize_exclude
        and (_tc_server is None or _tc_server not in summarize_exclude)
        and len(result_for_llm) > summarize_threshold
    )

    result_obj.envelope = _select_result_envelope(
        name=name,
        tool_call_id=tool_call_id,
        redacted_result=result_obj.result,
        envelope_optin=_envelope_optin,
        redact=_redact_secrets,
    )

    # The row was inserted up-front in 'running' state (or reused from the
    # awaiting-approval re-dispatch). Decide whether to keep the full result
    # so retrieval pointers in subsequent turns work, then UPDATE.
    _store_full = (
        _will_summarize
        or _orig_len > settings.CONTEXT_PRUNING_MIN_LENGTH
        or result_obj.envelope.truncated
    )
    if result_obj.envelope.truncated:
        result_obj.envelope.record_id = _tc_record_id

    await _complete_tool_call(
        _tc_record_id,
        tool_name=name,
        arguments=_tc_args_pre,
        result=result_obj.result,  # use redacted result
        error=_tc_error,
        error_kind=_tc_error_kind,
        error_code=_tc_error_code,
        retryable=_tc_retryable,
        retry_after_seconds=_tc_retry_after_seconds,
        fallback=_tc_fallback,
        duration_ms=_tc_duration,
        status="error" if _tc_error else "done",
        store_full_result=_store_full,
        envelope=result_obj.envelope.compact_dict(),
        strict=True,
    )

    if _will_summarize:
        _was_summarized = True
        from app.config import settings as _settings
        result_for_llm = await _summarize_tool_result(
            tool_name=name,
            content=result_for_llm,
            model=summarize_model,
            max_tokens=summarize_max_tokens,
            provider_id=_settings.TOOL_RESULT_SUMMARIZE_MODEL_PROVIDER_ID or provider_id,
        )
        # Append retrieval hint so the bot can fetch full output
        result_for_llm += (
            f"\n\n[Full output stored — use read_conversation_history"
            f"(section='tool:{_tc_record_id}') to retrieve]"
        )
        if correlation_id is not None:
            safe_create_task(_record_trace_event(
                correlation_id=correlation_id,
                session_id=session_id,
                bot_id=bot_id,
                client_id=client_id,
                event_type="tool_result_summarization",
                data={
                    "tool_name": name,
                    "original_length": _orig_len,
                    "summarized_length": len(result_for_llm),
                    "tool_call_record_id": str(_tc_record_id),
                },
            ))

    result_obj.result_for_llm = result_for_llm
    result_obj.was_summarized = _was_summarized
    result_obj.record_id = _tc_record_id

    result_preview = result_for_llm[:200] + "..." if len(result_for_llm) > 200 else result_for_llm
    logger.debug("Tool result [%s]: %s", name, result_preview)

    tool_event = _build_tool_event(
        name=name,
        tool_call_id=tool_call_id,
        args=args,
        redacted_result=result_obj.result,
        result_for_llm=result_for_llm,
        envelope=result_obj.envelope,
        was_summarized=_was_summarized,
    )
    result_obj.tool_event = tool_event
    from app.agent.context import current_turn_id
    safe_create_task(_record_plan_tool_evidence(
        session_id=session_id,
        tool_name=name,
        tool_kind=_tc_type,
        status="error" if _tc_error else "done",
        error=_tc_error,
        error_kind=_tc_error_kind,
        error_code=_tc_error_code,
        retryable=_tc_retryable,
        retry_after_seconds=_tc_retry_after_seconds,
        fallback=_tc_fallback,
        tool_call_id=tool_call_id,
        record_id=_tc_record_id,
        arguments=_tc_args_pre,
        result_summary=tool_event.get("summary") or result_preview,
        turn_id=current_turn_id.get(),
        correlation_id=str(correlation_id) if correlation_id else None,
    ))

    return result_obj


# ---------------------------------------------------------------------------
# Widget-handler dispatch
# ---------------------------------------------------------------------------

async def _call_widget_handler_tool(
    tool_name: str,
    arguments_json: str | None,
    bot_id: str,
    channel_id: uuid.UUID | None,
) -> str:
    """Invoke a bot-callable widget handler by resolving pin + handler name.

    The handler runs under the pin's ``source_bot_id`` (same identity as
    iframe / cron / event paths). The calling bot's scopes don't widen the
    handler — the pin's bot is the ceiling. See
    ``app/services/widget_handler_tools.py`` for visibility rules.
    """
    from app.db.engine import async_session
    from app.services.widget_py import invoke_action

    try:
        args = json.loads(arguments_json) if arguments_json else {}
        if not isinstance(args, dict):
            args = {}
    except (json.JSONDecodeError, TypeError):
        args = {}

    async with async_session() as db:
        resolved = await resolve_widget_handler(
            db, tool_name, bot_id, str(channel_id) if channel_id else None,
        )
    if resolved is None:
        from app.services.tool_error_contract import build_tool_error
        return json.dumps(
            build_tool_error(
                message=(
                    f"widget handler {tool_name!r} could not be resolved — "
                    "the pin may have been removed or moved to a dashboard you can't see."
                ),
                error_code="widget_handler_not_found",
                error_kind="not_found",
                tool_name=tool_name,
            ),
            ensure_ascii=False,
        )

    pin, handler_name, _tier = resolved
    try:
        result = await invoke_action(pin, handler_name, args)
    except (FileNotFoundError, KeyError, ValueError, PermissionError) as exc:
        logger.info(
            "widget handler %s dispatch failed (%s): %s",
            tool_name, type(exc).__name__, exc,
        )
        from app.services.tool_error_contract import build_tool_error, infer_error_kind
        return json.dumps(
            build_tool_error(
                message=str(exc),
                error_code=f"widget_handler_{type(exc).__name__.lower()}",
                error_kind=infer_error_kind(type(exc).__name__, str(exc)),
                tool_name=tool_name,
            ),
            ensure_ascii=False,
        )
    except asyncio.TimeoutError:
        logger.warning("widget handler %s exceeded handler timeout", tool_name)
        from app.services.tool_error_contract import build_tool_error
        return json.dumps(
            build_tool_error(
                message="widget handler timed out",
                error_code="widget_handler_timeout",
                error_kind="timeout",
                retryable=True,
                retry_after_seconds=1,
                tool_name=tool_name,
            ),
            ensure_ascii=False,
        )
    except Exception:
        logger.exception("widget handler %s raised unexpectedly", tool_name)
        from app.services.tool_error_contract import build_tool_error
        return json.dumps(
            build_tool_error(
                message="widget handler raised an unexpected error",
                error_code="widget_handler_exception",
                error_kind="internal",
                tool_name=tool_name,
            ),
            ensure_ascii=False,
        )

    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return json.dumps({"result": repr(result)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Policy helpers
# ---------------------------------------------------------------------------

async def _check_tool_policy(
    bot_id: str, tool_name: str, arguments: dict,
    *, correlation_id: str | None = None,
) -> Any:
    """Evaluate tool policy. Returns PolicyDecision or None (allow = skip overhead)."""
    from app.config import settings
    from app.agent.context import current_run_origin
    from app.db.engine import async_session
    from app.services.tool_policies import evaluate_tool_policy

    if not settings.TOOL_POLICY_ENABLED:
        return None

    # Session-scoped allow: if this tool was approved earlier in this conversation,
    # skip the full policy evaluation.  This is the key UX improvement — after one
    # approval, the user isn't asked again for the same tool in the same run.
    from app.agent.session_allows import is_session_allowed
    if is_session_allowed(correlation_id, tool_name):
        return None

    origin_kind = current_run_origin.get(None)

    async with async_session() as db:
        decision = await evaluate_tool_policy(
            db, bot_id, tool_name, arguments, origin_kind=origin_kind,
        )
    if decision.action == "allow":
        return None
    return decision


async def _create_approval_record(
    *,
    session_id: uuid.UUID | None,
    channel_id: uuid.UUID | None,
    bot_id: str,
    client_id: str | None,
    correlation_id: uuid.UUID | None,
    tool_name: str,
    tool_type: str,
    arguments: dict,
    policy_rule_id: str | None,
    reason: str | None,
    timeout: int,
    extra_metadata: dict | None = None,
    tool_call_id: uuid.UUID | None = None,
) -> str:
    """Create a ToolApproval DB record and return its ID as string."""
    from app.db.engine import async_session
    from app.db.models import ToolApproval

    # Resolve dispatch info from context vars for notification routing
    from app.agent.context import current_dispatch_type, current_dispatch_config
    dispatch_type = current_dispatch_type.get(None)
    dispatch_config = current_dispatch_config.get(None)

    approval = ToolApproval(
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        client_id=client_id,
        correlation_id=correlation_id,
        tool_name=tool_name,
        tool_type=tool_type,
        arguments=arguments,
        policy_rule_id=uuid.UUID(policy_rule_id) if policy_rule_id else None,
        reason=reason,
        status="pending",
        dispatch_type=dispatch_type,
        dispatch_metadata=dispatch_config,
        approval_metadata=extra_metadata or None,
        tool_call_id=tool_call_id,
        timeout_seconds=timeout,
    )
    async with async_session() as db:
        db.add(approval)
        await db.commit()
        await db.refresh(approval)
        approval_id = str(approval.id)

    # Fire-and-forget bus publish so renderers can prompt the user.
    if channel_id is not None:
        safe_create_task(_notify_approval_request(
            approval_id=approval_id,
            bot_id=bot_id,
            tool_name=tool_name,
            arguments=arguments,
            reason=reason,
            extra_metadata=extra_metadata,
            channel_id=channel_id,
        ))

    return approval_id


async def _create_approval_state(
    *,
    session_id: uuid.UUID | None,
    channel_id: uuid.UUID | None,
    bot_id: str,
    client_id: str | None,
    correlation_id: uuid.UUID | None,
    tool_name: str,
    tool_type: str,
    arguments: dict,
    iteration: int,
    policy_rule_id: str | None,
    reason: str | None,
    timeout: int,
    extra_metadata: dict | None = None,
) -> tuple[uuid.UUID, str]:
    """Atomically create the awaiting-approval ToolCall and ToolApproval rows."""
    from datetime import datetime, timezone

    from app.agent.context import current_dispatch_config, current_dispatch_type
    from app.db.models import ToolApproval, ToolCall

    dispatch_type = current_dispatch_type.get(None)
    dispatch_config = current_dispatch_config.get(None)
    tool_call_id = uuid.uuid4()
    approval_id = uuid.uuid4()
    now = time.time()

    async with async_session() as db:
        db.add(ToolCall(
            id=tool_call_id,
            session_id=session_id,
            client_id=client_id,
            bot_id=bot_id,
            tool_name=tool_name,
            tool_type=tool_type,
            server_name=None,
            iteration=iteration,
            arguments=arguments,
            surface=None,
            summary=None,
            result=None,
            error=None,
            duration_ms=None,
            correlation_id=correlation_id,
            created_at=datetime.fromtimestamp(now, timezone.utc),
            status="awaiting_approval",
            completed_at=None,
        ))
        # ToolApproval has an FK to ToolCall, but there is no ORM relationship
        # between these objects for SQLAlchemy to infer insert ordering. Flush
        # the call row first so Postgres can satisfy the FK on approval insert.
        await db.flush()
        db.add(ToolApproval(
            id=approval_id,
            session_id=session_id,
            channel_id=channel_id,
            bot_id=bot_id,
            client_id=client_id,
            correlation_id=correlation_id,
            tool_name=tool_name,
            tool_type=tool_type,
            arguments=arguments,
            policy_rule_id=uuid.UUID(policy_rule_id) if policy_rule_id else None,
            reason=reason,
            status="pending",
            dispatch_type=dispatch_type,
            dispatch_metadata=dispatch_config,
            approval_metadata=extra_metadata or None,
            tool_call_id=tool_call_id,
            timeout_seconds=timeout,
            created_at=datetime.fromtimestamp(now, timezone.utc),
        ))
        await db.commit()

    if channel_id is not None:
        safe_create_task(_notify_approval_request(
            approval_id=str(approval_id),
            bot_id=bot_id,
            tool_name=tool_name,
            tool_type=tool_type,
            arguments=arguments,
            reason=reason,
            extra_metadata=extra_metadata,
            channel_id=channel_id,
        ))

    return tool_call_id, str(approval_id)


async def _notify_approval_request(
    *,
    approval_id: str,
    bot_id: str,
    tool_name: str,
    tool_type: str | None = None,
    arguments: dict,
    reason: str | None,
    extra_metadata: dict | None = None,
    channel_id: uuid.UUID | None = None,
) -> None:
    """Publish an APPROVAL_REQUESTED event for renderer pickup."""
    if channel_id is None:
        logger.warning(
            "approval %s for tool %s has no channel_id, dropping notification",
            approval_id, tool_name,
        )
        return
    try:
        from app.agent.context import current_turn_id
        from app.domain.channel_events import ChannelEvent, ChannelEventKind
        from app.domain.payloads import ApprovalRequestedPayload
        from app.services.channel_events import publish_typed

        cap = (extra_metadata or {}).get("_capability")
        publish_typed(
            channel_id,
            ChannelEvent(
                channel_id=channel_id,
                kind=ChannelEventKind.APPROVAL_REQUESTED,
                payload=ApprovalRequestedPayload(
                    approval_id=approval_id,
                    bot_id=bot_id,
                    tool_name=tool_name,
                    arguments=dict(arguments or {}),
                    reason=reason,
                    capability=cap if isinstance(cap, dict) else None,
                    turn_id=current_turn_id.get(),
                    tool_type=tool_type,
                ),
            ),
        )
    except Exception:
        logger.exception("Failed to publish APPROVAL_REQUESTED for %s", approval_id)


def enforce_turn_aggregate_cap(
    results: list[ToolCallResult], cap_chars: int
) -> int:
    """Proportionally shrink the largest `result_for_llm` strings when the
    combined turn payload exceeds `cap_chars`.

    Complements the per-tool `TOOL_RESULT_HARD_CAP`: N parallel tools can each
    sit under the per-tool cap yet collectively blow the context budget. This
    runs after gather and before messages are appended to the turn.

    Returns the total chars trimmed (0 when cap is disabled or already under).
    The full untruncated output stays in the DB via `record_id` — identical
    recovery path as the per-tool hard cap.
    """
    # Defensive guard: tests sometimes swap `settings` for a MagicMock, in
    # which case missing attrs come back as mocks that pass `if cap_chars:`
    # but blow up in arithmetic. Require a real number.
    if not isinstance(cap_chars, (int, float)) or cap_chars <= 0 or not results:
        return 0

    # Track original bodies (stripped of any prior marker) and a running
    # trim-to length per result. Multi-pass 50%-per-iteration shrink converges
    # quickly for any overage while guaranteeing no single result is trimmed
    # to zero in one pass.
    _MARKER = "\n\n[Turn-aggregate cap:"

    def _strip_marker(s: str) -> str:
        return s.split(_MARKER, 1)[0] if _MARKER in s else s

    originals = [_strip_marker(r.result_for_llm or "") for r in results]
    current_lens = [len(s) for s in originals]

    total = sum(current_lens)
    if total <= cap_chars:
        return 0

    # Multi-pass shrink: each pass halves the biggest result until under cap
    # or nothing trimmable remains. Bounded at len(results) * 30 iterations
    # (≈2**-30 of original) — plenty to converge on any realistic input.
    max_iters = max(1, len(results) * 30)
    for _ in range(max_iters):
        total = sum(current_lens)
        if total <= cap_chars:
            break
        # Pick the biggest
        idx = max(range(len(current_lens)), key=lambda i: current_lens[i])
        if current_lens[idx] <= 1:
            break  # nothing more to trim
        overage = total - cap_chars
        take = min(current_lens[idx] // 2 or 1, overage)
        if take <= 0:
            break
        current_lens[idx] -= take

    trimmed = 0
    for i, r in enumerate(results):
        orig = originals[i]
        new_len = current_lens[i]
        if new_len >= len(orig):
            # Restore original (may have lost a stale marker during strip)
            r.result_for_llm = orig
            continue
        take = len(orig) - new_len
        trimmed += take
        r.result_for_llm = (
            orig[:new_len]
            + f"\n\n[Turn-aggregate cap: trimmed {take:,} chars — full output stored]"
        )
    return trimmed
