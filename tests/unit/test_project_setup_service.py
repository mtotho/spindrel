from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from app.db.models import Project
from app.services.project_setup import (
    DEFAULT_SETUP_COMMAND_TIMEOUT_SECONDS,
    _redact_with_values,
    build_project_setup_plan,
    execute_project_setup_plan,
)


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
            "setup_commands": [{"name": "Install", "command": "npm install", "cwd": "repos/spindrel", "timeout_seconds": 60}],
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
    assert plan["commands"] == [
        {
            "name": "Install",
            "command": "npm install",
            "cwd": "repos/spindrel",
            "timeout_seconds": 60,
            "status": "pending",
            "errors": [],
        }
    ]
    assert plan["secret_slots"][0]["bound"] is True
    assert plan["secret_slots"][0]["secret_value_name"] == "github"
    assert plan["runtime"]["env_default_keys"] == ["NODE_ENV"]
    assert plan["runtime"]["secret_keys"] == ["GITHUB_TOKEN"]
    assert plan["runtime"]["missing_secrets"] == ["NPM_TOKEN"]


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


def test_setup_plan_accepts_command_only_blueprint() -> None:
    project = _project(
        {
            "setup_commands": [
                {"name": "Bootstrap", "command": "npm install", "cwd": "app"},
                "echo done",
            ],
            "required_secrets": [],
        }
    )

    plan = build_project_setup_plan(project, bindings=[])

    assert plan["ready"] is True
    assert plan["repos"] == []
    assert plan["commands"][0]["name"] == "Bootstrap"
    assert plan["commands"][0]["cwd"] == "app"
    assert plan["commands"][0]["timeout_seconds"] == DEFAULT_SETUP_COMMAND_TIMEOUT_SECONDS
    assert plan["commands"][1]["name"] == "Command 2"
    assert plan["commands"][1]["command"] == "echo done"


def test_setup_plan_rejects_invalid_commands() -> None:
    project = _project(
        {
            "setup_commands": [
                {"name": "Blank", "command": ""},
                {"name": "Escapes", "command": "echo no", "cwd": "../elsewhere"},
                {"name": "Slow", "command": "echo no", "timeout_seconds": 3601},
            ],
            "required_secrets": [],
        }
    )

    plan = build_project_setup_plan(project, bindings=[])

    assert plan["ready"] is False
    assert plan["reasons"] == ["invalid_commands"]
    assert [command["status"] for command in plan["commands"]] == ["invalid", "invalid", "invalid"]
    assert any("command is required" in error for error in plan["commands"][0]["errors"])
    assert any("stay inside" in error for error in plan["commands"][1]["errors"])
    assert any("between 1 and 3600" in error for error in plan["commands"][2]["errors"])


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


@pytest.mark.asyncio
async def test_execute_setup_runs_commands_with_project_env_and_redacts_output(tmp_path) -> None:
    project_root = tmp_path / "project"
    plan = {
        "ready": True,
        "repos": [],
        "commands": [
            {
                "name": "Write marker",
                "command": "printf '%s' \"$PROJECT_KIND\" > marker.txt && printf '%s' \"$GITHUB_TOKEN\"",
                "cwd": "",
                "timeout_seconds": 10,
                "status": "pending",
                "errors": [],
            }
        ],
        "env": {"PROJECT_KIND": "blueprint"},
    }

    result = await execute_project_setup_plan(
        plan,
        project_root=str(project_root),
        secret_env={"GITHUB_TOKEN": "ghp_setup_command_secret"},
    )

    assert result["status"] == "succeeded"
    assert result["commands"][0]["status"] == "succeeded"
    assert result["commands"][0]["message"] == "[REDACTED]"
    assert "ghp_setup_command_secret" not in str(result)
    assert (project_root / "marker.txt").read_text() == "blueprint"


@pytest.mark.asyncio
async def test_execute_setup_stops_commands_after_failure(tmp_path) -> None:
    project_root = tmp_path / "project"
    plan = {
        "ready": True,
        "repos": [],
        "commands": [
            {"name": "Fail", "command": "exit 7", "cwd": "", "timeout_seconds": 10, "status": "pending", "errors": []},
            {"name": "Skipped", "command": "touch should-not-exist", "cwd": "", "timeout_seconds": 10, "status": "pending", "errors": []},
        ],
        "env": {},
    }

    result = await execute_project_setup_plan(plan, project_root=str(project_root), secret_env={})

    assert result["status"] == "failed"
    assert [command["status"] for command in result["commands"]] == ["failed", "skipped"]
    assert not (project_root / "should-not-exist").exists()


@pytest.mark.asyncio
async def test_execute_setup_fails_when_command_cwd_is_missing(tmp_path) -> None:
    project_root = tmp_path / "project"
    plan = {
        "ready": True,
        "repos": [],
        "commands": [
            {"name": "Missing cwd", "command": "touch should-not-exist", "cwd": "missing", "timeout_seconds": 10, "status": "pending", "errors": []},
        ],
        "env": {},
    }

    result = await execute_project_setup_plan(plan, project_root=str(project_root), secret_env={})

    assert result["status"] == "failed"
    assert result["commands"][0]["status"] == "failed"
    assert result["commands"][0]["message"] == "Command cwd does not exist."
    assert not (project_root / "missing").exists()


@pytest.mark.asyncio
async def test_execute_setup_skips_commands_after_clone_failure(tmp_path) -> None:
    project_root = tmp_path / "project"
    plan = {
        "ready": True,
        "repos": [
            {
                "name": "missing",
                "url": str(tmp_path / "missing.git"),
                "path": "missing",
                "branch": None,
                "status": "pending",
                "errors": [],
            }
        ],
        "commands": [
            {"name": "Skipped", "command": "touch should-not-exist", "cwd": "", "timeout_seconds": 10, "status": "pending", "errors": []},
        ],
        "env": {},
    }

    result = await execute_project_setup_plan(plan, project_root=str(project_root), secret_env={})

    assert result["status"] == "failed"
    assert result["repos"][0]["status"] == "failed"
    assert result["commands"][0]["status"] == "skipped"
    assert not (project_root / "should-not-exist").exists()
