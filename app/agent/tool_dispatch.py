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
from app.agent.recording import _record_tool_call, _record_trace_event
from app.agent.tracing import _trace
from app.agent.pending import CLIENT_TOOL_TIMEOUT, create_pending
from app.config import settings
from app.tools.client_tools import is_client_tool
from app.tools.mcp import call_mcp_tool, get_mcp_server_for_tool, is_mcp_tool, resolve_mcp_tool_name
from app.tools.registry import call_local_tool, is_local_tool
from app.tools.local.persona import call_persona_tool

logger = logging.getLogger(__name__)


# Maximum bytes of envelope body that travel inline on SSE / Message metadata.
# Bodies larger than this are dropped from the inline envelope, the envelope is
# marked truncated, and the UI fetches the full body lazily via the
# session-scoped tool-call result endpoint. Tunable via settings.
INLINE_BODY_CAP_BYTES = 4096

# Default short summary length for envelope.plain_body.
PLAIN_BODY_CAP_CHARS = 200


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


def _build_default_envelope(text: str) -> ToolResultEnvelope:
    """Build a default envelope from raw tool result text.

    Used for tools that don't opt into the structured envelope. Detects
    content type from the text shape:

    - Markdown (headings, links, lists, emphasis) → ``text/markdown`` + inline
    - JSON (valid parse) → ``application/json`` + badge
    - Plain text fallback → ``text/plain`` + badge

    Caps body at INLINE_BODY_CAP_BYTES and sets the truncated flag if the
    underlying text is larger.
    """
    text = text or ""
    content_type, display = _detect_content_type(text)
    byte_size = len(text.encode("utf-8"))
    truncated = len(text) > INLINE_BODY_CAP_BYTES
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

    # JSON detection — must be a valid object or array.
    if stripped[0] in "{[":
        try:
            json.loads(stripped)
            return "application/json", "badge"
        except (json.JSONDecodeError, ValueError):
            pass

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


def _build_envelope_from_optin(envelope_data: dict, raw_text: str) -> ToolResultEnvelope:
    """Build an envelope from a tool's ``_envelope`` opt-in payload.

    Truncates ``body`` if it exceeds the inline cap and sets truncated/byte_size
    accordingly. ``raw_text`` is the redacted full result string that lives on
    the persisted ``tool_calls`` row — used to compute byte_size when the
    envelope omits its own ``body``.
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
    if len(body_str) > INLINE_BODY_CAP_BYTES:
        body_str = None
        truncated = True

    return ToolResultEnvelope(
        content_type=content_type,
        body=body_str,
        plain_body=plain_body,
        display=display,  # type: ignore[arg-type]
        truncated=truncated,
        byte_size=byte_size,
    )


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
        result_obj.tool_event = {"type": "tool_result", "tool": name, "error": _auth_err}
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
                    result_obj.tool_event = {"type": "tool_result", "tool": name, "error": f"Denied by policy: {decision.reason or 'no reason'}"}
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
                    )
                    result_obj.needs_approval = True
                    result_obj.approval_id = approval_id
                    result_obj.approval_timeout = decision.timeout
                    result_obj.approval_reason = _approval_reason
                    result_obj.result_for_llm = json.dumps({"status": "pending_approval", "reason": _approval_reason})
                    result_obj.tool_event = {"type": "tool_result", "tool": name, "pending_approval": True}
                    _trace("⏳ %s requires approval (%s)", name,
                           f"tier={decision.tier}" if decision.tier else f"rule {decision.rule_id}")
                    return result_obj
        except Exception:
            logger.exception("Policy check failed for %s — denying by default", name)
            _policy_err = "Tool call denied: policy evaluation error. Please retry."
            result_obj.result = json.dumps({"error": _policy_err})
            result_obj.result_for_llm = result_obj.result
            result_obj.tool_event = {"type": "tool_result", "tool": name, "error": _policy_err}
            return result_obj

        # --- Capability activation approval ---
        if (
            name == "activate_capability"
            and settings.CAPABILITY_APPROVAL == "required"
            and correlation_id is not None
        ):
            try:
                _cap_args = json.loads(args or "{}") if isinstance(args, str) else args
                _cap_id = (_cap_args.get("id") or "").strip()
            except Exception:
                _cap_id = ""

            if _cap_id:
                from app.agent.capability_session import is_approved as _cap_is_approved
                from app.agent.carapaces import get_carapace
                from app.agent.bots import get_bot

                _bot_cfg = get_bot(bot_id)
                _pinned = set(_bot_cfg.carapaces) if _bot_cfg and _bot_cfg.carapaces else set()

                if _cap_id not in _pinned and not _cap_is_approved(str(correlation_id), _cap_id):
                    _cap_data = get_carapace(_cap_id)
                    _cap_name = _cap_data.get("name", _cap_id) if _cap_data else _cap_id
                    _cap_desc = (_cap_data.get("description") or "") if _cap_data else ""
                    _cap_reason = f"Bot wants to activate '{_cap_name}' capability"
                    _cap_meta = {
                        "_capability": {
                            "id": _cap_id,
                            "name": _cap_name,
                            "description": _cap_desc,
                            "tools_count": len(_cap_data.get("local_tools") or []) if _cap_data else 0,
                        },
                    }
                    approval_id = await _create_approval_record(
                        session_id=session_id,
                        channel_id=channel_id,
                        bot_id=bot_id,
                        client_id=client_id,
                        correlation_id=correlation_id,
                        tool_name=name,
                        tool_type="local",
                        arguments=_tc_args_for_policy,
                        policy_rule_id=None,
                        reason=_cap_reason,
                        timeout=300,
                        extra_metadata=_cap_meta,
                    )
                    result_obj.needs_approval = True
                    result_obj.approval_id = approval_id
                    result_obj.approval_timeout = 300
                    result_obj.approval_reason = _cap_reason
                    result_obj.tool_event = {
                        "type": "tool_result", "tool": name, "pending_approval": True,
                        "_capability": _cap_meta["_capability"],
                    }
                    result_obj.result_for_llm = json.dumps({"status": "pending_approval", "reason": _cap_reason})
                    _trace("⏳ %s requires capability approval (%s)", name, _cap_id)
                    return result_obj

    # Determine tool type for hook data
    if is_client_tool(name):
        _pre_hook_type = "client"
    elif is_mcp_tool(name):
        _pre_hook_type = "mcp"
    else:
        _pre_hook_type = "local"

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

    # Record tool call
    _tc_error: str | None = None
    try:
        _parsed_r = json.loads(result)
        if isinstance(_parsed_r, dict) and "error" in _parsed_r:
            _tc_error = str(_parsed_r["error"])
    except Exception:
        pass
    try:
        _tc_args = json.loads(args or "{}")
        if not isinstance(_tc_args, dict):
            _tc_args = {}
    except Exception:
        _tc_args = {}

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

    # Pre-generate tool call ID so we can reference it in the retrieval hint.
    # Store full result for any result large enough to be pruned later, so the
    # retrieval pointer in subsequent turns actually works.
    _store_full = (
        _will_summarize
        or _orig_len > settings.CONTEXT_PRUNING_MIN_LENGTH
        or result_obj.envelope.truncated
    )
    _tc_record_id = uuid.uuid4() if _store_full else None
    if result_obj.envelope.truncated and _tc_record_id is not None:
        result_obj.envelope.record_id = _tc_record_id

    # Record tool call (store full result so retrieval pointers work)
    safe_create_task(_record_tool_call(
        id=_tc_record_id,
        session_id=session_id,
        client_id=client_id,
        bot_id=bot_id,
        tool_name=name,
        tool_type=_tc_type,
        server_name=_tc_server,
        iteration=iteration,
        arguments=_tc_args,
        result=result_obj.result,  # use redacted result
        error=_tc_error,
        duration_ms=_tc_duration,
        correlation_id=correlation_id,
        store_full_result=_store_full,
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
    tool_event: dict[str, Any] = {"type": "tool_result", "tool": name}
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
    result_obj.tool_event = tool_event

    return result_obj


# ---------------------------------------------------------------------------
# Policy helpers
# ---------------------------------------------------------------------------

async def _check_tool_policy(
    bot_id: str, tool_name: str, arguments: dict,
    *, correlation_id: str | None = None,
) -> Any:
    """Evaluate tool policy. Returns PolicyDecision or None (allow = skip overhead)."""
    from app.config import settings
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

    async with async_session() as db:
        decision = await evaluate_tool_policy(db, bot_id, tool_name, arguments)
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
