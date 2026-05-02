"""Tests for app/services/project_run_stall_sweep.py and stall propagation."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.db.models import Project, Task
from app.services.project_coding_run_lib import (
    PROJECT_CODING_RUN_PRESET_ID,
    _stall_state_for_task,
    _work_surface_summary,
    project_coding_run_review_queue_state,
)
from app.services.project_run_stall_sweep import (
    DEFAULT_STALL_TIMEOUT_SECONDS,
    _project_stall_timeout_seconds,
    sweep_stalled_project_runs,
)


def _make_task(*, status: str = "running", stall_state: dict | None = None) -> SimpleNamespace:
    cfg: dict = {"run_preset_id": PROJECT_CODING_RUN_PRESET_ID, "project_coding_run": {}}
    if stall_state is not None:
        cfg["stall_state"] = stall_state
    return SimpleNamespace(status=status, execution_config=cfg)


def test_stall_state_returns_payload_only_for_in_flight_tasks():
    payload = {"stalled_at": "2026-05-02T12:00:00+00:00", "timeout_seconds": 600}
    running = _make_task(status="running", stall_state=payload)
    complete = _make_task(status="complete", stall_state=payload)
    failed = _make_task(status="failed", stall_state=payload)
    pending = _make_task(status="pending", stall_state=payload)

    assert _stall_state_for_task(running) == payload
    assert _stall_state_for_task(pending) == payload
    # Terminal tasks ignore any leftover marker.
    assert _stall_state_for_task(complete) is None
    assert _stall_state_for_task(failed) is None


def test_stall_state_ignores_blank_or_missing_marker():
    assert _stall_state_for_task(_make_task()) is None
    blank = _make_task(stall_state={})
    assert _stall_state_for_task(blank) is None
    no_timestamp = _make_task(stall_state={"timeout_seconds": 600})
    assert _stall_state_for_task(no_timestamp) is None


def test_work_surface_propagates_stall_state_to_run_phase_override():
    project = SimpleNamespace(id=uuid.uuid4(), root_path="common/projects/p")
    payload = {
        "stalled_at": "2026-05-02T12:00:00+00:00",
        "last_activity_at": "2026-05-02T11:30:00+00:00",
        "timeout_seconds": 900,
        "idle_seconds": 1800,
        "reason": "No agent activity for 1800s (>= 900s threshold).",
    }
    task = _make_task(status="running", stall_state=payload)
    surface = _work_surface_summary(project=project, task=task, instance=None)

    assert surface["run_phase_override"] == "stalled"
    assert surface["stall_state"] == payload
    # Other invariants of the shared-root surface still hold.
    assert surface["kind"] == "project"
    assert surface["isolation"] == "shared"


def test_work_surface_drops_stall_overlay_for_terminal_task():
    project = SimpleNamespace(id=uuid.uuid4(), root_path="common/projects/p")
    payload = {"stalled_at": "2026-05-02T12:00:00+00:00", "timeout_seconds": 900}
    task = _make_task(status="complete", stall_state=payload)
    surface = _work_surface_summary(project=project, task=task, instance=None)

    assert "run_phase_override" not in surface
    assert "stall_state" not in surface


def test_queue_state_returns_blocked_when_stalled_via_work_surface():
    """Operator queue surfaces a sweep-flagged stall as ``blocked``."""
    row = {
        "task": {"status": "running"},
        "review": {"status": "pending", "evidence": {"changed_files_count": 1}},
        "work_surface": {"run_phase_override": "stalled"},
    }
    assert project_coding_run_review_queue_state(row) == "blocked"

    # Without the override, the same row would be ``reviewing``.
    row_without = {
        "task": {"status": "running"},
        "review": {"status": "pending", "evidence": {"changed_files_count": 1}},
        "work_surface": {},
    }
    assert project_coding_run_review_queue_state(row_without) == "reviewing"


def test_queue_state_review_outcome_still_wins_over_stall():
    """``reviewed`` remains terminal even if a stale stall marker survives."""
    row = {
        "task": {"status": "running"},
        "review": {"status": "reviewed", "reviewed": True, "evidence": {}},
        "work_surface": {"run_phase_override": "stalled"},
    }
    assert project_coding_run_review_queue_state(row) == "reviewed"


def test_default_stall_timeout_matches_cohesion_plan():
    """Cohesion plan default is 1200s (20 min). Drift is a regression."""
    assert DEFAULT_STALL_TIMEOUT_SECONDS == 1200


def test_project_stall_timeout_reads_blueprint_snapshot_override():
    project = SimpleNamespace(metadata_={"blueprint_snapshot": {"stall_timeout_seconds": 1800}})
    assert _project_stall_timeout_seconds(project) == 1800

    # Default when no snapshot override.
    bare = SimpleNamespace(metadata_={"blueprint_snapshot": {}})
    assert _project_stall_timeout_seconds(bare) == DEFAULT_STALL_TIMEOUT_SECONDS

    # Floor enforcement - too-small overrides clamp up to MIN_STALL_TIMEOUT.
    tiny = SimpleNamespace(metadata_={"blueprint_snapshot": {"stall_timeout_seconds": 5}})
    assert _project_stall_timeout_seconds(tiny) == 60

    # Junk values fall back to the default rather than 500-ing the sweep.
    junk = SimpleNamespace(metadata_={"blueprint_snapshot": {"stall_timeout_seconds": "soon"}})
    assert _project_stall_timeout_seconds(junk) == DEFAULT_STALL_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_sweep_marks_inactive_run_as_stalled_and_clears_when_active(db_session, monkeypatch):
    """Full sweep loop: idle run gets stall_state; resuming activity clears it."""
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="P",
        slug="p",
        root_path="common/projects/p",
        metadata_={"blueprint_snapshot": {"stall_timeout_seconds": 600}},
    )
    db_session.add(project)
    await db_session.flush()

    now = datetime(2026, 5, 2, 12, 0, 0, tzinfo=timezone.utc)
    long_ago = now - timedelta(seconds=1800)

    task = Task(
        id=uuid.uuid4(),
        bot_id="alpha",
        channel_id=channel_id,
        kind="agent",
        status="running",
        prompt="x",
        run_at=long_ago,
        created_at=long_ago,
        execution_config={
            "run_preset_id": PROJECT_CODING_RUN_PRESET_ID,
            "project_id": str(project_id),
            "project_coding_run": {"project_id": str(project_id)},
        },
    )
    db_session.add(task)
    await db_session.commit()

    # First pass: latest "activity" is the task.run_at (no agent_activity rows).
    # 1800s idle >= 600s timeout -> stalled.
    changed = await sweep_stalled_project_runs(db_session, now=now)
    assert task.id in changed

    await db_session.refresh(task)
    stall = task.execution_config.get("stall_state")
    assert stall is not None
    assert stall["timeout_seconds"] == 600
    assert stall["idle_seconds"] >= 1800
    assert "No agent activity" in stall["reason"]

    # Second pass with the same `now` is idempotent.
    changed_again = await sweep_stalled_project_runs(db_session, now=now)
    assert changed_again == []

    # Simulate resumed activity by sliding `run_at` forward, then sweep again -
    # the stall marker should be cleared.
    task.run_at = now - timedelta(seconds=10)
    await db_session.commit()
    changed_third = await sweep_stalled_project_runs(db_session, now=now)
    assert task.id in changed_third
    await db_session.refresh(task)
    assert task.execution_config.get("stall_state") is None


@pytest.mark.asyncio
async def test_sweep_emits_single_audit_receipt_per_stall_transition(db_session):
    """One ProjectRunReceipt per stall transition; subsequent passes are idempotent."""
    from sqlalchemy import select

    from app.db.models import ProjectRunReceipt

    project_id = uuid.uuid4()
    project = Project(
        id=project_id,
        workspace_id=uuid.uuid4(),
        name="P-audit",
        slug="p-audit",
        root_path="common/projects/p-audit",
        metadata_={"blueprint_snapshot": {"stall_timeout_seconds": 600}},
    )
    db_session.add(project)
    await db_session.flush()

    now = datetime(2026, 5, 2, 12, 0, 0, tzinfo=timezone.utc)
    long_ago = now - timedelta(seconds=1800)

    task = Task(
        id=uuid.uuid4(),
        bot_id="alpha",
        channel_id=uuid.uuid4(),
        kind="agent",
        status="running",
        prompt="x",
        run_at=long_ago,
        created_at=long_ago,
        execution_config={
            "run_preset_id": PROJECT_CODING_RUN_PRESET_ID,
            "project_id": str(project_id),
            "project_coding_run": {"project_id": str(project_id)},
        },
    )
    db_session.add(task)
    await db_session.commit()

    await sweep_stalled_project_runs(db_session, now=now)
    receipts = (await db_session.execute(
        select(ProjectRunReceipt)
        .where(ProjectRunReceipt.project_id == project_id, ProjectRunReceipt.task_id == task.id)
    )).scalars().all()
    assert len(receipts) == 1
    audit = receipts[0]
    assert audit.status == "blocked"
    assert (audit.metadata_ or {}).get("event") == "stall_detected"
    assert "No agent activity" in (audit.summary or "")
    assert audit.idempotency_key == f"stall:{task.id}:{now.isoformat()}"

    # Second pass at the same `now` must not duplicate the audit row.
    await sweep_stalled_project_runs(db_session, now=now)
    receipts_after = (await db_session.execute(
        select(ProjectRunReceipt)
        .where(ProjectRunReceipt.project_id == project_id, ProjectRunReceipt.task_id == task.id)
    )).scalars().all()
    assert len(receipts_after) == 1


@pytest.mark.asyncio
async def test_sweep_skips_completed_runs(db_session):
    """A finished run never gets stall_state, even if it sat idle."""
    project_id = uuid.uuid4()
    project = Project(
        id=project_id,
        workspace_id=uuid.uuid4(),
        name="P2",
        slug="p2",
        root_path="common/projects/p2",
        metadata_={},
    )
    db_session.add(project)
    await db_session.flush()

    long_ago = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
    task = Task(
        id=uuid.uuid4(),
        bot_id="alpha",
        channel_id=uuid.uuid4(),
        kind="agent",
        status="complete",
        prompt="done",
        run_at=long_ago,
        created_at=long_ago,
        completed_at=long_ago,
        execution_config={
            "run_preset_id": PROJECT_CODING_RUN_PRESET_ID,
            "project_id": str(project_id),
            "project_coding_run": {"project_id": str(project_id)},
        },
    )
    db_session.add(task)
    await db_session.commit()

    changed = await sweep_stalled_project_runs(
        db_session,
        now=datetime(2026, 5, 2, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert changed == []
    await db_session.refresh(task)
    assert task.execution_config.get("stall_state") is None


@pytest.mark.asyncio
async def test_sweep_ignores_non_project_coding_run_tasks(db_session):
    """Tasks from other run presets must not be touched by this sweep."""
    project_id = uuid.uuid4()
    project = Project(
        id=project_id,
        workspace_id=uuid.uuid4(),
        name="P3",
        slug="p3",
        root_path="common/projects/p3",
        metadata_={},
    )
    db_session.add(project)
    await db_session.flush()

    long_ago = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
    other = Task(
        id=uuid.uuid4(),
        bot_id="alpha",
        channel_id=uuid.uuid4(),
        kind="agent",
        status="running",
        prompt="other",
        run_at=long_ago,
        created_at=long_ago,
        execution_config={"run_preset_id": "some_other_preset"},
    )
    db_session.add(other)
    await db_session.commit()

    changed = await sweep_stalled_project_runs(
        db_session,
        now=datetime(2026, 5, 2, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert changed == []
    await db_session.refresh(other)
    assert other.execution_config.get("stall_state") is None
