"""Mission Control plan tools — structured plan management via plans.md.

Thin wrappers around integrations.mission_control.services.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date

from integrations import _register as reg
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
        },
        "required": ["channel_id", "title", "steps"],
    },
}})
async def draft_plan(
    channel_id: str,
    title: str,
    steps: list[str],
    notes: str = "",
) -> str:
    """Create a draft plan in plans.md."""
    from app.services.plan_board import generate_plan_id

    _raw, plans = await _read_plans_md(channel_id)

    plan_id = generate_plan_id()
    plan_steps = [
        {"position": i + 1, "status": "pending", "content": s}
        for i, s in enumerate(steps)
    ]

    plan = {
        "title": title,
        "status": "draft",
        "meta": {
            "id": plan_id,
            "created": date.today().isoformat(),
        },
        "steps": plan_steps,
        "notes": notes,
    }
    plans.append(plan)
    await _write_plans_md(channel_id, plans)

    try:
        await append_timeline(channel_id, f"Plan drafted: **{title}** ({plan_id})")
    except Exception:
        logger.debug("Failed to log timeline event for draft_plan", exc_info=True)

    return (
        f"Created draft plan '{title}' (id: {plan_id}) with {len(steps)} steps. "
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
    """Update a step's status in a plan."""
    if status not in ("pending", "in_progress", "done", "skipped", "failed"):
        return f"Invalid step status: {status}"

    _raw, plans = await _read_plans_md(channel_id)

    plan = None
    for p in plans:
        if p["meta"].get("id") == plan_id:
            plan = p
            break

    if not plan:
        return f"Plan '{plan_id}' not found in plans.md"

    if plan["status"] not in ("executing", "approved"):
        return f"Plan '{plan_id}' is [{plan['status']}] — can only update steps on executing/approved plans"

    step = None
    for s in plan["steps"]:
        if s["position"] == step_number:
            step = s
            break

    if not step:
        return f"Step {step_number} not found in plan '{plan_id}'"

    old_status = step["status"]
    step["status"] = status

    if plan["status"] == "approved":
        plan["status"] = "executing"

    all_terminal = all(s["status"] in ("done", "skipped", "failed") for s in plan["steps"])
    if all_terminal:
        plan["status"] = "complete"

    await _write_plans_md(channel_id, plans)

    if status == "done":
        await append_timeline(
            channel_id,
            f"Plan step {step_number} completed: **{step['content']}** ({plan_id})",
        )
    elif status == "in_progress":
        await append_timeline(
            channel_id,
            f"Plan step {step_number} started: **{step['content']}** ({plan_id})",
        )
    elif status == "failed":
        await append_timeline(
            channel_id,
            f"Plan step {step_number} failed: **{step['content']}** ({plan_id})",
        )

    if all_terminal:
        await append_timeline(channel_id, f"Plan completed: **{plan['title']}** ({plan_id})")

    result = f"Step {step_number} updated: {old_status} → {status}"
    if all_terminal:
        result += f" — plan auto-completed (all steps done/skipped)"
    return result


@reg.register({"type": "function", "function": {
    "name": "update_plan_status",
    "description": (
        "Change a plan's overall status. Bots can transition: "
        "executing→complete, draft→abandoned."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "channel_id": {"type": "string", "description": "Channel UUID"},
            "plan_id": {"type": "string", "description": "Plan ID (e.g. plan-a1b2c3)"},
            "status": {
                "type": "string",
                "enum": ["complete", "abandoned"],
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
    """Change a plan's overall status."""
    if status not in ("complete", "abandoned"):
        return f"Invalid status: {status}. Bots can only set complete or abandoned."

    _raw, plans = await _read_plans_md(channel_id)

    plan = None
    for p in plans:
        if p["meta"].get("id") == plan_id:
            plan = p
            break

    if not plan:
        return f"Plan '{plan_id}' not found in plans.md"

    allowed = {
        "complete": ("executing",),
        "abandoned": ("draft", "approved", "executing"),
    }
    if plan["status"] not in allowed.get(status, ()):
        return (
            f"Cannot transition plan '{plan_id}' from [{plan['status']}] to [{status}]. "
            f"Allowed from: {allowed.get(status, ())}"
        )

    old_status = plan["status"]
    plan["status"] = status
    await _write_plans_md(channel_id, plans)

    await append_timeline(
        channel_id,
        f"Plan {status}: **{plan['title']}** ({plan_id}) — was [{old_status}]",
    )

    return f"Plan '{plan['title']}' transitioned: {old_status} → {status}"
