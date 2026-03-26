"""Agent tools for scheduling and querying tasks."""
import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.agent.context import (
    current_bot_id,
    current_channel_id,
    current_client_id,
    current_dispatch_config,
    current_dispatch_type,
    current_session_id,
)
from app.db.engine import async_session
from app.db.models import PromptTemplate, Task
from app.tools.registry import register

_RELATIVE_RE = re.compile(r"^\+(\d+)([smhd])$")

_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}

# Distinct from None so JSON `null` / explicit None can clear fields while "key omitted" leaves them unchanged.
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


async def _resolve_template(name: str, prompt: str | None, db) -> PromptTemplate:
    """Look up a PromptTemplate by name (case-insensitive).

    If not found and `prompt` is provided, auto-create a manual template.
    If not found and no `prompt`, raise ValueError.
    """
    stmt = select(PromptTemplate).where(func.lower(PromptTemplate.name) == name.lower())
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        return existing

    if prompt:
        tpl = PromptTemplate(name=name, content=prompt, source_type="manual")
        db.add(tpl)
        await db.flush()
        return tpl

    raise ValueError(f"Template '{name}' not found. Provide a prompt to auto-create it.")


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
                "title": {
                    "type": "string",
                    "description": "Short human-readable title for the task (shown in UI). Keep under ~60 chars.",
                },
                "prompt": {
                    "type": "string",
                    "description": "The full prompt/instruction to run when the task executes.",
                },
                "prompt_template": {
                    "type": "string",
                    "description": (
                        "Name of a prompt template to link. If the name exists, it is linked. "
                        "If it doesn't exist, a new template is auto-created using the prompt text. "
                        "Linked templates are resolved at execution time, so editing the template "
                        "updates all future runs."
                    ),
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
                        "any needed follow-up action. Default false."
                    ),
                },
            },
            "required": ["prompt"],
        },
    },
})
async def create_task(
    prompt: str,
    title: str | None = None,
    prompt_template: str | None = None,
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

    template_id = None
    template_msg = ""

    async with async_session() as db:
        # Resolve template if provided
        if prompt_template:
            try:
                tpl = await _resolve_template(prompt_template, prompt, db)
                template_id = tpl.id
                created = tpl in db.new  # was just auto-created
                if created:
                    template_msg = f" Created new template '{prompt_template}' and linked."
                else:
                    template_msg = f" Linked to template '{tpl.name}'."
            except ValueError as e:
                return json.dumps({"error": str(e)})

        # Duplicate detection: same bot + template already pending/active
        dup_warning = ""
        if template_id:
            dup_stmt = (
                select(Task.id)
                .where(
                    Task.bot_id == effective_bot_id,
                    Task.prompt_template_id == template_id,
                    Task.status.in_(["pending", "active"]),
                )
                .limit(1)
            )
            dup_row = (await db.execute(dup_stmt)).scalar_one_or_none()
            if dup_row:
                dup_warning = f" Warning: existing task {dup_row} already uses this template (pending/active)."

        # If recurrence is set, create as an active schedule template
        initial_status = "active" if recurrence else "pending"
        task = Task(
            bot_id=effective_bot_id,
            client_id=effective_client_id,
            session_id=effective_session_id,
            channel_id=effective_channel_id,
            prompt=prompt,
            title=title or None,
            scheduled_at=scheduled,
            status=initial_status,
            task_type="scheduled",
            dispatch_type=dispatch_type,
            dispatch_config=dispatch_config,
            callback_config=callback_cfg,
            recurrence=recurrence or None,
            prompt_template_id=template_id,
            created_at=datetime.now(timezone.utc),
        )
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
        return f"Task {task.id} scheduled for {when_local} ({when_utc}).{recur_suffix}{template_msg}{dup_warning}"
    return f"Task {task.id} queued (runs immediately).{recur_suffix}{template_msg}{dup_warning}"


@register({
    "type": "function",
    "function": {
        "name": "list_tasks",
        "description": (
            "List tasks for the current channel, or get details on a specific task by ID. "
            "By default only shows pending/running/active (future) tasks."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": (
                        "If set, return detailed info for this specific task instead of listing. "
                        "Accepts a task UUID."
                    ),
                },
                "include_completed": {
                    "type": "boolean",
                    "description": (
                        "When true, include completed/failed/cancelled tasks in the listing. "
                        "Default false (only pending, running, and active tasks)."
                    ),
                },
            },
            "required": [],
        },
    },
})
async def list_tasks(task_id: str | None = None, include_completed: bool = False) -> str:
    # Detail mode: single task lookup
    if task_id:
        try:
            tid = uuid.UUID(task_id)
        except ValueError:
            return json.dumps({"error": f"Invalid task_id: {task_id}"})

        async with async_session() as db:
            task = await db.get(Task, tid)
            if not task:
                return json.dumps({"error": f"Task {task_id} not found."})

            # Fetch template name if linked
            tpl_name = None
            if task.prompt_template_id:
                tpl = await db.get(PromptTemplate, task.prompt_template_id)
                if tpl:
                    tpl_name = tpl.name

        data: dict = {
            "id": str(task.id),
            "status": task.status,
            "bot_id": task.bot_id,
            "title": task.title,
            "prompt": task.prompt,
            "scheduled_at": task.scheduled_at.isoformat() if task.scheduled_at else None,
            "run_at": task.run_at.isoformat() if task.run_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "dispatch_type": task.dispatch_type,
            "recurrence": task.recurrence,
            "run_count": task.run_count,
        }
        if tpl_name:
            data["prompt_template"] = tpl_name
        if task.result:
            data["result"] = task.result
        if task.error:
            data["error"] = task.error
        return json.dumps(data)

    # List mode
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
            conditions.append(Task.status.in_(["pending", "running", "active"]))
        stmt = (
            select(Task)
            .where(_and(*conditions))
            .order_by(Task.created_at.desc())
            .limit(20)
        )
        tasks = list((await db.execute(stmt)).scalars().all())

        if not tasks:
            label = "No tasks found for this session." if include_completed else "No pending/running/active tasks found."
            return label

        # Batch-fetch template names
        tpl_ids = {t.prompt_template_id for t in tasks if t.prompt_template_id}
        tpl_names: dict[uuid.UUID, str] = {}
        if tpl_ids:
            tpl_rows = (await db.execute(
                select(PromptTemplate.id, PromptTemplate.name)
                .where(PromptTemplate.id.in_(tpl_ids))
            )).all()
            tpl_names = {row.id: row.name for row in tpl_rows}

    lines = []
    for t in tasks:
        scheduled = t.scheduled_at.strftime("%Y-%m-%d %H:%M UTC") if t.scheduled_at else "immediately"
        if t.status == "active" and t.recurrence:
            status_label = f"active, recurs {t.recurrence}, {t.run_count} runs"
        else:
            status_label = t.status
        recur = f" recurrence={t.recurrence}" if t.recurrence and t.status != "active" else ""

        # Template badge
        tpl_badge = ""
        if t.prompt_template_id:
            name = tpl_names.get(t.prompt_template_id, "?")
            tpl_badge = f" template={name}"
        elif t.status == "active" and t.recurrence:
            tpl_badge = " [no template]"

        # Title / prompt preview
        title_label = ""
        if t.title:
            title_label = f" \"{t.title}\""
        elif t.prompt:
            preview = t.prompt[:60].replace("\n", " ")
            if len(t.prompt) > 60:
                preview += "..."
            title_label = f" \"{preview}\""

        result_preview = ""
        if t.result:
            result_preview = " | result: " + (t.result[:80] + "..." if len(t.result) > 80 else t.result)
        lines.append(
            f"- {t.id} [{status_label}] bot={t.bot_id} scheduled={scheduled}{recur}{tpl_badge}{title_label}{result_preview}"
        )
    return "Tasks:\n" + "\n".join(lines)


@register({
    "type": "function",
    "function": {
        "name": "cancel_task",
        "description": (
            "Cancel a pending task or active recurring schedule so it will not run. "
            "Works on tasks with status=pending or status=active (recurring schedules). "
            "Use list_tasks to find the task ID first."
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
        if task.status not in ("pending", "active"):
            return json.dumps({"error": f"Task is {task.status}, can only cancel pending or active tasks."})
        was_schedule = task.status == "active"
        task.status = "cancelled"
        task.completed_at = datetime.now(timezone.utc)
        await db.commit()

    label = "Schedule" if was_schedule else "Task"
    return f"{label} {task_id} cancelled."


@register({
    "type": "function",
    "function": {
        "name": "update_task",
        "description": (
            "Update a pending or active task: schedule time, prompt, template, recurrence, or bot. "
            "Omit any field to leave it unchanged. Set prompt_template to null to unlink."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task UUID to update.",
                },
                "title": {
                    "type": "string",
                    "description": "New short title for the task. Omit to leave unchanged.",
                },
                "scheduled_at": {
                    "type": "string",
                    "description": (
                        "New run time. ISO 8601 datetime or relative offset: +30m, +2h, +1d. "
                        "Pass null to run immediately. Omit to leave unchanged."
                    ),
                },
                "prompt": {
                    "type": "string",
                    "description": "New instruction text (replaces existing prompt). Omit to leave unchanged.",
                },
                "prompt_template": {
                    "type": "string",
                    "description": (
                        "Template name to link. Pass null to unlink the current template. "
                        "If the name doesn't exist, auto-creates a template using the task's prompt. "
                        "Omit to leave unchanged."
                    ),
                },
                "recurrence": {
                    "type": "string",
                    "description": (
                        "New repeat interval (+30m, +1h, +1d). Pass null to make one-shot. "
                        "Omit to leave unchanged."
                    ),
                },
                "bot_id": {
                    "type": "string",
                    "description": "Change the bot that will run this task. Omit to leave unchanged.",
                },
            },
            "required": ["task_id"],
        },
    },
})
async def update_task(
    task_id: str,
    title: str | None | object = _UNSET,
    scheduled_at: str | None | object = _UNSET,
    prompt: str | object = _UNSET,
    prompt_template: str | None | object = _UNSET,
    recurrence: str | None | object = _UNSET,
    bot_id: str | object = _UNSET,
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
        if task.status not in ("pending", "active"):
            return json.dumps({"error": f"Task is {task.status}, can only update pending or active tasks."})

        changes: list[str] = []

        if title is not _UNSET:
            task.title = title or None
            changes.append("title updated")

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

        if prompt_template is not _UNSET:
            if prompt_template is None:
                # Unlink template
                task.prompt_template_id = None
                changes.append("template unlinked")
            else:
                try:
                    tpl = await _resolve_template(prompt_template, task.prompt, db)
                    task.prompt_template_id = tpl.id
                    created = tpl in db.new
                    if created:
                        changes.append(f"created + linked template '{prompt_template}'")
                    else:
                        changes.append(f"linked template '{tpl.name}'")
                except ValueError as e:
                    return json.dumps({"error": str(e)})

        if recurrence is not _UNSET:
            old_recurrence = task.recurrence
            task.recurrence = recurrence or None
            if task.recurrence:
                # Ensure status is active for recurring tasks
                if task.status == "pending":
                    task.status = "active"
                    changes.append(f"recurrence → {task.recurrence} (status → active)")
                else:
                    changes.append(f"recurrence → {task.recurrence}")
            else:
                # Removing recurrence: if was active schedule, switch to pending
                if task.status == "active":
                    task.status = "pending"
                    changes.append("recurrence removed (status → pending)")
                else:
                    changes.append("recurrence removed")

        if bot_id is not _UNSET:
            from app.agent.bots import resolve_bot_id, list_bots
            resolved = resolve_bot_id(bot_id)
            if resolved is None:
                available = ", ".join(b.id for b in list_bots())
                return json.dumps({"error": f"Unknown bot {bot_id!r}. Available: {available}"})
            task.bot_id = resolved.id
            changes.append(f"bot → {resolved.id}")

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
