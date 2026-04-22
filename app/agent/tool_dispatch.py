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
from app.agent.pending import CLIENT_TOOL_TIMEOUT, create_pending
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

    # --- Authorization check ---
    if allowed_tool_names is not None and name not in allowed_tool_names:
        _trace("✗ %s not authorized for bot %s", name, bot_id)
        _auth_err = f"Tool '{name}' is not available. It must be explicitly assigned to this bot."
        result_obj.result = json.dumps({"error": _auth_err})
        result_obj.result_for_llm = result_obj.result
        result_obj.tool_event = {"type": "tool_result", "tool": name, "tool_call_id": tool_call_id, "error": _auth_err}
        safe_create_task(_record_tool_call(
            session_id=session_id,
            client_id=client_id,
            bot_id=bot_id,
            tool_name=name,
            tool_type="unknown",
            server_name=None,
            iteration=iteration,
            arguments=json.loads(args or "{}") if args else {},
            result=result_obj.result,
            error=_auth_err,
            duration_ms=0,
            correlation_id=correlation_id,
            status="denied",
        ))
        return result_obj

    # --- Policy check ---
    if not skip_policy:
        try:
            _tc_args_for_policy: dict = {}
            try:
                _tc_args_for_policy = json.loads(args or "{}") if args else {}
                if not isinstance(_tc_args_for_policy, dict):
                    _tc_args_for_policy = {}
            except Exception:
                pass
            decision = await _check_tool_policy(
                bot_id, name, _tc_args_for_policy,
                correlation_id=str(correlation_id) if correlation_id else None,
            )
            if decision is not None:
                if decision.action == "deny":
                    _deny_err = f"Tool call denied by policy: {decision.reason or 'no reason'}"
                    result_obj.result = json.dumps({"error": _deny_err})
                    result_obj.result_for_llm = result_obj.result
                    result_obj.tool_event = {"type": "tool_result", "tool": name, "tool_call_id": tool_call_id, "error": f"Denied by policy: {decision.reason or 'no reason'}"}
                    _trace("✗ %s denied by policy (rule %s)", name, decision.rule_id)
                    safe_create_task(_record_tool_call(
                        session_id=session_id,
                        client_id=client_id,
                        bot_id=bot_id,
                        tool_name=name,
                        tool_type="unknown",
                        server_name=None,
                        iteration=iteration,
                        arguments=_tc_args_for_policy,
                        result=result_obj.result,
                        error=_deny_err,
                        duration_ms=0,
                        correlation_id=correlation_id,
                        status="denied",
                    ))
                    return result_obj
                elif decision.action == "require_approval":
                    # Determine tool type for the approval record
                    if is_client_tool(name):
                        _ap_type = "client"
                    elif is_mcp_tool(name):
                        _ap_type = "mcp"
                    else:
                        _ap_type = "local"
                    # Include tier in reason for UI display
                    _approval_reason = decision.reason
                    if decision.tier:
                        _approval_reason = f"[{decision.tier}] {decision.reason}"
                    # Pre-allocate the ToolCall row id so the approval row
                    # links to it (the re-dispatch path in loop.py reuses
                    # the row via ``existing_record_id``).
                    _tc_pending_id = uuid.uuid4()
                    safe_create_task(_start_tool_call(
                        id=_tc_pending_id,
                        session_id=session_id,
                        client_id=client_id,
                        bot_id=bot_id,
                        tool_name=name,
                        tool_type=_ap_type,
                        server_name=None,
                        iteration=iteration,
                        arguments=_tc_args_for_policy,
                        correlation_id=correlation_id,
                        status="awaiting_approval",
                    ))
                    approval_id = await _create_approval_record(
                        session_id=session_id,
                        channel_id=channel_id,
                        bot_id=bot_id,
                        client_id=client_id,
                        correlation_id=correlation_id,
                        tool_name=name,
                        tool_type=_ap_type,
                        arguments=_tc_args_for_policy,
                        policy_rule_id=decision.rule_id,
                        reason=_approval_reason,
                        timeout=decision.timeout,
                        tool_call_id=_tc_pending_id,
                    )
                    result_obj.needs_approval = True
                    result_obj.approval_id = approval_id
                    result_obj.approval_timeout = decision.timeout
                    result_obj.approval_reason = _approval_reason
                    result_obj.record_id = _tc_pending_id
                    result_obj.result_for_llm = json.dumps({"status": "pending_approval", "reason": _approval_reason})
                    result_obj.tool_event = {"type": "tool_result", "tool": name, "tool_call_id": tool_call_id, "pending_approval": True}
                    _trace("⏳ %s requires approval (%s)", name,
                           f"tier={decision.tier}" if decision.tier else f"rule {decision.rule_id}")
                    return result_obj
        except Exception:
            logger.exception("Policy check failed for %s — denying by default", name)
            _policy_err = "Tool call denied: policy evaluation error. Please retry."
            result_obj.result = json.dumps({"error": _policy_err})
            result_obj.result_for_llm = result_obj.result
            result_obj.tool_event = {"type": "tool_result", "tool": name, "tool_call_id": tool_call_id, "error": _policy_err}
            return result_obj

    _pre_hook_type = "local"
    if is_client_tool(name):
        _pre_hook_type = "client"
    elif is_mcp_tool(name):
        _pre_hook_type = "mcp"
    elif is_widget_handler_tool_name(name):
        _pre_hook_type = "widget"

    _safety_tier = None
    if _pre_hook_type == "local":
        from app.tools.registry import get_tool_safety_tier

        _safety_tier = get_tool_safety_tier(name)

    if session_id is not None:
        try:
            from app.services.session_plan_mode import plan_mode_tool_denial_reason

            _session = await _load_session_for_plan_mode(session_id)
            if _session is not None:
                _plan_mode_err = plan_mode_tool_denial_reason(
                    _session,
                    tool_name=name,
                    tool_kind=_pre_hook_type,
                    safety_tier=_safety_tier,
                )
                if _plan_mode_err:
                    result_obj.result = json.dumps({"error": _plan_mode_err})
                    result_obj.result_for_llm = result_obj.result
                    result_obj.tool_event = {"type": "tool_result", "tool": name, "tool_call_id": tool_call_id, "error": _plan_mode_err}
                    safe_create_task(_record_tool_call(
                        session_id=session_id,
                        client_id=client_id,
                        bot_id=bot_id,
                        tool_name=name,
                        tool_type=_pre_hook_type,
                        server_name=None,
                        iteration=iteration,
                        arguments=json.loads(args or "{}") if args else {},
                        result=result_obj.result,
                        error=_plan_mode_err,
                        duration_ms=0,
                        correlation_id=correlation_id,
                        status="denied",
                    ))
                    return result_obj
        except Exception:
            logger.exception("Plan-mode guard failed for %s — denying by default", name)
            _plan_guard_err = "Tool call denied: unable to validate plan-mode restrictions. Please retry."
            result_obj.result = json.dumps({"error": _plan_guard_err})
            result_obj.result_for_llm = result_obj.result
            result_obj.tool_event = {"type": "tool_result", "tool": name, "tool_call_id": tool_call_id, "error": _plan_guard_err}
            return result_obj

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
        safe_create_task(_start_tool_call(
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
        ))

    # Fire before_tool_execution lifecycle hook (after auth/policy checks pass)
    from app.agent.hooks import fire_hook, HookContext
    safe_create_task(fire_hook("before_tool_execution", HookContext(
        bot_id=bot_id, session_id=session_id, channel_id=channel_id,
        client_id=client_id, correlation_id=correlation_id,
        extra={
            "tool_name": name,
            "tool_type": _pre_hook_type,
            "args": args,
            "iteration": iteration + 1,
        },
    )))

    t0 = time.monotonic()
    _tc_type = "local"
    _tc_server: str | None = None

    # The local / MCP branches build a coroutine and then run it under a
    # single wall-clock guard below. Client tools already have their own
    # CLIENT_TOOL_TIMEOUT wait_for (long-poll pattern), so they're handled
    # inline and never fall into the shared guard.
    _tool_coro = None

    if is_client_tool(name):
        _tc_type = "client"
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
            logger.warning("Client tool %s timed out (request %s)", name, request_id)
            result = json.dumps({"error": "Client did not respond in time"})
    elif is_local_tool(name):
        _tc_type = "local"
        if name in ("update_persona", "append_to_persona", "edit_persona"):
            _tool_coro = call_persona_tool(name, args or "{}", bot_id)
        else:
            _tool_coro = call_local_tool(name, args)
    elif is_mcp_tool(name):
        _tc_type = "mcp"
        _tc_server = get_mcp_server_for_tool(name)
        _tool_coro = call_mcp_tool(name, args)
    elif is_widget_handler_tool_name(name):
        _tc_type = "widget"
        _tool_coro = _call_widget_handler_tool(name, args, bot_id, channel_id)
    else:
        result = json.dumps({"error": f"Unknown tool: {name}"})

    if _tool_coro is not None:
        try:
            result = await asyncio.wait_for(
                _tool_coro, timeout=settings.TOOL_DISPATCH_TIMEOUT
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Tool %s exceeded %.0fs wall-clock — cancelled by dispatch guard",
                name, settings.TOOL_DISPATCH_TIMEOUT,
            )
            result = json.dumps({
                "error": (
                    f"Tool {name} exceeded {settings.TOOL_DISPATCH_TIMEOUT:.0f}s "
                    "wall-clock and was cancelled. Try a different approach."
                ),
            })

    _tc_duration = int((time.monotonic() - t0) * 1000)
    result_obj.duration_ms = _tc_duration

    # Detect tool-reported errors so the row gets status='error' on UPDATE
    _tc_error: str | None = None
    try:
        _parsed_r = json.loads(result)
        if isinstance(_parsed_r, dict) and "error" in _parsed_r:
            _tc_error = str(_parsed_r["error"])
    except Exception:
        pass

    # Redact known secrets from the raw result before storage
    from app.services.secret_registry import redact as _redact_secrets
    result_obj.result = _redact_secrets(result)

    # Extract embedded client_action / injected_images / _envelope.
    # The _envelope opt-in is additive — tools may pair it with client_action.
    # When present, the dispatcher lifts it onto result_obj.envelope; when
    # absent, _build_default_envelope (called after summarization) builds a
    # text/plain envelope from the redacted result so legacy tools render
    # in the existing badge UI without per-tool changes.
    result_for_llm = result
    _envelope_optin: dict | None = None
    try:
        parsed_tool = json.loads(result_for_llm)
        if isinstance(parsed_tool, dict):
            if isinstance(parsed_tool.get("_envelope"), dict):
                _envelope_optin = parsed_tool["_envelope"]
                # Fall through to client_action / injected_images so tools can
                # combine an envelope with the existing extension points.
            if "client_action" in parsed_tool:
                result_obj.embedded_client_action = parsed_tool["client_action"]
                result_for_llm = parsed_tool.get("message", "Done.")
            elif "injected_images" in parsed_tool:
                result_obj.injected_images = parsed_tool["injected_images"]
                result_for_llm = parsed_tool.get("message", "Image loaded for analysis.")
            elif _envelope_optin is not None:
                # Tool only sent an envelope — surface its plain_body to the LLM
                # so the bot has a short, readable hand-off without the full
                # rendered body bloating the context window. The full untruncated
                # body still flows to the bot via the result_for_llm path below
                # for tools that want their LLM-side answer intact (we only
                # take this branch when the tool didn't also set "message" or
                # "client_action"/"injected_images").
                _llm_text = parsed_tool.get("llm")
                if isinstance(_llm_text, str) and _llm_text:
                    result_for_llm = _llm_text
    except (json.JSONDecodeError, TypeError):
        pass

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

    # Build the user-visible envelope from the redacted result. Envelope opt-in
    # via {"_envelope": {...}} from the tool takes priority; otherwise we
    # construct a text/plain envelope so the existing badge UI keeps working.
    # The envelope body goes through redaction here because the opt-in dict
    # is lifted from the unredacted parse upstream.
    if _envelope_optin is not None:
        # Redact the body field in-place before building. Other fields
        # (content_type, display, plain_body) are short and structural —
        # plain_body still goes through redaction since tools may put
        # snippets there.
        _envelope_optin = dict(_envelope_optin)
        if isinstance(_envelope_optin.get("body"), str):
            _envelope_optin["body"] = _redact_secrets(_envelope_optin["body"])
        if isinstance(_envelope_optin.get("plain_body"), str):
            _envelope_optin["plain_body"] = _redact_secrets(_envelope_optin["plain_body"])
        result_obj.envelope = _build_envelope_from_optin(_envelope_optin, result_obj.result)
    else:
        # Check for widget template (any tool with a declared widget template)
        _widget_envelope: ToolResultEnvelope | None = None
        from app.services.widget_templates import apply_widget_template, get_state_poll_config
        _widget_envelope = apply_widget_template(name, result_obj.result)
        if _widget_envelope is not None:
            result_obj.envelope = _widget_envelope
        else:
            result_obj.envelope = _build_default_envelope(result_obj.result)

    # Stamp the tool name on every envelope — renderers that show a
    # compact tool-badge (e.g. Slack `:wrench: *get_weather*`) read it
    # via ``compact_dict()``. Set here (after both the opt-in and
    # default/widget branches) so all paths carry it uniformly.
    result_obj.envelope.tool_name = name

    if _envelope_optin is None:
        # A bot-triggered mutation may have changed state that a pinned widget
        # is tracking. Drop the cached poll result so the next refresh hits
        # the real service instead of serving stale data.
        _poll_cfg = get_state_poll_config(name)
        if _poll_cfg:
            try:
                from app.routers.api_v1_widget_actions import invalidate_poll_cache_for
                invalidate_poll_cache_for(_poll_cfg)
            except Exception:
                logger.debug("poll-cache invalidation skipped", exc_info=True)

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

    safe_create_task(_complete_tool_call(
        _tc_record_id,
        tool_name=name,
        arguments=_tc_args_pre,
        result=result_obj.result,  # use redacted result
        error=_tc_error,
        duration_ms=_tc_duration,
        status="error" if _tc_error else "done",
        store_full_result=_store_full,
        envelope=result_obj.envelope.compact_dict(),
    ))

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

    # Build tool_event — use redacted result to avoid leaking secrets
    # in SSE events, log output, or memory previews
    _redacted_result = result_obj.result
    tool_event: dict[str, Any] = {"type": "tool_result", "tool": name, "tool_call_id": tool_call_id}
    if _was_summarized:
        tool_event["summarized"] = True
    try:
        parsed = json.loads(_redacted_result)
        if isinstance(parsed, dict) and "error" in parsed:
            err = parsed["error"]
            logger.warning("Tool %s returned error: %s", name, err)
            tool_event["error"] = err
            _trace("← %s error: %s", name, str(err)[:80])
        else:
            _trace("← %s (%d chars)", name, len(result_for_llm))
    except (json.JSONDecodeError, TypeError):
        _trace("← %s (%d chars)", name, len(result_for_llm))
    # Attach the rendered envelope so SSE consumers (web UI) can pick a
    # mimetype-keyed renderer instead of just showing the tool name.
    tool_event["envelope"] = result_obj.envelope.compact_dict()
    from app.services.tool_presentation import derive_tool_presentation
    try:
        _tool_args = json.loads(args) if args else {}
    except (json.JSONDecodeError, TypeError):
        _tool_args = {}
    _surface, _summary = derive_tool_presentation(
        tool_name=name,
        arguments=_tool_args,
        result=result_obj.result,
        envelope=tool_event["envelope"],
        error=tool_event.get("error"),
    )
    tool_event["surface"] = _surface
    tool_event["summary"] = _summary
    result_obj.tool_event = tool_event

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
        return json.dumps({
            "error": (
                f"widget handler {tool_name!r} could not be resolved — "
                "the pin may have been removed or moved to a dashboard you can't see."
            )
        }, ensure_ascii=False)

    pin, handler_name, _tier = resolved
    try:
        result = await invoke_action(pin, handler_name, args)
    except (FileNotFoundError, KeyError, ValueError, PermissionError) as exc:
        logger.info(
            "widget handler %s dispatch failed (%s): %s",
            tool_name, type(exc).__name__, exc,
        )
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    except asyncio.TimeoutError:
        logger.warning("widget handler %s exceeded handler timeout", tool_name)
        return json.dumps({"error": "widget handler timed out"}, ensure_ascii=False)
    except Exception:
        logger.exception("widget handler %s raised unexpectedly", tool_name)
        return json.dumps({"error": "widget handler raised an unexpected error"}, ensure_ascii=False)

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


async def _notify_approval_request(
    *,
    approval_id: str,
    bot_id: str,
    tool_name: str,
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
