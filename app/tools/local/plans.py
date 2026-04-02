"""Agent tools for creating and managing channel-scoped plans."""
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, func

from app.agent.context import current_bot_id, current_channel_id, current_session_id
from app.db.engine import async_session
from app.db.models import Plan, PlanItem
from app.tools.registry import register


@register({
    "type": "function",
    "function": {
        "name": "create_plan",
        "description": (
            "Create a new plan with an ordered checklist of items for the current conversation. "
            "Use this to track multi-step work so progress persists across turns. "
            "The plan is automatically injected into every subsequent turn until completed or abandoned."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short title for the plan.",
                },
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ordered list of steps/tasks in the plan.",
                },
                "description": {
                    "type": "string",
                    "description": "Optional longer description or goal for the plan.",
                },
            },
            "required": ["title", "items"],
        },
    },
})
async def create_plan(title: str, items: list[str], description: str | None = None) -> str:
    bot_id = current_bot_id.get() or "unknown"
    session_id = current_session_id.get()
    channel_id = current_channel_id.get()

    now = datetime.now(timezone.utc)
    plan = Plan(
        bot_id=bot_id,
        session_id=session_id,
        channel_id=channel_id,
        title=title,
        description=description,
        status="active",
        created_at=now,
        updated_at=now,
    )
    async with async_session() as db:
        db.add(plan)
        await db.flush()
        for pos, content in enumerate(items):
            db.add(PlanItem(
                plan_id=plan.id,
                position=pos,
                content=content,
                status="pending",
                updated_at=now,
            ))
        await db.commit()

    return json.dumps({"plan_id": str(plan.id), "item_count": len(items)})


@register({
    "type": "function",
    "function": {
        "name": "get_plan",
        "description": "Retrieve a plan and all its items by plan ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "plan_id": {
                    "type": "string",
                    "description": "The plan UUID.",
                },
            },
            "required": ["plan_id"],
        },
    },
})
async def get_plan(plan_id: str) -> str:
    try:
        pid = uuid.UUID(plan_id)
    except ValueError:
        return json.dumps({"error": f"Invalid plan_id: {plan_id}"})

    async with async_session() as db:
        plan = await db.get(Plan, pid)
        if not plan:
            return json.dumps({"error": f"Plan {plan_id} not found."})
        items = (await db.execute(
            select(PlanItem).where(PlanItem.plan_id == pid).order_by(PlanItem.position)
        )).scalars().all()

    return json.dumps({
        "id": str(plan.id),
        "title": plan.title,
        "description": plan.description,
        "status": plan.status,
        "created_at": plan.created_at.isoformat(),
        "items": [
            {
                "id": str(i.id),
                "position": i.position,
                "content": i.content,
                "status": i.status,
                "notes": i.notes,
            }
            for i in items
        ],
    })


@register({
    "type": "function",
    "function": {
        "name": "list_plans",
        "description": "List plans for the current bot and channel.",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by plan status: active, complete, or abandoned. Defaults to active.",
                    "enum": ["active", "complete", "abandoned"],
                },
            },
            "required": [],
        },
    },
})
async def list_plans(status: str = "active") -> str:
    bot_id = current_bot_id.get() or "unknown"
    session_id = current_session_id.get()

    async with async_session() as db:
        stmt = (
            select(Plan)
            .where(Plan.bot_id == bot_id, Plan.status == status)
            .order_by(Plan.created_at.desc())
        )
        if session_id:
            stmt = stmt.where(Plan.session_id == session_id)
        plans = (await db.execute(stmt)).scalars().all()

    if not plans:
        return f"No {status} plans found."

    lines = [f"- {p.id} | {p.title} | {p.status}" for p in plans]
    return "Plans:\n" + "\n".join(lines)


@register({
    "type": "function",
    "function": {
        "name": "update_plan_item",
        "description": "Update the status, notes, or content of a single plan item.",
        "parameters": {
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "string",
                    "description": "The plan item UUID.",
                },
                "status": {
                    "type": "string",
                    "description": "New status for the item.",
                    "enum": ["pending", "in_progress", "done", "skipped"],
                },
                "notes": {
                    "type": "string",
                    "description": "Annotation or notes for this item.",
                },
                "content": {
                    "type": "string",
                    "description": "Replace the item's text content.",
                },
            },
            "required": ["item_id"],
        },
    },
})
async def update_plan_item(
    item_id: str,
    status: str | None = None,
    notes: str | None = None,
    content: str | None = None,
) -> str:
    try:
        iid = uuid.UUID(item_id)
    except ValueError:
        return json.dumps({"error": f"Invalid item_id: {item_id}"})

    now = datetime.now(timezone.utc)
    async with async_session() as db:
        item = await db.get(PlanItem, iid)
        if not item:
            return json.dumps({"error": f"PlanItem {item_id} not found."})
        if status is not None:
            item.status = status
        if notes is not None:
            item.notes = notes
        if content is not None:
            item.content = content
        item.updated_at = now
        await db.commit()

    return f"Item {item_id} updated."


@register({
    "type": "function",
    "function": {
        "name": "edit_plan",
        "description": (
            "Edit a plan: update title/description/status, add new items, or remove items. "
            "Set status to 'complete' or 'abandoned' to stop injecting the plan into future turns."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "plan_id": {
                    "type": "string",
                    "description": "The plan UUID.",
                },
                "title": {
                    "type": "string",
                    "description": "New title for the plan.",
                },
                "description": {
                    "type": "string",
                    "description": "New description for the plan.",
                },
                "status": {
                    "type": "string",
                    "description": "New plan status.",
                    "enum": ["active", "complete", "abandoned"],
                },
                "add_items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Additional items to append to the plan.",
                },
                "remove_item_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Item UUIDs to remove from the plan.",
                },
            },
            "required": ["plan_id"],
        },
    },
})
async def edit_plan(
    plan_id: str,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
    add_items: list[str] | None = None,
    remove_item_ids: list[str] | None = None,
) -> str:
    try:
        pid = uuid.UUID(plan_id)
    except ValueError:
        return json.dumps({"error": f"Invalid plan_id: {plan_id}"})

    now = datetime.now(timezone.utc)
    async with async_session() as db:
        plan = await db.get(Plan, pid)
        if not plan:
            return json.dumps({"error": f"Plan {plan_id} not found."})

        if title is not None:
            plan.title = title
        if description is not None:
            plan.description = description
        if status is not None:
            plan.status = status
        plan.updated_at = now

        if remove_item_ids:
            for rid in remove_item_ids:
                try:
                    riid = uuid.UUID(rid)
                except ValueError:
                    continue
                item = await db.get(PlanItem, riid)
                if item and item.plan_id == pid:
                    await db.delete(item)

        if add_items:
            max_pos_row = (await db.execute(
                select(func.max(PlanItem.position)).where(PlanItem.plan_id == pid)
            )).scalar()
            next_pos = (max_pos_row + 1) if max_pos_row is not None else 0
            for i, content in enumerate(add_items):
                db.add(PlanItem(
                    plan_id=pid,
                    position=next_pos + i,
                    content=content,
                    status="pending",
                    updated_at=now,
                ))

        await db.commit()

    return f"Plan {plan_id} updated."
