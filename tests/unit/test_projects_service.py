from __future__ import annotations

import uuid

import pytest

from app.db.models import Project
from app.services.projects import (
    PROJECT_KB_PATH,
    normalize_project_path,
    project_directory_from_project,
    project_knowledge_base_index_prefix,
    project_workspace_path,
)


def test_normalize_project_path_accepts_multi_repo_roots():
    assert normalize_project_path("/common/projects/") == "common/projects"
    assert normalize_project_path("common//projects/./spindrel") == "common/projects/spindrel"


def test_normalize_project_path_rejects_escape():
    with pytest.raises(ValueError):
        normalize_project_path("../outside")


def test_project_directory_stays_inside_shared_workspace(monkeypatch, tmp_path):
    workspace_id = uuid.uuid4()
    monkeypatch.setattr(
        "app.services.shared_workspace.local_workspace_base",
        lambda: str(tmp_path),
    )
    project = Project(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        name="Common Projects",
        slug="common-projects",
        root_path="common/projects",
    )

    project_dir = project_directory_from_project(project)

    assert project_dir.workspace_id == str(workspace_id)
    assert project_dir.path == "common/projects"
    assert project_workspace_path(project_dir) == "/workspace/common/projects"
    assert project_knowledge_base_index_prefix(project_dir) == f"common/projects/{PROJECT_KB_PATH}"
    assert (tmp_path / "shared" / str(workspace_id) / "common" / "projects" / PROJECT_KB_PATH).is_dir()
