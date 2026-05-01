"""Static guards for Claude Code SDK allowlists.

The runtime module imports ``claude_agent_sdk`` at module import time, so
environments without the SDK skip the bridge tests. These checks keep the
allowlist parity contract covered in the default local unit suite.
"""
from __future__ import annotations

import ast
from pathlib import Path


def _tuple_strings(name: str) -> set[str]:
    path = Path("integrations/claude_code/harness.py")
    module = ast.parse(path.read_text())
    for node in module.body:
        if isinstance(node, ast.Assign):
            if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                continue
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            value = node.value
        else:
            continue
        if isinstance(value, ast.Tuple):
            return {
                item.value
                for item in value.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            }
    raise AssertionError(f"{name} tuple assignment not found")


def test_claude_bypass_allowlist_keeps_native_code_sdk_surfaces():
    allowed = _tuple_strings("_BYPASS_ALLOWED")

    assert {"Agent", "Skill", "TodoWrite", "ToolSearch"}.issubset(allowed)
    assert "AskUserQuestion" not in allowed


def test_claude_restricted_allowlist_keeps_orchestration_behind_bridge_policy():
    allowed = _tuple_strings("_RESTRICTED_ALLOWED")

    assert {"Read", "Glob", "Grep", "WebSearch"}.issubset(allowed)
    assert {"Agent", "Skill", "TodoWrite", "AskUserQuestion"}.isdisjoint(allowed)
