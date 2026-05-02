"""Phase 4BC - tests for the canonical orchestration-policy view."""
from __future__ import annotations

import uuid

import pytest

from app.db.models import Channel, Project
from app.services.project_orchestration_policy import get_project_orchestration_policy
from app.services.project_run_stall_sweep import (
    DEFAULT_STALL_TIMEOUT_SECONDS,
    MIN_STALL_TIMEOUT_SECONDS,
)


def _project(metadata: dict) -> Project:
    return Project(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        name="Cap",
        slug="cap",
        root_path="common/projects/cap",
        metadata_=metadata,
    )


@pytest.mark.asyncio
async def test_orchestration_policy_unconfigured_project(db_session):
    project = _project({})
    db_session.add(project)
    await db_session.commit()

    policy = await get_project_orchestration_policy(db_session, project)
    assert policy["blueprint_applied"] is False
    assert policy["concurrency"] == {
        "max_concurrent_runs": None,
        "source": "unset",
        "in_flight": 0,
        "headroom": None,
        "saturated": False,
    }
    assert policy["timeouts"]["stall_timeout_seconds"] == DEFAULT_STALL_TIMEOUT_SECONDS
    assert policy["timeouts"]["stall_source"] == "default"
    assert policy["timeouts"]["stall_default"] == DEFAULT_STALL_TIMEOUT_SECONDS
    assert policy["timeouts"]["stall_min"] == MIN_STALL_TIMEOUT_SECONDS
    assert policy["timeouts"]["turn_timeout_seconds"] is None
    assert policy["timeouts"]["turn_source"] == "unset"
    assert policy["timeouts"]["turn_enforced"] is False
    assert policy["repo_workflow"]["present"] is False
    assert policy["repo_workflow"]["policy_section"] is None
    assert policy["canonical_repo"] == {"relative_path": None, "host_path": None}


@pytest.mark.asyncio
async def test_orchestration_policy_reports_blueprint_values_and_in_flight(db_session):
    project = _project({
        "blueprint_snapshot": {
            "repos": [{"name": "p", "path": "p", "branch": "main"}],
            "max_concurrent_runs": 2,
            "stall_timeout_seconds": 600,
            "turn_timeout_seconds": 90,
        }
    })
    channel = Channel(
        id=uuid.uuid4(),
        name="Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        workspace_id=project.workspace_id,
    )
    db_session.add_all([project, channel])
    await db_session.commit()

    policy = await get_project_orchestration_policy(db_session, project)
    assert policy["blueprint_applied"] is True
    assert policy["concurrency"]["max_concurrent_runs"] == 2
    assert policy["concurrency"]["source"] == "blueprint"
    assert policy["concurrency"]["in_flight"] == 0
    assert policy["concurrency"]["headroom"] == 2
    assert policy["concurrency"]["saturated"] is False
    assert policy["timeouts"]["stall_timeout_seconds"] == 600
    assert policy["timeouts"]["stall_source"] == "blueprint"
    assert policy["timeouts"]["turn_timeout_seconds"] == 90
    assert policy["timeouts"]["turn_source"] == "blueprint"
    assert policy["canonical_repo"]["relative_path"] == "p"


@pytest.mark.asyncio
async def test_orchestration_policy_marks_saturated_when_cap_reached(db_session):
    """When in_flight runs equal the cap, the policy view reports `saturated: true`
    and `headroom: 0` so the agent can refuse to launch another implementation
    run before consulting the user."""
    from app.services.project_coding_runs import ProjectCodingRunCreate, create_project_coding_run

    project = _project({
        "blueprint_snapshot": {
            "repos": [{"name": "p", "path": "p", "branch": "main"}],
            "max_concurrent_runs": 1,
        }
    })
    channel = Channel(
        id=uuid.uuid4(),
        name="Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        workspace_id=project.workspace_id,
    )
    db_session.add_all([project, channel])
    await db_session.commit()

    await create_project_coding_run(
        db_session,
        project,
        ProjectCodingRunCreate(channel_id=channel.id, request="first"),
    )

    policy = await get_project_orchestration_policy(db_session, project)
    assert policy["concurrency"]["in_flight"] == 1
    assert policy["concurrency"]["headroom"] == 0
    assert policy["concurrency"]["saturated"] is True


def test_orchestration_policy_tool_is_registered():
    # Importing the module triggers @register via the local-tools loader glob.
    import app.tools.local.project_orchestration_policy  # noqa: F401
    from app.tools.registry import _tools

    assert "get_project_orchestration_policy" in _tools
