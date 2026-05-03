from __future__ import annotations

import uuid
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.db.models import Channel, Project, ProjectInstance, Session
from app.services.channel_sessions import build_session_search_rows
from app.services.session_execution_environments import (
    ensure_isolated_session_environment,
    load_session_execution_runtime,
    manage_session_execution_environment,
    _prepare_session_worktree,
)


pytestmark = pytest.mark.asyncio


def _git(cwd, *args):
    proc = subprocess.run(["git", "-C", str(cwd), *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return proc.stdout.strip()


async def test_prepare_session_worktree_creates_branch_from_canonical_repo(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init")
    _git(source, "config", "user.email", "test@example.com")
    _git(source, "config", "user.name", "Test User")
    (source / "README.md").write_text("hello\n")
    _git(source, "add", "README.md")
    _git(source, "commit", "-m", "init")
    _git(source, "branch", "-M", "main")
    workspace_root = tmp_path / "workspace"
    project = Project(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        name="Worktree Project",
        slug="worktree-project",
        root_path="common/projects/worktree-project",
        metadata_={"blueprint_snapshot": {"repos": [{"path": "repo", "branch": "main", "canonical": True}]}},
    )
    monkeypatch.setattr(
        "app.services.session_execution_environments.project_repo_host_path",
        lambda _project, **_kwargs: str(source),
    )
    monkeypatch.setattr(
        "app.services.session_execution_environments._project_workspace_host_root",
        lambda _project: workspace_root,
    )
    session_id = uuid.uuid4()

    worktree = _prepare_session_worktree(
        project,
        session_id=session_id,
        branch="spindrel/test-worktree",
        base_branch="main",
    )

    assert worktree is not None
    assert worktree["kind"] == "git_worktree"
    assert worktree["branch"] == "spindrel/test-worktree"
    assert (workspace_root / "common/session-worktrees/worktree-project").exists()
    assert (Path(worktree["worktree_path"]) / "README.md").read_text() == "hello\n"


async def _seed_project_session(db_session):
    project_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    instance_id = uuid.uuid4()
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Session Env Project",
        slug="session-env-project",
        root_path="common/projects/session-env",
        metadata_={"blueprint_snapshot": {"repos": [{"path": "repo"}]}},
    )
    channel = Channel(
        id=channel_id,
        name="Project channel",
        bot_id="agent",
        client_id="client-session-env",
        project_id=project_id,
        workspace_id=workspace_id,
    )
    instance = ProjectInstance(
        id=instance_id,
        workspace_id=workspace_id,
        project_id=project_id,
        root_path="common/project-instances/session-env/abc123",
        status="ready",
        source="blueprint_snapshot",
        source_snapshot={},
        setup_result={},
        owner_kind="session",
        owner_id=session_id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session = Session(
        id=session_id,
        client_id="client-session-env",
        bot_id="agent",
        channel_id=channel_id,
        project_instance_id=instance_id,
        metadata_={"created_by": "project_coding_run", "source": "schedule", "project_id": str(project_id)},
        source_task_id=uuid.uuid4(),
    )
    db_session.add_all([project, channel, instance, session])
    await db_session.commit()
    return project, channel, instance, session


async def test_isolated_session_environment_sets_private_docker_env(db_session, monkeypatch):
    project, _channel, instance, session = await _seed_project_session(db_session)

    monkeypatch.setattr(
        "app.services.session_execution_environments._start_docker_daemon",
        lambda session_id: {
            "endpoint": "tcp://127.0.0.1:39001",
            "container_id": "abc",
            "container_name": "spindrel-session-docker-abc",
            "state_volume": "state",
            "port": 39001,
        },
    )

    env = await ensure_isolated_session_environment(
        db_session,
        session_id=session.id,
        project=project,
        project_instance=instance,
    )
    runtime = await load_session_execution_runtime(db_session, session.id)

    assert env.status == "ready"
    assert runtime.cwd and runtime.cwd.endswith("common/project-instances/session-env/abc123")
    assert runtime.env["DOCKER_HOST"] == "tcp://127.0.0.1:39001"
    assert runtime.env["COMPOSE_PROJECT_NAME"].startswith("spindrel_")


async def test_project_run_sessions_are_visible_with_origin_badges(db_session, monkeypatch):
    project, channel, instance, session = await _seed_project_session(db_session)
    monkeypatch.setattr(
        "app.services.session_execution_environments._start_docker_daemon",
        lambda session_id: {
            "endpoint": "tcp://127.0.0.1:39002",
            "container_id": "abc",
            "container_name": "spindrel-session-docker-abc",
            "state_volume": "state",
            "port": 39002,
        },
    )
    await ensure_isolated_session_environment(
        db_session,
        session_id=session.id,
        project=project,
        project_instance=instance,
    )

    rows = await build_session_search_rows(db_session, channel, auth=None, limit=10)

    assert [row.session_id for row in rows] == [session.id]
    assert rows[0].origin == "scheduled_run"
    assert rows[0].execution_environment == "isolated"
    assert rows[0].execution_environment_status == "ready"


async def test_session_environment_lifecycle_stops_starts_pins_and_cleans(db_session, monkeypatch):
    project, _channel, instance, session = await _seed_project_session(db_session)
    docker_payloads = [
        {
            "endpoint": "tcp://127.0.0.1:39003",
            "container_id": "abc",
            "container_name": "spindrel-session-docker-abc",
            "state_volume": "state",
            "port": 39003,
            "state": "running",
        },
        {
            "endpoint": "tcp://127.0.0.1:39004",
            "container_id": "def",
            "container_name": "spindrel-session-docker-abc",
            "state_volume": "state",
            "port": 39004,
            "state": "running",
        },
    ]

    monkeypatch.setattr(
        "app.services.session_execution_environments._start_docker_daemon",
        lambda _session_id: docker_payloads.pop(0),
    )
    monkeypatch.setattr(
        "app.services.session_execution_environments._run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "", ""),
    )

    env = await ensure_isolated_session_environment(
        db_session,
        session_id=session.id,
        project=project,
        project_instance=instance,
    )
    assert env.status == "ready"

    stopped = await manage_session_execution_environment(db_session, session.id, action="stop")
    assert stopped["environment"]["status"] == "stopped"
    runtime = await load_session_execution_runtime(db_session, session.id)
    assert "DOCKER_HOST" not in runtime.env

    started = await manage_session_execution_environment(db_session, session.id, action="start")
    assert started["environment"]["status"] == "ready"
    assert started["environment"]["docker_endpoint"] == "tcp://127.0.0.1:39004"

    pinned = await manage_session_execution_environment(db_session, session.id, action="pin")
    assert pinned["environment"]["pinned"] is True
    assert pinned["environment"]["expires_at"] is None

    cleaned = await manage_session_execution_environment(db_session, session.id, action="cleanup")
    assert cleaned["environment"]["status"] == "deleted"
