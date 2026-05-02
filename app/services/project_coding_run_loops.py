"""Bounded loop handling for Project coding runs.

Loops are a thin continuation policy on top of normal Project coding runs. The
implementation agent must publish an explicit loop decision in the receipt; this
module only starts the next existing continuation when that decision is
``continue`` and budget remains.
"""
from __future__ import annotations

import logging
import uuid
from datetime import timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.db.engine import async_session
from app.db.models import Project, ProjectRunReceipt, Task
from app.services.project_coding_run_lib import (
    PROJECT_CODING_RUN_PRESET_ID,
    ProjectCodingRunContinue,
    project_run_receipt_loop_metadata,
    normalize_project_run_loop_policy,
)

logger = logging.getLogger(__name__)


def _project_run_cfg(task: Task) -> dict[str, Any]:
    if not isinstance(task.execution_config, dict):
        return {}
    cfg = task.execution_config.get("project_coding_run")
    return cfg if isinstance(cfg, dict) else {}


def _root_task_id(task: Task, cfg: dict[str, Any]) -> uuid.UUID:
    raw = cfg.get("root_task_id") or task.id
    return uuid.UUID(str(raw))


def _continuation_index(cfg: dict[str, Any]) -> int:
    try:
        return max(0, int(cfg.get("continuation_index") or 0))
    except (TypeError, ValueError):
        return 0


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now(timezone.utc).isoformat()


def _set_loop_state(task: Task, **updates: Any) -> None:
    ecfg = task.execution_config if isinstance(task.execution_config, dict) else {}
    cfg = ecfg.get("project_coding_run")
    if not isinstance(cfg, dict):
        return
    state = cfg.get("loop_state") if isinstance(cfg.get("loop_state"), dict) else {}
    cfg["loop_state"] = {
        **state,
        **updates,
        "updated_at": _now_iso(),
    }
    task.execution_config = ecfg
    flag_modified(task, "execution_config")


async def _latest_receipt_for_task(db, project_id: uuid.UUID, task_id: uuid.UUID) -> ProjectRunReceipt | None:
    return (await db.execute(
        select(ProjectRunReceipt)
        .where(ProjectRunReceipt.project_id == project_id, ProjectRunReceipt.task_id == task_id)
        .order_by(ProjectRunReceipt.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()


def _loop_feedback(
    *,
    policy: dict[str, Any],
    receipt: ProjectRunReceipt,
    decision: dict[str, Any],
    next_iteration: int,
) -> str:
    parts = [
        f"Continue the bounded Project run loop. This is iteration {next_iteration} of {policy.get('max_iterations')}.",
        f"Stop condition: {policy.get('stop_condition')}",
        f"Prior receipt summary: {receipt.summary}",
    ]
    if decision.get("reason"):
        parts.append(f"Loop reason: {decision['reason']}")
    if decision.get("remaining_work"):
        parts.append(f"Remaining work: {decision['remaining_work']}")
    if policy.get("continuation_prompt"):
        parts.append(str(policy["continuation_prompt"]))
    parts.append("Reuse the same branch/PR, Project instance, dependency stack, and receipt trail.")
    return "\n\n".join(parts)


async def on_project_coding_run_task_complete(task_id: uuid.UUID | str, status: str) -> None:
    """Inspect the latest receipt and continue a loop-enabled coding run when requested."""
    async with async_session() as db:
        task = await db.get(Task, uuid.UUID(str(task_id)))
        if task is None:
            return
        if not isinstance(task.execution_config, dict) or task.execution_config.get("run_preset_id") != PROJECT_CODING_RUN_PRESET_ID:
            return
        cfg = _project_run_cfg(task)
        policy = normalize_project_run_loop_policy(cfg.get("loop_policy") if isinstance(cfg.get("loop_policy"), dict) else None)
        if not policy:
            return
        if cfg.get("latest_continuation_task_id"):
            return

        project_id = cfg.get("project_id")
        if not project_id:
            return
        project = await db.get(Project, uuid.UUID(str(project_id)))
        if project is None:
            return
        root = await db.get(Task, _root_task_id(task, cfg))
        root_task = root or task

        index = _continuation_index(cfg)
        receipt = await _latest_receipt_for_task(db, project.id, task.id)
        if status != "complete":
            _set_loop_state(task, state="stopped", stop_reason=f"task_{status}", latest_decision=None)
            if root_task.id != task.id:
                _set_loop_state(root_task, state="stopped", stop_reason=f"task_{status}", latest_decision=None)
            await db.commit()
            return
        if receipt is None:
            _set_loop_state(task, state="needs_review", stop_reason="missing_receipt", latest_decision=None)
            if root_task.id != task.id:
                _set_loop_state(root_task, state="needs_review", stop_reason="missing_receipt", latest_decision=None)
            await db.commit()
            return

        decision = project_run_receipt_loop_metadata(receipt)
        _set_loop_state(
            task,
            state="decided",
            latest_decision=decision.get("decision"),
            latest_reason=decision.get("reason"),
            remaining_work=decision.get("remaining_work"),
            latest_receipt_id=str(receipt.id),
            iteration=index + 1,
            max_iterations=policy["max_iterations"],
        )
        if not decision.get("decision"):
            _set_loop_state(root_task, state="needs_review", stop_reason="missing_loop_decision", latest_receipt_id=str(receipt.id))
            await db.commit()
            return
        if decision["decision"] != "continue":
            _set_loop_state(root_task, state=decision["decision"], stop_reason=decision["decision"], latest_receipt_id=str(receipt.id), latest_decision=decision["decision"])
            await db.commit()
            return
        if index + 1 >= int(policy["max_iterations"]):
            _set_loop_state(root_task, state="needs_review", stop_reason="loop_budget_exhausted", latest_receipt_id=str(receipt.id), latest_decision="continue")
            await db.commit()
            return

        feedback = _loop_feedback(
            policy=policy,
            receipt=receipt,
            decision=decision,
            next_iteration=index + 2,
        )
        await db.commit()

    # Use the public continuation path after the state commit so duplicate
    # completion hooks see latest_continuation_task_id and do not double-launch.
    async with async_session() as db:
        task = await db.get(Task, uuid.UUID(str(task_id)))
        if task is None:
            return
        cfg = _project_run_cfg(task)
        if cfg.get("latest_continuation_task_id"):
            return
        project_id = cfg.get("project_id")
        if not project_id:
            return
        project = await db.get(Project, uuid.UUID(str(project_id)))
        if project is None:
            return
        from app.services.project_coding_run_orchestration import continue_project_coding_run

        try:
            child = await continue_project_coding_run(db, project, task.id, ProjectCodingRunContinue(feedback=feedback))
        except Exception:
            logger.exception("Project coding-run loop continuation failed for task %s", task.id)
            return
        fresh_parent = await db.get(Task, task.id)
        fresh_root = await db.get(Task, _root_task_id(fresh_parent, _project_run_cfg(fresh_parent))) if fresh_parent is not None else None
        if fresh_parent is not None:
            _set_loop_state(fresh_parent, state="continued", latest_continuation_task_id=str(child.id))
        if fresh_root is not None:
            _set_loop_state(fresh_root, state="continued", latest_continuation_task_id=str(child.id), latest_decision="continue")
        await db.commit()


async def disable_project_coding_run_loop(db, project: Project, task_id: uuid.UUID) -> Task:
    """Disable further automatic continuations for a coding-run lineage."""
    from app.services.project_coding_run_lib import _load_project_coding_task

    task = await _load_project_coding_task(db, project, task_id)
    cfg = _project_run_cfg(task)
    root = await db.get(Task, _root_task_id(task, cfg))
    targets = [task]
    if root is not None and root.id != task.id:
        targets.append(root)
    for target in targets:
        ecfg = target.execution_config if isinstance(target.execution_config, dict) else {}
        run_cfg = ecfg.get("project_coding_run")
        if not isinstance(run_cfg, dict):
            continue
        policy = run_cfg.get("loop_policy") if isinstance(run_cfg.get("loop_policy"), dict) else {}
        run_cfg["loop_policy"] = {**policy, "enabled": False}
        state = run_cfg.get("loop_state") if isinstance(run_cfg.get("loop_state"), dict) else {}
        run_cfg["loop_state"] = {
            **state,
            "enabled": False,
            "state": "disabled",
            "stop_reason": "disabled_by_operator",
            "updated_at": _now_iso(),
        }
        target.execution_config = ecfg
        flag_modified(target, "execution_config")
    await db.commit()
    await db.refresh(task)
    return task
