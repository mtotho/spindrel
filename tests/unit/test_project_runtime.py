from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.db.models import Project
from app.services.encryption import encrypt
from app.services.project_runtime import build_project_runtime_environment
from app.services.shared_workspace import SharedWorkspaceService


def _project(snapshot: dict) -> Project:
    return Project(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        name="Runtime Project",
        slug="runtime-project",
        root_path="common/projects/runtime",
        metadata_={"blueprint_snapshot": snapshot},
    )


def test_project_runtime_env_uses_snapshot_defaults_and_bound_secrets() -> None:
    project = _project(
        {
            "env": {
                "PROJECT_KIND": "screenshot",
                "BAD-NAME": "ignored",
                "AGENT_SERVER_API_KEY": "reserved",
            },
            "required_secrets": ["GITHUB_TOKEN", "NPM_TOKEN"],
        }
    )
    bindings = [
        SimpleNamespace(
            logical_name="GITHUB_TOKEN",
            secret_value_id=uuid.uuid4(),
            secret_value=SimpleNamespace(value=encrypt("ghp_project_runtime_secret_123456")),
        ),
        SimpleNamespace(logical_name="NPM_TOKEN", secret_value_id=None, secret_value=None),
    ]

    runtime = build_project_runtime_environment(project, bindings=bindings)

    assert runtime.env["PROJECT_KIND"] == "screenshot"
    assert runtime.env["GITHUB_TOKEN"] == "ghp_project_runtime_secret_123456"
    assert runtime.env_default_keys == ("PROJECT_KIND",)
    assert runtime.secret_keys == ("GITHUB_TOKEN",)
    assert runtime.missing_secrets == ("NPM_TOKEN",)
    assert runtime.invalid_env_keys == ("BAD-NAME",)
    assert runtime.reserved_env_keys == ("AGENT_SERVER_API_KEY",)
    assert "ghp_project_runtime_secret_123456" not in str(runtime.safe_payload())
    assert runtime.redact_text("token=ghp_project_runtime_secret_123456") == "token=[REDACTED]"


def test_shared_workspace_env_overlays_project_runtime_env() -> None:
    service = SharedWorkspaceService()
    ws = SimpleNamespace(env={"PROJECT_KIND": "workspace", "BASE_ONLY": "1"})

    env = service._build_env(ws, extra_env={"PROJECT_KIND": "project", "PROJECT_ONLY": "2"})

    assert env["PROJECT_KIND"] == "project"
    assert env["BASE_ONLY"] == "1"
    assert env["PROJECT_ONLY"] == "2"
