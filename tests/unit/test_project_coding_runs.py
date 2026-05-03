from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.db.models import Channel, ExecutionReceipt, Message, Project, ProjectDependencyStackInstance, ProjectRunReceipt, SessionExecutionEnvironment, Task, TaskMachineGrant
from app.services.project_coding_runs import (
    ProjectCodingRunCreate,
    ProjectCodingRunReviewFinalize,
    ProjectConcurrencyCapExceeded,
    ProjectMachineTargetGrant,
    allocate_project_run_dev_targets,
    _review_summary,
    create_project_coding_run,
    create_project_coding_run_schedule,
    expand_project_review_prompt_template,
    fire_project_coding_run_schedule,
    finalize_project_coding_run_review,
    get_project_coding_run_review_context,
    list_project_coding_run_review_batches,
    list_project_coding_run_review_sessions,
    list_project_coding_runs,
    list_project_coding_run_schedules,
    project_coding_run_lifecycle_summary,
    project_coding_run_phase,
    project_coding_run_defaults,
    project_coding_run_review_next_action,
    project_coding_run_review_queue_state,
    ProjectCodingRunScheduleCreate,
    ProjectCodingRunScheduleUpdate,
    disable_project_coding_run_schedule,
    update_project_coding_run_schedule,
)
from app.services.project_runtime import load_project_runtime_environment_for_id
from app.services.project_run_handoff import CommandResult


def _factory_meta() -> dict:
    return {"blueprint_snapshot": {"repos": [{"path": "spindrel", "branch": "development"}]}}


def test_project_coding_run_defaults_use_repo_branch_and_safe_slug():
    task_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    project = Project(
        id=uuid.uuid4(),
        name="Spindrel",
        root_path="common/projects/spindrel",
        metadata_={
            "blueprint_snapshot": {
                "repos": [
                    {
                        "name": "spindrel",
                        "url": "https://github.com/mtotho/spindrel.git",
                        "path": "spindrel",
                        "branch": "development",
                    }
                ]
            }
        },
    )

    defaults = project_coding_run_defaults(project, request="Fix UI screenshot diff!", task_id=task_id)

    assert defaults == {
        "branch": "spindrel/project-12345678-fix-ui-screenshot-diff",
        "base_branch": "development",
        "repo": {
            "name": "spindrel",
            "path": "spindrel",
            "url": "https://github.com/mtotho/spindrel.git",
        },
    }


def test_project_coding_run_defaults_fall_back_when_no_repo_snapshot():
    task_id = uuid.UUID("abcdef12-1234-5678-1234-567812345678")
    project = Project(
        id=uuid.uuid4(),
        name="Loose Project",
        root_path="common/projects/loose",
        metadata_={},
    )

    defaults = project_coding_run_defaults(project, task_id=task_id)

    assert defaults["branch"] == "spindrel/project-abcdef12-loose-project"
    assert defaults["base_branch"] is None
    assert defaults["repo"] == {"name": None, "path": None, "url": None}


def test_project_coding_run_review_queue_state_uses_existing_run_signals():
    ready = {
        "status": "completed",
        "task": {"status": "complete"},
        "receipt": {"summary": "Done"},
        "review": {
            "status": "ready_for_review",
            "evidence": {"tests_count": 1, "screenshots_count": 1, "changed_files_count": 2, "dev_targets_count": 1},
        },
    }
    changes = {
        **ready,
        "latest_continuation": None,
        "review": {"status": "changes_requested", "evidence": {"tests_count": 1}},
    }
    missing = {
        "status": "completed",
        "task": {"status": "complete"},
        "receipt": None,
        "review": {"status": "pending_evidence", "evidence": {}},
    }
    follow_up = {
        **changes,
        "latest_continuation": {"status": "pending", "review_status": "pending"},
    }

    assert project_coding_run_review_queue_state(ready) == "ready_for_review"
    assert project_coding_run_review_queue_state(changes) == "changes_requested"
    assert project_coding_run_review_queue_state(missing) == "missing_evidence"
    assert project_coding_run_review_queue_state(follow_up) == "follow_up_running"
    assert "follow-up" in project_coding_run_review_next_action("changes_requested")
    ready_lifecycle = project_coding_run_lifecycle_summary(ready)
    assert ready_lifecycle["phase"] == "needs_review"
    assert ready_lifecycle["headline"] == "Run is ready for review"
    assert ready_lifecycle["evidence"] == {"tests": 1, "screenshots": 1, "files": 2, "dev_targets": 1}
    blocked_lifecycle = project_coding_run_lifecycle_summary({
        **ready,
        "readiness": {"blockers": ["Missing required runtime secret: GITHUB_TOKEN"]},
        "work_surface": {"blocker": "Fresh Project instance unavailable"},
    })
    assert blocked_lifecycle["phase"] == "setup_blocked"
    assert blocked_lifecycle["blocker"] == "Fresh Project instance unavailable"


def test_project_coding_run_phase_derives_symphony_equivalent_activity_phase():
    """run_phase tracks what the run is doing right now, not the operator queue.

    Distinct from review_queue_state and from the legacy lifecycle.phase
    headline. Order of precedence: failed > reviewed > stalled > review_ready
    > handoff > testing > editing > branching > preparing.
    """
    base = {"task": {"status": "running"}, "review": {"status": "pending", "evidence": {}}}

    assert project_coding_run_phase(base) == "preparing"

    branched = {
        **base,
        "review": {"status": "pending", "evidence": {}, "steps": {"branch": {"status": "succeeded"}}},
    }
    assert project_coding_run_phase(branched) == "branching"

    editing = {
        **base,
        "review": {"status": "pending", "evidence": {"changed_files_count": 3}, "steps": {"branch": {"status": "succeeded"}}},
    }
    assert project_coding_run_phase(editing) == "editing"

    testing = {
        **base,
        "review": {
            "status": "pending",
            "evidence": {"changed_files_count": 3, "tests_count": 2},
            "steps": {"branch": {"status": "succeeded"}},
        },
    }
    assert project_coding_run_phase(testing) == "testing"

    handed_off = {
        "task": {"status": "complete"},
        "receipt": {"summary": "Done"},
        "review": {
            "status": "pending_evidence",
            "handoff_url": "https://github.com/x/y/pull/1",
            "evidence": {"changed_files_count": 3, "tests_count": 2},
        },
    }
    # missing_evidence queue state with handoff present surfaces as handoff
    assert project_coding_run_phase(handed_off) == "handoff"

    ready = {
        "status": "completed",
        "task": {"status": "complete"},
        "receipt": {"summary": "Done"},
        "review": {
            "status": "ready_for_review",
            "handoff_url": "https://github.com/x/y/pull/1",
            "evidence": {"tests_count": 1, "screenshots_count": 1, "changed_files_count": 2, "dev_targets_count": 1},
        },
    }
    assert project_coding_run_phase(ready) == "review_ready"

    reviewed = {**ready, "review": {**ready["review"], "reviewed": True, "status": "reviewed"}}
    assert project_coding_run_phase(reviewed) == "reviewed"

    failed = {"task": {"status": "failed"}, "review": {"status": "failed", "evidence": {}}}
    assert project_coding_run_phase(failed) == "failed"

    # Sweep marker (4BB.2) flips run_phase to stalled even though queue_state
    # might still report blocked/reviewing.
    stalled = {
        **editing,
        "readiness": {"stalled": True, "blockers": []},
    }
    assert project_coding_run_phase(stalled) == "stalled"
    stalled_via_work_surface = {
        **editing,
        "work_surface": {"run_phase_override": "stalled"},
    }
    assert project_coding_run_phase(stalled_via_work_surface) == "stalled"

    # Lifecycle summary exposes both axes.
    lifecycle = project_coding_run_lifecycle_summary(ready)
    assert lifecycle["run_phase"] == "review_ready"
    assert lifecycle["phase"] == "needs_review"  # legacy headline preserved


@pytest.mark.asyncio
async def test_create_project_coding_run_uses_explicit_repo_path(db_session):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Projects",
        slug="projects",
        root_path="common/projects",
        metadata_={
            "blueprint_snapshot": {
                "repos": [
                    {"name": "vault", "path": "vault", "branch": "master"},
                    {"name": "spindrel", "path": "spindrel", "branch": "development"},
                ],
            },
        },
    )
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        workspace_id=workspace_id,
    )
    db_session.add_all([project, channel])
    await db_session.commit()

    task = await create_project_coding_run(
        db_session,
        project,
        ProjectCodingRunCreate(channel_id=channel_id, request="Smoke.", repo_path="spindrel"),
    )

    run_cfg = task.execution_config["project_coding_run"]
    assert run_cfg["repo"] == {"name": "spindrel", "path": "spindrel", "url": None}
    assert run_cfg["base_branch"] == "development"
    assert "Repository path: spindrel" in task.prompt


@pytest.mark.asyncio
async def test_project_coding_run_records_environment_failure_in_task_runner(db_session, monkeypatch):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Projects",
        slug="projects",
        root_path="common/projects",
        metadata_={"blueprint_snapshot": {"repos": [{"name": "spindrel", "path": "spindrel", "branch": "development"}]}},
    )
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        workspace_id=workspace_id,
    )
    db_session.add_all([project, channel])
    await db_session.commit()

    async def fail_environment(*_args, **_kwargs):
        raise RuntimeError("private Docker daemon is unreachable at tcp://127.0.0.1:50209")

    monkeypatch.setattr(
        "app.services.session_execution_environments.ensure_isolated_session_environment",
        fail_environment,
    )

    task = await create_project_coding_run(
        db_session,
        project,
        ProjectCodingRunCreate(channel_id=channel_id, request="Smoke.", repo_path="spindrel"),
    )
    task.status = "running"
    await db_session.commit()

    from app.agent.task_run_host import _ensure_session_environment_if_requested

    ok = await _ensure_session_environment_if_requested(
        db_session,
        task=task,
        project_instance=None,
    )

    assert ok is False
    assert task.status == "failed"
    assert task.error == "private Docker daemon is unreachable at tcp://127.0.0.1:50209"
    run_cfg = task.execution_config["project_coding_run"]
    assert run_cfg["session_environment"]["status"] == "failed"
    assert run_cfg["session_environment"]["requested_repo_path"] == "spindrel"
    assert run_cfg["loop_state"]["state"] == "blocked"

    receipt = (await db_session.execute(
        select(ProjectRunReceipt).where(ProjectRunReceipt.task_id == task.id)
    )).scalar_one()
    assert receipt.status == "blocked"
    assert receipt.metadata_["loop"]["decision"] == "blocked"

    message = (await db_session.execute(
        select(Message).where(Message.session_id == task.session_id, Message.role == "assistant")
    )).scalar_one()
    assert "blocked before the agent started" in (message.content or "")
    assert "tcp://127.0.0.1:50209" in (message.content or "")


@pytest.mark.asyncio
async def test_shared_repo_project_run_does_not_create_isolated_environment(db_session, monkeypatch):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Projects",
        slug="projects",
        root_path="common/projects",
        metadata_={"blueprint_snapshot": {"repos": [{"name": "spindrel", "path": "spindrel", "branch": "development"}]}},
    )
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        workspace_id=workspace_id,
    )
    db_session.add_all([project, channel])
    await db_session.commit()

    async def fail_environment(*_args, **_kwargs):
        raise AssertionError("shared_repo must not create an isolated session environment")

    monkeypatch.setattr(
        "app.services.session_execution_environments.ensure_isolated_session_environment",
        fail_environment,
    )

    task = await create_project_coding_run(
        db_session,
        project,
        ProjectCodingRunCreate(
            channel_id=channel_id,
            request="Smoke.",
            repo_path="spindrel",
            work_surface_mode="shared_repo",
        ),
    )
    task.status = "running"
    await db_session.commit()

    from app.agent.task_run_host import _ensure_session_environment_if_requested

    ok = await _ensure_session_environment_if_requested(
        db_session,
        task=task,
        project_instance=None,
    )

    assert ok is None
    assert task.execution_config["project_coding_run"]["session_environment"] == {
        "mode": "shared_repo",
        "status": "not_configured",
    }


@pytest.mark.asyncio
async def test_project_run_environment_profile_is_deferred_to_task_runner(db_session, monkeypatch, tmp_path):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    run_root = tmp_path / "worktree" / "spindrel"
    run_root.mkdir(parents=True)
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Spindrel",
        slug="spindrel",
        root_path="common/projects",
        metadata_={
            "blueprint_snapshot": {
                "repos": [{"name": "spindrel", "path": "spindrel", "branch": "development"}],
                "run_environment_profiles": {
                    "touch-ready": {
                        "name": "Touch ready",
                        "setup_commands": ["mkdir -p scratch/profile && printf ready > scratch/profile/ready.txt"],
                        "required_artifacts": ["scratch/profile/ready.txt"],
                    }
                },
            },
        },
    )
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        workspace_id=workspace_id,
    )
    db_session.add_all([project, channel])
    await db_session.commit()

    async def fake_environment(db, *, session_id, project, branch=None, base_branch=None, repo_path=None, **_kwargs):
        env = SessionExecutionEnvironment(
            session_id=session_id,
            project_id=project.id,
            mode="isolated",
            status="ready",
            cwd=str(run_root),
            docker_endpoint="tcp://session-docker:2375",
            docker_status="running",
            metadata_={
                "worktree": {
                    "kind": "git_worktree",
                    "branch": branch,
                    "base_ref": base_branch,
                    "repo_path": repo_path,
                    "worktree_path": str(run_root),
                },
                "docker": {"endpoint": "tcp://session-docker:2375", "state": "running"},
            },
        )
        db.add(env)
        await db.flush()
        return env

    monkeypatch.setattr(
        "app.services.session_execution_environments.ensure_isolated_session_environment",
        fake_environment,
    )

    task = await create_project_coding_run(
        db_session,
        project,
        ProjectCodingRunCreate(
            channel_id=channel_id,
            request="Run profile.",
            repo_path="spindrel",
            run_environment_profile="touch-ready",
        ),
    )

    assert task.status == "pending"
    assert not (run_root / "scratch" / "profile" / "ready.txt").exists()
    assert "run_environment_preflight" not in task.execution_config["project_coding_run"]


@pytest.mark.asyncio
async def test_project_run_environment_profile_failure_blocks_in_task_runner(db_session, tmp_path):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    run_root = tmp_path / "worktree" / "spindrel"
    run_root.mkdir(parents=True)
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Spindrel",
        slug="spindrel",
        root_path="common/projects",
        metadata_={
            "blueprint_snapshot": {
                "repos": [{"name": "spindrel", "path": "spindrel", "branch": "development"}],
                "run_environment_profiles": {
                    "broken": {
                        "setup_commands": [{"name": "fail-fast", "command": "echo nope >&2; exit 7"}],
                    }
                },
            },
        },
    )
    session_id = uuid.uuid4()
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        workspace_id=workspace_id,
        active_session_id=session_id,
    )
    task = Task(
        id=uuid.uuid4(),
        bot_id="agent",
        client_id=channel.client_id,
        channel_id=channel_id,
        session_id=session_id,
        status="running",
        task_type="agent",
        execution_config={
            "project_coding_run": {
                "project_id": str(project_id),
                "branch": "spindrel/test",
                "base_branch": "development",
                "run_environment_profile": "broken",
                "loop_state": {"state": "running"},
            }
        },
    )
    env = SessionExecutionEnvironment(
        session_id=session_id,
        project_id=project_id,
        mode="isolated",
        status="ready",
        cwd=str(run_root),
        docker_endpoint="tcp://session-docker:2375",
        docker_status="running",
        metadata_={"docker": {"endpoint": "tcp://session-docker:2375", "state": "running"}},
    )
    db_session.add_all([project, channel, task, env])
    await db_session.commit()

    from app.agent.task_run_host import _preflight_project_run_environment_if_requested

    ok = await _preflight_project_run_environment_if_requested(
        db_session,
        task=task,
        project_instance=None,
        prepared=SimpleNamespace(task=task, ecfg=task.execution_config, task_prompt="Run profile."),
    )

    assert ok is False
    assert task.status == "failed"
    assert "fail-fast" in task.error
    preflight = task.execution_config["project_coding_run"]["run_environment_preflight"]
    assert preflight["ok"] is False
    assert preflight["commands"][0]["exit_code"] == 7
    assert "nope" in preflight["commands"][0]["stderr"]

    receipt = (await db_session.execute(
        select(ProjectRunReceipt).where(ProjectRunReceipt.task_id == task.id)
    )).scalar_one()
    assert receipt.status == "blocked"
    assert receipt.metadata_["category"] == "run_environment_preflight"

    message = (await db_session.execute(
        select(Message).where(Message.session_id == task.session_id, Message.role == "assistant")
    )).scalars().all()[-1]
    assert "Run environment preflight failed" in (message.content or "")


@pytest.mark.asyncio
async def test_project_run_environment_profile_success_runs_in_task_runner(db_session, tmp_path):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    run_root = tmp_path / "worktree" / "spindrel"
    run_root.mkdir(parents=True)
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Spindrel",
        slug="spindrel",
        root_path="common/projects",
        metadata_={
            "blueprint_snapshot": {
                "repos": [{"name": "spindrel", "path": "spindrel", "branch": "development"}],
                "run_environment_profiles": {
                    "touch-ready": {
                        "name": "Touch ready",
                        "env": {"READY_PATH": "scratch/profile/ready.txt"},
                        "setup_commands": ["mkdir -p scratch/profile && printf ready > ${READY_PATH}"],
                        "required_artifacts": ["${READY_PATH}"],
                        "readiness_checks": ["test -f ${READY_PATH}"],
                    }
                },
            },
        },
    )
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        workspace_id=workspace_id,
        active_session_id=session_id,
    )
    task = Task(
        id=uuid.uuid4(),
        bot_id="agent",
        client_id=channel.client_id,
        channel_id=channel_id,
        session_id=session_id,
        status="running",
        task_type="agent",
        execution_config={
            "project_coding_run": {
                "project_id": str(project_id),
                "branch": "spindrel/test",
                "base_branch": "development",
                "run_environment_profile": "touch-ready",
            }
        },
    )
    env = SessionExecutionEnvironment(
        session_id=session_id,
        project_id=project_id,
        mode="isolated",
        status="ready",
        cwd=str(run_root),
        docker_endpoint="tcp://session-docker:2375",
        docker_status="running",
        metadata_={"docker": {"endpoint": "tcp://session-docker:2375", "state": "running"}},
    )
    db_session.add_all([project, channel, task, env])
    await db_session.commit()

    from app.agent.task_run_host import _preflight_project_run_environment_if_requested

    ok = await _preflight_project_run_environment_if_requested(
        db_session,
        task=task,
        project_instance=None,
        prepared=SimpleNamespace(task=task, ecfg=task.execution_config, task_prompt="Run profile."),
    )

    assert ok is True
    assert (run_root / "scratch" / "profile" / "ready.txt").read_text() == "ready"
    preflight = task.execution_config["project_coding_run"]["run_environment_preflight"]
    assert preflight["ok"] is True
    assert preflight["profile_id"] == "touch-ready"
    assert preflight["artifacts"] == [{"path": "scratch/profile/ready.txt", "exists": True}]
    assert preflight["readiness_checks"][0]["ok"] is True

    messages = list((await db_session.execute(
        select(Message).where(Message.session_id == task.session_id).order_by(Message.created_at)
    )).scalars().all())
    assert any("Project run environment prepared before agent start" in (msg.content or "") for msg in messages)


@pytest.mark.asyncio
async def test_repo_file_run_environment_profile_requires_trust_and_approval(db_session, tmp_path):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    run_root = tmp_path / "worktree" / "spindrel"
    profile_dir = run_root / ".spindrel" / "profiles"
    profile_dir.mkdir(parents=True)
    profile_text = """
name: Repo file profile
setup_commands:
  - mkdir -p scratch/profile && printf ready > scratch/profile/repo-ready.txt
required_artifacts:
  - scratch/profile/repo-ready.txt
""".lstrip()
    profile_path = profile_dir / "repo-ready.yaml"
    profile_path.write_text(profile_text)
    profile_hash = hashlib.sha256(profile_text.encode("utf-8")).hexdigest()
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Spindrel",
        slug="spindrel",
        root_path="common/projects",
        metadata_={
            "trust_repo_environment_profiles": True,
            "run_environment_profile_approvals": {
                "repo-ready": {"sha256": profile_hash, "approved_by": "admin"},
            },
            "blueprint_snapshot": {"repos": [{"name": "spindrel", "path": "spindrel", "branch": "development"}]},
        },
    )
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        workspace_id=workspace_id,
        active_session_id=session_id,
    )
    task = Task(
        id=uuid.uuid4(),
        bot_id="agent",
        client_id=channel.client_id,
        channel_id=channel_id,
        session_id=session_id,
        status="running",
        task_type="agent",
        execution_config={
            "project_coding_run": {
                "project_id": str(project_id),
                "branch": "spindrel/test",
                "base_branch": "development",
                "run_environment_profile": "repo-ready",
            }
        },
    )
    env = SessionExecutionEnvironment(
        session_id=session_id,
        project_id=project_id,
        mode="isolated",
        status="ready",
        cwd=str(run_root),
    )
    db_session.add_all([project, channel, task, env])
    await db_session.commit()

    from app.agent.task_run_host import _preflight_project_run_environment_if_requested

    ok = await _preflight_project_run_environment_if_requested(
        db_session,
        task=task,
        project_instance=None,
        prepared=SimpleNamespace(task=task, ecfg=task.execution_config, task_prompt="Run profile."),
    )

    assert ok is True
    preflight = task.execution_config["project_coding_run"]["run_environment_preflight"]
    assert preflight["source_layer"] == "repo_file"
    assert preflight["profile_path"] == ".spindrel/profiles/repo-ready.yaml"
    assert preflight["current_hash"] == profile_hash
    assert (run_root / "scratch" / "profile" / "repo-ready.txt").read_text() == "ready"


@pytest.mark.asyncio
async def test_repo_file_run_environment_profile_change_blocks_before_execution(db_session, tmp_path):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    run_root = tmp_path / "worktree" / "spindrel"
    profile_dir = run_root / ".spindrel" / "profiles"
    profile_dir.mkdir(parents=True)
    (profile_dir / "repo-ready.yaml").write_text(
        "setup_commands:\n  - mkdir -p scratch/profile && printf ready > scratch/profile/repo-ready.txt\n"
    )
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Spindrel",
        slug="spindrel",
        root_path="common/projects",
        metadata_={
            "trust_repo_environment_profiles": True,
            "run_environment_profile_approvals": {"repo-ready": {"sha256": "oldhash", "approved_by": "admin"}},
            "blueprint_snapshot": {"repos": [{"name": "spindrel", "path": "spindrel", "branch": "development"}]},
        },
    )
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        workspace_id=workspace_id,
        active_session_id=session_id,
    )
    task = Task(
        id=uuid.uuid4(),
        bot_id="agent",
        client_id=channel.client_id,
        channel_id=channel_id,
        session_id=session_id,
        status="running",
        task_type="agent",
        execution_config={
            "project_coding_run": {
                "project_id": str(project_id),
                "branch": "spindrel/test",
                "base_branch": "development",
                "run_environment_profile": "repo-ready",
            }
        },
    )
    env = SessionExecutionEnvironment(
        session_id=session_id,
        project_id=project_id,
        mode="isolated",
        status="ready",
        cwd=str(run_root),
    )
    db_session.add_all([project, channel, task, env])
    await db_session.commit()

    from app.agent.task_run_host import _preflight_project_run_environment_if_requested

    ok = await _preflight_project_run_environment_if_requested(
        db_session,
        task=task,
        project_instance=None,
        prepared=SimpleNamespace(task=task, ecfg=task.execution_config, task_prompt="Run profile."),
    )

    assert ok is False
    preflight = task.execution_config["project_coding_run"]["run_environment_preflight"]
    assert preflight["status"] == "needs_review"
    assert preflight["approved_hash"] == "oldhash"
    assert not (run_root / "scratch" / "profile" / "repo-ready.txt").exists()


@pytest.mark.asyncio
async def test_shared_repo_non_mutating_profile_runs_without_explicit_mode_opt_in(db_session, tmp_path):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    run_root = tmp_path / "shared" / "spindrel"
    run_root.mkdir(parents=True)
    (run_root / "marker.txt").write_text("ready")
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Spindrel",
        slug="spindrel",
        root_path="common/projects",
        metadata_={
            "blueprint_snapshot": {
                "repos": [{"name": "spindrel", "path": "spindrel", "branch": "development"}],
                "run_environment_profiles": {
                    "shared-check": {
                        "readiness_checks": ["test -f marker.txt"],
                        "required_artifacts": ["marker.txt"],
                    }
                },
            },
        },
    )
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        workspace_id=workspace_id,
        active_session_id=session_id,
    )
    task = Task(
        id=uuid.uuid4(),
        bot_id="agent",
        client_id=channel.client_id,
        channel_id=channel_id,
        session_id=session_id,
        status="running",
        task_type="agent",
        execution_config={
            "project_coding_run": {
                "project_id": str(project_id),
                "branch": "spindrel/test",
                "base_branch": "development",
                "work_surface_mode": "shared_repo",
                "run_environment_profile": "shared-check",
            }
        },
    )
    env = SessionExecutionEnvironment(
        session_id=session_id,
        project_id=project_id,
        mode="shared",
        status="ready",
        cwd=str(run_root),
    )
    db_session.add_all([project, channel, task, env])
    await db_session.commit()

    from app.agent.task_run_host import _preflight_project_run_environment_if_requested

    ok = await _preflight_project_run_environment_if_requested(
        db_session,
        task=task,
        project_instance=None,
        prepared=SimpleNamespace(task=task, ecfg=task.execution_config, task_prompt="Run profile."),
    )

    assert ok is True
    preflight = task.execution_config["project_coding_run"]["run_environment_preflight"]
    assert preflight["ok"] is True
    assert preflight["readiness_checks"][0]["ok"] is True
    assert preflight["artifacts"] == [{"path": "marker.txt", "exists": True}]


@pytest.mark.asyncio
async def test_run_environment_profile_cleans_background_process_when_later_step_fails(db_session, tmp_path):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    run_root = tmp_path / "worktree" / "spindrel"
    run_root.mkdir(parents=True)
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Spindrel",
        slug="spindrel",
        root_path="common/projects",
        metadata_={
            "blueprint_snapshot": {
                "repos": [{"name": "spindrel", "path": "spindrel", "branch": "development"}],
                "run_environment_profiles": {
                    "background-fails": {
                        "background_processes": [{"name": "sleepy", "command": "sleep 60"}],
                        "setup_commands": [{"name": "fail-after-start", "command": "exit 9"}],
                    }
                },
            },
        },
    )
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        workspace_id=workspace_id,
        active_session_id=session_id,
    )
    task = Task(
        id=uuid.uuid4(),
        bot_id="agent",
        client_id=channel.client_id,
        channel_id=channel_id,
        session_id=session_id,
        status="running",
        task_type="agent",
        execution_config={
            "project_coding_run": {
                "project_id": str(project_id),
                "branch": "spindrel/test",
                "base_branch": "development",
                "run_environment_profile": "background-fails",
            }
        },
    )
    env = SessionExecutionEnvironment(
        session_id=session_id,
        project_id=project_id,
        mode="isolated",
        status="ready",
        cwd=str(run_root),
    )
    db_session.add_all([project, channel, task, env])
    await db_session.commit()

    from app.agent.task_run_host import _preflight_project_run_environment_if_requested

    ok = await _preflight_project_run_environment_if_requested(
        db_session,
        task=task,
        project_instance=None,
        prepared=SimpleNamespace(task=task, ecfg=task.execution_config, task_prompt="Run profile."),
    )

    assert ok is False
    preflight = task.execution_config["project_coding_run"]["run_environment_preflight"]
    process = preflight["background_processes"][0]
    assert process["terminated"] is True
    with pytest.raises(ProcessLookupError):
        os.killpg(int(process["pgid"]), 0)


@pytest.mark.asyncio
async def test_run_environment_profile_redacts_project_runtime_secret_values(db_session, monkeypatch, tmp_path):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    run_root = tmp_path / "worktree" / "spindrel"
    run_root.mkdir(parents=True)
    secret_value = "supersecretvalue12345"
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Spindrel",
        slug="spindrel",
        root_path="common/projects",
        metadata_={
            "blueprint_snapshot": {
                "repos": [{"name": "spindrel", "path": "spindrel", "branch": "development"}],
                "run_environment_profiles": {
                    "secret-echo": {
                        "setup_commands": [{"name": "echo-secret", "command": "printf \"$MY_SECRET\""}],
                    }
                },
            },
        },
    )
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        workspace_id=workspace_id,
        active_session_id=session_id,
    )
    task = Task(
        id=uuid.uuid4(),
        bot_id="agent",
        client_id=channel.client_id,
        channel_id=channel_id,
        session_id=session_id,
        status="running",
        task_type="agent",
        execution_config={
            "project_coding_run": {
                "project_id": str(project_id),
                "branch": "spindrel/test",
                "base_branch": "development",
                "run_environment_profile": "secret-echo",
            }
        },
    )
    env = SessionExecutionEnvironment(
        session_id=session_id,
        project_id=project_id,
        mode="isolated",
        status="ready",
        cwd=str(run_root),
    )
    db_session.add_all([project, channel, task, env])
    await db_session.commit()

    fake_runtime = SimpleNamespace(
        env={"MY_SECRET": secret_value},
        redact_text=lambda text: str(text).replace(secret_value, "[REDACTED]"),
    )
    async def fake_runtime_loader(*_args, **_kwargs):
        return fake_runtime

    monkeypatch.setattr(
        "app.services.project_run_environment_profiles.load_project_runtime_environment_for_id",
        fake_runtime_loader,
    )

    from app.agent.task_run_host import _preflight_project_run_environment_if_requested

    ok = await _preflight_project_run_environment_if_requested(
        db_session,
        task=task,
        project_instance=None,
        prepared=SimpleNamespace(task=task, ecfg=task.execution_config, task_prompt="Run profile."),
    )

    assert ok is True
    preflight = task.execution_config["project_coding_run"]["run_environment_preflight"]
    assert preflight["commands"][0]["stdout"] == "[REDACTED]"
    assert secret_value not in str(preflight)


@pytest.mark.asyncio
async def test_create_project_coding_run_enforces_concurrency_cap(db_session):
    """Phase 4BB.4 - Blueprint `max_concurrent_runs=1` lets the first run launch
    and rejects the second with `ProjectConcurrencyCapExceeded` until the first
    finishes."""
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Capped",
        slug="capped",
        root_path="common/projects/capped",
        metadata_={
            "blueprint_snapshot": {
                "repos": [{"name": "p", "path": "p", "branch": "main"}],
                "max_concurrent_runs": 1,
            }
        },
    )
    channel = Channel(
        id=channel_id,
        name="Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        workspace_id=workspace_id,
    )
    db_session.add_all([project, channel])
    await db_session.commit()

    first = await create_project_coding_run(
        db_session,
        project,
        ProjectCodingRunCreate(channel_id=channel_id, request="first"),
    )
    assert first.status == "pending"

    with pytest.raises(ProjectConcurrencyCapExceeded) as excinfo:
        await create_project_coding_run(
            db_session,
            project,
            ProjectCodingRunCreate(channel_id=channel_id, request="second"),
        )
    assert excinfo.value.cap == 1
    assert excinfo.value.in_flight == 1

    # Once the first run completes, the cap frees up.
    first.status = "completed"
    await db_session.commit()

    third = await create_project_coding_run(
        db_session,
        project,
        ProjectCodingRunCreate(channel_id=channel_id, request="third"),
    )
    assert third.status == "pending"


@pytest.mark.asyncio
async def test_create_project_coding_run_attaches_task_scoped_machine_grant(db_session, monkeypatch):
    async def validate_target(provider_id: str, target_id: str):
        assert provider_id == "ssh"
        assert target_id == "e2e-8000"
        return {"label": "E2E 8000"}, ["inspect", "exec"]

    monkeypatch.setattr("app.services.machine_task_grants._validate_task_machine_target", validate_target)
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    user_id = uuid.uuid4()
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Spindrel",
        slug="spindrel",
        root_path="common/projects/spindrel",
        metadata_={"blueprint_snapshot": {"repos": [{"path": "spindrel", "branch": "development"}]}},
    )
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        workspace_id=workspace_id,
    )
    db_session.add_all([project, channel])
    await db_session.commit()

    task = await create_project_coding_run(
        db_session,
        project,
        ProjectCodingRunCreate(
            channel_id=channel_id,
            request="Run the e2e screenshot loop.",
            machine_target_grant=ProjectMachineTargetGrant(
                provider_id="ssh",
                target_id="e2e-8000",
                capabilities=["inspect", "exec"],
                allow_agent_tools=True,
            ),
            granted_by_user_id=user_id,
            source_artifact={"path": "docs/tracks/foo.md", "section": "Proposed Run Packs"},
        ),
    )

    grant = (await db_session.execute(
        select(TaskMachineGrant).where(TaskMachineGrant.task_id == task.id)
    )).scalar_one()
    run_cfg = task.execution_config["project_coding_run"]
    assert grant.provider_id == "ssh"
    assert grant.target_id == "e2e-8000"
    assert grant.capabilities == ["inspect", "exec"]
    assert grant.granted_by_user_id == user_id
    assert run_cfg["machine_target_grant"] == {
        "provider_id": "ssh",
        "target_id": "e2e-8000",
        "capabilities": ["inspect", "exec"],
        "allow_agent_tools": True,
        "expires_at": None,
    }
    assert run_cfg["source_artifact"] == {
        "path": "docs/tracks/foo.md",
        "section": "Proposed Run Packs",
        "commit_sha": None,
    }
    assert "Task-scoped grant: ssh/e2e-8000" in task.prompt
    assert "machine_status, machine_inspect_command, and machine_exec_command" in task.prompt


@pytest.mark.asyncio
async def test_project_coding_run_allocates_dev_targets_and_runtime_env(db_session, monkeypatch):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Spindrel",
        slug="spindrel",
        root_path="common/projects/spindrel",
        metadata_={
            "blueprint_snapshot": {
                "dev_targets": [
                    {
                        "key": "api",
                        "label": "API",
                        "port_env": "SPINDREL_DEV_API_PORT",
                        "url_env": "SPINDREL_DEV_API_URL",
                        "port_range": [31100, 31102],
                    }
                ]
            }
        },
    )
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        workspace_id=workspace_id,
    )
    db_session.add_all([project, channel])
    await db_session.commit()
    fake_listening = lambda port, host="127.0.0.1": port == 31100
    monkeypatch.setattr("app.services.project_coding_runs._is_port_listening", fake_listening)
    monkeypatch.setattr("app.services.project_task_execution_context.default_port_prober", fake_listening)

    task = await create_project_coding_run(
        db_session,
        project,
        ProjectCodingRunCreate(channel_id=channel_id, request="Run the local API."),
    )

    targets = task.execution_config["project_coding_run"]["dev_targets"]
    assert targets == [{
        "key": "api",
        "label": "API",
        "port": 31101,
        "port_env": "SPINDREL_DEV_API_PORT",
        "url": "http://127.0.0.1:31101",
        "url_env": "SPINDREL_DEV_API_URL",
    }]
    assert "API: http://127.0.0.1:31101" in task.prompt
    runtime = await load_project_runtime_environment_for_id(db_session, project_id, task_id=task.id)
    assert runtime is not None
    assert runtime.env["SPINDREL_DEV_API_PORT"] == "31101"
    assert runtime.env["SPINDREL_DEV_API_URL"] == "http://127.0.0.1:31101"

    rows = await list_project_coding_runs(db_session, project)
    assert rows[0]["id"] == str(task.id)
    assert rows[0]["readiness"]["ready"] is True
    assert rows[0]["readiness"]["dev_targets"]["targets"] == targets
    assert rows[0]["readiness"]["receipt_evidence"][0]["key"] == "changed_files"


@pytest.mark.asyncio
async def test_project_runtime_merges_task_dependency_stack_env(db_session):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    task_id = uuid.uuid4()
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Generic App",
        slug="generic-app",
        root_path="common/projects/generic-app",
        metadata_={"blueprint_snapshot": {"env": {"APP_ENV": "test"}}},
    )
    task = Task(
        id=task_id,
        workspace_id=workspace_id,
        title="Project coding run",
        channel_id=uuid.uuid4(),
        task_type="agent",
        status="running",
        execution_config={"project_coding_run": {"project_id": str(project_id)}},
    )
    stack = ProjectDependencyStackInstance(
        project_id=project_id,
        task_id=task_id,
        scope="task",
        status="running",
        env={
            "DATABASE_URL": "postgresql://agent:agent@host.docker.internal:39001/app",
            "PROJECT_DEPENDENCY_STACK_ID": "stack-1",
        },
    )
    db_session.add_all([project, task, stack])
    await db_session.commit()

    runtime = await load_project_runtime_environment_for_id(db_session, project_id, task_id=task_id)

    assert runtime is not None
    assert runtime.env["APP_ENV"] == "test"
    assert runtime.env["DATABASE_URL"] == "postgresql://agent:agent@host.docker.internal:39001/app"
    assert runtime.env["SPINDREL_PROJECT_RUN_GUARD"] == "1"
    assert runtime.env["SPINDREL_PROJECT_TASK_ID"] == str(task_id)
    payload = runtime.safe_payload()
    assert "DATABASE_URL" in payload["env_default_keys"]
    assert "postgresql://agent:agent" not in str(payload)


@pytest.mark.asyncio
async def test_project_run_dev_target_allocation_avoids_active_run_ports(db_session, monkeypatch):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Spindrel",
        slug="spindrel",
        root_path="common/projects/spindrel",
        metadata_={"dev_targets": [{"key": "ui", "port_range": [31200, 31202]}]},
    )
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        workspace_id=workspace_id,
    )
    active = Task(
        id=uuid.uuid4(),
        bot_id="agent",
        client_id=channel.client_id,
        channel_id=channel_id,
        status="running",
        title="Active",
        execution_config={
            "run_preset_id": "project_coding_run",
            "project_coding_run": {
                "project_id": str(project_id),
                "dev_targets": [{"key": "ui", "port": 31200}],
            },
        },
    )
    db_session.add_all([project, channel, active])
    await db_session.commit()
    monkeypatch.setattr("app.services.project_coding_runs._is_port_listening", lambda port, host="127.0.0.1": False)

    targets = await allocate_project_run_dev_targets(db_session, project, task_id=uuid.uuid4())

    assert targets[0]["port"] == 31201


@pytest.mark.asyncio
async def test_project_coding_run_schedule_fires_concrete_run_with_provenance(db_session):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Spindrel",
        slug="spindrel",
        root_path="common/projects/spindrel",
        metadata_={"blueprint_snapshot": {"repos": [{"path": "spindrel", "branch": "development"}]}},
    )
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        workspace_id=workspace_id,
    )
    db_session.add_all([project, channel])
    await db_session.commit()

    schedule = await create_project_coding_run_schedule(
        db_session,
        project,
        ProjectCodingRunScheduleCreate(
            channel_id=channel_id,
            title="Weekly Project review",
            request="Review the project and open a PR only when changes are needed.",
            scheduled_at=datetime(2026, 4, 30, 12, tzinfo=timezone.utc),
            recurrence="+1w",
        ),
    )
    run = await fire_project_coding_run_schedule(db_session, schedule, advance=False)

    assert run is not None
    assert run.parent_task_id == schedule.id
    assert run.recurrence is None
    assert run.execution_config["run_preset_id"] == "project_coding_run"
    cfg = run.execution_config["project_coding_run"]
    assert cfg["schedule_task_id"] == str(schedule.id)
    assert cfg["schedule_run_number"] == 1
    assert cfg["request"] == "Review the project and open a PR only when changes are needed."
    rows = await list_project_coding_run_schedules(db_session, project)
    assert rows[0]["id"] == str(schedule.id)
    assert rows[0]["run_count"] == 1
    assert rows[0]["last_run"]["task_id"] == str(run.id)
    assert rows[0]["recent_runs"][0]["task_id"] == str(run.id)


@pytest.mark.asyncio
async def test_project_coding_run_manual_schedule_round_trips_and_runs_now(db_session):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Spindrel",
        slug="spindrel-manual-schedule",
        root_path="common/projects/spindrel",
        metadata_=_factory_meta(),
    )
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        workspace_id=workspace_id,
    )
    db_session.add_all([project, channel])
    await db_session.commit()

    schedule = await create_project_coding_run_schedule(
        db_session,
        project,
        ProjectCodingRunScheduleCreate(
            channel_id=channel_id,
            title="Manual prompt",
            request="Run this only when asked.",
            recurrence="",
        ),
    )

    assert schedule.recurrence is None
    rows = await list_project_coding_run_schedules(db_session, project)
    assert rows[0]["recurrence"] is None

    run = await fire_project_coding_run_schedule(db_session, schedule, advance=False)

    assert run is not None
    assert run.parent_task_id == schedule.id
    assert run.recurrence is None
    rows = await list_project_coding_run_schedules(db_session, project)
    assert rows[0]["run_count"] == 1
    assert rows[0]["last_run"]["task_id"] == str(run.id)


@pytest.mark.asyncio
async def test_project_coding_run_schedule_can_be_edited_resumed_and_blocks_disabled_run_now(db_session):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Spindrel",
        slug="spindrel-schedule-edit",
        root_path="common/projects/spindrel",
        metadata_={"blueprint_snapshot": {"repos": [{"path": "spindrel", "branch": "development"}]}},
    )
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        workspace_id=workspace_id,
    )
    db_session.add_all([project, channel])
    await db_session.commit()

    schedule = await create_project_coding_run_schedule(
        db_session,
        project,
        ProjectCodingRunScheduleCreate(
            channel_id=channel_id,
            title="Nightly review",
            request="Review architecture and publish a concrete receipt.",
            recurrence="+1d",
            loop_policy={"enabled": True, "max_iterations": 3},
        ),
    )

    disabled = await disable_project_coding_run_schedule(db_session, project, schedule.id)
    assert disabled.status == "cancelled"
    assert await fire_project_coding_run_schedule(db_session, disabled, advance=False) is None

    resumed = await update_project_coding_run_schedule(
        db_session,
        project,
        schedule.id,
        ProjectCodingRunScheduleUpdate(
            title="Weekly architecture review",
            request="Review architecture and publish a receipt.",
            recurrence="+1w",
            enabled=True,
            loop_policy={},
        ),
    )
    assert resumed.status == "active"
    assert resumed.title == "Weekly architecture review"
    assert resumed.prompt == "Review architecture and publish a receipt."
    assert resumed.recurrence == "+1w"
    assert resumed.execution_config["project_coding_run_schedule"]["request"] == "Review architecture and publish a receipt."
    assert resumed.execution_config["project_coding_run_schedule"]["loop_policy"] == {}

    run = await fire_project_coding_run_schedule(db_session, resumed, advance=False)
    assert run is not None
    rows = await list_project_coding_run_schedules(db_session, project)
    assert rows[0]["enabled"] is True
    assert rows[0]["request"] == "Review architecture and publish a receipt."
    assert rows[0]["last_run"]["task_id"] == str(run.id)
    assert rows[0]["recent_runs"][0]["task_id"] == str(run.id)


@pytest.mark.asyncio
async def test_project_coding_run_schedule_update_can_clear_nullable_fields(db_session):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Spindrel",
        slug="spindrel",
        root_path="common/projects/spindrel",
        metadata_=_factory_meta(),
    )
    channel = Channel(
        id=channel_id,
        workspace_id=workspace_id,
        project_id=project_id,
        name="Claude Spindrel",
        bot_id="claude-code-bot",
        client_id="web",
    )
    db_session.add_all([project, channel])
    await db_session.commit()

    schedule = await create_project_coding_run_schedule(
        db_session,
        project,
        ProjectCodingRunScheduleCreate(
            channel_id=channel_id,
            title="Harness parity nightly",
            request="Run the harness parity smoke tier and publish a concrete receipt.",
            scheduled_at=datetime(2026, 5, 9, 22, 0, tzinfo=timezone.utc),
            recurrence="+5d",
            repo_path="spindrel",
            machine_target_grant=ProjectMachineTargetGrant(target_id="server", inspect=True),
        ),
    )

    updated = await update_project_coding_run_schedule(
        db_session,
        project,
        schedule.id,
        ProjectCodingRunScheduleUpdate(
            scheduled_at=None,
            scheduled_at_set=True,
            repo_path=None,
            repo_path_set=True,
            machine_target_grant=None,
            machine_target_grant_set=True,
        ),
    )

    cfg = updated.execution_config["project_coding_run_schedule"]
    assert updated.scheduled_at is None
    assert cfg["repo_path"] is None
    assert cfg["machine_target_grant"] is None
    grant = (await db_session.execute(select(TaskMachineGrant).where(TaskMachineGrant.task_id == schedule.id))).scalar_one_or_none()
    assert grant is None


@pytest.mark.asyncio
async def test_project_coding_run_schedule_definitions_are_not_listed_as_runs(db_session):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Spindrel",
        slug="spindrel",
        root_path="common/projects/spindrel",
        metadata_=_factory_meta(),
    )
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        workspace_id=workspace_id,
    )
    db_session.add_all([project, channel])
    await db_session.commit()

    schedule = await create_project_coding_run_schedule(
        db_session,
        project,
        ProjectCodingRunScheduleCreate(
            channel_id=channel_id,
            title="Nightly review",
            request="Review the project and publish a concrete receipt.",
            recurrence="+1d",
        ),
    )

    from app.services.project_coding_runs import list_project_coding_runs

    runs = await list_project_coding_runs(db_session, project)
    schedules = await list_project_coding_run_schedules(db_session, project)
    assert runs == []
    assert [item["id"] for item in schedules] == [str(schedule.id)]


@pytest.mark.asyncio
async def test_project_review_batches_group_launch_batch_runs_with_source_packs_and_review_tasks(db_session):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    launch_batch_id = f"issue-work-pack-batch:{uuid.uuid4()}"
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Spindrel",
        slug="spindrel-review-inbox",
        root_path="common/projects/spindrel",
        metadata_=_factory_meta(),
    )
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        workspace_id=workspace_id,
    )
    db_session.add_all([project, channel])
    await db_session.commit()

    first = await create_project_coding_run(
        db_session,
        project,
        ProjectCodingRunCreate(channel_id=channel_id, request="Fix the review inbox."),
    )
    second = await create_project_coding_run(
        db_session,
        project,
        ProjectCodingRunCreate(channel_id=channel_id, request="Add batch evidence."),
    )
    first_config = dict(first.execution_config)
    first_run_config = dict(first_config["project_coding_run"])
    first_run_config["launch_batch_id"] = launch_batch_id
    first_run_config["source_artifact"] = {
        "path": "docs/tracks/morning.md",
        "section": "Proposed Run Packs",
        "commit_sha": None,
    }
    first_config["project_coding_run"] = first_run_config
    first.execution_config = first_config
    second_config = dict(second.execution_config)
    second_run_config = dict(second_config["project_coding_run"])
    second_run_config["launch_batch_id"] = launch_batch_id
    second_config["project_coding_run"] = second_run_config
    second.execution_config = second_config
    receipt = ProjectRunReceipt(
        project_id=project_id,
        task_id=first.id,
        status="needs_review",
        summary="Ready for review.",
        changed_files=[{"path": "app.py"}],
        tests=[{"command": "pytest", "status": "passed"}],
        screenshots=[{"path": "docs/images/project-workspace-runs.png"}],
    )
    review_task = Task(
        id=uuid.uuid4(),
        bot_id="agent",
        client_id=channel.client_id,
        channel_id=channel_id,
        title="Review launch batch",
        prompt="Review",
        status="running",
        task_type="agent",
        execution_config={
            "run_preset_id": "project_coding_run_review",
            "project_coding_run_review": {
                "project_id": str(project_id),
                "selected_task_ids": [str(first.id), str(second.id)],
            },
        },
    )
    db_session.add_all([receipt, review_task])
    await db_session.commit()

    batches = await list_project_coding_run_review_batches(db_session, project)

    assert len(batches) == 1
    batch = batches[0]
    assert batch["id"] == launch_batch_id
    assert batch["status"] == "reviewing"
    assert batch["run_count"] == 2
    assert set(batch["task_ids"]) == {str(first.id), str(second.id)}
    assert batch["status_counts"]["ready_for_review"] == 1
    assert batch["evidence"]["tests_count"] == 1
    assert batch["evidence"]["screenshots_count"] == 1
    assert batch["source_artifacts"][0]["path"] == "docs/tracks/morning.md"
    assert batch["active_review_task"]["task_id"] == str(review_task.id)
    assert batch["actions"]["can_resume_review"] is True


@pytest.mark.asyncio
async def test_project_review_session_ledger_derives_outcomes_sources_and_evidence(db_session):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    launch_batch_id = f"issue-work-pack-batch:{uuid.uuid4()}"
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Spindrel",
        slug="spindrel-review-ledger",
        root_path="common/projects/spindrel",
        metadata_=_factory_meta(),
    )
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        workspace_id=workspace_id,
    )
    db_session.add_all([project, channel])
    await db_session.commit()

    run_task = await create_project_coding_run(
        db_session,
        project,
        ProjectCodingRunCreate(channel_id=channel_id, request="Fix ledger."),
    )
    run_config = dict(run_task.execution_config)
    project_run_config = dict(run_config["project_coding_run"])
    project_run_config["launch_batch_id"] = launch_batch_id
    project_run_config["source_artifact"] = {
        "path": "docs/tracks/ledger.md",
        "section": "Proposed Run Packs",
        "commit_sha": None,
    }
    run_config["project_coding_run"] = project_run_config
    run_task.execution_config = run_config

    run_receipt = ProjectRunReceipt(
        project_id=project_id,
        task_id=run_task.id,
        status="needs_review",
        summary="Ready for review.",
        changed_files=[{"path": "app/services/project_coding_run_lib.py"}],
        tests=[{"command": "pytest tests/unit/test_project_coding_runs.py", "status": "passed"}],
        screenshots=[{"path": "docs/images/project-workspace-review-ledger.png"}],
    )
    review_task = Task(
        id=uuid.uuid4(),
        bot_id="agent",
        client_id=channel.client_id,
        channel_id=channel_id,
        title="Review ledger run",
        prompt="Review",
        status="complete",
        task_type="agent",
        execution_config={
            "run_preset_id": "project_coding_run_review",
            "project_coding_run_review": {
                "project_id": str(project_id),
                "selected_task_ids": [str(run_task.id)],
                "merge_method": "squash",
            },
        },
    )
    review_receipt = ExecutionReceipt(
        scope="project_coding_run",
        action_type="review.marked",
        status="succeeded",
        summary="Accepted ledger run.",
        task_id=run_task.id,
        channel_id=channel_id,
        bot_id="agent",
        result={
            "outcome": "accepted",
            "review_task_id": str(review_task.id),
            "review_session_id": str(review_task.session_id) if review_task.session_id else None,
            "merge": False,
            "merge_method": "squash",
        },
    )
    db_session.add_all([run_receipt, review_task, review_receipt])
    await db_session.commit()

    sessions = await list_project_coding_run_review_sessions(db_session, project)

    assert len(sessions) == 1
    session = sessions[0]
    assert session["task_id"] == str(review_task.id)
    assert session["status"] == "finalized"
    assert session["selected_task_ids"] == [str(run_task.id)]
    assert session["selected_run_ids"] == [str(run_task.id)]
    assert session["launch_batch_ids"] == [launch_batch_id]
    assert session["source_artifacts"][0]["path"] == "docs/tracks/ledger.md"
    assert session["outcome_counts"] == {"accepted": 1}
    assert session["evidence"]["tests_count"] == 1
    assert session["evidence"]["screenshots_count"] == 1
    assert session["latest_summary"] == "Accepted ledger run."
    assert session["merge"]["method"] == "squash"


def test_project_coding_run_review_summary_uses_receipt_and_handoff_activity():
    task_id = uuid.uuid4()
    task = Task(
        id=task_id,
        bot_id="test-bot",
        status="complete",
        title="Project coding run",
    )
    receipt = ProjectRunReceipt(
        project_id=uuid.uuid4(),
        task_id=task_id,
        status="completed",
        summary="Ready for review.",
        handoff_url="https://github.com/mtotho/spindrel/pull/123",
        changed_files=["app.py"],
        tests=[{"command": "pytest", "status": "passed"}],
        screenshots=[{"path": "docs/images/project-workspace-runs.png"}],
    )
    activity = [
        {
            "kind": "execution_receipt",
            "status": "succeeded",
            "summary": "Project run repository state inspected.",
            "source": {
                "scope": "project_coding_run",
                "action_type": "handoff.status",
                "result": {
                    "pr_status": {
                        "url": "https://github.com/mtotho/spindrel/pull/123",
                        "state": "OPEN",
                        "isDraft": True,
                        "checks": [{"conclusion": "SUCCESS"}],
                    }
                },
            },
        },
        {
            "kind": "execution_receipt",
            "status": "succeeded",
            "summary": "Project run draft PR ready.",
            "source": {
                "scope": "project_coding_run",
                "action_type": "handoff.open_pr",
                "result": {"pr_url": "https://github.com/mtotho/spindrel/pull/123"},
            },
        },
    ]

    review = _review_summary(task=task, receipt=receipt, activity=activity, instance=None)

    assert review["status"] == "ready_for_review"
    assert review["handoff_url"] == "https://github.com/mtotho/spindrel/pull/123"
    assert review["evidence"] == {
        "changed_files_count": 1,
        "tests_count": 1,
        "screenshots_count": 1,
        "dev_targets_count": 0,
        "has_tests": True,
        "has_screenshots": True,
        "has_dev_targets": False,
    }
    assert review["actions"]["can_mark_reviewed"] is True


@pytest.mark.asyncio
async def test_project_review_prompt_template_marks_commands_before_substitution(tmp_path):
    calls: list[tuple[str, ...]] = []

    async def runner(cwd: str, args: tuple[str, ...], env: dict[str, str], timeout: int) -> CommandResult:
        calls.append(args)
        return CommandResult(args=args, cwd=cwd, exit_code=0, stdout="clean\n")

    prompt = await expand_project_review_prompt_template(
        "Operator:\n{{operator_prompt}}\n! `git status --short`\n",
        variables={"operator_prompt": "text\n! `echo should-not-run`"},
        cwd=str(tmp_path),
        env={},
        command_runner=runner,
    )

    assert calls == [("bash", "-lc", "git status --short")]
    assert "echo should-not-run" in prompt
    assert "$ git status --short" in prompt


@pytest.mark.asyncio
async def test_finalize_project_coding_run_review_marks_only_accepted_selected_runs(db_session):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    run_task_id = uuid.uuid4()
    rejected_task_id = uuid.uuid4()
    review_task_id = uuid.uuid4()
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Spindrel",
        slug="spindrel",
        root_path="common/projects/spindrel",
        metadata_={},
    )
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        workspace_id=workspace_id,
    )
    now = datetime.now(timezone.utc)
    run_task = Task(
        id=run_task_id,
        bot_id="agent",
        client_id=channel.client_id,
        channel_id=channel_id,
        title="Project Coding Run",
        prompt="Do the work",
        status="complete",
        task_type="agent",
        created_at=now,
        execution_config={
            "run_preset_id": "project_coding_run",
            "project_coding_run": {"project_id": str(project_id), "branch": "spindrel/demo", "repo": {}},
        },
    )
    rejected_task = Task(
        id=rejected_task_id,
        bot_id="agent",
        client_id=channel.client_id,
        channel_id=channel_id,
        title="Project Coding Run",
        prompt="Do other work",
        status="complete",
        task_type="agent",
        created_at=now,
        execution_config={
            "run_preset_id": "project_coding_run",
            "project_coding_run": {"project_id": str(project_id), "branch": "spindrel/other", "repo": {}},
        },
    )
    review_task = Task(
        id=review_task_id,
        bot_id="agent",
        client_id=channel.client_id,
        channel_id=channel_id,
        title="Review Runs",
        prompt="Review",
        status="running",
        task_type="agent",
        created_at=now,
        execution_config={
            "run_preset_id": "project_coding_run_review",
            "project_coding_run_review": {
                "project_id": str(project_id),
                "selected_task_ids": [str(run_task_id), str(rejected_task_id)],
                "merge_method": "squash",
            },
        },
    )
    db_session.add_all([project, channel, run_task, rejected_task, review_task])
    await db_session.commit()

    accepted = await finalize_project_coding_run_review(
        db_session,
        project,
        ProjectCodingRunReviewFinalize(
            review_task_id=review_task_id,
            run_task_id=run_task_id,
            outcome="accepted",
            summary="Accepted after review.",
            details={"checks": "passed"},
        ),
    )
    rejected = await finalize_project_coding_run_review(
        db_session,
        project,
        ProjectCodingRunReviewFinalize(
            review_task_id=review_task_id,
            run_task_id=rejected_task_id,
            outcome="rejected",
            summary="Needs changes.",
            details={"reason": "missing screenshot"},
        ),
    )

    assert accepted["status"] == "reviewed"
    assert rejected["status"] == "rejected"
    receipts = list((await db_session.execute(
        select(ExecutionReceipt).where(ExecutionReceipt.scope == "project_coding_run").order_by(ExecutionReceipt.action_type)
    )).scalars().all())
    assert [(receipt.task_id, receipt.action_type, receipt.status) for receipt in receipts] == [
        (run_task_id, "review.marked", "succeeded"),
        (rejected_task_id, "review.result", "needs_review"),
    ]
    assert receipts[0].result["review_task_id"] == str(review_task_id)


@pytest.mark.asyncio
async def test_project_coding_run_review_context_returns_selected_evidence(db_session):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    run_task_id = uuid.uuid4()
    review_task_id = uuid.uuid4()
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Spindrel",
        slug="spindrel",
        root_path="common/projects/spindrel",
        metadata_={
            "blueprint_snapshot": {
                "env": {"E2E_PORT": "8000"},
                "required_secrets": ["GITHUB_TOKEN"],
                "repos": [{"path": "spindrel", "branch": "development"}],
            }
        },
    )
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        workspace_id=workspace_id,
    )
    now = datetime.now(timezone.utc)
    run_task = Task(
        id=run_task_id,
        bot_id="agent",
        client_id=channel.client_id,
        channel_id=channel_id,
        title="Project Coding Run",
        prompt="Do the work",
        status="complete",
        task_type="agent",
        created_at=now,
        execution_config={
            "run_preset_id": "project_coding_run",
            "project_coding_run": {
                "project_id": str(project_id),
                "branch": "spindrel/demo",
                "base_branch": "development",
                "repo": {"path": "spindrel"},
            },
        },
    )
    review_task = Task(
        id=review_task_id,
        bot_id="agent",
        client_id=channel.client_id,
        channel_id=channel_id,
        title="Review Runs",
        prompt="Review",
        status="running",
        task_type="agent",
        created_at=now,
        execution_config={
            "run_preset_id": "project_coding_run_review",
            "project_coding_run_review": {
                "project_id": str(project_id),
                "selected_task_ids": [str(run_task_id)],
                "operator_prompt": "Merge accepted work.",
                "merge_method": "squash",
                "repo_path": "spindrel",
            },
        },
    )
    receipt = ProjectRunReceipt(
        project_id=project_id,
        task_id=run_task_id,
        bot_id="agent",
        status="completed",
        summary="Ready for review.",
        handoff_url="https://github.com/mtotho/spindrel/pull/123",
        changed_files=["app.py"],
        tests=[{"command": "pytest tests/unit/test_project_coding_runs.py", "status": "passed"}],
        screenshots=[{"path": "docs/images/project-workspace-runs.png", "status": "captured"}],
    )
    db_session.add_all([project, channel, run_task, review_task, receipt])
    await db_session.commit()

    payload = await get_project_coding_run_review_context(db_session, project, review_task_id)

    assert payload["ok"] is True
    assert payload["operator_prompt"] == "Merge accepted work."
    assert payload["readiness"]["ready"] is True
    assert payload["readiness"]["e2e"]["configured"] is True
    assert payload["readiness"]["github"]["token_configured"] is False
    assert payload["readiness"]["runtime_env"]["missing_secrets"] == ["GITHUB_TOKEN"]
    assert payload["selected_task_ids"] == [str(run_task_id)]
    selected = payload["selected_runs"][0]
    assert selected["task_id"] == str(run_task_id)
    assert selected["handoff_url"] == "https://github.com/mtotho/spindrel/pull/123"
    assert selected["review"]["evidence"]["tests_count"] == 1
    assert selected["review"]["evidence"]["screenshots_count"] == 1


@pytest.mark.asyncio
async def test_finalize_project_coding_run_review_returns_structured_error_for_unselected_run(db_session):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    selected_task_id = uuid.uuid4()
    other_task_id = uuid.uuid4()
    review_task_id = uuid.uuid4()
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Spindrel",
        slug="spindrel",
        root_path="common/projects/spindrel",
        metadata_={},
    )
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        workspace_id=workspace_id,
    )
    now = datetime.now(timezone.utc)
    selected_task = Task(
        id=selected_task_id,
        bot_id="agent",
        client_id=channel.client_id,
        channel_id=channel_id,
        title="Selected Run",
        prompt="Do work",
        status="complete",
        task_type="agent",
        created_at=now,
        execution_config={
            "run_preset_id": "project_coding_run",
            "project_coding_run": {"project_id": str(project_id), "branch": "spindrel/selected", "repo": {}},
        },
    )
    other_task = Task(
        id=other_task_id,
        bot_id="agent",
        client_id=channel.client_id,
        channel_id=channel_id,
        title="Other Run",
        prompt="Do other work",
        status="complete",
        task_type="agent",
        created_at=now,
        execution_config={
            "run_preset_id": "project_coding_run",
            "project_coding_run": {"project_id": str(project_id), "branch": "spindrel/other", "repo": {}},
        },
    )
    review_task = Task(
        id=review_task_id,
        bot_id="agent",
        client_id=channel.client_id,
        channel_id=channel_id,
        title="Review Runs",
        prompt="Review",
        status="running",
        task_type="agent",
        created_at=now,
        execution_config={
            "run_preset_id": "project_coding_run_review",
            "project_coding_run_review": {
                "project_id": str(project_id),
                "selected_task_ids": [str(selected_task_id)],
            },
        },
    )
    db_session.add_all([project, channel, selected_task, other_task, review_task])
    await db_session.commit()

    payload = await finalize_project_coding_run_review(
        db_session,
        project,
        ProjectCodingRunReviewFinalize(
            review_task_id=review_task_id,
            run_task_id=other_task_id,
            outcome="accepted",
            summary="Should not finalize.",
        ),
    )

    assert payload == {
        "ok": False,
        "status": "blocked",
        "error": "coding run was not selected for this review session",
        "error_code": "project_review_run_not_selected",
        "error_kind": "validation",
        "retryable": False,
        "run_task_id": str(other_task_id),
    }
