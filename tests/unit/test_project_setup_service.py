from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from app.db.models import Project
from app.services.project_setup import _redact_with_values, build_project_setup_plan, execute_project_setup_plan


def _project(snapshot: dict) -> Project:
    return Project(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        name="Setup Project",
        slug="setup-project",
        root_path="common/projects/setup",
        metadata_={"blueprint_snapshot": snapshot},
    )


def test_setup_plan_uses_blueprint_snapshot_and_secret_bindings() -> None:
    project = _project(
        {
            "repos": [
                {
                    "name": "spindrel",
                    "url": "https://github.com/mtotho/spindrel.git",
                    "path": "repos/spindrel",
                    "branch": "main",
                }
            ],
            "env": {"NODE_ENV": "development"},
            "required_secrets": ["GITHUB_TOKEN", {"name": "NPM_TOKEN"}],
        }
    )
    bindings = [
        SimpleNamespace(logical_name="GITHUB_TOKEN", secret_value_id=uuid.uuid4(), secret_value=SimpleNamespace(name="github")),
        SimpleNamespace(logical_name="NPM_TOKEN", secret_value_id=None, secret_value=None),
    ]

    plan = build_project_setup_plan(project, bindings=bindings)

    assert plan["source"] == "blueprint_snapshot"
    assert plan["ready"] is False
    assert plan["missing_secrets"] == ["NPM_TOKEN"]
    assert plan["env"] == {"NODE_ENV": "development"}
    assert plan["repos"] == [
        {
            "name": "spindrel",
            "url": "https://github.com/mtotho/spindrel.git",
            "path": "repos/spindrel",
            "branch": "main",
            "status": "pending",
            "errors": [],
        }
    ]
    assert plan["secret_slots"][0]["bound"] is True
    assert plan["secret_slots"][0]["secret_value_name"] == "github"


def test_setup_plan_rejects_repo_paths_outside_project() -> None:
    project = _project(
        {
            "repos": [
                {"name": "bad", "url": "https://example.invalid/repo.git", "path": "../repo"},
                {"name": "root", "url": "https://example.invalid/root.git", "path": "."},
            ],
            "required_secrets": [],
        }
    )

    plan = build_project_setup_plan(project, bindings=[])

    assert plan["ready"] is False
    assert [repo["status"] for repo in plan["repos"]] == ["invalid", "invalid"]
    assert any("stay inside" in error for error in plan["repos"][0]["errors"])
    assert any("must not target the Project root" in error for error in plan["repos"][1]["errors"])


def test_setup_redaction_uses_project_secret_values() -> None:
    assert _redact_with_values(
        "clone failed with ghp_project_secret_token_123",
        {"GITHUB_TOKEN": "ghp_project_secret_token_123"},
    ) == "clone failed with [REDACTED]"


@pytest.mark.asyncio
async def test_execute_setup_clones_missing_repo_and_skips_existing(tmp_path) -> None:
    source = tmp_path / "source.git"
    work = tmp_path / "work"
    target_root = tmp_path / "project"
    proc = await asyncio.create_subprocess_exec("git", "init", "--bare", str(source))
    assert await proc.wait() == 0
    proc = await asyncio.create_subprocess_exec("git", "init", str(work))
    assert await proc.wait() == 0
    (work / "README.md").write_text("# Demo\n")
    for args in [
        ("-C", str(work), "config", "user.email", "test@example.invalid"),
        ("-C", str(work), "config", "user.name", "Test"),
        ("-C", str(work), "add", "README.md"),
        ("-C", str(work), "commit", "-m", "init"),
        ("-C", str(work), "branch", "-M", "main"),
        ("-C", str(work), "remote", "add", "origin", str(source)),
        ("-C", str(work), "push", "origin", "main"),
    ]:
        proc = await asyncio.create_subprocess_exec("git", *args)
        assert await proc.wait() == 0

    plan = {
        "ready": True,
        "repos": [
            {
                "name": "demo",
                "url": str(source),
                "path": "demo",
                "branch": "main",
                "status": "pending",
                "errors": [],
            }
        ],
        "env": {},
    }

    result = await execute_project_setup_plan(plan, project_root=str(target_root), secret_env={})
    second = await execute_project_setup_plan(plan, project_root=str(target_root), secret_env={})

    assert result["status"] == "succeeded"
    assert result["repos"][0]["status"] == "cloned"
    assert (target_root / "demo" / "README.md").read_text() == "# Demo\n"
    assert second["status"] == "succeeded"
    assert second["repos"][0]["status"] == "already_present"
