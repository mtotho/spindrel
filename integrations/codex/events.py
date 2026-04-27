"""Map codex app-server notifications onto the Spindrel channel-event bus.

Pure functions. Mutates the dict + list kwargs the harness owns; never
touches a DB or async IO. All notification kind names come from
``schema.py`` constants.
"""

from __future__ import annotations

import logging
from typing import Any

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
        tool_id = str(item.get("id") or item.get("itemId") or "")
        tool_name = tool_name_by_id.get(tool_id, str(item.get("name") or item.get("kind") or "tool"))
        result_summary = _summarize_item_result(item)
        is_error = bool(item.get("isError") or item.get("is_error") or item.get("error"))
        emit.tool_result(
            tool_name=tool_name,
            tool_call_id=tool_id or None,
            result_summary=result_summary,
            is_error=is_error,
        )
        return

    if method in (schema.ITEM_COMMAND_OUTPUT_DELTA, schema.ITEM_FILE_CHANGE_OUTPUT_DELTA):
        # Per-item output streams. v1 does not emit a per-chunk bus event;
        # callers may extend tool transcripts in a follow-up.
        return

    if method == schema.NOTIFICATION_PLAN_UPDATED:
        result_meta["plan"] = params.get("plan") or params
        return

    if method == schema.NOTIFICATION_TOKEN_USAGE_UPDATED:
        result_meta["usage"] = params.get("usage") or params
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
