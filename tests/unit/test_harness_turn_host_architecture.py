"""Architecture guards for host-side harness turn orchestration."""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TURN_WORKER = REPO_ROOT / "app" / "services" / "turn_worker.py"
TURN_HOST = REPO_ROOT / "app" / "services" / "agent_harnesses" / "turn_host.py"
TASK_RUN_HOST = REPO_ROOT / "app" / "agent" / "task_run_host.py"
HEARTBEAT = REPO_ROOT / "app" / "services" / "heartbeat.py"


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
    assert loc <= 30

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


def test_run_harness_turn_takes_single_request_argument():
    """The seam is one typed envelope, not 13 loose kwargs."""
    node = _function_node(TURN_WORKER, "_run_harness_turn")
    args = node.args
    assert len(args.args) == 1
    assert args.args[0].arg == "request"
    assert not args.kwonlyargs
    assert args.vararg is None
    assert args.kwarg is None


def test_run_harness_turn_host_request_first_di_kwargs_only():
    """``run_harness_turn`` takes one positional ``request`` then DI callables."""
    node = _function_node(TURN_HOST, "run_harness_turn")
    args = node.args
    assert len(args.args) == 1
    assert args.args[0].arg == "request"
    forbidden_kwonly = {
        "channel_id",
        "bus_key",
        "session_id",
        "turn_id",
        "bot",
        "user_message",
        "correlation_id",
        "harness_tool_names",
        "harness_skill_ids",
        "harness_attachments",
        "harness_permission_mode_override",
        "harness_model_override",
        "harness_effort_override",
    }
    kwonly_names = {a.arg for a in args.kwonlyargs}
    assert not (kwonly_names & forbidden_kwonly)


def test_callsites_construct_harness_turn_request():
    """The three production callers must build a ``HarnessTurnRequest``."""
    for path in (TURN_WORKER, TASK_RUN_HOST, HEARTBEAT):
        source = path.read_text()
        assert "HarnessTurnRequest(" in source, (
            f"{path.relative_to(REPO_ROOT)} must construct the typed envelope"
        )


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
