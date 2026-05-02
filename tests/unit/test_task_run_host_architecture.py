"""Architecture guards for task-run host orchestration."""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TASKS = REPO_ROOT / "app" / "agent" / "tasks.py"
TASK_RUN_HOST = REPO_ROOT / "app" / "agent" / "task_run_host.py"


def _function_node(path: Path, name: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{path}: missing function {name}")


def test_tasks_run_task_stays_wrapper_sized():
    node = _function_node(TASKS, "run_task")
    assert node.end_lineno is not None
    loc = node.end_lineno - node.lineno + 1
    assert loc <= 40

    calls = {
        call.func.id
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    }
    assert "run_task_host" in calls
    assert "TaskRunHostDeps" in calls


def test_tasks_run_task_passes_patchable_dependencies():
    source = ast.get_source_segment(TASKS.read_text(), _function_node(TASKS, "run_task"))
    assert source is not None

    for needle in (
        "async_session=async_session",
        "settings=settings",
        "session_locks=session_locks",
        "get_bot=get_bot",
        "resolve_task_session_target=resolve_task_session_target",
        "is_pipeline_child=_is_pipeline_child",
        "resolve_sub_session_bus_channel=_resolve_sub_session_bus_channel",
        "dispatch_to_specialized_runner=_dispatch_to_specialized_runner",
        "publish_turn_ended=_publish_turn_ended",
        "fire_task_complete=_fire_task_complete",
        "record_timeout_event=_record_timeout_event",
        "resolve_task_timeout=resolve_task_timeout",
        "mark_task_failed_in_db=_mark_task_failed_in_db",
        "publish_turn_ended_safe=_publish_turn_ended_safe",
        "mark_heartbeat_task_started=_mark_heartbeat_task_started",
        "finalize_heartbeat_task_run=_finalize_heartbeat_task_run",
        "heartbeat_execution_meta=_heartbeat_execution_meta",
    ):
        assert needle in source


def test_tasks_run_task_does_not_reabsorb_policy():
    source = ast.get_source_segment(TASKS.read_text(), _function_node(TASKS, "run_task"))
    assert source is not None

    for forbidden in (
        "queued_task_starting",
        "session_locks.acquire",
        "asyncio.wait_for",
        "RateLimitError",
        "rate_limited",
        "persist_turn",
        "_prepare_task_run",
        "_run_normal_agent_task",
    ):
        assert forbidden not in source


def test_task_run_host_owns_general_task_orchestration():
    source = TASK_RUN_HOST.read_text()
    for needle in (
        "resolve_task_session_target",
        "deps.session_locks.acquire",
        "queued_task_starting",
        "_prepare_task_run",
        "_run_harness_task_if_needed",
        "_run_normal_agent_task",
        "persist_turn",
        "RateLimitError",
        "rate_limited",
    ):
        assert needle in source


def test_harness_task_reuses_pre_persisted_user_message_id():
    source = ast.get_source_segment(TASK_RUN_HOST.read_text(), _function_node(TASK_RUN_HOST, "_run_harness_task_if_needed"))
    assert source is not None

    assert 'prepared.ecfg.get("pre_user_msg_id")' in source
    assert "uuid.UUID(str(pre_user_msg_id_str))" in source
    assert "pre_user_msg_id=pre_user_msg_id" in source
