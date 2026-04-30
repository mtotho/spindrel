from __future__ import annotations

import uuid

from app.db.models import Project, ProjectRunReceipt, Task
from app.services.project_coding_runs import _review_summary, project_coding_run_defaults


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
