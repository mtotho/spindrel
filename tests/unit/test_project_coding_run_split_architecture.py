"""Architecture guards for the four-module split of ``project_coding_runs``.

After 2026-05-01, ``app.services.project_coding_runs`` is a re-export facade.
The canonical owners are:

- ``project_coding_run_lib`` — shared types, utilities, read endpoints
- ``project_coding_run_orchestration`` — create + continue
- ``project_coding_run_review`` — review session, finalize, mark-reviewed,
  cleanup, review-context endpoint
- ``project_run_schedule`` — schedule CRUD, firing, listing

Each lifecycle is independent. The single allowed cross-lifecycle import is
``schedule → orchestration.create_project_coding_run`` (a schedule fire
spawns a fresh coding run). Lib must not import any of the three lifecycle
modules — that would be a cycle.

These guards are AST-only: they don't import the modules, so the test runs
without DB or settings.
"""
from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SERVICES = _REPO_ROOT / "app" / "services"
_FACADE = _SERVICES / "project_coding_runs.py"
_LIB = _SERVICES / "project_coding_run_lib.py"
_ORCHESTRATION = _SERVICES / "project_coding_run_orchestration.py"
_REVIEW = _SERVICES / "project_coding_run_review.py"
_SCHEDULE = _SERVICES / "project_run_schedule.py"

_LIFECYCLE_MODULES = {
    "app.services.project_coding_run_orchestration",
    "app.services.project_coding_run_review",
    "app.services.project_run_schedule",
}


def _module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _imported_modules(tree: ast.Module, *, include_lazy: bool = True) -> set[str]:
    """Collect every fully-qualified module that this tree imports.

    ``include_lazy=True`` walks function bodies too — important because the
    schedule fire path uses a lazy import to dodge cycle-at-load-time.
    """
    found: set[str] = set()
    walker = ast.walk(tree) if include_lazy else iter(tree.body)
    for node in walker:
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
    return found


def test_project_coding_runs_is_a_facade_only():
    """``project_coding_runs.py`` must contain no executable bodies — only
    re-export ``from ... import ...`` statements (and the module docstring /
    ``from __future__``).

    Regression target: the file used to be 1,950 LOC with three lifecycles
    bundled in. The split moved every body to a canonical owner; this guard
    pins the facade shape so the bundling can't grow back.
    """
    tree = _module(_FACADE)
    illegal: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            # Module docstring (or string in expression position) is fine.
            continue
        if isinstance(node, ast.Assign):
            # ``__all__ = [...]`` style re-export hints are fine; nothing else.
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if targets == ["__all__"]:
                continue
            illegal.append(f"line {node.lineno}: {ast.dump(node)[:80]}")
            continue
        illegal.append(f"line {node.lineno}: {type(node).__name__} ({getattr(node, 'name', '')})")
    assert not illegal, (
        "project_coding_runs.py must be re-export only — no def/class/assign "
        "bodies. Found: " + "; ".join(illegal)
    )


def test_orchestration_module_does_not_import_review_or_schedule():
    """Orchestration is independent of the other two lifecycles."""
    tree = _module(_ORCHESTRATION)
    imported = _imported_modules(tree)
    forbidden = imported & {
        "app.services.project_coding_run_review",
        "app.services.project_run_schedule",
        "app.services.project_coding_runs",
    }
    assert not forbidden, (
        "project_coding_run_orchestration.py imports from another lifecycle "
        "module: " + ", ".join(sorted(forbidden))
    )


def test_review_module_does_not_import_orchestration_or_schedule():
    """Review is independent of orchestration and schedule. It uses the
    deepened ``ProjectTaskExecutionContext`` directly via lib."""
    tree = _module(_REVIEW)
    imported = _imported_modules(tree)
    forbidden = imported & {
        "app.services.project_coding_run_orchestration",
        "app.services.project_run_schedule",
        "app.services.project_coding_runs",
    }
    assert not forbidden, (
        "project_coding_run_review.py imports from another lifecycle "
        "module: " + ", ".join(sorted(forbidden))
    )


def test_schedule_fires_through_orchestration():
    """Schedule's ``fire_project_coding_run_schedule`` is the one allowed
    cross-lifecycle import: it spawns a fresh coding run by calling
    ``create_project_coding_run`` from orchestration. Schedule must NOT
    import from review, and must NOT bounce through the facade."""
    tree = _module(_SCHEDULE)
    imported = _imported_modules(tree)
    forbidden = imported & {
        "app.services.project_coding_run_review",
        "app.services.project_coding_runs",
    }
    assert not forbidden, (
        "project_run_schedule.py imports from review or the facade: "
        + ", ".join(sorted(forbidden))
    )
    assert "app.services.project_coding_run_orchestration" in imported, (
        "project_run_schedule.py must import from "
        "project_coding_run_orchestration (the schedule-fire seam)."
    )


def test_lib_does_not_import_lifecycle_modules():
    """Lib is the shared substrate. Importing any lifecycle module from lib
    would close a cycle (lifecycle → lib → lifecycle)."""
    tree = _module(_LIB)
    imported = _imported_modules(tree)
    forbidden = imported & (_LIFECYCLE_MODULES | {"app.services.project_coding_runs"})
    assert not forbidden, (
        "project_coding_run_lib.py imports from a lifecycle/facade module: "
        + ", ".join(sorted(forbidden))
    )
