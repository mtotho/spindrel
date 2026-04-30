from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.db.models import Channel, ExecutionReceipt, Project, ProjectRunReceipt, Task
from app.services.project_coding_runs import (
    ProjectCodingRunReviewFinalize,
    _review_summary,
    expand_project_review_prompt_template,
    finalize_project_coding_run_review,
    get_project_coding_run_review_context,
    project_coding_run_defaults,
)
from app.services.project_run_handoff import CommandResult


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
        "has_tests": True,
        "has_screenshots": True,
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
