"""Architecture guards for task worker host orchestration."""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TASKS = REPO_ROOT / "app" / "agent" / "tasks.py"
TASK_WORKER_HOST = REPO_ROOT / "app" / "agent" / "task_worker_host.py"


def _function_node(path: Path, name: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{path}: missing function {name}")


def test_task_worker_wrappers_stay_small():
    for name in (
        "fetch_due_tasks",
        "recover_stuck_tasks",
        "recover_stalled_workflow_runs",
        "task_worker",
    ):
        node = _function_node(TASKS, name)
        assert node.end_lineno is not None
        loc = node.end_lineno - node.lineno + 1
        assert loc <= 16


def test_task_worker_wrappers_pass_patchable_dependencies():
    source = TASKS.read_text()
    deps_source = ast.get_source_segment(source, _function_node(TASKS, "_task_worker_deps"))
    assert deps_source is not None

    for needle in (
        "async_session=async_session",
        "settings=settings",
        "resolve_task_timeout=resolve_task_timeout",
        "record_timeout_event=_record_timeout_event",
        "fire_task_complete=_fire_task_complete",
        "fetch_due_tasks=fetch_due_tasks",
        "run_task=run_task",
        "recover_stuck_tasks=recover_stuck_tasks",
        "recover_stalled_workflow_runs=recover_stalled_workflow_runs",
        "spawn_due_schedules=spawn_due_schedules",
        "spawn_due_subscriptions=spawn_due_subscriptions",
        "create_task=asyncio.create_task",
        "sleep=asyncio.sleep",
    ):
        assert needle in deps_source


def test_task_worker_policy_does_not_drift_back_to_tasks_wrappers():
    source = TASKS.read_text()
    wrapper_sources = "\n".join(
        ast.get_source_segment(source, _function_node(TASKS, name)) or ""
        for name in (
            "fetch_due_tasks",
            "recover_stuck_tasks",
            "recover_stalled_workflow_runs",
            "task_worker",
        )
    )

    for forbidden in (
        "select(",
        ".with_for_update",
        "last_recovery_at",
        "last_workflow_sweep_at",
        "last_hygiene_check_at",
        "last_daily_summary_check_at",
        "task_timeout",
        "_set_step_states",
        "on_step_task_completed",
    ):
        assert forbidden not in wrapper_sources


def test_task_worker_host_owns_worker_and_recovery_orchestration():
    source = TASK_WORKER_HOST.read_text()
    for needle in (
        "select(Task)",
        ".with_for_update(skip_locked=True)",
        "resolve_task_timeout",
        "record_timeout_event",
        "fire_task_complete",
        "select(WorkflowRun)",
        "on_step_task_completed",
        "_set_step_states",
        "last_recovery_at",
        "last_workflow_sweep_at",
        "last_hygiene_check_at",
        "last_daily_summary_check_at",
        "spawn_due_widget_crons",
        "spawn_due_native_widget_ticks",
    ):
        assert needle in source
