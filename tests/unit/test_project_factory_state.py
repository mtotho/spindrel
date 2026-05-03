"""Tests for app/services/project_factory_state.py - stage classification + composition."""
from __future__ import annotations

import uuid

import pytest

from app.db.models import (
    Channel,
    Project,
    SharedWorkspace,
    WorkspaceAttentionItem,
)
from app.services.project_factory_state import (
    _classify_stage,
    get_project_factory_state,
)


def _runs(
    *,
    by_state: dict[str, int] | None = None,
    has_active_review_task: bool = False,
    active_implementation: int = 0,
) -> dict[str, object]:
    by_state = dict(by_state or {})
    return {
        "by_queue_state": by_state,
        "ready_for_review": by_state.get("ready_for_review", 0),
        "in_flight": sum(
            by_state.get(s, 0)
            for s in ("changes_requested", "follow_up_running", "reviewing", "blocked", "missing_evidence")
        ),
        "active_implementation": active_implementation,
        "has_active_review_task": has_active_review_task,
        "reviewed": by_state.get("reviewed", 0),
        "total": sum(by_state.values()),
    }


def _planning(present: bool = False) -> dict[str, object]:
    return {"prd_path": None, "prd_files": [], "present": present}


def test_classify_unconfigured_when_no_blueprint():
    stage = _classify_stage(
        blueprint_applied=False,
        runtime_ready=True,
        runs=_runs(),
        pack_counts={"proposed": 0, "needs_info": 0, "launched": 0, "dismissed": 0},
        intake_counts={"pending": 0},
        planning=_planning(),
    )
    assert stage == "unconfigured"


def test_classify_unconfigured_when_runtime_not_ready():
    stage = _classify_stage(
        blueprint_applied=True,
        runtime_ready=False,
        runs=_runs(),
        pack_counts={"proposed": 0, "needs_info": 0, "launched": 0, "dismissed": 0},
        intake_counts={"pending": 0},
        planning=_planning(),
    )
    assert stage == "unconfigured"


def test_classify_needs_review_wins_over_runs_in_flight():
    """A ready_for_review run with no active reviewer should surface as needs_review,
    even when other in-flight runs exist - that's the user's actual next action."""
    stage = _classify_stage(
        blueprint_applied=True,
        runtime_ready=True,
        runs=_runs(by_state={"ready_for_review": 1, "changes_requested": 1}),
        pack_counts={"proposed": 0, "needs_info": 0, "launched": 0, "dismissed": 0},
        intake_counts={"pending": 0},
        planning=_planning(),
    )
    assert stage == "needs_review"


def test_classify_runs_in_flight_when_reviewer_active_on_ready_run():
    stage = _classify_stage(
        blueprint_applied=True,
        runtime_ready=True,
        runs=_runs(by_state={"ready_for_review": 1}, has_active_review_task=True),
        pack_counts={"proposed": 0, "needs_info": 0, "launched": 0, "dismissed": 0},
        intake_counts={"pending": 0},
        planning=_planning(),
    )
    assert stage == "runs_in_flight"


def test_classify_runs_in_flight_when_active_implementation():
    stage = _classify_stage(
        blueprint_applied=True,
        runtime_ready=True,
        runs=_runs(active_implementation=1),
        pack_counts={"proposed": 0, "needs_info": 0, "launched": 0, "dismissed": 0},
        intake_counts={"pending": 0},
        planning=_planning(),
    )
    assert stage == "runs_in_flight"


def test_classify_planning_when_prd_signal_present_and_no_packs():
    stage = _classify_stage(
        blueprint_applied=True,
        runtime_ready=True,
        runs=_runs(),
        pack_counts={"proposed": 0, "needs_info": 0, "launched": 0, "dismissed": 0},
        intake_counts={"pending": 0},
        planning=_planning(present=True),
    )
    assert stage == "planning"


def test_classify_ready_no_work_when_configured_and_idle():
    stage = _classify_stage(
        blueprint_applied=True,
        runtime_ready=True,
        runs=_runs(),
        pack_counts={"proposed": 0, "needs_info": 0, "launched": 0, "dismissed": 0},
        intake_counts={"pending": 0},
        planning=_planning(),
    )
    assert stage == "ready_no_work"


def test_classify_reviewed_idle_when_all_runs_reviewed():
    stage = _classify_stage(
        blueprint_applied=True,
        runtime_ready=True,
        runs=_runs(by_state={"reviewed": 3}),
        pack_counts={"proposed": 0, "needs_info": 0, "launched": 2, "dismissed": 1},
        intake_counts={"pending": 0},
        planning=_planning(),
    )
    assert stage == "reviewed_idle"


def test_classify_pending_intake_does_not_count_as_ready_no_work():
    """A pile of intake should not surface as ready_no_work - it should fall through
    to reviewed_idle (configured but not actively-needs-something)."""
    stage = _classify_stage(
        blueprint_applied=True,
        runtime_ready=True,
        runs=_runs(),
        pack_counts={"proposed": 0, "needs_info": 0, "launched": 0, "dismissed": 0},
        intake_counts={"pending": 12},
        planning=_planning(),
    )
    assert stage != "ready_no_work"


@pytest.mark.asyncio
async def test_get_project_factory_state_unconfigured_for_brand_new_project(db_session):
    workspace = SharedWorkspace(id=uuid.uuid4(), name="ws", slug="ws")
    db_session.add(workspace)
    await db_session.flush()

    project = Project(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        name="Greenfield",
        slug="greenfield",
        root_path="common/projects/greenfield",
        metadata_={},
    )
    db_session.add(project)
    await db_session.commit()

    state = await get_project_factory_state(db_session, project)
    assert state["current_stage"] == "unconfigured"
    assert state["blueprint"]["applied"] is False
    # Phase 4BD.0 - canonical_repo present even when no blueprint applied.
    assert state["canonical_repo"] == {"relative_path": None, "host_path": None}
    # Phase 4BD.1 - intake_config defaults to "unset" with empty target/metadata.
    assert state["intake_config"]["kind"] == "unset"
    assert state["intake_config"]["configured"] is False
    assert state["intake_config"]["target"] is None
    assert state["intake_config"]["host_target"] is None
    # Phase 4BE.1 - repo_workflow surface present even with no canonical repo.
    repo_workflow = state["repo_workflow"]
    assert repo_workflow["relative_path"] == ".spindrel/WORKFLOW.md"
    assert repo_workflow["present"] is False
    assert repo_workflow["host_path"] is None
    assert repo_workflow["sections"] == {
        "policy": None,
        "artifacts": None,
        "intake": None,
        "runs": None,
        "hooks": None,
        "dependencies": None,
    }
    assert state["intake"] == {"pending": 0}
    assert state["run_packs"] == {"proposed": 0, "needs_info": 0, "launched": 0, "dismissed": 0}
    assert state["runs"]["total"] == 0
    # Phase 4BG.3 - by_phase + concurrency block present even when no runs exist.
    assert state["runs"]["by_phase"] == {}
    assert state["runs"]["concurrency"] == {"cap": None, "in_flight": 0, "headroom": None}
    suggested = state["suggested_next_action"]
    assert suggested["stage"] == "unconfigured"
    assert suggested["skill_id_to_load"] == "project/setup/init"


@pytest.mark.asyncio
async def test_get_project_factory_state_counts_pending_intake_and_packs(db_session):
    workspace = SharedWorkspace(id=uuid.uuid4(), name="ws", slug="ws")
    db_session.add(workspace)
    await db_session.flush()

    project = Project(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        name="P",
        slug="p",
        root_path="common/projects/p",
        metadata_={"blueprint_snapshot": {"repos": [{"path": "p", "branch": "main"}]}},
    )
    db_session.add(project)
    await db_session.flush()

    channel = Channel(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        name="planning",
        client_id="default",
    )
    db_session.add(channel)
    await db_session.flush()

    db_session.add_all([
        WorkspaceAttentionItem(
            id=uuid.uuid4(),
            source_type="user",
            source_id="u1",
            channel_id=channel.id,
            target_kind="channel",
            target_id=str(channel.id),
            dedupe_key=f"intake-{i}",
            severity="info",
            title=f"intake {i}",
            message="",
            status="open",
        )
        for i in range(3)
    ])
    await db_session.commit()

    state = await get_project_factory_state(db_session, project)
    assert state["intake"]["pending"] == 3
    # Phase 4BD.6: run_packs is a stable zeroed schema; the substrate is
    # file-resident now. The factory state never re-derives shaping_packs.
    assert state["run_packs"] == {"proposed": 0, "needs_info": 0, "launched": 0, "dismissed": 0}
    assert state["current_stage"] != "shaping_packs"
    # Phase 4BD.0 - canonical_repo resolves to first repo when no flag is set.
    assert state["canonical_repo"]["relative_path"] == "p"
    # Phase 4BD.1 - intake_config rides along even when project still uses defaults.
    assert state["intake_config"]["kind"] == "unset"
    assert state["intake_config"]["configured"] is False
