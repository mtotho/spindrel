from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.db.models import Channel, ExecutionReceipt, Project, Task
from app.services.project_run_handoff import CommandResult, _extract_pr_url, prepare_project_run_handoff


pytestmark = pytest.mark.asyncio


class FakeGitRunner:
    def __init__(self, *, current_branch: str = "development", dirty: str = "", pr_url: str | None = None) -> None:
        self.current_branch = current_branch
        self.dirty = dirty
        self.pr_url = pr_url
        self.calls: list[tuple[str, ...]] = []

    async def __call__(self, cwd: str, args: tuple[str, ...], env: dict[str, str], timeout: int) -> CommandResult:
        self.calls.append(args)
        self.last_env = dict(env)
        if args == ("git", "rev-parse", "--show-toplevel"):
            return CommandResult(args=args, cwd=cwd, exit_code=0, stdout=cwd)
        if args == ("git", "status", "--short"):
            return CommandResult(args=args, cwd=cwd, exit_code=0, stdout=self.dirty)
        if args == ("git", "rev-parse", "--abbrev-ref", "HEAD"):
            return CommandResult(args=args, cwd=cwd, exit_code=0, stdout=f"{self.current_branch}\n")
        if args[:3] == ("git", "remote", "get-url"):
            return CommandResult(args=args, cwd=cwd, exit_code=0, stdout="git@github.com:mtotho/spindrel.git\n")
        if args[:3] == ("git", "rev-parse", "--verify"):
            exists = args[-1] == self.current_branch
            return CommandResult(args=args, cwd=cwd, exit_code=0 if exists else 1, stdout=args[-1] if exists else "")
        if args[:2] == ("git", "fetch"):
            return CommandResult(args=args, cwd=cwd, exit_code=0)
        if args[:2] == ("git", "switch"):
            self.current_branch = args[3] if len(args) > 3 and args[2] == "-c" else args[-1]
            return CommandResult(args=args, cwd=cwd, exit_code=0)
        if args[:2] == ("git", "push"):
            return CommandResult(args=args, cwd=cwd, exit_code=0, stdout="pushed\n")
        if args[:3] == ("gh", "pr", "view"):
            if self.pr_url:
                return CommandResult(args=args, cwd=cwd, exit_code=0, stdout=f'{{"url":"{self.pr_url}","state":"OPEN"}}')
            return CommandResult(args=args, cwd=cwd, exit_code=1, stderr="no pull request")
        if args[:3] == ("gh", "pr", "create"):
            return CommandResult(args=args, cwd=cwd, exit_code=0, stdout="https://github.com/mtotho/spindrel/pull/123\n")
        return CommandResult(args=args, cwd=cwd, exit_code=0)


async def _seed_project_run(db_session, monkeypatch, tmp_path):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    task_id = uuid.uuid4()
    monkeypatch.setattr("app.services.shared_workspace.local_workspace_base", lambda: str(tmp_path))
    monkeypatch.setattr(
        "app.services.project_run_handoff.get_bot",
        lambda _bot_id: SimpleNamespace(id="agent", shared_workspace_id=str(workspace_id)),
    )
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
    task = Task(
        id=task_id,
        bot_id="agent",
        client_id=channel.client_id,
        channel_id=channel_id,
        title="Project Coding Run",
        prompt="Do the work",
        status="running",
        task_type="agent",
        created_at=datetime.now(timezone.utc),
        execution_config={
            "run_preset_id": "project_coding_run",
            "project_coding_run": {
                "project_id": str(project_id),
                "branch": "spindrel/project-12345678-demo",
                "base_branch": "development",
                "repo": {"path": "repo"},
            },
        },
    )
    db_session.add_all([project, channel, task])
    await db_session.commit()
    repo_dir = tmp_path / "shared" / str(workspace_id) / "common" / "projects" / "spindrel" / "repo"
    repo_dir.mkdir(parents=True)
    return project, channel, task, repo_dir


async def test_prepare_project_run_handoff_creates_branch_and_progress_receipt(db_session, monkeypatch, tmp_path):
    project, channel, task, repo_dir = await _seed_project_run(db_session, monkeypatch, tmp_path)
    runner = FakeGitRunner(current_branch="development")

    payload = await prepare_project_run_handoff(
        db_session,
        task_id=task.id,
        channel_id=channel.id,
        bot_id="agent",
        command_runner=runner,
    )

    assert payload["ok"] is True
    assert payload["branch"] == "spindrel/project-12345678-demo"
    assert payload["repo_root"] == str(repo_dir)
    assert ("git", "switch", "-c", "spindrel/project-12345678-demo", "origin/development") in runner.calls
    receipts = list((await db_session.execute(
        select(ExecutionReceipt).where(ExecutionReceipt.scope == "project_coding_run")
    )).scalars().all())
    assert [(receipt.action_type, receipt.status) for receipt in receipts] == [
        ("handoff.prepare_branch", "succeeded")
    ]
    assert receipts[0].target["project_id"] == str(project.id)
    assert receipts[0].task_id == task.id


async def test_prepare_project_run_handoff_maps_github_token_for_git_and_gh(db_session, monkeypatch, tmp_path):
    _project, channel, task, _repo_dir = await _seed_project_run(db_session, monkeypatch, tmp_path)

    async def _runtime(_db, _project_id):
        return SimpleNamespace(env={"GITHUB_TOKEN": "ghp_project_token"})

    monkeypatch.setattr(
        "app.services.project_run_handoff.load_project_runtime_environment_for_id",
        _runtime,
    )
    runner = FakeGitRunner(current_branch="development")

    payload = await prepare_project_run_handoff(
        db_session,
        task_id=task.id,
        channel_id=channel.id,
        bot_id="agent",
        command_runner=runner,
    )

    assert payload["ok"] is True
    assert runner.last_env["GITHUB_TOKEN"] == "ghp_project_token"
    assert runner.last_env["GH_TOKEN"] == "ghp_project_token"
    assert runner.last_env["GIT_TERMINAL_PROMPT"] == "0"
    assert runner.last_env["GIT_ASKPASS"].endswith("spindrel-github-askpass.sh")


async def test_prepare_project_run_handoff_blocks_branch_switch_when_dirty(db_session, monkeypatch, tmp_path):
    _project, channel, task, _repo_dir = await _seed_project_run(db_session, monkeypatch, tmp_path)
    runner = FakeGitRunner(current_branch="development", dirty=" M app.py\n")

    payload = await prepare_project_run_handoff(
        db_session,
        task_id=task.id,
        channel_id=channel.id,
        bot_id="agent",
        command_runner=runner,
    )

    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert "uncommitted changes" in payload["blockers"][0]
    assert not any(call[:2] == ("git", "switch") for call in runner.calls)
    receipt = (await db_session.execute(
        select(ExecutionReceipt).where(ExecutionReceipt.scope == "project_coding_run")
    )).scalar_one()
    assert receipt.action_type == "handoff.prepare_branch"
    assert receipt.status == "blocked"


async def test_prepare_project_run_handoff_uses_isolated_session_worktree(db_session, monkeypatch, tmp_path):
    _project, channel, task, _repo_dir = await _seed_project_run(db_session, monkeypatch, tmp_path)
    isolated_repo = tmp_path / "session-worktrees" / "spindrel" / "repo"
    isolated_repo.mkdir(parents=True)
    task.execution_config = {
        **task.execution_config,
        "work_surface_mode": "isolated_worktree",
        "project_coding_run": {
            **task.execution_config["project_coding_run"],
            "session_environment": {
                "mode": "isolated",
                "status": "ready",
                "cwd": str(isolated_repo),
            },
        },
    }
    await db_session.commit()
    runner = FakeGitRunner(current_branch="spindrel/project-12345678-demo")

    payload = await prepare_project_run_handoff(
        db_session,
        task_id=task.id,
        channel_id=channel.id,
        bot_id="agent",
        command_runner=runner,
    )

    assert payload["ok"] is True
    assert payload["repo_root"] == str(isolated_repo)
    assert runner.calls[0] == ("git", "rev-parse", "--show-toplevel")


async def test_open_pr_pushes_branch_and_returns_handoff(db_session, monkeypatch, tmp_path):
    _project, channel, task, _repo_dir = await _seed_project_run(db_session, monkeypatch, tmp_path)
    runner = FakeGitRunner(current_branch="spindrel/project-12345678-demo")

    payload = await prepare_project_run_handoff(
        db_session,
        action="open_pr",
        task_id=task.id,
        channel_id=channel.id,
        bot_id="agent",
        title="Project handoff",
        body="Ready for review.",
        command_runner=runner,
    )

    assert payload["ok"] is True
    assert payload["pr_url"] == "https://github.com/mtotho/spindrel/pull/123"
    assert payload["handoff"]["type"] == "pull_request"
    action_types = set((await db_session.execute(
        select(ExecutionReceipt.action_type).where(ExecutionReceipt.scope == "project_coding_run")
    )).scalars().all())
    assert action_types == {"handoff.prepare_branch", "handoff.push", "handoff.open_pr"}


async def test_extract_pr_url_handles_json_and_plain_output():
    assert _extract_pr_url('{"url":"https://github.com/acme/repo/pull/1"}') == "https://github.com/acme/repo/pull/1"
    assert _extract_pr_url("Created https://github.com/acme/repo/pull/2") == "https://github.com/acme/repo/pull/2"
