"""Lint-style guard that pins the tool-result redaction boundary.

Goal: there is exactly one place in ``app/agent/tool_dispatch.py`` that
writes ``result_obj.result = ...`` directly — the ``_set_tool_result``
helper — plus a small allowlist of well-known sites that already route
their write through ``_set_tool_result(...)`` or the ``_redact_secrets``
helper. Every other write site in this file is a regression risk.

Failure mode this catches: a future refactor adds a new error/exception
branch that writes the raw tool result without redaction. The cost is a
few seconds of grep on every pytest run; the benefit is that the boundary
is mechanically enforced rather than memo-style.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_DISPATCH = REPO_ROOT / "app" / "agent" / "tool_dispatch.py"

# Sites that write ``result_obj.result =`` directly. Each must be inside the
# ``_set_tool_result`` helper or a comment that documents the boundary.
_RESULT_WRITE_RE = re.compile(r"^\s*result_obj\.result\s*=", re.MULTILINE)
_LLM_WRITE_RE = re.compile(r"^\s*result_obj\.result_for_llm\s*=", re.MULTILINE)


def _line_for(text: str, match_pos: int) -> int:
    return text.count("\n", 0, match_pos) + 1


def test_result_writes_are_inside_boundary_helper():
    src = TOOL_DISPATCH.read_text()
    write_lines = [
        _line_for(src, m.start()) for m in _RESULT_WRITE_RE.finditer(src)
    ]
    # The only ``result_obj.result =`` write should be inside
    # ``_set_tool_result``. Locate that function.
    helper_start_match = re.search(
        r"^def _set_tool_result\(", src, re.MULTILINE,
    )
    assert helper_start_match, (
        "Boundary helper ``_set_tool_result`` is missing — every direct "
        "write to ``result_obj.result`` must route through it for redaction."
    )
    helper_start = _line_for(src, helper_start_match.start())
    # Helper body is short; pin a generous window. The next top-level def is
    # the soft upper bound.
    next_def = re.search(
        r"^(?:def |class )", src[helper_start_match.end():], re.MULTILINE,
    )
    helper_end_offset = (
        helper_start_match.end() + next_def.start() if next_def else len(src)
    )
    helper_end = _line_for(src, helper_end_offset)
    illegal = [ln for ln in write_lines if not (helper_start <= ln <= helper_end)]
    assert not illegal, (
        "Found direct writes to ``result_obj.result`` outside the "
        f"``_set_tool_result`` boundary at lines {illegal}. Route them "
        "through ``_set_tool_result(result_obj, payload)`` instead so the "
        "secret-redaction call is impossible to forget."
    )


def test_llm_writes_redact():
    """Every direct ``result_obj.result_for_llm =`` site must redact.

    We accept a write if the same line or an immediately preceding line
    references ``_redact`` or ``_set_tool_result`` (the boundary helper).
    """
    src = TOOL_DISPATCH.read_text()
    lines = src.splitlines()
    offending: list[int] = []
    for m in _LLM_WRITE_RE.finditer(src):
        line_no = _line_for(src, m.start())
        # Look back up to 5 lines for evidence of redaction
        window = "\n".join(lines[max(0, line_no - 6) : line_no])
        if "_redact" in window or "_set_tool_result" in window:
            continue
        # Also accept the boundary helper itself
        if "_set_tool_result" in lines[line_no - 1]:
            continue
        # The boundary helper writes both fields; allow its own body.
        if "persisted_redacted" in lines[line_no - 1]:
            continue
        offending.append(line_no)
    assert not offending, (
        "Found writes to ``result_obj.result_for_llm`` without nearby "
        f"redaction at lines {offending}. Apply ``_redact_secrets(...)`` "
        "or route through ``_set_tool_result(...)``."
    )
