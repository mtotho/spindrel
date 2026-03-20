"""Agent tools for scheduling and querying tasks."""
import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.agent.context import (
    current_bot_id,
    current_client_id,
    current_dispatch_config,
    current_dispatch_type,
    current_session_id,
)
from app.db.engine import async_session
from app.db.models import Task
from app.tools.registry import register

_RELATIVE_RE = re.compile(r"^\+(\d+)([smhd])$")

_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _parse_scheduled_at(value: str | None) -> datetime | None:
    """Parse ISO timestamp or relative offset (+30m, +2h, +1d) to UTC datetime."""
    if not value:
        return None
    value = value.strip()
    m = _RELATIVE_RE.match(value)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return datetime.now(timezone.utc) + timedelta(seconds=n * _UNIT_SECONDS[unit])
    # Try ISO
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        raise ValueError(f"Cannot parse scheduled_at: {value!r}. Use ISO format or relative like +30m, +2h, +1d.")


@register({
    "type": "function",
    "function": {
        "name": "create_task",
        "description": (
            "Schedule a task to be run by the agent at a later time or immediately. "
            "The task will be dispatched back to the originating channel/thread automatically. "
            "Use this for reminders, deferred work, or sub-agent jobs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The full prompt/instruction to run when the task executes.",
                },
                "scheduled_at": {
                    "type": "string",
                    "description": (
                        "When to run. ISO 8601 datetime or relative offset: +30m, +2h, +1d. "
                        "Omit or null to run immediately."
                    ),
                },
                "bot_id": {
                    "type": "string",
                    "description": "Bot to use. Defaults to the current bot.",
                },
                "reply_in_thread": {
                    "type": "boolean",
                    "description": (
                        "Slack only. When true (default), the result is posted as a reply "
                        "in the same thread as the original message. When false, the result "
                        "is posted as a new top-level message in the channel."
                    ),
                },
                "recurrence": {
                    "type": "string",
                    "description": (
                        "Repeat interval. Same format as scheduled_at offsets: +30m, +1h, +1d. "
                        "After each successful run, the next occurrence is automatically scheduled. "
                        "Omit for one-shot tasks."
                    ),
                },
            },
            "required": ["prompt"],
        },
    },
})
async def create_task(
    prompt: str,
    scheduled_at: str | None = None,
    bot_id: str | None = None,
    reply_in_thread: bool = True,
    recurrence: str | None = None,
) -> str:
    scheduled = _parse_scheduled_at(scheduled_at)
    effective_bot_id = bot_id or current_bot_id.get() or "default"
    effective_client_id = current_client_id.get()
    effective_session_id = current_session_id.get()
    dispatch_type = current_dispatch_type.get() or "none"
    dispatch_config = dict(current_dispatch_config.get() or {})
    if dispatch_type == "slack":
        dispatch_config["reply_in_thread"] = reply_in_thread

    task = Task(
        bot_id=effective_bot_id,
        client_id=effective_client_id,
        session_id=effective_session_id,
        prompt=prompt,
        scheduled_at=scheduled,
        status="pending",
        dispatch_type=dispatch_type,
        dispatch_config=dispatch_config,
        recurrence=recurrence or None,
        created_at=datetime.now(timezone.utc),
    )
    async with async_session() as db:
        db.add(task)
        await db.commit()
        await db.refresh(task)

    recur_suffix = f" Repeats every {recurrence}." if recurrence else ""
    if scheduled:
        when = scheduled.strftime("%Y-%m-%d %H:%M UTC")
        return f"Task {task.id} scheduled for {when}.{recur_suffix}"
    return f"Task {task.id} queued (runs immediately).{recur_suffix}"


@register({
    "type": "function",
    "function": {
        "name": "list_my_tasks",
        "description": "List recent tasks for the current session.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
})
async def list_my_tasks() -> str:
    session_id = current_session_id.get()
    if not session_id:
        return "No session context available."

    async with async_session() as db:
        stmt = (
            select(Task)
            .where(Task.session_id == session_id)
            .order_by(Task.created_at.desc())
            .limit(20)
        )
        tasks = list((await db.execute(stmt)).scalars().all())

    if not tasks:
        return "No tasks found for this session."

    lines = []
    for t in tasks:
        scheduled = t.scheduled_at.strftime("%Y-%m-%d %H:%M UTC") if t.scheduled_at else "immediately"
        result_preview = ""
        if t.result:
            result_preview = " | result: " + (t.result[:80] + "..." if len(t.result) > 80 else t.result)
        lines.append(
            f"- {t.id} [{t.status}] bot={t.bot_id} scheduled={scheduled}{result_preview}"
        )
    return "Tasks:\n" + "\n".join(lines)


@register({
    "type": "function",
    "function": {
        "name": "get_task",
        "description": "Get the status and result of a specific task by ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task UUID.",
                },
            },
            "required": ["task_id"],
        },
    },
})
async def get_task(task_id: str) -> str:
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        return json.dumps({"error": f"Invalid task_id: {task_id}"})

    async with async_session() as db:
        task = await db.get(Task, tid)

    if not task:
        return json.dumps({"error": f"Task {task_id} not found."})

    data: dict = {
        "id": str(task.id),
        "status": task.status,
        "bot_id": task.bot_id,
        "scheduled_at": task.scheduled_at.isoformat() if task.scheduled_at else None,
        "run_at": task.run_at.isoformat() if task.run_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "dispatch_type": task.dispatch_type,
    }
    if task.result:
        data["result"] = task.result
    if task.error:
        data["error"] = task.error
    return json.dumps(data)


@register({
    "type": "function",
    "function": {
        "name": "cancel_task",
        "description": (
            "Cancel a pending task so it will not run. "
            "Only works on tasks with status=pending. "
            "Use list_my_tasks to find the task ID first."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task UUID to cancel.",
                },
            },
            "required": ["task_id"],
        },
    },
})
async def cancel_task(task_id: str) -> str:
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        return json.dumps({"error": f"Invalid task_id: {task_id}"})

    async with async_session() as db:
        task = await db.get(Task, tid)
        if not task:
            return json.dumps({"error": f"Task {task_id} not found."})
        if task.status != "pending":
            return json.dumps({"error": f"Task is {task.status}, can only cancel pending tasks."})
        task.status = "cancelled"
        task.completed_at = datetime.now(timezone.utc)
        await db.commit()

    return f"Task {task_id} cancelled."


@register({
    "type": "function",
    "function": {
        "name": "reschedule_task",
        "description": (
            "Change when a pending task will run. "
            "Only works on tasks with status=pending."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task UUID to reschedule.",
                },
                "scheduled_at": {
                    "type": "string",
                    "description": (
                        "New run time. ISO 8601 datetime or relative offset: +30m, +2h, +1d. "
                        "Pass null to run immediately."
                    ),
                },
            },
            "required": ["task_id"],
        },
    },
})
async def reschedule_task(task_id: str, scheduled_at: str | None = None) -> str:
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        return json.dumps({"error": f"Invalid task_id: {task_id}"})

    scheduled = _parse_scheduled_at(scheduled_at)

    async with async_session() as db:
        task = await db.get(Task, tid)
        if not task:
            return json.dumps({"error": f"Task {task_id} not found."})
        if task.status != "pending":
            return json.dumps({"error": f"Task is {task.status}, can only reschedule pending tasks."})
        task.scheduled_at = scheduled
        await db.commit()

    if scheduled:
        when = scheduled.strftime("%Y-%m-%d %H:%M UTC")
        return f"Task {task_id} rescheduled for {when}."
    return f"Task {task_id} will run immediately on next worker poll."
