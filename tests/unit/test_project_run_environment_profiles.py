from __future__ import annotations

import uuid

import pytest

from app.db.models import Project
from app.services.project_run_environment_profiles import (
    approve_run_environment_profile_hash,
    validate_project_run_environment_profile_or_raise,
    validate_project_run_environment_profile_selection,
    validate_run_environment_profile,
)


@pytest.mark.asyncio
async def test_validate_run_environment_profile_allows_shared_repo_non_mutating_blueprint(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    project = Project(
        id=uuid.uuid4(),
        name="Profile Project",
        root_path="common/projects/profile",
        metadata_={
            "blueprint_snapshot": {
                "run_environment_profiles": {
                    "check-only": {
                        "readiness_checks": ["test -f README.md"],
                        "required_artifacts": ["README.md"],
                    }
                }
            }
        },
    )

    result = await validate_run_environment_profile(
        project,
        "check-only",
        cwd=str(root),
        work_surface_mode="shared_repo",
    )

    assert result["ok"] is True
    assert result["source_layer"] == "blueprint_snapshot"


@pytest.mark.asyncio
async def test_validate_run_environment_profile_rejects_shared_repo_mutating_without_opt_in(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    project = Project(
        id=uuid.uuid4(),
        name="Profile Project",
        root_path="common/projects/profile",
        metadata_={
            "blueprint_snapshot": {
                "run_environment_profiles": {
                    "setup": {
                        "setup_commands": ["touch generated.txt"],
                    }
                }
            }
        },
    )

    result = await validate_run_environment_profile(
        project,
        "setup",
        cwd=str(root),
        work_surface_mode="shared_repo",
    )

    assert result["ok"] is False
    assert "shared_repo profiles with setup commands" in result["error"]


def test_approve_run_environment_profile_hash_records_metadata():
    project = Project(
        id=uuid.uuid4(),
        name="Profile Project",
        root_path="common/projects/profile",
        metadata_={},
    )
    digest = "b" * 64

    result = approve_run_environment_profile_hash(
        project,
        profile_id="harness-parity",
        sha256=digest,
        approved_by="admin",
    )

    assert result["profile_id"] == "harness-parity"
    assert result["sha256"] == digest
    assert project.metadata_["run_environment_profile_approvals"]["harness-parity"]["sha256"] == digest


def test_approve_run_environment_profile_hash_rejects_invalid_digest():
    project = Project(
        id=uuid.uuid4(),
        name="Profile Project",
        root_path="common/projects/profile",
        metadata_={},
    )

    with pytest.raises(ValueError, match="sha256"):
        approve_run_environment_profile_hash(
            project,
            profile_id="harness-parity",
            sha256="not-a-hash",
            approved_by="admin",
        )


@pytest.mark.asyncio
async def test_validate_project_run_environment_profile_selection_reports_missing_profile(tmp_path, monkeypatch):
    from app.services import project_run_environment_profiles as profiles

    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(profiles, "project_repo_host_path", lambda *_args, **_kwargs: str(root))
    project = Project(
        id=uuid.uuid4(),
        name="Profile Project",
        root_path="common/projects/profile",
        metadata_={"blueprint_snapshot": {"repos": [{"path": root.name, "branch": "main"}]}},
    )

    result = await validate_project_run_environment_profile_selection(
        project,
        profile_id="missing",
        repo_path=root.name,
        work_surface_mode="isolated_worktree",
    )

    assert result["ok"] is False
    assert result["configured"] is True
    assert result["status"] == "blocked"
    assert result["cwd"]
    assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_validate_project_run_environment_profile_selection_preserves_needs_review_status(tmp_path, monkeypatch):
    from app.services import project_run_environment_profiles as profiles

    root = tmp_path / "repo"
    profile_dir = root / ".spindrel" / "profiles"
    profile_dir.mkdir(parents=True)
    (profile_dir / "setup.yaml").write_text("setup_commands:\n  - echo ready\n", encoding="utf-8")
    monkeypatch.setattr(profiles, "project_repo_host_path", lambda *_args, **_kwargs: str(root))
    project = Project(
        id=uuid.uuid4(),
        name="Profile Project",
        root_path="common/projects/profile",
        metadata_={
            "trust_repo_environment_profiles": True,
            "blueprint_snapshot": {"repos": [{"path": root.name, "branch": "main"}]},
        },
    )

    result = await validate_project_run_environment_profile_selection(
        project,
        profile_id="setup",
        repo_path=root.name,
        work_surface_mode="isolated_worktree",
    )

    assert result["ok"] is False
    assert result["status"] == "needs_review"
    assert result["current_hash"]
    assert result["approved_hash"] is None


@pytest.mark.asyncio
async def test_validate_project_run_environment_profile_or_raise_blocks_bad_schedule_profile(tmp_path, monkeypatch):
    from app.services import project_run_environment_profiles as profiles

    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(profiles, "project_repo_host_path", lambda *_args, **_kwargs: str(root))
    project = Project(
        id=uuid.uuid4(),
        name="Profile Project",
        root_path="common/projects/profile",
        metadata_={
            "blueprint_snapshot": {
                "repos": [{"path": root.name, "branch": "main"}],
                "run_environment_profiles": {
                    "bad-shared": {"setup_commands": ["touch generated.txt"]},
                },
            }
        },
    )

    with pytest.raises(ValueError, match="shared_repo profiles with setup commands"):
        await validate_project_run_environment_profile_or_raise(
            project,
            profile_id="bad-shared",
            repo_path=root.name,
            work_surface_mode="shared_repo",
        )
