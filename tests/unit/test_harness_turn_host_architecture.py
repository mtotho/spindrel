"""Architecture guards for host-side harness turn orchestration."""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TURN_WORKER = REPO_ROOT / "app" / "services" / "turn_worker.py"
TURN_HOST = REPO_ROOT / "app" / "services" / "agent_harnesses" / "turn_host.py"


def _function_node(path: Path, name: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{path}: missing function {name}")


def test_turn_worker_harness_turn_stays_wrapper_sized():
    node = _function_node(TURN_WORKER, "_run_harness_turn")
    assert node.end_lineno is not None
    loc = node.end_lineno - node.lineno + 1
    assert loc <= 70

    calls = {
        call.func.id
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    }
    assert "_run_harness_turn_host" in calls

    forbidden = {
        "build_turn_context",
        "load_session_mode",
        "load_session_settings",
        "load_context_hints",
        "load_latest_harness_metadata",
        "resolve_harness_paths",
        "record_harness_token_usage",
        "maybe_run_harness_auto_compaction",
    }
    assert not (calls & forbidden)


def test_harness_turn_host_owns_host_orchestration():
    source = TURN_HOST.read_text()
    for needle in (
        "build_turn_context",
        "load_session_mode",
        "load_session_settings",
        "load_context_hints",
        "load_latest_harness_metadata",
        "resolve_harness_paths",
        "record_harness_token_usage",
        "maybe_run_harness_auto_compaction",
    ):
        assert needle in source

