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
from integrations.sdk import ChannelEventEmitter, build_diff_tool_result, build_text_tool_result

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
        if kind in schema.TOOL_ITEM_KINDS:
            tool_name = _tool_name_for_item(item, kind)
            tool_id = str(item.get("id") or item.get("itemId") or "")
            if tool_id:
                tool_name_by_id[tool_id] = tool_name
                if kind == schema.ITEM_KIND_COMMAND_EXECUTION:
                    _record_codex_command_item(result_meta, tool_id, tool_name)
                elif kind == schema.ITEM_KIND_FILE_CHANGE:
                    _record_codex_file_change_item(result_meta, tool_id, item)
            emit.tool_start(
                tool_name=tool_name,
                tool_call_id=tool_id or None,
                arguments=_tool_arguments_for_item(item, kind),
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
        if kind and kind not in schema.TOOL_ITEM_KINDS:
            return
        tool_id = str(item.get("id") or item.get("itemId") or "")
        tool_name = tool_name_by_id.get(tool_id, _tool_name_for_item(item, kind or "tool"))
        if kind == schema.ITEM_KIND_COMMAND_EXECUTION and tool_id:
            _record_codex_command_item(result_meta, tool_id, tool_name)
        elif kind == schema.ITEM_KIND_FILE_CHANGE and tool_id:
            _record_codex_file_change_item(result_meta, tool_id, item)
        result_summary = _summarize_item_result(item)
        is_error = bool(item.get("isError") or item.get("is_error") or item.get("error"))
        envelope = None
        surface = None
        summary = None
        execution_surface_text = ""
        if kind == schema.ITEM_KIND_FILE_CHANGE:
            diff_body = (
                _extract_diff_body(item)
                or _pop_codex_diff_for_item(result_meta, tool_id)
            )
            if diff_body:
                path = _extract_file_path(item) or _pop_codex_file_change_path(result_meta, tool_id)
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
        elif kind == schema.ITEM_KIND_COMMAND_EXECUTION:
            command_output = _pop_codex_command_output_for_item(result_meta, tool_id)
            if command_output:
                if looks_like_execution_surface_failure(command_output):
                    execution_surface_text = command_output
                envelope, summary = build_text_tool_result(
                    tool_name=tool_name,
                    tool_call_id=tool_id or None,
                    body=command_output,
                    label=result_summary or None,
                )
                surface = "rich_result"
                result_summary = result_summary or envelope["plain_body"]
                _mark_codex_command_result_enveloped(result_meta, tool_id)
            else:
                _record_codex_command_without_envelope(result_meta, tool_id)
        elif kind == schema.ITEM_KIND_COLLAB_TOOL_CALL:
            summary = _collab_summary(item, result_summary)
            result_summary = result_summary or summary["label"]
        elif kind == schema.ITEM_KIND_WEB_SEARCH:
            summary = _web_search_summary(item, result_summary)
            result_summary = result_summary or summary["label"]
        elif kind == schema.ITEM_KIND_IMAGE_VIEW:
            summary = _image_view_summary(item, result_summary)
            result_summary = result_summary or summary["label"]
        elif kind in {
            schema.ITEM_KIND_MCP_TOOL_CALL,
            schema.ITEM_KIND_DYNAMIC_TOOL,
            schema.ITEM_KIND_TOOL_CALL,
        }:
            summary = _generic_tool_summary(tool_name, item, result_summary)
            output_body = _generic_tool_output_body(item)
            if output_body:
                prior_summary = summary
                envelope, summary = build_text_tool_result(
                    tool_name=tool_name,
                    tool_call_id=tool_id or None,
                    body=output_body,
                    label=result_summary or prior_summary["label"],
                    summary_kind=str(prior_summary.get("kind") or "result"),
                    subject_type=str(prior_summary.get("subject_type") or "tool"),
                    preview_text=str(prior_summary.get("preview_text") or output_body)[:240],
                )
                server = prior_summary.get("target_label")
                if server:
                    summary["target_label"] = server
                surface = "rich_result"
                result_summary = result_summary or envelope["plain_body"]
            result_summary = result_summary or summary["label"]
        emit.tool_result(
            tool_name=tool_name,
            tool_call_id=tool_id or None,
            result_summary=result_summary,
            is_error=is_error,
            envelope=envelope,
            surface=surface,
            summary=summary,
        )
        if (
            kind == schema.ITEM_KIND_COMMAND_EXECUTION
            and is_error
            and (
                looks_like_execution_surface_failure(result_summary)
                or looks_like_execution_surface_failure(execution_surface_text)
            )
        ):
            result_meta["is_error"] = True
            result_meta["error"] = format_execution_surface_failure(
                execution_surface_text or result_summary
            )
        return

    if method == schema.ITEM_FILE_CHANGE_OUTPUT_DELTA:
        _append_codex_file_change_delta(result_meta, params)
        return

    if method == schema.ITEM_COMMAND_OUTPUT_DELTA:
        _append_codex_command_output_delta(result_meta, params)
        return

    if method == schema.ITEM_PLAN_DELTA:
        delta = _extract_text_delta(params)
        if delta:
            result_meta.setdefault("native_plan_delta_parts", []).append(delta)
        return

    if method in {
        schema.NOTIFICATION_WARNING,
        schema.NOTIFICATION_CONFIG_WARNING,
        schema.NOTIFICATION_GUARDIAN_WARNING,
    }:
        _emit_warning_notification(method, params, emit=emit, result_meta=result_meta)
        return

    if method == schema.NOTIFICATION_FS_CHANGED:
        _emit_fs_changed_notification(params, emit=emit, result_meta=result_meta)
        return

    if method == schema.NOTIFICATION_MCP_TOOL_CALL_PROGRESS:
        _emit_mcp_progress_notification(params, emit=emit, result_meta=result_meta)
        return

    if method in {
        schema.NOTIFICATION_ITEM_GUARDIAN_REVIEW_STARTED,
        schema.NOTIFICATION_ITEM_GUARDIAN_REVIEW_COMPLETED,
    }:
        _emit_guardian_review_notification(method, params, emit=emit, result_meta=result_meta)
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
        _maybe_emit_final_text_command_envelope(
            emit=emit,
            result_meta=result_meta,
            final_text=str(result_meta.get("final_text") or ""),
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
                message = turn_error.get("message") or str(turn_error)
            else:
                message = str(turn_error)
            result_meta["error"] = (
                format_execution_surface_failure(message)
                if looks_like_execution_surface_failure(message)
                else message
            )
        result_meta["completed"] = True
        return

    if method == schema.NOTIFICATION_ERROR:
        err = params.get("error") if isinstance(params.get("error"), dict) else params
        message = (err or {}).get("message") or "codex error"
        result_meta["is_error"] = True
        result_meta["error"] = (
            format_execution_surface_failure(message)
            if looks_like_execution_surface_failure(message)
            else message
        )
        return

    logger.debug("codex: unhandled notification %s", method)


def _tool_name_for_item(item: dict[str, Any], kind: str) -> str:
    if kind == schema.ITEM_KIND_COMMAND_EXECUTION:
        return "Bash"
    if kind == schema.ITEM_KIND_FILE_CHANGE:
        return "fileChange"
    if kind == schema.ITEM_KIND_COLLAB_TOOL_CALL:
        tool = item.get("tool")
        if isinstance(tool, str) and tool.strip():
            return "Codex subagent"
        return "Codex collaboration"
    if kind == schema.ITEM_KIND_WEB_SEARCH:
        return "Web search"
    if kind == schema.ITEM_KIND_IMAGE_VIEW:
        return "View image"
    if kind == schema.ITEM_KIND_MCP_TOOL_CALL:
        return _native_tool_label(item, default="MCP tool")
    if kind == schema.ITEM_KIND_DYNAMIC_TOOL:
        return _native_tool_label(item, default="Codex dynamic tool")
    if kind == schema.ITEM_KIND_TOOL_CALL:
        return _native_tool_label(item, default="Codex tool")
    return str(item.get("name") or item.get("toolName") or item.get("command") or kind)


def _tool_arguments_for_item(item: dict[str, Any], kind: str) -> dict[str, Any]:
    if kind == schema.ITEM_KIND_COMMAND_EXECUTION:
        command = str(item.get("command") or item.get("name") or item.get("toolName") or "").strip()
        args: dict[str, Any] = {}
        if command:
            args["command"] = command
            cwd, display = _split_command_cwd(command)
            if cwd:
                args["cwd"] = cwd
            if display and display != command:
                args["display_command"] = display
        for key in ("status", "exitCode", "exit_code", "durationMs", "duration_ms"):
            if key in item:
                args[key] = item[key]
        return args
    if kind == schema.ITEM_KIND_FILE_CHANGE:
        path = _extract_file_path(item)
        args = {}
        if path:
            args["path"] = path
        changes = item.get("changes")
        if isinstance(changes, list):
            paths = [
                change.get("path")
                for change in changes
                if isinstance(change, dict) and isinstance(change.get("path"), str)
            ]
            if paths:
                args["paths"] = paths
        return args
    if kind == schema.ITEM_KIND_COLLAB_TOOL_CALL:
        return _collab_arguments(item)
    if kind == schema.ITEM_KIND_WEB_SEARCH:
        return _non_empty_args({
            "query": item.get("query"),
            "action": item.get("action"),
            "status": item.get("status"),
        })
    if kind == schema.ITEM_KIND_IMAGE_VIEW:
        return _non_empty_args({"path": item.get("path")})
    if kind in {
        schema.ITEM_KIND_MCP_TOOL_CALL,
        schema.ITEM_KIND_DYNAMIC_TOOL,
        schema.ITEM_KIND_TOOL_CALL,
    }:
        return _generic_tool_arguments(item)
    raw = item.get("input") or item.get("arguments") or {}
    return raw if isinstance(raw, dict) else {}


def _native_tool_label(item: dict[str, Any], *, default: str) -> str:
    for key in ("name", "toolName", "tool", "serverToolName"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            if key == "serverToolName":
                server = item.get("server")
                return f"{server}:{value}" if isinstance(server, str) and server.strip() else value
            return value.strip()
    return default


def _generic_tool_arguments(item: dict[str, Any]) -> dict[str, Any]:
    raw = item.get("input") or item.get("arguments") or item.get("args") or {}
    args = raw if isinstance(raw, dict) else {}
    return _non_empty_args({
        **args,
        "server": item.get("server"),
        "tool": item.get("tool") or item.get("toolName") or item.get("name"),
        "status": item.get("status"),
        "call_id": item.get("callId") or item.get("call_id"),
    })


def _non_empty_args(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value not in (None, "", [], {})}


def _split_command_cwd(command: str) -> tuple[str | None, str | None]:
    inner = _unwrap_shell_command(command)
    if inner.startswith("cd ") and " && " in inner:
        cwd, rest = inner[3:].split(" && ", 1)
        return cwd.strip().strip("'\"") or None, rest.strip() or inner
    return None, inner or command


def _unwrap_shell_command(command: str) -> str:
    text = command.strip()
    for prefix in ("/bin/bash -lc ", "bash -lc ", "/bin/sh -lc ", "sh -lc "):
        if text.startswith(prefix):
            rest = text[len(prefix):].strip()
            if len(rest) >= 2 and rest[0] == rest[-1] and rest[0] in {"'", '"'}:
                return rest[1:-1]
            return rest
    return text


def _collab_arguments(item: dict[str, Any]) -> dict[str, Any]:
    return _non_empty_args({
        "tool": item.get("tool"),
        "status": item.get("status"),
        "sender_thread_id": item.get("senderThreadId"),
        "receiver_thread_id": item.get("receiverThreadId"),
        "new_thread_id": item.get("newThreadId"),
        "agent_status": item.get("agentStatus"),
        "prompt": item.get("prompt"),
    })


def _collab_summary(item: dict[str, Any], fallback: str) -> dict[str, Any]:
    args = _collab_arguments(item)
    tool = str(args.get("tool") or "collaboration").replace("_", " ")
    status = str(args.get("agent_status") or args.get("status") or "").replace("_", " ")
    label = f"Codex subagent {tool}".strip()
    if status:
        label = f"{label}: {status}"
    prompt = args.get("prompt")
    return {
        "kind": "result",
        "subject_type": "session",
        "label": fallback or label,
        "target_id": args.get("new_thread_id") or args.get("receiver_thread_id"),
        "target_label": str(args.get("tool") or "subagent"),
        **({"preview_text": str(prompt)[:240]} if isinstance(prompt, str) and prompt.strip() else {}),
    }


def _web_search_summary(item: dict[str, Any], fallback: str) -> dict[str, Any]:
    query = item.get("query")
    label = fallback or (f"Searched web: {query}" if isinstance(query, str) and query else "Searched web")
    return {
        "kind": "lookup",
        "subject_type": "generic",
        "label": label,
        **({"preview_text": str(query)} if isinstance(query, str) and query else {}),
    }


def _image_view_summary(item: dict[str, Any], fallback: str) -> dict[str, Any]:
    path = item.get("path")
    label = fallback or (f"Viewed image {path}" if isinstance(path, str) and path else "Viewed image")
    return {
        "kind": "read",
        "subject_type": "file",
        "label": label,
        **({"path": str(path)} if isinstance(path, str) and path else {}),
    }


def _generic_tool_summary(tool_name: str, item: dict[str, Any], fallback: str) -> dict[str, Any]:
    preview = _summarize_item_result(item)
    if not preview:
        raw_output = item.get("output") or item.get("result")
        if isinstance(raw_output, dict):
            preview = raw_output.get("text") or raw_output.get("summary") or ""
    label = fallback or tool_name
    summary = {
        "kind": "result",
        "subject_type": "tool",
        "label": label,
    }
    if preview:
        summary["preview_text"] = str(preview)[:240]
    server = item.get("server")
    if isinstance(server, str) and server.strip():
        summary["target_label"] = server.strip()
    return summary


def _generic_tool_output_body(item: dict[str, Any]) -> str:
    for key in ("output", "result", "content"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            for nested_key in ("text", "summary", "content", "message"):
                nested = value.get(nested_key)
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
    return ""


def _emit_warning_notification(
    method: str,
    params: dict[str, Any],
    *,
    emit: ChannelEventEmitter,
    result_meta: dict[str, Any],
) -> None:
    message = (
        params.get("message")
        or params.get("summary")
        or params.get("details")
        or "Codex warning"
    )
    detail = str(params.get("details") or message)
    path = params.get("path")
    call_id = f"codex-warning:{len(result_meta.setdefault('codex_warnings', [])) + 1}"
    warning = {
        "method": method,
        "message": str(message),
        **({"details": str(params.get("details"))} if params.get("details") else {}),
        **({"path": str(path)} if isinstance(path, str) and path else {}),
        **({"thread_id": str(params.get("threadId"))} if params.get("threadId") else {}),
    }
    warnings = result_meta.setdefault("codex_warnings", [])
    if isinstance(warnings, list):
        warnings.append(warning)
    envelope, summary = build_text_tool_result(
        tool_name="Codex warning",
        tool_call_id=call_id,
        body=detail,
        label=str(message),
        summary_kind="warning",
        subject_type="runtime",
        path=path if isinstance(path, str) else None,
        preview_text=detail,
    )
    emit.tool_result(
        tool_name="Codex warning",
        tool_call_id=call_id,
        result_summary=envelope["plain_body"],
        is_error=False,
        envelope=envelope,
        surface="rich_result",
        summary=summary,
    )


def _emit_fs_changed_notification(
    params: dict[str, Any],
    *,
    emit: ChannelEventEmitter,
    result_meta: dict[str, Any],
) -> None:
    changed = params.get("changedPaths") or params.get("changed_paths") or []
    paths = [str(path) for path in changed if isinstance(path, str)]
    watch_id = str(params.get("watchId") or params.get("watch_id") or "")
    label = f"Filesystem changed: {len(paths)} path{'s' if len(paths) != 1 else ''}"
    body = "\n".join(paths) or label
    call_id = f"codex-fs:{watch_id or len(result_meta.setdefault('codex_fs_events', [])) + 1}"
    events = result_meta.setdefault("codex_fs_events", [])
    if isinstance(events, list):
        events.append({"watch_id": watch_id, "paths": paths})
    envelope, summary = build_text_tool_result(
        tool_name="Filesystem watch",
        tool_call_id=call_id,
        body=body,
        label=label,
        summary_kind="watch",
        subject_type="file",
        path=paths[0] if len(paths) == 1 else None,
        preview_text=body,
    )
    emit.tool_result(
        tool_name="Filesystem watch",
        tool_call_id=call_id,
        result_summary=envelope["plain_body"],
        is_error=False,
        envelope=envelope,
        surface="rich_result",
        summary=summary,
    )


def _emit_mcp_progress_notification(
    params: dict[str, Any],
    *,
    emit: ChannelEventEmitter,
    result_meta: dict[str, Any],
) -> None:
    item_id = str(params.get("itemId") or params.get("item_id") or "")
    message = str(params.get("message") or "MCP tool call progress")
    call_id = item_id or f"codex-mcp-progress:{len(result_meta.setdefault('codex_mcp_progress', [])) + 1}"
    progress = result_meta.setdefault("codex_mcp_progress", [])
    if isinstance(progress, list):
        progress.append({"item_id": item_id, "message": message})
    envelope, summary = build_text_tool_result(
        tool_name="MCP progress",
        tool_call_id=call_id,
        body=message,
        label="MCP progress",
        summary_kind="progress",
        subject_type="tool",
        preview_text=message,
    )
    emit.tool_result(
        tool_name="MCP progress",
        tool_call_id=call_id,
        result_summary=envelope["plain_body"],
        is_error=False,
        envelope=envelope,
        surface="rich_result",
        summary=summary,
    )


def _emit_guardian_review_notification(
    method: str,
    params: dict[str, Any],
    *,
    emit: ChannelEventEmitter,
    result_meta: dict[str, Any],
) -> None:
    started = method == schema.NOTIFICATION_ITEM_GUARDIAN_REVIEW_STARTED
    review_id = str(params.get("reviewId") or params.get("review_id") or "")
    target_id = str(params.get("targetItemId") or params.get("target_item_id") or "")
    decision = str(params.get("decisionSource") or "")
    label = "Approval auto-review started" if started else "Approval auto-review completed"
    body_parts = [label]
    if target_id:
        body_parts.append(f"target: {target_id}")
    if decision:
        body_parts.append(f"decision source: {decision}")
    body = "\n".join(body_parts)
    call_id = f"codex-guardian-review:{review_id or len(result_meta.setdefault('codex_guardian_reviews', [])) + 1}"
    reviews = result_meta.setdefault("codex_guardian_reviews", [])
    if isinstance(reviews, list):
        reviews.append({
            "review_id": review_id,
            "target_item_id": target_id,
            "status": "started" if started else "completed",
            **({"decision_source": decision} if decision else {}),
        })
    envelope, summary = build_text_tool_result(
        tool_name="Approval auto-review",
        tool_call_id=call_id,
        body=body,
        label=label,
        summary_kind="approval_review",
        subject_type="runtime",
        preview_text=body,
    )
    emit.tool_result(
        tool_name="Approval auto-review",
        tool_call_id=call_id,
        result_summary=envelope["plain_body"],
        is_error=False,
        envelope=envelope,
        surface="rich_result",
        summary=summary,
    )


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


def _append_codex_command_output_delta(result_meta: dict[str, Any], params: dict[str, Any]) -> None:
    item_id = _item_id(params)
    delta = _extract_command_output_delta(params)
    if not item_id or not delta:
        return
    by_item = result_meta.setdefault("codex_command_output_deltas", {})
    if isinstance(by_item, dict):
        by_item[item_id] = str(by_item.get(item_id) or "") + delta


def _record_codex_command_item(result_meta: dict[str, Any], item_id: str, tool_name: str) -> None:
    if not item_id:
        return
    by_item = result_meta.setdefault("codex_command_items", {})
    if isinstance(by_item, dict):
        by_item[item_id] = tool_name


def _record_codex_file_change_item(result_meta: dict[str, Any], item_id: str, item: dict[str, Any]) -> None:
    path = _extract_file_path(item)
    if not item_id or not path:
        return
    by_item = result_meta.setdefault("codex_file_change_paths", {})
    if isinstance(by_item, dict):
        by_item[item_id] = path


def _pop_codex_file_change_path(result_meta: dict[str, Any], item_id: str) -> str | None:
    if not item_id:
        return None
    by_item = result_meta.get("codex_file_change_paths")
    if not isinstance(by_item, dict):
        return None
    value = by_item.pop(item_id, None)
    return value if isinstance(value, str) and value.strip() else None


def _mark_codex_command_result_enveloped(result_meta: dict[str, Any], item_id: str) -> None:
    if not item_id:
        return
    emitted = result_meta.setdefault("codex_command_enveloped_items", set())
    if isinstance(emitted, set):
        emitted.add(item_id)


def _record_codex_command_without_envelope(result_meta: dict[str, Any], item_id: str) -> None:
    if not item_id:
        return
    pending = result_meta.setdefault("codex_command_items_without_envelope", set())
    if isinstance(pending, set):
        pending.add(item_id)


def _maybe_emit_final_text_command_envelope(
    *,
    emit: ChannelEventEmitter,
    result_meta: dict[str, Any],
    final_text: str,
) -> None:
    """Use final answer text as a narrow fallback for single command output.

    Codex CLI 0.125 can report native commandExecution items without the
    matching outputDelta payload that the schema advertises. When the turn has
    exactly one command and the final answer is the command's reported output,
    persist a text/plain envelope on the existing tool call so refresh keeps a
    useful inline result.
    """
    command_items = result_meta.get("codex_command_items")
    if not isinstance(command_items, dict) or len(command_items) != 1:
        return
    tool_id, tool_name = next(iter(command_items.items()))
    if not isinstance(tool_id, str) or not isinstance(tool_name, str):
        return
    pending = result_meta.get("codex_command_items_without_envelope")
    if not isinstance(pending, set) or tool_id not in pending:
        return
    emitted = result_meta.get("codex_command_enveloped_items")
    if isinstance(emitted, set) and tool_id in emitted:
        return
    buffered_output = _pop_codex_command_output_for_item(result_meta, tool_id)
    body = (buffered_output or final_text).strip()
    if not body:
        return
    if buffered_output is None and _looks_like_generic_command_status(body):
        return
    envelope, summary = build_text_tool_result(
        tool_name=tool_name,
        tool_call_id=tool_id,
        body=body,
        label=None,
    )
    emit.tool_result(
        tool_name=tool_name,
        tool_call_id=tool_id,
        result_summary=envelope["plain_body"],
        is_error=False,
        envelope=envelope,
        surface="rich_result",
        summary=summary,
    )
    _mark_codex_command_result_enveloped(result_meta, tool_id)


def _looks_like_generic_command_status(text: str) -> bool:
    normalized = text.strip().lower().rstrip(".")
    return normalized in {
        "done",
        "completed",
        "complete",
        "ok",
        "success",
        "succeeded",
        "deleted",
        "removed",
    }


def looks_like_execution_surface_failure(text: str) -> bool:
    normalized = " ".join(text.strip().lower().split())
    if not normalized:
        return False
    failure_markers = (
        "sandbox namespace",
        "namespace error",
        "create new namespace",
        "failed to enter namespace",
        "failed to create namespace",
        "failed to join namespace",
        "no permissions to create new namespace",
        "setns",
        "unshare",
        "bubblewrap",
        "bwrap",
        "seccomp",
    )
    return any(marker in normalized for marker in failure_markers)


def format_execution_surface_failure(text: str) -> str:
    return (
        "Codex native shell execution surface failed before a usable command result. "
        "This is a harness/runtime sandbox problem, not a missing repo command: "
        f"{text}"
    )


def _pop_codex_command_output_for_item(result_meta: dict[str, Any], item_id: str) -> str | None:
    if not item_id:
        return None
    by_item = result_meta.get("codex_command_output_deltas")
    if not isinstance(by_item, dict):
        return None
    value = by_item.pop(item_id, None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _extract_command_output_delta(params: dict[str, Any]) -> str:
    direct = _extract_text_delta(params)
    if direct:
        return direct
    for key in ("chunk", "output"):
        value = params.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            nested = _extract_text_delta(value)
            if nested:
                return nested
    return ""


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
    changes = item.get("changes")
    if isinstance(changes, list):
        paths: list[str] = []
        for change in changes:
            if not isinstance(change, dict):
                continue
            value = change.get("path") or change.get("filePath") or change.get("file_path")
            if isinstance(value, str) and value.strip():
                paths.append(value.strip())
        if len(paths) == 1:
            return paths[0]
        if len(paths) > 1:
            return f"{len(paths)} files"
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
