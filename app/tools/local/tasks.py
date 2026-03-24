"""Agent tools for scheduling and querying tasks."""
import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.agent.context import (
    current_bot_id,
    current_channel_id,
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

# Distinct from None so JSON `null` / explicit None can clear scheduled_at while "key omitted" leaves it unchanged.
_UNSET = object()


def _parse_scheduled_at(value: str | None) -> datetime | None:
    """Parse ISO timestamp or relative offset (+30m, +2h, +1d) to UTC datetime.

    Naive ISO timestamps (no timezone suffix) are treated as local time per settings.TIMEZONE.
    """
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
            from zoneinfo import ZoneInfo
            from app.config import settings
            dt = dt.replace(tzinfo=ZoneInfo(settings.TIMEZONE))
        return dt.astimezone(timezone.utc)
    except ValueError:
        raise ValueError(f"Cannot parse scheduled_at: {value!r}. Use ISO format or relative like +30m, +2h, +1d.")


@register({
    "type": "function",
    "function": {
        "name": "create_task",
        "description": (
            "Schedule a task for THIS bot to run later, or immediately. "
            "Use for reminders, recurring jobs, or deferred self-work. "
            "To run a DIFFERENT bot, use delegate_to_agent instead (preferred for cross-bot work). "
            "The result is dispatched back to the originating channel/thread automatically."
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
                        "Omit or null to run immediately. "
                        "Naive datetimes (no timezone suffix) are interpreted as the server's "
                        "local timezone. To be safe, prefer relative offsets (+1h) or include "
                        "a timezone in ISO 8601 format (e.g. 2026-03-21T09:00:00-05:00)."
                    ),
                },
                "bot_id": {
                    "type": "string",
                    "description": "Bot to use. Defaults to the current bot.",
                },
                "reply_in_thread": {
                    "type": "boolean",
                    "description": (
                        "Slack only. When false (default), the result is posted as a new "
                        "top-level message in the channel. When true, the result is posted "
                        "as a reply in the same thread as the original message."
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
                "trigger_rag_loop": {
                    "type": "boolean",
                    "description": (
                        "When true, after the task posts its result, an immediate follow-up "
                        "agent run is triggered so the bot can review what it posted and take "
                        "any needed follow-up action. Useful for tasks that should self-check "
                        "or continue work after posting. Default false."
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
    reply_in_thread: bool = False,
    recurrence: str | None = None,
    trigger_rag_loop: bool = False,
) -> str:
    scheduled = _parse_scheduled_at(scheduled_at)

    # Resolve bot_id: validate early so we don't queue a task that will explode at runtime
    if bot_id:
        from app.agent.bots import resolve_bot_id, list_bots
        resolved = resolve_bot_id(bot_id)
        if resolved is None:
            available = ", ".join(b.id for b in list_bots())
            return json.dumps({"error": f"Unknown bot {bot_id!r}. Available: {available}"})
        if resolved.id != bot_id:
            bot_id = resolved.id  # silently use the canonical ID

    effective_bot_id = bot_id or current_bot_id.get() or "default"
    effective_client_id = current_client_id.get()
    effective_session_id = current_session_id.get()
    effective_channel_id = current_channel_id.get()
    dispatch_type = current_dispatch_type.get() or "none"
    dispatch_config = dict(current_dispatch_config.get() or {})
    if dispatch_type == "slack":
        dispatch_config["reply_in_thread"] = reply_in_thread

    callback_cfg = {"trigger_rag_loop": True} if trigger_rag_loop else None
    task = Task(
        bot_id=effective_bot_id,
        client_id=effective_client_id,
        session_id=effective_session_id,
        channel_id=effective_channel_id,
        prompt=prompt,
        scheduled_at=scheduled,
        status="pending",
        task_type="scheduled",
        dispatch_type=dispatch_type,
        dispatch_config=dispatch_config,
        callback_config=callback_cfg,
        recurrence=recurrence or None,
        created_at=datetime.now(timezone.utc),
    )
    async with async_session() as db:
        db.add(task)
        await db.commit()
        await db.refresh(task)

    recur_suffix = f" Repeats every {recurrence}." if recurrence else ""
    if scheduled:
        from zoneinfo import ZoneInfo
        from app.config import settings
        local_dt = scheduled.astimezone(ZoneInfo(settings.TIMEZONE))
        when_local = local_dt.strftime("%Y-%m-%d %H:%M %Z")
        when_utc = scheduled.strftime("%H:%M UTC")
        return f"Task {task.id} scheduled for {when_local} ({when_utc}).{recur_suffix}"
    return f"Task {task.id} queued (runs immediately).{recur_suffix}"


@register({
    "type": "function",
    "function": {
        "name": "list_my_tasks",
        "description": (
            "List tasks for the current session. By default only shows pending/running "
            "(future) tasks. Set include_completed=true to also see completed, failed, "
            "and cancelled tasks."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "include_completed": {
                    "type": "boolean",
                    "description": (
                        "When true, include completed/failed/cancelled tasks in the listing. "
                        "Default false (only pending and running tasks)."
                    ),
                },
            },
            "required": [],
        },
    },
})
async def list_my_tasks(include_completed: bool = False) -> str:
    session_id = current_session_id.get()
    channel_id = current_channel_id.get()
    if not session_id and not channel_id:
        return "No session or channel context available."

    async with async_session() as db:
        from sqlalchemy import or_ as _or, and_ as _and
        scope_filters = []
        if channel_id:
            scope_filters.append(Task.channel_id == channel_id)
        if session_id:
            scope_filters.append(Task.session_id == session_id)
        conditions = [_or(*scope_filters)]
        if not include_completed:
            conditions.append(Task.status.in_(["pending", "running"]))
        stmt = (
            select(Task)
            .where(_and(*conditions))
            .order_by(Task.created_at.desc())
            .limit(20)
        )
        tasks = list((await db.execute(stmt)).scalars().all())

    if not tasks:
        label = "No tasks found for this session." if include_completed else "No pending/running tasks found."
        return label

    lines = []
    for t in tasks:
        scheduled = t.scheduled_at.strftime("%Y-%m-%d %H:%M UTC") if t.scheduled_at else "immediately"
        recur = f" recurrence={t.recurrence}" if t.recurrence else ""
        result_preview = ""
        if t.result:
            result_preview = " | result: " + (t.result[:80] + "..." if len(t.result) > 80 else t.result)
        lines.append(
            f"- {t.id} [{t.status}] bot={t.bot_id} scheduled={scheduled}{recur}{result_preview}"
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
            "Update a pending task: run time, prompt, reply_in_thread, or trigger_rag_loop. "
            "Only works on tasks with status=pending. Omit any field to leave it unchanged."
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
                        "Pass null to run immediately. Omit to leave unchanged. "
                        "Naive datetimes (no timezone suffix) are interpreted as the server's "
                        "local timezone. Prefer relative offsets or include a timezone suffix."
                    ),
                },
                "prompt": {
                    "type": "string",
                    "description": (
                        "New instruction text for when the task runs (replaces the existing prompt). "
                        "Omit to leave unchanged."
                    ),
                },
                "reply_in_thread": {
                    "type": "boolean",
                    "description": (
                        "Slack only. When false (default), result posts as a top-level channel message. "
                        "When true, posts as a thread reply. Omit to leave unchanged."
                    ),
                },
                "trigger_rag_loop": {
                    "type": "boolean",
                    "description": (
                        "When true, after the task posts its result a follow-up agent run is triggered "
                        "so the bot can react. Omit to leave unchanged."
                    ),
                },
            },
            "required": ["task_id"],
        },
    },
})
async def reschedule_task(
    task_id: str,
    scheduled_at: str | None | object = _UNSET,
    prompt: str | object = _UNSET,
    reply_in_thread: bool | object = _UNSET,
    trigger_rag_loop: bool | object = _UNSET,
) -> str:
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        return json.dumps({"error": f"Invalid task_id: {task_id}"})

    async with async_session() as db:
        task = await db.get(Task, tid)
        if not task:
            return json.dumps({"error": f"Task {task_id} not found."})
        if task.status != "pending":
            return json.dumps({"error": f"Task is {task.status}, can only reschedule pending tasks."})

        changes: list[str] = []
        if scheduled_at is not _UNSET:
            scheduled = _parse_scheduled_at(scheduled_at)
            task.scheduled_at = scheduled
            if scheduled:
                changes.append(f"time → {scheduled.strftime('%Y-%m-%d %H:%M UTC')}")
            else:
                changes.append("time → run immediately on next poll")
        if prompt is not _UNSET:
            task.prompt = prompt
            changes.append("prompt updated")
        if reply_in_thread is not _UNSET:
            cfg = dict(task.dispatch_config or {})
            cfg["reply_in_thread"] = reply_in_thread
            task.dispatch_config = cfg
            changes.append(f"reply_in_thread → {reply_in_thread}")
        if trigger_rag_loop is not _UNSET:
            task.callback_config = {**(task.callback_config or {}), "trigger_rag_loop": trigger_rag_loop}
            changes.append(f"trigger_rag_loop → {trigger_rag_loop}")

        if not changes:
            return json.dumps({"error": "Provide at least one field to change."})

        await db.commit()

    return f"Task {task_id} updated ({'; '.join(changes)})."
