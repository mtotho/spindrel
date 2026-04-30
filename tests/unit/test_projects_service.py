from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.db.models import Project, ProjectInstance
from app.agent.context import current_project_instance_id
from app.services.project_instances import (
    project_directory_from_instance,
    project_instance_root_path,
    task_project_instance_policy,
    work_surface_from_project_instance,
)
from app.services.projects import (
    PROJECT_KB_PATH,
    WorkSurfaceResolutionError,
    is_project_like_surface,
    materialize_project_blueprint,
    materialize_project_blueprint_snapshot,
    normalize_project_path,
    project_blueprint_snapshot,
    project_directory_from_project,
    project_knowledge_base_index_prefix,
    project_workspace_path,
    render_project_blueprint_root_path,
    resolve_channel_work_surface,
)


def test_normalize_project_path_accepts_multi_repo_roots():
    assert normalize_project_path("/common/projects/") == "common/projects"
    assert normalize_project_path("common//projects/./spindrel") == "common/projects/spindrel"


def test_normalize_project_path_rejects_escape():
    with pytest.raises(ValueError):
        normalize_project_path("../outside")


def test_render_project_blueprint_root_path_uses_slug_tokens():
    assert render_project_blueprint_root_path(
        "common/projects/{slug}",
        project_name="My API",
        project_slug="my-api",
    ) == "common/projects/my-api"
    assert render_project_blueprint_root_path(
        "common/projects/{name}",
        project_name="My API",
        project_slug="custom",
    ) == "common/projects/my-api"


def test_materialize_project_blueprint_creates_starter_surface(tmp_path):
    project_dir = SimpleNamespace(host_path=str(tmp_path / "project"))
    blueprint = SimpleNamespace(
        id=uuid.uuid4(),
        name="Starter",
        slug="starter",
        default_root_path_pattern="common/projects/{slug}",
        prompt_file_path=".spindrel/project-prompt.md",
        folders=["docs"],
        files={"README.md": "# Starter\n"},
        knowledge_files={"overview.md": "Knowledge\n"},
        repos=[{"name": "app"}],
        env={"NODE_ENV": "development"},
        required_secrets=["GITHUB_TOKEN"],
        metadata_={"kind": "test"},
    )
    result = materialize_project_blueprint(project_dir, blueprint)

    assert result.payload()["folders_created"] == ["docs"]
    assert result.payload()["files_written"] == ["README.md"]
    assert (tmp_path / "project" / "docs").is_dir()
    assert (tmp_path / "project" / "README.md").read_text() == "# Starter\n"
    assert (tmp_path / "project" / PROJECT_KB_PATH / "overview.md").read_text() == "Knowledge\n"
    assert project_blueprint_snapshot(blueprint)["required_secrets"] == ["GITHUB_TOKEN"]

    second = materialize_project_blueprint(project_dir, blueprint)
    assert second.payload()["files_skipped"] == ["README.md"]
    assert second.payload()["knowledge_files_skipped"] == ["overview.md"]


def test_materialize_project_blueprint_snapshot_reuses_blueprint_policy(tmp_path):
    project_dir = SimpleNamespace(host_path=str(tmp_path / "instance"))
    snapshot = {
        "folders": ["app"],
        "files": {"app/README.md": "Fresh\n"},
        "knowledge_files": {"overview.md": "Instance KB\n"},
    }

    result = materialize_project_blueprint_snapshot(project_dir, snapshot)

    assert result.files_written == ["app/README.md"]
    assert (tmp_path / "instance" / "app" / "README.md").read_text() == "Fresh\n"
    assert (tmp_path / "instance" / PROJECT_KB_PATH / "overview.md").read_text() == "Instance KB\n"


def test_project_instance_work_surface_keeps_parent_project_policy(monkeypatch, tmp_path):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    instance_id = uuid.uuid4()
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
    )
    instance = ProjectInstance(
        id=instance_id,
        workspace_id=workspace_id,
        project_id=project_id,
        root_path=project_instance_root_path(project, instance_id),
        status="ready",
        source_snapshot={},
        setup_result={},
        metadata_={},
    )

    project_dir = project_directory_from_instance(instance, project)
    surface = work_surface_from_project_instance(instance, project, channel_id=uuid.uuid4(), prompt="Project prompt")

    assert project_dir.project_id == str(project_id)
    assert project_dir.project_instance_id == str(instance_id)
    assert surface.kind == "project_instance"
    assert surface.project_id == str(project_id)
    assert surface.project_instance_id == str(instance_id)
    assert surface.index_prefix == instance.root_path
    assert surface.prompt == "Project prompt"
    assert is_project_like_surface(surface) is True


def test_task_project_instance_policy_accepts_nested_and_shortcut_forms():
    assert task_project_instance_policy({"project_instance": {"mode": "fresh"}}).fresh is True
    assert task_project_instance_policy({"fresh_project_instance": True}).fresh is True
    assert task_project_instance_policy({"project_instance": {"mode": "shared"}}).fresh is False


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


@pytest.mark.asyncio
async def test_project_work_surface_fails_when_bound_project_is_missing():
    project_id = uuid.uuid4()
    channel = SimpleNamespace(id=uuid.uuid4(), project_id=project_id, config={}, workspace_id=None, name="Broken")
    bot = SimpleNamespace(id="test-bot", shared_workspace_id=str(uuid.uuid4()))

    class _DB:
        async def get(self, model, value):
            assert model is Project
            assert value == project_id
            return None

    with pytest.raises(WorkSurfaceResolutionError, match="Project binding is broken"):
        await resolve_channel_work_surface(_DB(), channel, bot)


@pytest.mark.asyncio
async def test_project_instance_surface_must_belong_to_channel_project(monkeypatch, tmp_path):
    workspace_id = uuid.uuid4()
    channel_project_id = uuid.uuid4()
    other_project_id = uuid.uuid4()
    instance_id = uuid.uuid4()
    monkeypatch.setattr(
        "app.services.shared_workspace.local_workspace_base",
        lambda: str(tmp_path),
    )
    channel = SimpleNamespace(id=uuid.uuid4(), project_id=channel_project_id, config={}, workspace_id=None, name="Project channel")
    bot = SimpleNamespace(id="test-bot", shared_workspace_id=str(workspace_id))
    other_project = Project(
        id=other_project_id,
        workspace_id=workspace_id,
        name="Other Project",
        slug="other-project",
        root_path="common/projects/other",
    )
    instance = ProjectInstance(
        id=instance_id,
        workspace_id=workspace_id,
        project_id=other_project_id,
        root_path="common/project-instances/other/instance",
        status="ready",
        source_snapshot={},
        setup_result={},
        metadata_={},
    )

    class _DB:
        async def get(self, model, value):
            if model is ProjectInstance and value == instance_id:
                return instance
            if model is Project and value == other_project_id:
                return other_project
            if model is Project and value == channel_project_id:
                return Project(
                    id=channel_project_id,
                    workspace_id=workspace_id,
                    name="Channel Project",
                    slug="channel-project",
                    root_path="common/projects/channel",
                )
            return None

    token = current_project_instance_id.set(instance_id)
    try:
        with pytest.raises(WorkSurfaceResolutionError, match="does not belong"):
            await resolve_channel_work_surface(_DB(), channel, bot)
    finally:
        current_project_instance_id.reset(token)
