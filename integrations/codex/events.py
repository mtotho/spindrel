"""Map codex app-server notifications onto the Spindrel channel-event bus.

Pure functions. Mutates the dict + list kwargs the harness owns; never
touches a DB or async IO. All notification kind names come from
``schema.py`` constants.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.agent_harnesses.tool_results import build_diff_tool_result
from integrations.codex import schema
from integrations.codex.app_server import Notification
from integrations.sdk import ChannelEventEmitter

logger = logging.getLogger(__name__)


def translate_notification(
    note: Notification,
    *,
    emit: ChannelEventEmitter,
    tool_name_by_id: dict[str, str],
    final_text_parts: list[str],
    result_meta: dict[str, Any],
) -> None:
    """Translate one notification into emitter calls + result_meta updates."""
    method = note.method
    params = note.params or {}

    if method == schema.ITEM_AGENT_MESSAGE_DELTA:
        delta = _extract_text_delta(params)
        if delta:
            emit.token(delta)
            final_text_parts.append(delta)
        return

    if method == schema.ITEM_REASONING_DELTA:
        delta = _extract_text_delta(params)
        if delta:
            emit.thinking(delta)
        return

    if method == schema.ITEM_STARTED:
        item = params.get("item") or params
        kind = str(item.get("kind") or item.get("type") or "")
        if kind in {"commandExecution", "fileChange", "mcpToolCall", "dynamicTool", "toolCall"}:
            tool_name = str(
                item.get("name") or item.get("toolName") or item.get("command") or kind
            )
            tool_id = str(item.get("id") or item.get("itemId") or "")
            if tool_id:
                tool_name_by_id[tool_id] = tool_name
            emit.tool_start(
                tool_name=tool_name,
                tool_call_id=tool_id or None,
                arguments=item.get("input") or item.get("arguments") or {},
            )
        return

    if method == schema.ITEM_COMPLETED:
        item = params.get("item") or params
        kind = str(item.get("kind") or item.get("type") or "")
        if kind == "plan":
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                result_meta["native_plan_text"] = text.strip()
                if not final_text_parts:
                    final_text_parts.append(text.strip())
            return
        if kind and kind not in {"commandExecution", "fileChange", "mcpToolCall", "dynamicTool", "toolCall"}:
            return
        tool_id = str(item.get("id") or item.get("itemId") or "")
        tool_name = tool_name_by_id.get(tool_id, str(item.get("name") or item.get("kind") or "tool"))
        result_summary = _summarize_item_result(item)
        is_error = bool(item.get("isError") or item.get("is_error") or item.get("error"))
        envelope = None
        surface = None
        summary = None
        if kind == "fileChange":
            diff_body = (
                _extract_diff_body(item)
                or _pop_codex_diff_for_item(result_meta, tool_id)
            )
            if diff_body:
                path = _extract_file_path(item)
                label = result_summary or None
                envelope, summary = build_diff_tool_result(
                    tool_name=tool_name,
                    tool_call_id=tool_id or None,
                    diff_body=diff_body,
                    path=path,
                    label=label,
                )
                surface = "rich_result"
                result_summary = envelope["plain_body"]
        emit.tool_result(
            tool_name=tool_name,
            tool_call_id=tool_id or None,
            result_summary=result_summary,
            is_error=is_error,
            envelope=envelope,
            surface=surface,
            summary=summary,
        )
        return

    if method == schema.ITEM_FILE_CHANGE_OUTPUT_DELTA:
        _append_codex_file_change_delta(result_meta, params)
        return

    if method == schema.ITEM_COMMAND_OUTPUT_DELTA:
        # Per-command output streams. v1 does not emit a per-chunk bus event.
        return

    if method == schema.ITEM_PLAN_DELTA:
        delta = _extract_text_delta(params)
        if delta:
            result_meta.setdefault("native_plan_delta_parts", []).append(delta)
        return

    if method == schema.NOTIFICATION_PLAN_UPDATED:
        result_meta["plan"] = params.get("plan") or params
        return

    if method == schema.NOTIFICATION_DIFF_UPDATED:
        _record_codex_diff_update(result_meta, params)
        return

    if method == schema.NOTIFICATION_TOKEN_USAGE_UPDATED:
        result_meta["usage"] = normalize_token_usage(params)
        return

    if method == schema.NOTIFICATION_TURN_COMPLETED:
        turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
        result_meta["final_text"] = (
            (turn or {}).get("text")
            or params.get("text")
            or "".join(final_text_parts)
        )
        cost = (turn or {}).get("costUsd") or params.get("costUsd")
        if cost is not None:
            result_meta["total_cost_usd"] = cost
        usage = (turn or {}).get("usage") or params.get("usage")
        if usage:
            result_meta["usage"] = usage
        # turn.error is non-null on a failing turn even though the wrapping
        # method is still ``turn/completed``.
        turn_error = (turn or {}).get("error") or params.get("error")
        if turn_error:
            result_meta["is_error"] = True
            if isinstance(turn_error, dict):
                result_meta["error"] = turn_error.get("message") or str(turn_error)
            else:
                result_meta["error"] = str(turn_error)
        result_meta["completed"] = True
        return

    if method == schema.NOTIFICATION_ERROR:
        err = params.get("error") if isinstance(params.get("error"), dict) else params
        result_meta["is_error"] = True
        result_meta["error"] = (err or {}).get("message") or "codex error"
        return

    logger.debug("codex: unhandled notification %s", method)


def _extract_text_delta(params: dict[str, Any]) -> str:
    for key in ("delta", "text", "content"):
        value = params.get(key)
        if isinstance(value, str):
            return value
    return ""


def _summarize_item_result(item: dict[str, Any]) -> str:
    for key in ("summary", "text", "result"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    output = item.get("output")
    if isinstance(output, str):
        return output.strip()
    return ""


def _append_codex_file_change_delta(result_meta: dict[str, Any], params: dict[str, Any]) -> None:
    item_id = _item_id(params)
    delta = _extract_text_delta(params)
    if not item_id or not delta:
        return
    by_item = result_meta.setdefault("codex_file_change_deltas", {})
    if isinstance(by_item, dict):
        by_item[item_id] = str(by_item.get(item_id) or "") + delta


def _record_codex_diff_update(result_meta: dict[str, Any], params: dict[str, Any]) -> None:
    diff_body = _extract_diff_body(params)
    if not diff_body:
        return
    item_id = _item_id(params)
    if item_id:
        by_item = result_meta.setdefault("codex_diff_by_item_id", {})
        if isinstance(by_item, dict):
            by_item[item_id] = diff_body
    else:
        result_meta["codex_latest_diff"] = diff_body


def _pop_codex_diff_for_item(result_meta: dict[str, Any], item_id: str) -> str | None:
    if item_id:
        by_item = result_meta.get("codex_diff_by_item_id")
        if isinstance(by_item, dict):
            value = by_item.pop(item_id, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
        deltas = result_meta.get("codex_file_change_deltas")
        if isinstance(deltas, dict):
            value = deltas.pop(item_id, None)
            if isinstance(value, str) and _looks_like_diff(value):
                return value.strip()
    latest = result_meta.pop("codex_latest_diff", None)
    if isinstance(latest, str) and latest.strip():
        return latest.strip()
    return None


def _item_id(params: dict[str, Any]) -> str:
    for key in ("itemId", "item_id", "id"):
        value = params.get(key)
        if isinstance(value, str) and value:
            return value
    item = params.get("item")
    if isinstance(item, dict):
        for key in ("id", "itemId", "item_id"):
            value = item.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def _extract_file_path(item: dict[str, Any]) -> str | None:
    for key in ("path", "file", "filePath", "file_path"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("input", "arguments"):
        value = item.get(key)
        if isinstance(value, dict):
            nested = _extract_file_path(value)
            if nested:
                return nested
    return None


def _extract_diff_body(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if _looks_like_diff(stripped) else None
    if isinstance(value, list):
        for item in value:
            found = _extract_diff_body(item)
            if found:
                return found
        return None
    if not isinstance(value, dict):
        return None
    for key in (
        "diff",
        "patch",
        "unified_diff",
        "unifiedDiff",
        "diffText",
        "body",
        "output",
    ):
        found = _extract_diff_body(value.get(key))
        if found:
            return found
    for key in ("changes", "files", "fileChanges", "data", "item"):
        found = _extract_diff_body(value.get(key))
        if found:
            return found
    return None


def _looks_like_diff(value: str) -> bool:
    text = value.lstrip()
    return (
        "\n@@" in text
        or text.startswith("@@")
        or text.startswith("diff --git")
        or text.startswith("--- ")
        or "\n--- " in text
    )


def normalize_token_usage(params: dict[str, Any]) -> dict[str, Any]:
    """Normalize Codex camelCase token usage into Spindrel's usage shape."""
    raw = params.get("tokenUsage") or params.get("usage") or params
    if not isinstance(raw, dict):
        return {}
    total = raw.get("total")
    last = raw.get("last")
    if not isinstance(total, dict):
        normalized = dict(raw)
        window = normalized.get("modelContextWindow") or normalized.get("model_context_window")
        if isinstance(window, (int, float)):
            normalized["context_window_tokens"] = int(window)
        return normalized

    def _num(source: dict[str, Any], key: str) -> int | None:
        value = source.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
        return None

    normalized = {
        "input_tokens": _num(total, "inputTokens"),
        "output_tokens": _num(total, "outputTokens"),
        "reasoning_output_tokens": _num(total, "reasoningOutputTokens"),
        "cached_tokens": _num(total, "cachedInputTokens"),
        "total_tokens": _num(total, "totalTokens"),
    }
    window = raw.get("modelContextWindow")
    if isinstance(window, (int, float)):
        normalized["context_window_tokens"] = int(window)
    if isinstance(last, dict):
        normalized.update({
            "last_input_tokens": _num(last, "inputTokens"),
            "last_output_tokens": _num(last, "outputTokens"),
            "last_reasoning_output_tokens": _num(last, "reasoningOutputTokens"),
            "last_cached_tokens": _num(last, "cachedInputTokens"),
            "last_total_tokens": _num(last, "totalTokens"),
        })
    return {key: value for key, value in normalized.items() if value is not None}
