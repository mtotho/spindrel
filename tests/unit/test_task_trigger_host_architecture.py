"""Architecture guards for task trigger host orchestration."""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TASKS = REPO_ROOT / "app" / "agent" / "tasks.py"
TASK_TRIGGER_HOST = REPO_ROOT / "app" / "agent" / "task_trigger_host.py"


def _function_node(path: Path, name: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{path}: missing function {name}")


def test_task_trigger_wrappers_stay_small():
    for name in (
        "_parse_recurrence",
        "validate_recurrence",
        "_spawn_from_schedule",
        "spawn_due_schedules",
        "_fire_subscription",
        "spawn_due_subscriptions",
        "_matches_event_filter",
        "_spawn_from_event_trigger",
        "fire_event_triggers",
    ):
        node = _function_node(TASKS, name)
        assert node.end_lineno is not None
        loc = node.end_lineno - node.lineno + 1
        assert loc <= 12


def test_task_trigger_wrappers_pass_patchable_dependencies():
    source = TASKS.read_text()
    deps_source = ast.get_source_segment(source, _function_node(TASKS, "_task_trigger_deps"))
    assert deps_source is not None

    for needle in (
        "async_session=async_session",
        "spawn_from_schedule=_spawn_from_schedule",
        "fire_subscription=_fire_subscription",
        "matches_event_filter=_matches_event_filter",
        "spawn_from_event_trigger=_spawn_from_event_trigger",
    ):
        assert needle in deps_source


def test_task_trigger_policy_does_not_drift_back_to_tasks_wrappers():
    source = TASKS.read_text()
    wrapper_sources = "\n".join(
        ast.get_source_segment(source, _function_node(TASKS, name)) or ""
        for name in (
            "_spawn_from_schedule",
            "spawn_due_schedules",
            "_fire_subscription",
            "spawn_due_subscriptions",
            "_spawn_from_event_trigger",
            "fire_event_triggers",
        )
    )

    for forbidden in (
        "select(",
        "Task(",
        "resolve_prompt",
        "ChannelPipelineSubscription",
        "spawn_child_run",
        "trigger_config",
        "run_count",
        "sub.next_fire_at",
    ):
        assert forbidden not in wrapper_sources


def test_task_trigger_host_owns_trigger_orchestration():
    source = TASK_TRIGGER_HOST.read_text()
    for needle in (
        "select(Task.id)",
        "Task(",
        "resolve_prompt",
        "ChannelPipelineSubscription",
        "spawn_child_run",
        "trigger_config",
        "event_data",
        "next_fire_at",
        "run_count",
    ):
        assert needle in source
