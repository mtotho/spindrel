from __future__ import annotations

import uuid

import pytest

from app.db.models import Project
from app.services.project_run_environment_profiles import (
    approve_run_environment_profile_hash,
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
