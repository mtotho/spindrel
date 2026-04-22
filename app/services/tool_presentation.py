"""Normalized presentation metadata for persisted tool outcomes.

This layer sits between the raw audit payload (`tool_name`, `arguments`,
`result`, `error`) and first-party chat renderers. The goal is to keep raw
tool fidelity intact while giving the UI one stable, server-derived render
contract.
"""

from __future__ import annotations

import json
from typing import Any, Literal, Mapping, cast


ToolSurface = Literal["transcript", "widget", "rich_result"]
ToolSummaryKind = Literal["lookup", "read", "write", "diff", "action", "result", "error"]
ToolSummarySubject = Literal["file", "skill", "widget", "tool", "session", "channel", "entity", "generic"]

ToolSummary = dict[str, Any]

_WIDGET_CONTENT_TYPES = {
    "application/vnd.spindrel.components+json",
    "application/vnd.spindrel.html+interactive",
}

_RICH_TRANSCRIPT_CONTENT_TYPES = {
    "application/vnd.spindrel.diff+text",
    "application/vnd.spindrel.file-listing+json",
}


def _short_tool_name(name: str) -> str:
    if "-" in name:
        return name.rsplit("-", 1)[-1]
    return name


def _parse_json_object(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if isinstance(parsed, dict):
        return cast(dict[str, Any], parsed)
    return None


def _coerce_arguments(arguments: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(arguments, Mapping):
        return {}
    return {str(k): v for k, v in arguments.items()}


def _normalize_label(label: str | None) -> str | None:
    if not isinstance(label, str):
        return None
    clean = " ".join(label.strip().split())
    if not clean:
        return None
    return clean.replace("−", "-")


def _format_skill_ref(skill_id: str) -> str:
    clean = skill_id.strip()
    if not clean:
        return "skill"
    if "/" in clean:
        return f"{clean}.md"
    return f"{clean}/INDEX.md"


def _first_nonempty(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str):
            clean = value.strip()
            if clean:
                return clean
    return None


def _diff_stats_from_text(text: str | None) -> dict[str, int] | None:
    if not text:
        return None
    additions = 0
    deletions = 0
    for line in text.splitlines():
        if not line:
            continue
        if line.startswith("+++ ") or line.startswith("--- ") or line.startswith("@@"):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    if additions == 0 and deletions == 0:
        return None
    return {"additions": additions, "deletions": deletions}


def _extract_diff_body(result: str | None, envelope: Mapping[str, Any] | None) -> str | None:
    env_body = envelope.get("body") if isinstance(envelope, Mapping) else None
    if isinstance(env_body, str) and env_body.strip():
        return env_body
    if not result:
        return None
    parsed = _parse_json_object(result)
    env = parsed.get("_envelope") if isinstance(parsed, dict) else None
    if isinstance(env, dict):
        body = env.get("body")
        if isinstance(body, str) and body.strip():
            return body
    return result if result.startswith(("---", "+++", "@@", "+", "-")) else None


def _derive_file_presentation(
    *,
    arguments: dict[str, Any],
    envelope: Mapping[str, Any] | None,
    result: str | None,
) -> tuple[ToolSurface, ToolSummary]:
    operation = _first_nonempty(arguments.get("operation")) or "action"
    path = _first_nonempty(arguments.get("path"), arguments.get("file_path"), arguments.get("target_path"))
    plain_body = _normalize_label(cast(str | None, envelope.get("plain_body")) if envelope else None)
    content_type = _first_nonempty(envelope.get("content_type") if envelope else None)
    diff_text = _extract_diff_body(result, envelope)
    diff_stats = _diff_stats_from_text(diff_text)

    read_ops = {"read"}
    diff_ops = {"append", "edit", "json_patch", "restore"}
    write_ops = {"create", "overwrite", "delete", "mkdir", "move"}
    lookup_ops = {"grep", "glob", "list", "history"}

    if operation in read_ops:
        label = plain_body or (f"Read {path}" if path else "Read file")
        summary: ToolSummary = {"kind": "read", "subject_type": "file", "label": label}
        if path:
            summary["path"] = path
        return "transcript", summary

    if operation in diff_ops or content_type == "application/vnd.spindrel.diff+text" or diff_stats is not None:
        label = plain_body or (f"Edited {path}" if path else "Edited file")
        summary = {"kind": "diff", "subject_type": "file", "label": label}
        if path:
            summary["path"] = path
        if diff_stats:
            summary["diff_stats"] = diff_stats
        return "transcript", summary

    if operation in write_ops:
        label = plain_body or {
            "create": f"Created {path}" if path else "Created file",
            "overwrite": f"Overwrote {path}" if path else "Overwrote file",
            "delete": f"Deleted {path}" if path else "Deleted file",
            "mkdir": f"Created directory {path}" if path else "Created directory",
            "move": (
                f"Moved {path} → {_first_nonempty(arguments.get('destination'))}"
                if path and _first_nonempty(arguments.get("destination"))
                else (f"Moved {path}" if path else "Moved file")
            ),
        }.get(operation, f"Updated {path}" if path else "Updated file")
        summary = {"kind": "write", "subject_type": "file", "label": label}
        if path:
            summary["path"] = path
        return "transcript", summary

    if operation in lookup_ops:
        label = plain_body or {
            "list": f"Listed {path}" if path else "Listed files",
            "glob": f"Matched files in {path}" if path else "Matched files",
            "grep": f"Searched {path}" if path else "Searched files",
            "history": f"Viewed history for {path}" if path else "Viewed file history",
        }.get(operation, "Inspected files")
        summary = {"kind": "lookup", "subject_type": "file", "label": label}
        if path:
            summary["path"] = path
        return "transcript", summary

    label = plain_body or (f"{operation.title()} {path}" if path else "File operation")
    summary = {"kind": "action", "subject_type": "file", "label": label}
    if path:
        summary["path"] = path
    return "transcript", summary


def derive_tool_presentation(
    *,
    tool_name: str,
    arguments: Mapping[str, Any] | None,
    result: str | None,
    envelope: Mapping[str, Any] | None,
    error: str | None = None,
) -> tuple[ToolSurface, ToolSummary]:
    args = _coerce_arguments(arguments)
    short_name = _short_tool_name(tool_name)
    result_json = _parse_json_object(result)
    envelope = envelope if isinstance(envelope, Mapping) else None
    envelope_label = _normalize_label(_first_nonempty(
        envelope.get("display_label") if envelope else None,
        envelope.get("panel_title") if envelope else None,
        envelope.get("plain_body") if envelope else None,
    ))

    error_text = _first_nonempty(
        error,
        result_json.get("error") if isinstance(result_json, dict) else None,
    )
    if error_text:
        return "transcript", {
            "kind": "error",
            "subject_type": "tool",
            "label": tool_name.replace("_", " "),
            "error": error_text,
        }

    if short_name in {"get_skill", "load_skill"}:
        skill_id = _first_nonempty(
            args.get("skill_id"),
            args.get("skill_name"),
            result_json.get("id") if isinstance(result_json, dict) else None,
            result_json.get("name") if isinstance(result_json, dict) else None,
        )
        summary: ToolSummary = {
            "kind": "read",
            "subject_type": "skill",
            "label": "Loaded skill",
        }
        if skill_id:
            summary["target_id"] = skill_id
            summary["target_label"] = _format_skill_ref(skill_id)
        return "transcript", summary

    if short_name == "inspect_widget_pin":
        summary = {
            "kind": "lookup",
            "subject_type": "widget",
            "label": "Inspected widget pin",
        }
        pin_id = _first_nonempty(
            args.get("pin_id"),
            result_json.get("pin_id") if isinstance(result_json, dict) else None,
        )
        if pin_id:
            summary["target_id"] = pin_id
        return "transcript", summary

    if short_name == "file":
        return _derive_file_presentation(arguments=args, envelope=envelope, result=result)

    if short_name == "get_memory_file":
        path = _first_nonempty(
            result_json.get("path") if isinstance(result_json, dict) else None,
            args.get("name"),
        )
        summary = {"kind": "read", "subject_type": "file", "label": f"Read {path}" if path else "Read memory file"}
        if path:
            summary["path"] = path
        return "transcript", summary

    content_type = _first_nonempty(envelope.get("content_type") if envelope else None)
    if content_type in _WIDGET_CONTENT_TYPES:
        summary = {"kind": "result", "subject_type": "widget", "label": "Widget available"}
        if envelope_label:
            summary["target_label"] = envelope_label
        return "widget", summary

    if content_type in _RICH_TRANSCRIPT_CONTENT_TYPES or (envelope and envelope.get("display") == "inline"):
        summary = {
            "kind": "result",
            "subject_type": "generic",
            "label": envelope_label or tool_name.replace("_", " "),
        }
        return "rich_result", summary

    return "transcript", {
        "kind": "action",
        "subject_type": "generic",
        "label": tool_name.replace("_", " "),
    }


def extract_tool_call_name_and_arguments(tool_call: Mapping[str, Any]) -> tuple[str, str]:
    function = tool_call.get("function")
    if isinstance(function, Mapping):
        name = _first_nonempty(function.get("name"), tool_call.get("name")) or "unknown"
        fn_args = function.get("arguments")
        if isinstance(fn_args, str):
            return name, fn_args
        if fn_args is None:
            return name, "{}"
        return name, json.dumps(fn_args, ensure_ascii=False)
    name = _first_nonempty(tool_call.get("name"), tool_call.get("tool_name")) or "unknown"
    raw_args = tool_call.get("arguments", tool_call.get("args"))
    if isinstance(raw_args, str):
        return name, raw_args
    if raw_args is None:
        return name, "{}"
    return name, json.dumps(raw_args, ensure_ascii=False)


def normalize_persisted_tool_call(
    tool_call: Mapping[str, Any],
    *,
    envelope: Mapping[str, Any] | None = None,
    result: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    name, arguments_raw = extract_tool_call_name_and_arguments(tool_call)
    arguments_dict = _parse_json_object(arguments_raw) or {}
    surface, summary = derive_tool_presentation(
        tool_name=name,
        arguments=arguments_dict,
        result=result,
        envelope=envelope,
        error=error,
    )

    normalized = dict(tool_call)
    normalized["name"] = name
    normalized["arguments"] = arguments_raw
    normalized["surface"] = surface
    normalized["summary"] = summary
    function = normalized.get("function")
    if isinstance(function, Mapping):
        normalized["function"] = {
            **function,
            "name": name,
            "arguments": arguments_raw,
        }
    return normalized


def normalize_persisted_tool_calls(
    tool_calls: list[Mapping[str, Any]] | None,
    *,
    envelopes: list[Mapping[str, Any] | None] | None = None,
) -> list[dict[str, Any]] | None:
    if not tool_calls:
        return None
    out: list[dict[str, Any]] = []
    for index, tool_call in enumerate(tool_calls):
        envelope = envelopes[index] if envelopes and index < len(envelopes) else None
        out.append(normalize_persisted_tool_call(tool_call, envelope=envelope))
    return out
