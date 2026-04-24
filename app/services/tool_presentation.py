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


def _skill_name_from_markdown_body(result: str | None) -> str | None:
    """Extract the skill name from a raw markdown tool result starting with ``# Name``.

    Auto-injected synthetic get_skill results pass raw markdown (not JSON) —
    the body always starts with ``# <Name>`` by convention. This recovers the
    display name so the transcript shows ``Loaded skill (Workspace Files)``
    instead of ``Loaded skill (workspace/files)`` in that path too.
    """
    if not isinstance(result, str):
        return None
    first = _first_meaningful_line(result)
    if not first or not first.startswith("# "):
        return None
    candidate = first[2:].strip()
    return candidate or None


def _first_body_paragraph(text: str | None) -> str | None:
    """First non-heading, non-frontmatter paragraph from a markdown body.

    Skips leading blank lines, YAML frontmatter, and any ``#``-prefixed
    heading lines. Used for transcript preview when no frontmatter
    description is available.
    """
    if not isinstance(text, str):
        return None
    lines = text.splitlines()
    i = 0
    # Skip leading frontmatter block.
    if i < len(lines) and lines[i].strip() == "---":
        i += 1
        while i < len(lines) and lines[i].strip() != "---":
            i += 1
        if i < len(lines):
            i += 1  # consume closing ---
    for raw_line in lines[i:]:
        clean = raw_line.strip()
        if not clean or clean.startswith("#"):
            continue
        return clean
    return None


def _first_nonempty(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str):
            clean = value.strip()
            if clean:
                return clean
    return None


def _first_meaningful_line(text: str | None) -> str | None:
    if not isinstance(text, str):
        return None
    for raw_line in text.splitlines():
        clean = raw_line.strip()
        if clean:
            return clean
    return None


def _preview_text(
    *,
    envelope: Mapping[str, Any] | None,
    result: str | None,
) -> str | None:
    preview = _normalize_label(_first_nonempty(
        envelope.get("plain_body") if envelope else None,
        _first_meaningful_line(cast(str | None, envelope.get("body")) if envelope else None),
        _first_meaningful_line(result),
    ))
    if not preview:
        return None
    if preview.startswith("{") or preview.startswith("["):
        return None
    return preview


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
        return "rich_result", summary

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


_MANAGE_BOT_SKILL_WRITE_LABELS: dict[str, str] = {
    "create": "Created skill",
    "upsert": "Upserted skill",
    "update": "Updated skill",
    "patch": "Patched skill",
    "delete": "Archived skill",
    "restore": "Restored skill",
    "merge": "Merged skills",
    "add_script": "Added skill script",
    "update_script": "Updated skill script",
    "delete_script": "Deleted skill script",
}

_MANAGE_BOT_SKILL_SCRIPT_ACTIONS = {"get_script", "add_script", "update_script", "delete_script"}


def _derive_manage_bot_skill_presentation(
    *,
    args: dict[str, Any],
    result_json: dict[str, Any] | None,
) -> tuple[ToolSurface, ToolSummary]:
    action = _first_nonempty(args.get("action")) or "action"
    short = action.lower()

    def _first_result_skill_field(key: str) -> str | None:
        if not isinstance(result_json, dict):
            return None
        skills = result_json.get("skills")
        if isinstance(skills, list) and skills:
            first = skills[0]
            if isinstance(first, dict):
                value = first.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

    result_id = (
        result_json.get("id") if isinstance(result_json, dict) else None
    ) or _first_result_skill_field("id")
    result_name = (
        result_json.get("name") if isinstance(result_json, dict) else None
    ) or _first_result_skill_field("name")
    target_id = _first_nonempty(result_id, args.get("name"))
    target_label = _first_nonempty(result_name, args.get("title"), target_id)

    if short == "list":
        total = 0
        if isinstance(result_json, dict):
            raw_total = result_json.get("total")
            if isinstance(raw_total, int):
                total = raw_total
            elif isinstance(raw_total, str) and raw_total.isdigit():
                total = int(raw_total)
        noun = "skill" if total == 1 else "skills"
        summary: ToolSummary = {
            "kind": "lookup",
            "subject_type": "skill",
            "label": "Listed authored skills",
            "preview_text": f"{total} {noun}",
        }
        return "transcript", summary

    if short == "get":
        names_arg = args.get("names")
        is_batch = isinstance(names_arg, list) and len(names_arg) > 0
        if is_batch:
            count = 0
            missing = 0
            if isinstance(result_json, dict):
                skills_list = result_json.get("skills")
                if isinstance(skills_list, list):
                    count = len(skills_list)
                missing_list = result_json.get("missing")
                if isinstance(missing_list, list):
                    missing = len(missing_list)
            label = f"Loaded {count} skill(s)" if count != 1 else "Loaded skill"
            summary = {
                "kind": "read",
                "subject_type": "skill",
                "label": label,
            }
            if missing:
                summary["preview_text"] = f"{missing} missing"
            return "transcript", summary
        summary = {
            "kind": "read",
            "subject_type": "skill",
            "label": "Loaded skill",
        }
        if target_id:
            summary["target_id"] = target_id
        if target_label:
            summary["target_label"] = target_label
        return "transcript", summary

    if short == "get_script":
        summary = {
            "kind": "read",
            "subject_type": "skill",
            "label": "Loaded skill script",
        }
        script_name = _first_nonempty(
            result_json.get("script_name") if isinstance(result_json, dict) else None,
            args.get("script_name"),
        )
        if target_id:
            summary["target_id"] = target_id
        if target_label:
            summary["target_label"] = target_label
        if script_name:
            summary["preview_text"] = script_name
        return "transcript", summary

    label = _MANAGE_BOT_SKILL_WRITE_LABELS.get(short, f"Skill {short}")
    summary = {
        "kind": "write",
        "subject_type": "skill",
        "label": label,
    }
    if target_id:
        summary["target_id"] = target_id
    if target_label:
        summary["target_label"] = target_label
    if short in _MANAGE_BOT_SKILL_SCRIPT_ACTIONS:
        script_name = _first_nonempty(args.get("script_name"))
        if script_name:
            summary["preview_text"] = script_name
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
    content_type = _first_nonempty(envelope.get("content_type") if envelope else None)
    is_inline_envelope = bool(envelope and envelope.get("display") == "inline")

    error_text = _first_nonempty(
        error,
        result_json.get("error") if isinstance(result_json, dict) else None,
    )
    if error_text:
        if content_type in _WIDGET_CONTENT_TYPES:
            summary = {
                "kind": "error",
                "subject_type": "widget",
                "label": "Widget unavailable",
                "error": error_text,
            }
            if envelope_label:
                summary["target_label"] = envelope_label
            return "widget", summary
        if content_type in _RICH_TRANSCRIPT_CONTENT_TYPES or is_inline_envelope:
            return "rich_result", {
                "kind": "error",
                "subject_type": "generic",
                "label": envelope_label or tool_name.replace("_", " "),
                "error": error_text,
            }
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
        )
        skill_name = _first_nonempty(
            result_json.get("name") if isinstance(result_json, dict) else None,
            _skill_name_from_markdown_body(result),
        )
        skill_description = _first_nonempty(
            result_json.get("description") if isinstance(result_json, dict) else None,
        )
        already_loaded = bool(result_json.get("already_loaded")) if isinstance(result_json, dict) else False
        summary: ToolSummary = {
            "kind": "result" if already_loaded else "read",
            "subject_type": "skill",
            "label": "Skill already loaded" if already_loaded else "Loaded skill",
        }
        if skill_id:
            summary["target_id"] = skill_id
        if skill_name:
            summary["target_label"] = skill_name
        elif skill_id:
            summary["target_label"] = skill_id
        # Preview priority: (1) description from result JSON, (2) already-loaded
        # message, (3) first body paragraph of the markdown content (skipping
        # the ``# Name`` heading that becomes target_label). Heading-only
        # envelope bodies never become preview text — they'd just echo the
        # target_label.
        body_text: str | None = None
        if isinstance(result_json, dict):
            content_val = result_json.get("content")
            if isinstance(content_val, str):
                body_text = content_val
        if body_text is None and isinstance(result, str) and not isinstance(result_json, dict):
            body_text = result
        preview_text = (
            _normalize_label(skill_description)
            or _normalize_label(
                result_json.get("message") if already_loaded and isinstance(result_json, dict) else None,
            )
            or _normalize_label(_first_body_paragraph(body_text))
        )
        if preview_text and preview_text != summary.get("target_label"):
            summary["preview_text"] = preview_text
        return "transcript", summary

    if short_name == "get_skill_list":
        count = 0
        if isinstance(result_json, dict):
            raw_count = result_json.get("count")
            if isinstance(raw_count, int):
                count = raw_count
            elif isinstance(raw_count, str) and raw_count.isdigit():
                count = int(raw_count)
        noun = "skill" if count == 1 else "skills"
        summary = {
            "kind": "lookup",
            "subject_type": "skill",
            "label": "Listed skills",
            "preview_text": f"{count} {noun}",
        }
        return "transcript", summary

    if short_name == "prune_enrolled_skills":
        def _int_field(key: str) -> int:
            if not isinstance(result_json, dict):
                return 0
            raw = result_json.get(key)
            if isinstance(raw, int):
                return raw
            if isinstance(raw, str) and raw.isdigit():
                return int(raw)
            return 0

        removed = _int_field("removed")
        archived = _int_field("archived")
        blocked = _int_field("blocked")
        parts: list[str] = []
        if removed:
            parts.append(f"unenrolled {removed}")
        if archived:
            parts.append(f"archived {archived}")
        if blocked:
            parts.append(f"{blocked} blocked")
        summary = {
            "kind": "write",
            "subject_type": "skill",
            "label": "Pruned skills",
            "preview_text": ", ".join(parts) or "no changes",
        }
        return "transcript", summary

    if short_name == "manage_bot_skill":
        return _derive_manage_bot_skill_presentation(args=args, result_json=result_json)

    if short_name in {"get_current_local_time", "get_current_time"}:
        label = "Got current local time" if short_name == "get_current_local_time" else "Got current time"
        summary = {
            "kind": "result",
            "subject_type": "generic",
            "label": label,
        }
        preview_text = _preview_text(envelope=envelope, result=result)
        if preview_text:
            summary["preview_text"] = preview_text
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

    if content_type in _WIDGET_CONTENT_TYPES:
        summary = {"kind": "result", "subject_type": "widget", "label": "Widget available"}
        if envelope_label:
            summary["target_label"] = envelope_label
        return "widget", summary

    if content_type in _RICH_TRANSCRIPT_CONTENT_TYPES or is_inline_envelope:
        summary = {
            "kind": "result",
            "subject_type": "generic",
            "label": envelope_label or tool_name.replace("_", " "),
        }
        return "rich_result", summary

    summary = {
        "kind": "action",
        "subject_type": "generic",
        "label": tool_name.replace("_", " "),
    }
    preview_text = _preview_text(envelope=envelope, result=result)
    if preview_text and preview_text != summary["label"]:
        summary["preview_text"] = preview_text
    return "transcript", summary


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
    # Persisted flow (persist_turn) passes envelope only; envelope.body IS the
    # tool result string for JSON envelopes, so use it as result when an
    # explicit result wasn't supplied. Presentation branches parse JSON from
    # ``result`` to read fields like ``name`` and ``description``.
    effective_result = result
    if effective_result is None and isinstance(envelope, Mapping):
        body = envelope.get("body")
        if isinstance(body, str) and body:
            effective_result = body
    surface, summary = derive_tool_presentation(
        tool_name=name,
        arguments=arguments_dict,
        result=effective_result,
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
    envelopes_by_tool_call_id: dict[str, Mapping[str, Any] | None] = {}
    legacy_envelopes: list[Mapping[str, Any] | None] = []
    for envelope in envelopes or []:
        envelope_tool_call_id = (
            envelope.get("tool_call_id") if isinstance(envelope, Mapping) else None
        )
        if isinstance(envelope_tool_call_id, str) and envelope_tool_call_id:
            envelopes_by_tool_call_id[envelope_tool_call_id] = envelope
            continue
        legacy_envelopes.append(envelope)

    out: list[dict[str, Any]] = []
    legacy_index = 0
    for tool_call in tool_calls:
        tool_call_id = tool_call.get("id") if isinstance(tool_call, Mapping) else None
        envelope = (
            envelopes_by_tool_call_id.get(tool_call_id)
            if isinstance(tool_call_id, str) and tool_call_id
            else None
        )
        if envelope is None and legacy_index < len(legacy_envelopes):
            envelope = legacy_envelopes[legacy_index]
            legacy_index += 1
        out.append(normalize_persisted_tool_call(tool_call, envelope=envelope))
    return out
