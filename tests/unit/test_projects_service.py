from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.db.models import Project
from app.services.projects import (
    PROJECT_KB_PATH,
    normalize_project_path,
    project_directory_from_project,
    project_knowledge_base_index_prefix,
    project_workspace_path,
    resolve_channel_work_surface,
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


@pytest.mark.asyncio
async def test_project_work_surface_exposes_policy(monkeypatch, tmp_path):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    monkeypatch.setattr(
        "app.services.shared_workspace.local_workspace_base",
        lambda: str(tmp_path),
    )
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Common Projects",
        slug="common-projects",
        root_path="common/projects",
        prompt="Inline project prompt.",
        prompt_file_path=".spindrel/project-prompt.md",
    )
    project_dir = project_directory_from_project(project)
    prompt_file = tmp_path / "shared" / str(workspace_id) / "common" / "projects" / ".spindrel" / "project-prompt.md"
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text("Prompt from file.")
    channel_id = uuid.uuid4()
    channel = SimpleNamespace(id=channel_id, project_id=project_id, config={}, workspace_id=None, name="Demo")
    bot = SimpleNamespace(id="test-bot", shared_workspace_id=str(workspace_id))

    class _DB:
        async def get(self, model, value):
            assert model is Project
            assert value == project_id
            return project

    surface = await resolve_channel_work_surface(_DB(), channel, bot, include_prompt=True)

    assert surface is not None
    assert surface.kind == "project"
    assert surface.root_host_path == project_dir.host_path
    assert surface.display_path == "/workspace/common/projects"
    assert surface.index_root_host_path == str((tmp_path / "shared" / str(workspace_id)).resolve())
    assert surface.index_prefix == "common/projects"
    assert surface.knowledge_index_prefix == f"common/projects/{PROJECT_KB_PATH}"
    assert surface.project_id == str(project_id)
    assert surface.project_name == "Common Projects"
    assert surface.channel_id == str(channel_id)
    assert surface.prompt == "Inline project prompt.\n\nPrompt from file."
    assert surface.payload()["project_id"] == str(project_id)


@pytest.mark.asyncio
async def test_channel_work_surface_exposes_channel_policy(monkeypatch, tmp_path):
    workspace_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    monkeypatch.setattr(
        "app.services.shared_workspace.local_workspace_base",
        lambda: str(tmp_path),
    )
    channel = SimpleNamespace(id=channel_id, project_id=None, config={}, workspace_id=None, name="Room")
    bot = SimpleNamespace(id="test-bot", shared_workspace_id=str(workspace_id))

    surface = await resolve_channel_work_surface(SimpleNamespace(), channel, bot)

    assert surface is not None
    assert surface.kind == "channel"
    assert surface.root_host_path == str(tmp_path / "shared" / str(workspace_id) / "channels" / str(channel_id))
    assert surface.display_path == f"/workspace/channels/{channel_id}"
    assert surface.index_root_host_path == str((tmp_path / "shared" / str(workspace_id)).resolve())
    assert surface.index_prefix == f"channels/{channel_id}"
    assert surface.knowledge_index_prefix == f"channels/{channel_id}/knowledge-base"
    assert surface.workspace_id == str(workspace_id)
