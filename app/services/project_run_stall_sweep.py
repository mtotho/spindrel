"""Background sweep that flags Project coding runs with no recent activity.

Phase 4BB.2 - Symphony-equivalent observability. The sweep is the single
source of truth for *whether a run is stalled right now*. It writes
``task.execution_config['stall_state']`` for the lifecycle layer (read by
``_work_surface_summary`` and ``project_coding_run_review_queue_state``).

Stalled runs surface as:
  - ``lifecycle.run_phase = 'stalled'`` (recoverable / no recent activity)
  - ``review_queue_state = 'blocked'`` (operator queue)

The two axes stay distinct: stalled = sweep-detected idleness; blocked =
operator-facing "needs your attention". The sweep is idempotent - on the next
pass it either re-confirms (no change) or clears the marker when activity has
resumed.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.db.engine import async_session
from app.db.models import Project, Task
from app.services.agent_activity import list_agent_activity
from app.services.project_coding_run_lib import PROJECT_CODING_RUN_PRESET_ID
from app.services.project_run_receipts import create_project_run_receipt

logger = logging.getLogger(__name__)

DEFAULT_STALL_TIMEOUT_SECONDS = 1200  # 20 minutes (matches cohesion plan default)
DEFAULT_SWEEP_INTERVAL_SECONDS = 60
MIN_STALL_TIMEOUT_SECONDS = 60
MIN_SWEEP_INTERVAL_SECONDS = 10


def _project_stall_timeout_seconds(project: Project | None) -> int:
    """Resolve the effective stall_timeout for a Project.

    Prefers the applied Blueprint snapshot when 4BB.3 has populated it.
    Falls back to ``DEFAULT_STALL_TIMEOUT_SECONDS``.
    """
    if project is None:
        return DEFAULT_STALL_TIMEOUT_SECONDS
    metadata = project.metadata_ if isinstance(project.metadata_, dict) else {}
    snapshot = metadata.get("blueprint_snapshot") if isinstance(metadata.get("blueprint_snapshot"), dict) else {}
    raw = snapshot.get("stall_timeout_seconds")
    try:
        seconds = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_STALL_TIMEOUT_SECONDS
    return max(MIN_STALL_TIMEOUT_SECONDS, seconds)


async def _latest_activity_at(db, task: Task) -> datetime | None:
    items = await list_agent_activity(
        db,
        bot_id=task.bot_id,
        channel_id=task.channel_id,
        session_id=task.session_id,
        task_id=task.id,
        correlation_id=task.correlation_id,
        limit=1,
    )
    if items:
        raw = items[0].get("created_at")
        if isinstance(raw, str):
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return None
    # Fall back to task lifecycle timestamps - a freshly-launched task with no
    # activity yet should be measured against its run_at/created_at, not be
    # treated as instantly stalled.
    return task.run_at or task.created_at


def _ensure_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _set_stall_state(task: Task, payload: dict[str, Any] | None) -> bool:
    """Apply or clear the stall_state on the task. Returns True if changed."""
    cfg = task.execution_config if isinstance(task.execution_config, dict) else None
    if cfg is None:
        cfg = {}
        task.execution_config = cfg
    existing = cfg.get("stall_state") if isinstance(cfg.get("stall_state"), dict) else None
    if payload is None:
        if existing is None:
            return False
        cfg.pop("stall_state", None)
    else:
        if existing == payload:
            return False
        cfg["stall_state"] = payload
    flag_modified(task, "execution_config")
    return True


async def sweep_stalled_project_runs(db, *, now: datetime | None = None) -> list[uuid.UUID]:
    """Single sweep pass. Returns the task ids whose stall_state was changed.

    Iterates every in-flight Project coding-run task, compares the latest
    agent_activity timestamp against the project's effective stall timeout,
    and updates ``task.execution_config['stall_state']`` accordingly. Emits
    one ``ProjectRunReceipt`` audit row per *transition into* stalled
    (idempotent by ``stall:<task_id>:<stalled_at>``); resume transitions
    rely on subsequent normal receipts to tell the story.
    """
    moment = _ensure_aware(now) or datetime.now(timezone.utc)
    candidates = list((await db.execute(
        select(Task).where(Task.status.in_(("pending", "running")))
    )).scalars().all())
    project_cache: dict[uuid.UUID, Project | None] = {}
    changed: list[uuid.UUID] = []
    new_stalls: list[tuple[Task, uuid.UUID, dict[str, Any]]] = []
    for task in candidates:
        if not isinstance(task.execution_config, dict):
            continue
        if task.execution_config.get("run_preset_id") != PROJECT_CODING_RUN_PRESET_ID:
            continue
        project_id = task.execution_config.get("project_id")
        try:
            project_uuid = uuid.UUID(str(project_id)) if project_id else None
        except (TypeError, ValueError):
            project_uuid = None
        project = None
        if project_uuid is not None:
            if project_uuid not in project_cache:
                project_cache[project_uuid] = await db.get(Project, project_uuid)
            project = project_cache[project_uuid]
        timeout = _project_stall_timeout_seconds(project)
        latest = _ensure_aware(await _latest_activity_at(db, task))
        if latest is None:
            continue
        idle_seconds = (moment - latest).total_seconds()
        had_stall_marker = isinstance(task.execution_config.get("stall_state"), dict) and bool(
            task.execution_config["stall_state"].get("stalled_at")
        )
        if idle_seconds >= timeout:
            payload = {
                "stalled_at": moment.isoformat(),
                "last_activity_at": latest.isoformat(),
                "timeout_seconds": timeout,
                "idle_seconds": int(idle_seconds),
                "reason": f"No agent activity for {int(idle_seconds)}s (>= {timeout}s threshold).",
            }
            if _set_stall_state(task, payload):
                changed.append(task.id)
                if not had_stall_marker and project_uuid is not None:
                    new_stalls.append((task, project_uuid, payload))
        else:
            # Activity has resumed - clear any prior stall marker.
            if _set_stall_state(task, None):
                changed.append(task.id)
    if changed:
        await db.commit()
    for task, project_uuid, payload in new_stalls:
        await _record_stall_audit_receipt(db, task=task, project_id=project_uuid, payload=payload)
    return changed


async def _record_stall_audit_receipt(
    db,
    *,
    task: Task,
    project_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """Write one ProjectRunReceipt per stall transition for audit history.

    Uses ``status='blocked'`` (closest existing receipt status) plus
    ``metadata.event='stall_detected'`` so consumers can distinguish a sweep-
    detected stall from an operator-reported block.
    """
    try:
        await create_project_run_receipt(
            db,
            project_id=project_id,
            task_id=task.id,
            session_id=task.session_id,
            bot_id=task.bot_id,
            status="blocked",
            summary=payload.get("reason") or "Run stalled",
            metadata={"event": "stall_detected", "stall_state": payload},
            idempotency_key=f"stall:{task.id}:{payload.get('stalled_at')}",
        )
    except Exception:
        logger.exception("Failed to record stall audit receipt for task %s", task.id)


async def project_run_stall_sweep_loop(interval_seconds: int | None = None) -> None:
    """Long-running sweep loop. Registered from ``startup_runtime``."""
    interval = max(MIN_SWEEP_INTERVAL_SECONDS, int(interval_seconds or DEFAULT_SWEEP_INTERVAL_SECONDS))
    logger.info("Project run stall sweep loop starting (interval=%ss)", interval)
    while True:
        try:
            async with async_session() as db:
                changed = await sweep_stalled_project_runs(db)
            if changed:
                logger.info("Project run stall sweep updated %d task(s)", len(changed))
        except Exception:
            logger.exception("Project run stall sweep failed")
        await asyncio.sleep(interval)


def _sweep_disabled_via_env() -> bool:
    return os.environ.get("SPINDREL_DISABLE_RUN_STALL_SWEEP") == "1"
