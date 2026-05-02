"""Project Factory state - one stage-aware aggregate for agents and UI.

Compositional read-only view over existing Project services. The single
source of truth for "what stage is this Project in and what should the
agent do next?" so neither a runtime skill nor the UI cockpit reconstructs
stage from scattered counts.

Stage precedence (highest first wins; first match wins):

  1. unconfigured     - no applied Blueprint OR runtime env not ready
  2. needs_review     - one or more runs ready_for_review AND no active review task
  3. runs_in_flight   - runs in changes_requested/follow_up_running/reviewing/blocked/missing_evidence,
                        OR active review task, OR pending/running implementation task
  4. planning         - PRD/brief artifact reference exists OR recent planning signal
  5. ready_no_work    - configured, zero intake, zero runs
  6. reviewed_idle    - all runs reviewed, no pending intake
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Project,
    ProjectRunReceipt,
    Task,
    WorkspaceAttentionItem,
)
from app.services.project_coding_run_lib import (
    apply_project_coding_run_review_queue,
    list_project_coding_runs,
)
from app.services.project_dependency_stacks import project_dependency_stack_spec
from app.services.project_run_receipts import (
    list_project_run_receipts,
    serialize_project_run_receipt,
)
from app.services.project_runtime import load_project_runtime_environment
from app.services.project_workflow_file import (
    STANDARD_SECTIONS as _WORKFLOW_STANDARD_SECTIONS,
    project_workflow_file,
)
from app.services.projects import (
    project_blueprint_snapshot,
    project_canonical_repo_host_path,
    project_canonical_repo_relative_path,
    project_directory_from_project,
    project_intake_config,
)


def _concurrency_payload(
    snapshot: dict[str, Any] | None, runs_classification: dict[str, Any]
) -> dict[str, Any]:
    """Phase 4BG.3 - cap / in_flight / headroom view of run concurrency.

    `cap` is the Blueprint policy from 4BB.3 (`max_concurrent_runs`) when set,
    else `null`. `in_flight` counts currently executing coding runs (pending +
    running implementation tasks). `headroom` is `null` when no cap is set,
    otherwise `max(0, cap - in_flight)` so the agent can answer "safe to
    launch another?" without consuming a launch slot. Symphony Orchestrator
    Runtime State analog (concurrency view only - claim/retry queues defer).
    """
    cap_raw = snapshot.get("max_concurrent_runs") if isinstance(snapshot, dict) else None
    cap = int(cap_raw) if isinstance(cap_raw, int) and cap_raw > 0 else None
    in_flight = int(runs_classification.get("active_implementation") or 0)
    headroom = max(0, cap - in_flight) if cap is not None else None
    return {"cap": cap, "in_flight": in_flight, "headroom": headroom}


def _repo_workflow_payload(project: Any, snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """Surface the parsed ``.spindrel/WORKFLOW.md`` for a Project.

    Always emits all ``STANDARD_SECTIONS`` keys (``None`` when absent) so
    skill consumers can read ``sections.intake`` etc. without guarding the
    dict shape. Extra sections the author defined ride along under their
    kebab-slug keys.
    """
    workflow = project_workflow_file(project, snapshot)
    sections: dict[str, str | None] = {key: None for key in _WORKFLOW_STANDARD_SECTIONS}
    for key, body in workflow.sections.items():
        sections[key] = body
    return {
        "relative_path": workflow.relative_path,
        "host_path": workflow.host_path,
        "present": workflow.present,
        "sections": sections,
    }


_QUEUE_STATES_RUNS_IN_FLIGHT = {
    "changes_requested",
    "follow_up_running",
    "reviewing",
    "blocked",
    "missing_evidence",
}
_QUEUE_STATES_TERMINAL_REVIEWED = {"reviewed"}


def _intake_visible_statuses() -> tuple[str, ...]:
    return ("open", "acknowledged", "responded")


async def _intake_counts_for_project(db: AsyncSession, project: Project) -> dict[str, int]:
    """Pending intake = visible WorkspaceAttentionItem rows on a channel bound to this project.

    Intake is captured per-channel; project-scoped count joins through Channel.project_id.
    Done in two queries to avoid an outer-join expression in the count aggregate.
    """
    from app.db.models import Channel

    channel_id_stmt = select(Channel.id).where(Channel.project_id == project.id)
    channel_ids = [row[0] for row in (await db.execute(channel_id_stmt)).all()]
    if not channel_ids:
        return {"pending": 0}

    pending_stmt = (
        select(WorkspaceAttentionItem.id)
        .where(
            WorkspaceAttentionItem.channel_id.in_(channel_ids),
            WorkspaceAttentionItem.status.in_(_intake_visible_statuses()),
            WorkspaceAttentionItem.source_type.in_(("user", "bot")),
        )
    )
    pending_ids = [row[0] for row in (await db.execute(pending_stmt)).all()]
    return {"pending": len(pending_ids)}


def _run_pack_counts_for_project() -> dict[str, int]:
    """Phase 4BD.6: Run Packs are file-resident artifacts now (markdown sections
    in repo-resident files). The factory-state aggregate keeps zeroed counts
    so consumers see a stable schema; the live count would require parsing
    every Track/audit/PRD file under the canonical repo on each call, which is
    not worth the IO. Stage classification no longer emits ``shaping_packs``.
    """
    return {"proposed": 0, "needs_info": 0, "launched": 0, "dismissed": 0}


def _planning_artifact_signals(project: Project) -> dict[str, Any]:
    """Detect PRD/brief presence as a heuristic for the `planning` stage.

    Heuristic, not definition. We check (a) explicit `prd_path` in Project metadata
    and (b) `.spindrel/prds/*.md` existence in the Project root. Either signal counts.
    """
    metadata = project.metadata_ if isinstance(project.metadata_, dict) else {}
    prd_path = metadata.get("prd_path") if isinstance(metadata.get("prd_path"), str) else None

    files: list[str] = []
    try:
        project_dir = project_directory_from_project(project)
        prds_root = Path(project_dir.host_path) / ".spindrel" / "prds"
        if prds_root.exists() and prds_root.is_dir():
            files = sorted(p.name for p in prds_root.glob("*.md"))[:10]
    except Exception:
        files = []

    return {
        "prd_path": prd_path,
        "prd_files": files,
        "present": bool(prd_path) or bool(files),
    }


def _classify_runs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply queue-state derivation to each run; return counts + flags used by stage rules."""
    from app.services.project_coding_run_lib import project_coding_run_phase

    counts: dict[str, int] = {}
    by_phase: dict[str, int] = {}
    ready_for_review = 0
    in_flight = 0
    active_implementation = 0
    has_active_review_task = False
    reviewed = 0
    total = 0

    for row in rows:
        apply_project_coding_run_review_queue(row)
        state = str(row.get("review_queue_state") or "").strip()
        counts[state] = counts.get(state, 0) + 1
        # Phase 4BG.3 - by_phase mirror of by_queue_state; agent uses this to
        # answer "is this Project bottlenecked on testing vs handoff?" without
        # iterating run rows itself.
        phase = project_coding_run_phase(row)
        by_phase[phase] = by_phase.get(phase, 0) + 1
        total += 1
        task = row.get("task") if isinstance(row.get("task"), dict) else {}
        task_status = str(task.get("status") or "").lower()
        is_review = bool(row.get("is_review_task")) or bool(task.get("is_review_session"))

        if state == "ready_for_review":
            ready_for_review += 1
        elif state in _QUEUE_STATES_RUNS_IN_FLIGHT:
            in_flight += 1
        elif state in _QUEUE_STATES_TERMINAL_REVIEWED:
            reviewed += 1

        if task_status in {"pending", "running"}:
            if is_review:
                has_active_review_task = True
            else:
                active_implementation += 1

    return {
        "by_queue_state": counts,
        "by_phase": by_phase,
        "ready_for_review": ready_for_review,
        "in_flight": in_flight,
        "active_implementation": active_implementation,
        "has_active_review_task": has_active_review_task,
        "reviewed": reviewed,
        "total": total,
    }


def _classify_stage(
    *,
    blueprint_applied: bool,
    runtime_ready: bool,
    runs: dict[str, Any],
    pack_counts: dict[str, int],
    intake_counts: dict[str, int],
    planning: dict[str, Any],
) -> str:
    """Apply the precedence table from the module docstring."""
    if not blueprint_applied or not runtime_ready:
        return "unconfigured"

    # needs_review wins over runs_in_flight when there is a ready run and no active reviewer.
    if runs["ready_for_review"] > 0 and not runs["has_active_review_task"]:
        return "needs_review"

    if (
        runs["in_flight"] > 0
        or runs["has_active_review_task"]
        or runs["active_implementation"] > 0
    ):
        return "runs_in_flight"

    if planning["present"]:
        return "planning"

    has_any_intake = intake_counts.get("pending", 0) > 0
    has_any_runs = runs["total"] > 0
    if not has_any_intake and not has_any_runs:
        return "ready_no_work"

    if runs["total"] > 0 and runs["reviewed"] == runs["total"] and not has_any_intake:
        return "reviewed_idle"

    # Fallback: if runs exist but none active/ready, treat as reviewed_idle.
    return "reviewed_idle"


def _suggested_next_action(stage: str, *, blueprint_applied: bool, runtime_ready: bool) -> dict[str, Any]:
    """Map stage to the skill an agent should load next and a short headline."""
    if stage == "unconfigured":
        if not blueprint_applied:
            return {
                "stage": stage,
                "headline": "This Project has no applied Blueprint. Inspect the repo and apply one.",
                "skill_id_to_load": "project/setup/init",
                "why": "blueprint_applied=false",
            }
        return {
            "stage": stage,
            "headline": "Project runtime env is not ready. Resolve missing secrets or env declarations.",
            "skill_id_to_load": "project/setup/init",
            "why": "runtime_env.ready=false",
        }
    if stage == "needs_review":
        return {
            "stage": stage,
            "headline": "One or more runs are ready for review.",
            "skill_id_to_load": "project/runs/review",
            "why": "ready_for_review>0 and no active review task",
        }
    if stage == "runs_in_flight":
        return {
            "stage": stage,
            "headline": "Runs are in progress or need follow-up. Inspect the Runs cockpit.",
            "skill_id_to_load": "project/runs/implement",
            "why": "implementation/review/follow-up runs active",
        }
    if stage == "planning":
        return {
            "stage": stage,
            "headline": "A PRD or planning artifact exists. Continue shaping it into Run Packs when ready.",
            "skill_id_to_load": "project/plan/prd",
            "why": "PRD/brief signal present and no shaping/in-flight work",
        }
    if stage == "ready_no_work":
        return {
            "stage": stage,
            "headline": "Project is configured and idle. Ask the user what to build, or capture intake.",
            "skill_id_to_load": "project",
            "why": "configured with zero intake, zero packs, zero runs",
        }
    return {
        "stage": stage,
        "headline": "All runs reviewed. Capture new intake or start a new PRD when ready.",
        "skill_id_to_load": "project",
        "why": "all runs reviewed and no pending intake/packs",
    }


def _recent_receipt_summary(receipt: ProjectRunReceipt) -> dict[str, Any]:
    payload = serialize_project_run_receipt(receipt)
    return {
        "task_id": payload.get("task_id"),
        "summary": payload.get("summary"),
        "branch": payload.get("branch"),
        "handoff_url": payload.get("handoff_url"),
        "created_at": payload.get("created_at"),
    }


async def get_project_factory_state(
    db: AsyncSession,
    project: Project,
    *,
    recent_receipt_limit: int = 5,
    coding_runs_limit: int = 50,
) -> dict[str, Any]:
    """Return the factory-state aggregate for a Project.

    Composes existing services. Does not mutate state. Safe to call from
    agents (via tool wrapper) and from the UI cockpit using the same shape.
    """
    snapshot = project_blueprint_snapshot(project)
    blueprint_applied = bool(snapshot)

    runtime = await load_project_runtime_environment(db, project)
    runtime_ready = bool(runtime.ready) if hasattr(runtime, "ready") else True
    runtime_payload: dict[str, Any] = {
        "ready": runtime_ready,
        "missing_secrets": list(getattr(runtime, "missing_secrets", []) or []),
        "configured_keys": list(getattr(runtime, "configured_keys", []) or []),
    }

    dep_spec = project_dependency_stack_spec(project)
    dep_payload: dict[str, Any] = {
        "configured": bool(dep_spec.configured),
        "source_path": dep_spec.source_path,
    }

    intake_counts = await _intake_counts_for_project(db, project)
    pack_counts = _run_pack_counts_for_project()

    raw_runs = await list_project_coding_runs(db, project, limit=max(1, min(coding_runs_limit, 200)))
    runs_classification = _classify_runs(raw_runs)

    planning_signals = _planning_artifact_signals(project)

    recent_receipts_models = await list_project_run_receipts(
        db, project.id, limit=max(1, min(recent_receipt_limit, 25))
    )
    recent_receipts = [_recent_receipt_summary(r) for r in recent_receipts_models]

    stage = _classify_stage(
        blueprint_applied=blueprint_applied,
        runtime_ready=runtime_ready,
        runs=runs_classification,
        pack_counts=pack_counts,
        intake_counts=intake_counts,
        planning=planning_signals,
    )
    suggested = _suggested_next_action(
        stage,
        blueprint_applied=blueprint_applied,
        runtime_ready=runtime_ready,
    )

    return {
        "project": {
            "id": str(project.id),
            "name": project.name,
            "slug": project.slug,
        },
        "current_stage": stage,
        "blueprint": {
            "applied": blueprint_applied,
        },
        "canonical_repo": {
            "relative_path": project_canonical_repo_relative_path(snapshot),
            "host_path": project_canonical_repo_host_path(project, snapshot),
        },
        "intake_config": project_intake_config(project),
        "repo_workflow": _repo_workflow_payload(project, snapshot),
        "runtime_env": runtime_payload,
        "dependency_stack": dep_payload,
        "intake": intake_counts,
        "run_packs": pack_counts,
        "runs": {
            "by_queue_state": runs_classification["by_queue_state"],
            "by_phase": runs_classification["by_phase"],
            "total": runs_classification["total"],
            "ready_for_review": runs_classification["ready_for_review"],
            "in_flight": runs_classification["in_flight"],
            "active_implementation": runs_classification["active_implementation"],
            "reviewed": runs_classification["reviewed"],
            "active_review_task": runs_classification["has_active_review_task"],
            "concurrency": _concurrency_payload(snapshot, runs_classification),
        },
        "planning": planning_signals,
        "recent_receipts": recent_receipts,
        "suggested_next_action": suggested,
    }
