"""Architecture guards for the ProjectTaskExecutionContext deepening.

AST-level checks that pin the boundary between
``app.services.project_task_execution_context`` (the deep Module) and
``app.services.project_coding_runs`` (the orchestration layer that consumes
it). Same shape as other ``test_*_architecture.py`` files in this repo.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_CODING_RUNS = _REPO_ROOT / "app" / "services" / "project_coding_runs.py"
_CONTEXT = _REPO_ROOT / "app" / "services" / "project_task_execution_context.py"


def _module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _all_imports(tree: ast.Module) -> list[ast.ImportFrom | ast.Import]:
    found: list[ast.ImportFrom | ast.Import] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            found.append(node)
    return found


def _function_local_imports(tree: ast.Module) -> list[ast.ImportFrom | ast.Import]:
    """Imports nested inside a function/method body, not at module top level."""
    out: list[ast.ImportFrom | ast.Import] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if sub is node:
                    continue
                if isinstance(sub, (ast.Import, ast.ImportFrom)):
                    out.append(sub)
    return out


def test_project_coding_runs_has_no_function_local_dependency_stacks_import():
    """The lazy ``from app.services.project_dependency_stacks import ...``
    inside ``_safe_dependency_stack_target`` is the smell that motivated the
    deepening. The new Module owns dependency-stack resolution at top level;
    this guard prevents the lazy import from coming back."""
    tree = _module(_CODING_RUNS)
    bad: list[str] = []
    for node in _function_local_imports(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "app.services.project_dependency_stacks":
            names = ", ".join(alias.name for alias in node.names)
            if "project_dependency_stack_spec" in names:
                bad.append(f"line {node.lineno}: from {node.module} import {names}")
    assert not bad, (
        "Lazy function-local import of project_dependency_stack_spec is back. "
        "It belongs at module top-level (or behind ProjectTaskExecutionContext): "
        + "; ".join(bad)
    )


def test_project_task_execution_context_does_not_import_project_coding_runs():
    """The new Module must not depend on the orchestration layer it deepens.

    A reverse import would re-introduce the cycle that motivated lazy imports
    in the first place. ``project_coding_runs`` consumes the new Module;
    never the other way.
    """
    tree = _module(_CONTEXT)
    bad: list[str] = []
    for node in _all_imports(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "app.services.project_coding_runs":
            bad.append(f"line {node.lineno}: from {node.module} import ...")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "app.services.project_coding_runs":
                    bad.append(f"line {node.lineno}: import {alias.name}")
    assert not bad, (
        "project_task_execution_context imports project_coding_runs — that's "
        "a cycle. The orchestration layer consumes the deep Module, never the "
        "reverse: " + "; ".join(bad)
    )


def test_project_coding_runs_imports_execution_context_at_top_level():
    """Production callers go through the new Module, top-level import — not
    a lazy in-function import."""
    tree = _module(_CODING_RUNS)
    top_level_names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "app.services.project_task_execution_context":
            for alias in node.names:
                top_level_names.add(alias.name)
    assert "ProjectTaskExecutionContext" in top_level_names, (
        "project_coding_runs.py must import ProjectTaskExecutionContext at "
        "module top level."
    )


def test_create_project_coding_run_uses_execution_context_fresh():
    """Verify the create-orchestration entry point delegates to the deepened
    Module via ``ProjectTaskExecutionContext.fresh`` rather than the old
    inline ``allocate_project_run_dev_targets`` + ``_execution_config_from_preset``
    pair."""
    tree = _module(_CODING_RUNS)
    create_fn: ast.AsyncFunctionDef | None = None
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "create_project_coding_run":
            create_fn = node
            break
    assert create_fn is not None, "create_project_coding_run not found"

    saw_fresh = False
    saw_apply_to_task = False
    saw_execution_config_from_preset = False
    for sub in ast.walk(create_fn):
        if isinstance(sub, ast.Attribute):
            if sub.attr == "fresh" and isinstance(sub.value, ast.Name) and sub.value.id == "ProjectTaskExecutionContext":
                saw_fresh = True
            if sub.attr == "apply_to_task":
                saw_apply_to_task = True
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
            if sub.func.id == "_execution_config_from_preset":
                saw_execution_config_from_preset = True

    assert saw_fresh, "create_project_coding_run must call ProjectTaskExecutionContext.fresh"
    assert saw_apply_to_task, "create_project_coding_run must call ctx.apply_to_task"
    assert not saw_execution_config_from_preset, (
        "create_project_coding_run still calls _execution_config_from_preset; "
        "should route through ctx.execution_config()/apply_to_task instead."
    )


def test_continue_project_coding_run_uses_from_parent():
    """Continuation goes through ``from_parent`` (which raises typed errors
    on malformed parent) rather than the silent ``cfg.get(...) or []`` fallback
    + manual re-allocation. Validates the user-decided behavior change."""
    tree = _module(_CODING_RUNS)
    continue_fn: ast.AsyncFunctionDef | None = None
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "continue_project_coding_run":
            continue_fn = node
            break
    assert continue_fn is not None, "continue_project_coding_run not found"

    saw_from_parent = False
    saw_allocate_call = False
    for sub in ast.walk(continue_fn):
        if isinstance(sub, ast.Attribute) and sub.attr == "from_parent":
            if isinstance(sub.value, ast.Name) and sub.value.id == "ProjectTaskExecutionContext":
                saw_from_parent = True
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
            if sub.func.id == "allocate_project_run_dev_targets":
                saw_allocate_call = True

    assert saw_from_parent, (
        "continue_project_coding_run must call ProjectTaskExecutionContext.from_parent"
    )
    assert not saw_allocate_call, (
        "continue_project_coding_run still calls allocate_project_run_dev_targets; "
        "the silent re-allocation fallback should be gone — parent context is "
        "reused verbatim, raises MalformedExecutionContextError on bad parent."
    )


def test_create_review_session_uses_execution_context_review():
    """Review session goes through ``ProjectTaskExecutionContext.review`` so
    runtime + dependency-stack resolution share the canonical seam."""
    tree = _module(_CODING_RUNS)
    fn: ast.AsyncFunctionDef | None = None
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "create_project_coding_run_review_session":
            fn = node
            break
    assert fn is not None, "create_project_coding_run_review_session not found"

    saw_review = False
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Attribute) and sub.attr == "review":
            if isinstance(sub.value, ast.Name) and sub.value.id == "ProjectTaskExecutionContext":
                saw_review = True

    assert saw_review, (
        "create_project_coding_run_review_session must call "
        "ProjectTaskExecutionContext.review"
    )
