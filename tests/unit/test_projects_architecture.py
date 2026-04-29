"""Architecture guards for Project work-surface deepening."""

from __future__ import annotations

import ast
from pathlib import Path


FORBIDDEN_PROJECT_HELPERS = {
    "resolve_channel_project_directory",
    "resolve_project_directory_for_channel_id",
    "project_workspace_path",
    "project_knowledge_base_index_prefix",
}


def test_project_callers_use_work_surface_interface() -> None:
    root = Path(__file__).resolve().parents[2] / "app"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        if rel == Path("services/projects.py"):
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module != "app.services.projects":
                continue
            imported = {alias.name for alias in node.names}
            forbidden = sorted(imported & FORBIDDEN_PROJECT_HELPERS)
            if forbidden:
                offenders.append(f"{rel}:{node.lineno} imports {', '.join(forbidden)}")

    assert offenders == []
