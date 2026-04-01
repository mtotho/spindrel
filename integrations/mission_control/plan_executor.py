"""Plan execution engine — automatic step sequencing with approval gates.

Core function: advance_plan(plan_db_id) — finds the next pending step and either:
  - Creates a core Task to execute it (auto step)
  - Pauses the plan at an approval gate (requires_approval step)
  - Marks the plan complete (no more pending steps)

Called from:
  - on_step_task_completed() — when a linked task finishes (via after_task_complete hook)
  - approve_plan() in router_plans.py — after user approves the plan
  - approve_step() in router_plans.py — when user approves a gated step
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

logger = logging.getLogger(__name__)


async def advance_plan(plan_db_id: str) -> None:
    """Find and execute the next pending step in a plan.

    Args:
        plan_db_id: The MC SQLite primary key (UUID string) of the plan.
    """
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McPlan, McPlanStep
    from integrations.mission_control.services import _render_plans_md, append_timeline

    async with await mc_session() as session:
        db_plan = await session.get(McPlan, plan_db_id)
        if not db_plan:
            logger.warning("advance_plan: plan %s not found", plan_db_id)
            return

        if db_plan.status not in ("approved", "executing"):
            logger.info("advance_plan: plan %s is [%s], skipping", plan_db_id, db_plan.status)
            return

        await session.refresh(db_plan, ["steps"])

        # Find next pending step (lowest position)
        next_step = None
        for s in db_plan.steps:
            if s.status == "pending":
                next_step = s
                break

        if next_step is None:
            # All steps are terminal — mark plan complete
            all_terminal = all(
                s.status in ("done", "skipped", "failed") for s in db_plan.steps
            )
            if all_terminal:
                db_plan.status = "complete"
                await session.commit()
                await _render_plans_md(db_plan.channel_id)
                try:
                    await append_timeline(
                        db_plan.channel_id,
                        f"Plan completed: **{db_plan.title}** ({db_plan.plan_id})",
                    )
                except Exception:
                    pass
            return

        channel_id = db_plan.channel_id
        plan_id = db_plan.plan_id
        plan_title = db_plan.title
        step_position = next_step.position
        step_content = next_step.content
        step_db_id = next_step.id
        requires_approval = next_step.requires_approval

        # Ensure plan is in executing state
        if db_plan.status == "approved":
            db_plan.status = "executing"
            await session.commit()

    if requires_approval:
        # Pause at approval gate
        async with await mc_session() as session:
            db_plan = await session.get(McPlan, plan_db_id)
            if db_plan:
                db_plan.status = "awaiting_approval"
                await session.commit()

        await _render_plans_md(channel_id)
        try:
            await append_timeline(
                channel_id,
                f"Plan paused: step {step_position} requires approval — "
                f"**{step_content}** ({plan_id})",
            )
        except Exception:
            pass
        return

    # Auto step: create a core Task to execute it
    await _create_step_task(
        channel_id=channel_id,
        plan_id=plan_id,
        plan_title=plan_title,
        step_db_id=step_db_id,
        step_position=step_position,
        step_content=step_content,
    )

    # Mark step as in_progress
    async with await mc_session() as session:
        step = await session.get(McPlanStep, step_db_id)
        if step:
            step.status = "in_progress"
            step.started_at = datetime.now(timezone.utc)
            await session.commit()

    await _render_plans_md(channel_id)

    try:
        await append_timeline(
            channel_id,
            f"Plan step {step_position} started: **{step_content}** ({plan_id})",
        )
    except Exception:
        pass


async def _create_step_task(
    channel_id: str,
    plan_id: str,
    plan_title: str,
    step_db_id: str,
    step_position: int,
    step_content: str,
) -> None:
    """Create a core Task to execute a plan step."""
    import uuid as _uuid

    from app.db.engine import async_session
    from app.db.models import Channel
    from app.db.models import Task as TaskModel
    from app.services.channels import ensure_active_session
    from app.services.sessions import store_passive_message

    async with async_session() as db:
        channel = await db.get(Channel, _uuid.UUID(channel_id))
        if not channel:
            logger.warning("_create_step_task: channel %s not found", channel_id)
            return

        session_id = await ensure_active_session(db, channel)
        await db.commit()

        prompt = (
            f"Execute step {step_position} of plan '{plan_title}' ({plan_id}): "
            f"{step_content}"
        )
        await store_passive_message(db, session_id, prompt, {"source": "mission_control"})
        await db.commit()

        task = TaskModel(
            bot_id=channel.bot_id,
            client_id=channel.client_id,
            session_id=session_id,
            channel_id=channel.id,
            prompt=prompt,
            status="pending",
            task_type="api",
            dispatch_type=channel.integration or "none",
            dispatch_config=channel.dispatch_config or {},
            execution_config={
                "system_preamble": (
                    f"You are executing step {step_position} of plan '{plan_title}' ({plan_id}). "
                    f"Step: {step_content}\n\n"
                    "Focus on this single step. When done, call update_plan_step to mark it "
                    "as done (or failed if it cannot be completed). "
                    "Write results to workspace files. "
                    "Do NOT call schedule_task or try to advance to the next step — "
                    "the plan executor handles sequencing automatically."
                ),
            },
            callback_config={
                "trigger_rag_loop": True,
                "mc_plan_step_id": step_db_id,
            },
            created_at=datetime.now(timezone.utc),
        )
        db.add(task)
        await db.commit()

        # Link the task back to the step
        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McPlanStep
        async with await mc_session() as mc_db:
            step = await mc_db.get(McPlanStep, step_db_id)
            if step:
                step.task_id = str(task.id)
                await mc_db.commit()

        logger.info(
            "Created step task %s for plan %s step %d",
            task.id, plan_id, step_position,
        )


async def on_step_task_completed(step_id: str, status: str, task) -> None:
    """Called when a task linked to a plan step completes.

    Updates the step status and advances the plan to the next step.
    """
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McPlanStep

    async with await mc_session() as session:
        step = await session.get(McPlanStep, step_id)
        if not step:
            logger.warning("on_step_task_completed: step %s not found", step_id)
            return

        # Only update if step is still in_progress (bot may have already updated it)
        if step.status == "in_progress":
            step.status = "done" if status == "complete" else "failed"
            step.completed_at = datetime.now(timezone.utc)
            if task and hasattr(task, "result"):
                step.result_summary = (task.result or "")[:500]
            await session.commit()

        plan_id = step.plan_id

    # Advance to next step
    await advance_plan(plan_id)
