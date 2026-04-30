"""Shared agent-facing tool error contract.

The legacy contract is a top-level ``error`` string.  Keep that stable and add
machine-actionable fields beside it so agents and review surfaces can classify
failures without regexing prose.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any


TOOL_ERROR_CONTRACT_VERSION = "tool-error.v1"

TOOL_ERROR_FIELDS = (
    "success",
    "error",
    "error_code",
    "error_kind",
    "retryable",
    "retry_after_seconds",
    "fallback",
)

ERROR_KIND_DESCRIPTIONS: dict[str, str] = {
    "validation": "The request shape or arguments are invalid; fix inputs before retrying.",
    "not_found": "The requested resource or tool does not exist.",
    "forbidden": "The caller lacks permission or the operation is blocked by policy.",
    "approval_required": "A human approval or machine-control lease is required before execution.",
    "config_missing": "Required bot, API, integration, or runtime configuration is missing.",
    "conflict": "The target state conflicts with this operation.",
    "rate_limited": "The target is throttling requests; retry after backoff.",
    "timeout": "The call exceeded a timeout; retry may succeed.",
    "unavailable": "The target service is temporarily unavailable.",
    "internal": "The platform or tool hit an unexpected error.",
    "unknown": "The failure could not be classified.",
}

RETRYABLE_ERROR_KINDS = frozenset({"rate_limited", "timeout", "unavailable"})
BENIGN_REVIEW_ERROR_KINDS = frozenset({
    "validation",
    "not_found",
    "forbidden",
    "approval_required",
    "config_missing",
    "conflict",
})


@dataclass(frozen=True)
class ToolErrorEnvelope:
    error: str
    error_code: str
    error_kind: str
    retryable: bool = False
    retry_after_seconds: int | None = None
    fallback: str | None = None

    def as_payload(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "success": False,
            "error": self.error,
            "error_code": self.error_code,
            "error_kind": self.error_kind,
            "retryable": self.retryable,
            "retry_after_seconds": self.retry_after_seconds,
            "fallback": self.fallback,
        }
        if extra:
            payload.update({key: value for key, value in extra.items() if key not in payload})
        return payload


def tool_error_contract() -> dict[str, Any]:
    return {
        "version": TOOL_ERROR_CONTRACT_VERSION,
        "fields": list(TOOL_ERROR_FIELDS),
        "retryable_kinds": sorted(RETRYABLE_ERROR_KINDS),
        "benign_review_kinds": sorted(BENIGN_REVIEW_ERROR_KINDS),
        "error_kind_descriptions": dict(sorted(ERROR_KIND_DESCRIPTIONS.items())),
        "backward_compatibility": "The top-level error string remains present for existing callers.",
    }


def _normalize_error_code(value: str | None, *, fallback: str = "tool_error") -> str:
    text = (value or fallback).strip().lower()
    out = []
    previous_sep = False
    for ch in text:
        if ch.isalnum():
            out.append(ch)
            previous_sep = False
        elif not previous_sep:
            out.append("_")
            previous_sep = True
    return "".join(out).strip("_") or fallback


def infer_error_kind(error_code: str | None = None, message: str | None = None) -> str:
    text = f"{error_code or ''} {message or ''}".lower()
    if any(token in text for token in ("rate_limit", "rate limited", "429", "too many requests")):
        return "rate_limited"
    if any(token in text for token in ("timeout", "timed out", "wall-clock", "did not respond in time")):
        return "timeout"
    if any(token in text for token in ("unavailable", "bad gateway", "gateway", "503", "502", "504", "service down")):
        return "unavailable"
    if any(token in text for token in ("approval", "local_control_required", "lease", "machine access required")):
        return "approval_required"
    if any(token in text for token in ("not configured", "no bot context", "no api key", "missing api", "missing required settings")):
        return "config_missing"
    if any(token in text for token in ("permission", "forbidden", "unauthorized", "not authorized", "access", "policy")):
        return "forbidden"
    if any(token in text for token in ("not found", "unknown tool", "missing resource", "404")):
        return "not_found"
    if any(token in text for token in ("invalid", "validation", "required", "must ", "malformed", "bad request", "422", "400")):
        return "validation"
    if any(token in text for token in ("conflict", "already exists", "409", "locked")):
        return "conflict"
    if any(token in text for token in ("internal", "unexpected", "exception", "failed")):
        return "internal"
    return "unknown"


def default_fallback_for_kind(error_kind: str, *, tool_name: str | None = None) -> str | None:
    target = f" for {tool_name}" if tool_name else ""
    if error_kind == "validation":
        return f"Fix the arguments{target} and retry."
    if error_kind == "not_found":
        if tool_name:
            return (
                f"Do not retry {tool_name} under invented aliases. Use only exact "
                "tool names listed by list_agent_capabilities or loaded with "
                "get_tool_info; if this name is absent, report the missing "
                "capability/tool surface."
            )
        return (
            "Refresh the available surface with list_agent_capabilities or "
            "get_tool_info, then use only exact listed tool names. Do not invent "
            "alternate workspace/file helper names; report the missing capability "
            "if the needed tool is absent."
        )
    if error_kind == "forbidden":
        return "Ask for the required permission or choose an allowed tool."
    if error_kind == "approval_required":
        return "Request or wait for the required human approval or machine-control lease."
    if error_kind == "config_missing":
        return "Run run_agent_doctor and ask an admin to complete the missing setup."
    if error_kind == "conflict":
        return "Refresh current state, resolve the conflict, then retry."
    if error_kind == "rate_limited":
        return "Wait for retry_after_seconds when provided, then retry with backoff."
    if error_kind == "timeout":
        return "Retry once with narrower scope, then choose a different approach."
    if error_kind == "unavailable":
        return "Retry later or use an alternate integration/API path."
    if error_kind == "internal":
        return "Capture the tool call id and surface this as a platform/tool bug if it repeats."
    return None


def parse_retry_after(value: str | int | float | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return max(0, int(value))
    text = str(value).strip()
    if not text:
        return None
    try:
        return max(0, int(float(text)))
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = (dt - datetime.now(timezone.utc)).total_seconds()
        return max(0, int(delta))
    except (TypeError, ValueError, OverflowError):
        return None


def build_tool_error(
    *,
    message: str,
    error_code: str | None = None,
    error_kind: str | None = None,
    retryable: bool | None = None,
    retry_after_seconds: int | None = None,
    fallback: str | None = None,
    tool_name: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    code = _normalize_error_code(error_code, fallback="tool_error")
    kind = error_kind or infer_error_kind(code, message)
    is_retryable = kind in RETRYABLE_ERROR_KINDS if retryable is None else bool(retryable)
    envelope = ToolErrorEnvelope(
        error=str(message),
        error_code=code,
        error_kind=kind,
        retryable=is_retryable,
        retry_after_seconds=retry_after_seconds,
        fallback=fallback or default_fallback_for_kind(kind, tool_name=tool_name),
    )
    return envelope.as_payload(extra)


def enrich_tool_error_payload(
    payload: dict[str, Any],
    *,
    default_code: str = "tool_error",
    default_kind: str | None = None,
    retryable: bool | None = None,
    retry_after_seconds: int | None = None,
    fallback: str | None = None,
    tool_name: str | None = None,
) -> dict[str, Any]:
    if not payload.get("error"):
        return payload
    message = str(payload.get("error"))
    error_code = str(payload.get("error_code") or default_code)
    error_kind = str(payload.get("error_kind") or default_kind or infer_error_kind(error_code, message))
    if retryable is None:
        retryable_value = payload.get("retryable")
        retryable = bool(retryable_value) if retryable_value is not None else error_kind in RETRYABLE_ERROR_KINDS
    if retry_after_seconds is None:
        retry_after_seconds = parse_retry_after(payload.get("retry_after_seconds"))
    fallback = str(payload.get("fallback") or fallback or default_fallback_for_kind(error_kind, tool_name=tool_name) or "")
    enriched = dict(payload)
    enriched.update({
        "success": False,
        "error_code": _normalize_error_code(error_code),
        "error_kind": error_kind,
        "retryable": retryable,
        "retry_after_seconds": retry_after_seconds,
        "fallback": fallback or None,
    })
    return enriched


def error_fields_from_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict) or not payload.get("error"):
        return {
            "error_code": None,
            "error_kind": None,
            "retryable": None,
            "retry_after_seconds": None,
            "fallback": None,
        }
    enriched = enrich_tool_error_payload(payload)
    return {
        "error_code": enriched.get("error_code"),
        "error_kind": enriched.get("error_kind"),
        "retryable": enriched.get("retryable"),
        "retry_after_seconds": enriched.get("retry_after_seconds"),
        "fallback": enriched.get("fallback"),
    }


def error_for_http_status(
    status_code: int,
    *,
    message: str | None = None,
    retry_after: str | int | float | None = None,
) -> dict[str, Any]:
    retry_after_seconds = parse_retry_after(retry_after)
    if status_code == 429:
        kind = "rate_limited"
        retryable = True
    elif status_code >= 500:
        kind = "unavailable"
        retryable = True
    elif status_code == 404:
        kind = "not_found"
        retryable = False
    elif status_code in (401, 403):
        kind = "forbidden"
        retryable = False
    elif status_code == 409:
        kind = "conflict"
        retryable = False
    else:
        kind = "validation"
        retryable = False
    return build_tool_error(
        message=message or f"HTTP {status_code}",
        error_code=f"http_{status_code}",
        error_kind=kind,
        retryable=retryable,
        retry_after_seconds=retry_after_seconds,
    )
