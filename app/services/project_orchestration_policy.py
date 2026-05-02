"""Phase 4BC - canonical orchestration policy view for a Project.

Single read-model that merges Blueprint policy fields, the live in-flight
concurrency picture, the WORKFLOW.md `## policy` override, intake convention,
and canonical-repo info into one shape so neither runtime skills nor the UI
re-derive policy from scattered sources.

Each numeric / config field reports a `source` so callers can see whether a
value came from the Blueprint snapshot, a default, or is unset.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project
from app.services.project_coding_run_lib import count_active_project_coding_implementations
from app.services.project_run_stall_sweep import (
    DEFAULT_STALL_TIMEOUT_SECONDS,
    MIN_STALL_TIMEOUT_SECONDS,
)
from app.services.project_runtime import project_snapshot
from app.services.project_workflow_file import project_workflow_file
from app.services.projects import (
    project_canonical_repo_host_path,
    project_canonical_repo_relative_path,
    project_intake_config,
)


def _positive_int(value: Any) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return None
    return coerced if coerced > 0 else None


async def get_project_orchestration_policy(
    db: AsyncSession, project: Project
) -> dict[str, Any]:
    """Return the merged orchestration-policy view for a Project."""
    snapshot = project_snapshot(project) or {}

    cap = _positive_int(snapshot.get("max_concurrent_runs"))
    in_flight = await count_active_project_coding_implementations(db, project)
    concurrency = {
        "max_concurrent_runs": cap,
        "source": "blueprint" if cap is not None else "unset",
        "in_flight": in_flight,
        "headroom": (max(0, cap - in_flight) if cap is not None else None),
        "saturated": (cap is not None and in_flight >= cap),
    }

    raw_stall = snapshot.get("stall_timeout_seconds")
    stall_value = _positive_int(raw_stall)
    if stall_value is None:
        stall_effective = DEFAULT_STALL_TIMEOUT_SECONDS
        stall_source = "default"
    else:
        stall_effective = max(MIN_STALL_TIMEOUT_SECONDS, stall_value)
        stall_source = "blueprint"

    raw_turn = snapshot.get("turn_timeout_seconds")
    turn_value = _positive_int(raw_turn)
    timeouts = {
        "stall_timeout_seconds": stall_effective,
        "stall_source": stall_source,
        "stall_default": DEFAULT_STALL_TIMEOUT_SECONDS,
        "stall_min": MIN_STALL_TIMEOUT_SECONDS,
        "turn_timeout_seconds": turn_value,
        "turn_source": "blueprint" if turn_value is not None else "unset",
        "turn_enforced": False,  # 4BC documents the field; no enforcer wired yet.
    }

    workflow = project_workflow_file(project, snapshot)
    repo_workflow_policy = workflow.section("policy")

    return {
        "project": {
            "id": str(project.id),
            "name": project.name,
            "slug": project.slug,
        },
        "blueprint_applied": bool(snapshot),
        "concurrency": concurrency,
        "timeouts": timeouts,
        "intake": project_intake_config(project),
        "canonical_repo": {
            "relative_path": project_canonical_repo_relative_path(snapshot),
            "host_path": project_canonical_repo_host_path(project, snapshot),
        },
        "repo_workflow": {
            "relative_path": workflow.relative_path,
            "present": workflow.present,
            "policy_section": repo_workflow_policy,
        },
    }
