"""Small helpers for harness-native rich tool results.

Harness runtimes already know when their native CLI emitted a file diff. These
helpers convert that runtime-supplied data into the same compact envelope shape
normal Spindrel tools use, without inspecting the workspace after the fact.
"""

from __future__ import annotations

import difflib
from typing import Any


DIFF_CONTENT_TYPE = "application/vnd.spindrel.diff+text"
TEXT_CONTENT_TYPE = "text/plain"


def build_text_tool_result(
    *,
    tool_name: str,
    body: str,
    label: str | None = None,
    tool_call_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(envelope, summary)`` for runtime-supplied plain output."""
    text = body.strip("\n")
    plain = label or first_nonempty_line(text) or "Command output"
    envelope: dict[str, Any] = {
        "content_type": TEXT_CONTENT_TYPE,
        "body": text,
        "plain_body": plain,
        "display": "inline",
        "truncated": False,
        "record_id": None,
        "byte_size": len(text.encode("utf-8")),
        "tool_name": tool_name,
    }
    if tool_call_id:
        envelope["tool_call_id"] = tool_call_id
    summary: dict[str, Any] = {
        "kind": "result",
        "subject_type": "generic",
        "label": plain,
        "preview_text": plain,
    }
    return envelope, summary


def build_diff_tool_result(
    *,
    tool_name: str,
    diff_body: str,
    path: str | None = None,
    label: str | None = None,
    tool_call_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(envelope, summary)`` for a runtime-supplied unified diff."""
    body = diff_body.strip("\n")
    additions, deletions = diff_stats(body)
    target = (path or label or "file changes").strip()
    plain = label or f"Changed {target}: +{additions} -{deletions} lines"
    envelope: dict[str, Any] = {
        "content_type": DIFF_CONTENT_TYPE,
        "body": body,
        "plain_body": plain,
        "display": "inline",
        "truncated": False,
        "record_id": None,
        "byte_size": len(body.encode("utf-8")),
        "tool_name": tool_name,
    }
    if path:
        envelope["display_label"] = path
    if tool_call_id:
        envelope["tool_call_id"] = tool_call_id
    summary: dict[str, Any] = {
        "kind": "diff",
        "subject_type": "file",
        "label": plain,
        "diff_stats": {"additions": additions, "deletions": deletions},
    }
    if path:
        summary["path"] = path
    return envelope, summary


def unified_diff_from_strings(
    *,
    old: str,
    new: str,
    path: str,
) -> str:
    """Build a unified diff from old/new text supplied by a harness tool call."""
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
    )
    return "\n".join(diff)


def diff_stats(diff_body: str) -> tuple[int, int]:
    additions = 0
    deletions = 0
    for line in diff_body.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return additions, deletions


def first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:160]
    return ""
