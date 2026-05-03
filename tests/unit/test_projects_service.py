from __future__ import annotations

import uuid
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import Project, ProjectInstance
from app.agent.context import current_project_instance_id
from app.services.project_instances import (
    project_directory_from_instance,
    project_instance_cleanup_summary,
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
        prompt_file_path=".spindrel/WORKFLOW.md",
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
    snapshot = project_blueprint_snapshot(blueprint)
    assert snapshot["required_secrets"] == ["GITHUB_TOKEN"]
    # Phase 4BB.3: orchestration policy fields are absent from the snapshot
    # when unset, so legacy snapshots stay byte-identical.
    assert "stall_timeout_seconds" not in snapshot
    assert "turn_timeout_seconds" not in snapshot
    assert "max_concurrent_runs" not in snapshot

    second = materialize_project_blueprint(project_dir, blueprint)
    assert second.payload()["files_skipped"] == ["README.md"]
    assert second.payload()["knowledge_files_skipped"] == ["overview.md"]


def test_normalize_project_intake_kind_accepts_known_kinds_and_rejects_others():
    """Phase 4BD.1 - intake_kind must be one of the four known values."""
    from app.services.projects import (
        PROJECT_INTAKE_KINDS,
        normalize_project_intake_kind,
    )

    assert set(PROJECT_INTAKE_KINDS) == {"unset", "repo_file", "repo_folder", "external_tracker"}
    assert normalize_project_intake_kind(None) == "unset"
    assert normalize_project_intake_kind("UNSET") == "unset"
    assert normalize_project_intake_kind(" repo_file ") == "repo_file"
    for kind in PROJECT_INTAKE_KINDS:
        assert normalize_project_intake_kind(kind) == kind

    for bad in ("github", "github_issues", "tracker", ""):
        with pytest.raises(ValueError):
            normalize_project_intake_kind(bad)
    with pytest.raises(ValueError):
        normalize_project_intake_kind(42)


def test_project_intake_config_resolves_host_target_against_canonical_repo(monkeypatch, tmp_path):
    """Phase 4BD.1 - host_target joins canonical repo path with relative target for repo kinds."""
    from app.services import projects as projects_module
    from app.services.projects import project_intake_config

    workspace_id = uuid.uuid4()
    project = Project(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        name="P",
        slug="p",
        root_path="common/projects/p",
        metadata_={"blueprint_snapshot": {"repos": [{"path": "app", "canonical": True}]}},
        intake_kind="repo_file",
        intake_target="docs/inbox.md",
        intake_metadata={"format": "spindrel-md"},
    )

    monkeypatch.setattr(
        projects_module,
        "project_directory_from_project",
        lambda _: SimpleNamespace(host_path=str(tmp_path / "common/projects/p")),
    )

    config = project_intake_config(project)
    assert config["kind"] == "repo_file"
    assert config["target"] == "docs/inbox.md"
    assert config["metadata"] == {"format": "spindrel-md"}
    assert config["configured"] is True
    assert config["host_target"] == str(tmp_path / "common/projects/p/app/docs/inbox.md")

    # Unset projects expose the full shape with host_target=None.
    project.intake_kind = "unset"
    project.intake_target = None
    project.intake_metadata = {}
    bare = project_intake_config(project)
    assert bare == {
        "kind": "unset",
        "target": None,
        "metadata": {},
        "host_target": None,
        "configured": False,
    }

    # External tracker keeps target but never resolves a host path.
    project.intake_kind = "external_tracker"
    project.intake_target = "https://github.com/me/repo/issues"
    project.intake_metadata = {"tracker": "github"}
    external = project_intake_config(project)
    assert external["kind"] == "external_tracker"
    assert external["target"] == "https://github.com/me/repo/issues"
    assert external["host_target"] is None
    assert external["configured"] is True


def test_project_canonical_repo_helpers_resolve_explicit_flag_then_first():
    """Phase 4BD.0 - canonical: true wins, otherwise first repo wins, None for empty."""
    from app.services.projects import (
        project_canonical_repo_entry,
        project_canonical_repo_relative_path,
    )

    snapshot_explicit = {
        "repos": [
            {"path": "docs", "branch": "main"},
            {"path": "app", "branch": "main", "canonical": True},
        ]
    }
    entry = project_canonical_repo_entry(snapshot_explicit)
    assert entry is not None and entry["path"] == "app"
    assert project_canonical_repo_relative_path(snapshot_explicit) == "app"

    snapshot_fallback = {"repos": [{"path": "docs"}, {"path": "app"}]}
    fallback = project_canonical_repo_entry(snapshot_fallback)
    assert fallback is not None and fallback["path"] == "docs"

    snapshot_canonical_false_ignored = {
        "repos": [
            {"path": "docs", "canonical": False},
            {"path": "app"},
        ]
    }
    # canonical: false is the same as no flag - first wins
    assert project_canonical_repo_entry(snapshot_canonical_false_ignored)["path"] == "docs"

    assert project_canonical_repo_entry(None) is None
    assert project_canonical_repo_entry({}) is None
    assert project_canonical_repo_entry({"repos": []}) is None
    assert project_canonical_repo_relative_path({"repos": [{"branch": "main"}]}) is None  # no path


def test_validate_blueprint_repos_canonical_rejects_multiple_flags():
    """At most one repo entry may be flagged canonical."""
    import pytest as _pytest

    from app.services.projects import validate_blueprint_repos_canonical

    # No-op cases
    validate_blueprint_repos_canonical(None)
    validate_blueprint_repos_canonical([])
    validate_blueprint_repos_canonical([{"path": "a", "canonical": True}])
    validate_blueprint_repos_canonical([{"path": "a"}, {"path": "b"}])
    validate_blueprint_repos_canonical([
        {"path": "a", "canonical": True},
        {"path": "b", "canonical": False},
    ])

    with _pytest.raises(ValueError, match="At most one"):
        validate_blueprint_repos_canonical([
            {"path": "a", "canonical": True},
            {"path": "b", "canonical": True},
        ])


def test_project_blueprint_write_rejects_non_positive_orchestration_values():
    """Validator guards against zero / negative timeouts and concurrency caps."""
    import pytest as _pytest
    from pydantic import ValidationError

    from app.routers.api_v1_projects import ProjectBlueprintWrite

    # Null is the "use default" sentinel and must be allowed.
    ProjectBlueprintWrite(stall_timeout_seconds=None, turn_timeout_seconds=None, max_concurrent_runs=None)

    for field in ("stall_timeout_seconds", "turn_timeout_seconds", "max_concurrent_runs"):
        with _pytest.raises(ValidationError):
            ProjectBlueprintWrite(**{field: 0})
        with _pytest.raises(ValidationError):
            ProjectBlueprintWrite(**{field: -5})


def test_project_blueprint_snapshot_emits_orchestration_policy_when_set():
    """Phase 4BB.3 - stall/turn/concurrency fields ride along when configured."""
    blueprint = SimpleNamespace(
        id=uuid.uuid4(),
        name="Policy",
        slug="policy",
        default_root_path_pattern=None,
        prompt_file_path=None,
        folders=[],
        files={},
        knowledge_files={},
        repos=[],
        setup_commands=[],
        dependency_stack={},
        env={},
        required_secrets=[],
        metadata_={},
        stall_timeout_seconds=600,
        turn_timeout_seconds=2700,
        max_concurrent_runs=3,
    )
    snapshot = project_blueprint_snapshot(blueprint)
    assert snapshot["stall_timeout_seconds"] == 600
    assert snapshot["turn_timeout_seconds"] == 2700
    assert snapshot["max_concurrent_runs"] == 3


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


def test_project_instance_cleanup_summary_blocks_active_task_instances():
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    instance = ProjectInstance(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        root_path="common/project-instances/demo/abcdef",
        status="ready",
        owner_kind="task",
        owner_id=uuid.uuid4(),
        expires_at=now - timedelta(hours=1),
    )

    active = project_instance_cleanup_summary(instance, task_status="running", now=now)
    complete = project_instance_cleanup_summary(instance, task_status="complete", now=now)

    assert active["expired"] is True
    assert active["can_cleanup"] is False
    assert "active run" in active["blocker"]
    assert complete["can_cleanup"] is True
    assert complete["auto_cleanup_eligible"] is True


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
        prompt="Inline project instructions.",
        prompt_file_path=".spindrel/WORKFLOW.md",
    )
    project_dir = project_directory_from_project(project)
    prompt_file = tmp_path / "shared" / str(workspace_id) / "common" / "projects" / ".spindrel" / "WORKFLOW.md"
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
    assert surface.prompt == "Inline project instructions.\n\nPrompt from file."
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
