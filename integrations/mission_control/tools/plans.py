"""Mission Control plan tools — structured plan management via MC SQLite DB.

Thin wrappers around DB operations. Markdown files are rendered as read-only
context injection (write-through from DB).
"""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select

from integrations import sdk as reg
from integrations.mission_control.services import (
    _read_plans_md,
    _write_plans_md,
    append_timeline,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@reg.register({"type": "function", "function": {
    "name": "draft_plan",
    "description": (
        "Create a draft plan in the channel's plans.md. The plan will appear "
        "in Mission Control for user review and approval before execution begins."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "channel_id": {"type": "string", "description": "Channel UUID"},
            "title": {"type": "string", "description": "Plan title (concise, action-oriented)"},
            "steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Ordered list of step descriptions",
            },
            "notes": {
                "type": "string",
                "description": "Optional context, estimates, or rationale",
                "default": "",
            },
            "approval_steps": {
                "type": "array",
                "items": {"type": "integer"},
                "description": (
                    "Optional list of step positions (1-based) that require human approval "
                    "before execution. The plan executor will pause at these steps."
                ),
            },
        },
        "required": ["channel_id", "title", "steps"],
    },
}})
async def draft_plan(
    channel_id: str,
    title: str,
    steps: list[str],
    notes: str = "",
    approval_steps: list[int] | None = None,
) -> str:
    """Create a draft plan in the MC database."""
    from app.services.plan_board import generate_plan_id
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McPlan, McPlanStep
    from integrations.mission_control.services import _ensure_plans_migrated, _render_plans_md

    # Guard: LLMs sometimes pass a bare string instead of a list
    if isinstance(steps, str):
        steps = [steps]

    await _ensure_plans_migrated(channel_id)

    plan_id = generate_plan_id()
    approval_set = set(approval_steps or [])

    async with await mc_session() as session:
        db_plan = McPlan(
            channel_id=channel_id,
            plan_id=plan_id,
            title=title,
            status="draft",
            notes=notes,
            created_date=date.today().isoformat(),
        )
        session.add(db_plan)
        await session.flush()

        for i, step_content in enumerate(steps, 1):
            session.add(McPlanStep(
                plan_id=db_plan.id,
                position=i,
                content=step_content,
                status="pending",
                requires_approval=i in approval_set,
            ))

        await session.commit()

    await _render_plans_md(channel_id)

    try:
        await append_timeline(channel_id, f"Plan drafted: **{title}** ({plan_id})")
    except Exception:
        logger.debug("Failed to log timeline event for draft_plan", exc_info=True)

    approval_note = ""
    if approval_set:
        approval_note = f" Steps {sorted(approval_set)} require human approval."

    return (
        f"Created draft plan '{title}' (id: {plan_id}) with {len(steps)} steps.{approval_note} "
        f"The plan is visible in Mission Control for review. "
        f"The user must approve it before execution can begin."
    )


@reg.register({"type": "function", "function": {
    "name": "update_plan_step",
    "description": (
        "Update a step's status in a plan. Use after completing or starting a step. "
        "If all steps are done/skipped, the plan auto-transitions to complete."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "channel_id": {"type": "string", "description": "Channel UUID"},
            "plan_id": {"type": "string", "description": "Plan ID (e.g. plan-a1b2c3)"},
            "step_number": {
                "type": "integer",
                "description": "Step position number (1-based)",
            },
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "done", "skipped", "failed"],
                "description": "New step status",
            },
        },
        "required": ["channel_id", "plan_id", "step_number", "status"],
    },
}})
async def update_plan_step(
    channel_id: str,
    plan_id: str,
    step_number: int,
    status: str,
) -> str:
    """Update a step's status in a plan via DB."""
    if status not in ("pending", "in_progress", "done", "skipped", "failed"):
        return f"Invalid step status: {status}"

    from datetime import datetime, timezone

    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McPlan, McPlanStep
    from integrations.mission_control.services import _ensure_plans_migrated, _render_plans_md

    await _ensure_plans_migrated(channel_id)

    async with await mc_session() as session:
        result = await session.execute(
            select(McPlan)
            .where(McPlan.plan_id == plan_id)
            .where(McPlan.channel_id == channel_id)
        )
        db_plan = result.scalar_one_or_none()
        if not db_plan:
            return f"Plan '{plan_id}' not found"

        if db_plan.status not in ("executing", "approved", "awaiting_approval"):
            return f"Plan '{plan_id}' is [{db_plan.status}] — can only update steps on executing/approved/awaiting_approval plans"

        await session.refresh(db_plan, ["steps"])
        step = next((s for s in db_plan.steps if s.position == step_number), None)
        if not step:
            return f"Step {step_number} not found in plan '{plan_id}'"

        old_status = step.status
        step.status = status

        now = datetime.now(timezone.utc)
        if status == "in_progress":
            step.started_at = now
        elif status in ("done", "skipped", "failed"):
            step.completed_at = now

        if db_plan.status in ("approved", "awaiting_approval"):
            db_plan.status = "executing"

        all_terminal = all(s.status in ("done", "skipped", "failed") for s in db_plan.steps)
        if all_terminal:
            db_plan.status = "complete"

        plan_title = db_plan.title
        step_content = step.content
        await session.commit()

    await _render_plans_md(channel_id)

    if status == "done":
        await append_timeline(
            channel_id,
            f"Plan step {step_number} completed: **{step_content}** ({plan_id})",
        )
    elif status == "in_progress":
        await append_timeline(
            channel_id,
            f"Plan step {step_number} started: **{step_content}** ({plan_id})",
        )
    elif status == "failed":
        await append_timeline(
            channel_id,
            f"Plan step {step_number} failed: **{step_content}** ({plan_id})",
        )

    if all_terminal:
        await append_timeline(channel_id, f"Plan completed: **{plan_title}** ({plan_id})")

    result_msg = f"Step {step_number} updated: {old_status} → {status}"
    if all_terminal:
        result_msg += " — plan auto-completed (all steps done/skipped)"
    return result_msg


@reg.register({"type": "function", "function": {
    "name": "update_plan_status",
    "description": (
        "Change a plan's overall status. Transitions: "
        "draft→approved (starts automatic execution), "
        "executing→complete, draft/approved/executing→abandoned. "
        "Use 'approved' after the user confirms a draft plan in chat."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "channel_id": {"type": "string", "description": "Channel UUID"},
            "plan_id": {"type": "string", "description": "Plan ID (e.g. plan-a1b2c3)"},
            "status": {
                "type": "string",
                "enum": ["approved", "complete", "abandoned"],
                "description": "New plan status",
            },
        },
        "required": ["channel_id", "plan_id", "status"],
    },
}})
async def update_plan_status(
    channel_id: str,
    plan_id: str,
    status: str,
) -> str:
    """Change a plan's overall status via DB."""
    if status not in ("approved", "complete", "abandoned"):
        return f"Invalid status: {status}. Bots can set approved, complete, or abandoned."

    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McPlan
    from integrations.mission_control.services import _ensure_plans_migrated, _render_plans_md

    await _ensure_plans_migrated(channel_id)

    allowed = {
        "approved": ("draft",),
        "complete": ("executing",),
        "abandoned": ("draft", "approved", "executing", "awaiting_approval"),
    }

    async with await mc_session() as session:
        result = await session.execute(
            select(McPlan)
            .where(McPlan.plan_id == plan_id)
            .where(McPlan.channel_id == channel_id)
        )
        db_plan = result.scalar_one_or_none()
        if not db_plan:
            return f"Plan '{plan_id}' not found"

        if db_plan.status not in allowed.get(status, ()):
            return (
                f"Cannot transition plan '{plan_id}' from [{db_plan.status}] to [{status}]. "
                f"Allowed from: {allowed.get(status, ())}"
            )

        old_status = db_plan.status
        db_plan.status = status

        if status == "approved":
            from datetime import date as _date
            db_plan.approved_date = _date.today().isoformat()

        plan_title = db_plan.title
        plan_db_id = db_plan.id
        await session.commit()

    await _render_plans_md(channel_id)

    await append_timeline(
        channel_id,
        f"Plan {status}: **{plan_title}** ({plan_id}) — was [{old_status}]",
    )

    # Kick off the plan executor for approved plans
    if status == "approved":
        try:
            from integrations.mission_control.plan_executor import advance_plan
            await advance_plan(plan_db_id)
        except Exception:
            logger.warning("Failed to start plan execution for %s", plan_id, exc_info=True)
            return (
                f"Plan '{plan_title}' approved but execution engine failed to start. "
                f"You can retry via the Mission Control dashboard."
            )
        return (
            f"Plan '{plan_title}' approved and execution started. "
            f"Steps will execute automatically — do not call schedule_task or try to advance manually."
        )

    return f"Plan '{plan_title}' transitioned: {old_status} → {status}"
