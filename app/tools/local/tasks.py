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
    task_creation_count,
)

_MAX_TASK_CREATIONS_PER_REQUEST = 20
from app.db.engine import async_session
from app.db.models import PromptTemplate, Task
from app.tools.registry import register

_RELATIVE_RE = re.compile(r"^\+(\d+)([smhdw])$")

_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}

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


_SCHEDULE_TASK_SCHEMA = {
    "type": "function",
    "function": {
        "name": "schedule_task",
        "description": (
            "Schedule a task for any bot to run later (or immediately). "
            "Defaults to the current bot in the current channel. "
            "To schedule work for a DIFFERENT bot, pass bot_id — the task "
            "will run in that bot's primary channel automatically. "
            "The result is dispatched back to the target channel/thread."
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
                "bot_id": {
                    "type": "string",
                    "description": (
                        "Bot to run this task. Defaults to the current bot. "
                        "When targeting a different bot, the task runs in that bot's "
                        "primary channel with its dispatch config."
                    ),
                },
                "workspace_file_path": {
                    "type": "string",
                    "description": (
                        "Path to a file in the bot's shared workspace to use as the prompt. "
                        "The file content is read at execution time (always up-to-date). "
                        "Takes priority over the inline prompt. "
                        "Example: 'prompts/daily-review.md'"
                    ),
                },
                "scheduled_at": {
                    "type": "string",
                    "description": (
                        "When to run. ISO 8601 datetime or relative offset: +30m, +2h, +1d. "
                        "Omit or null to run immediately. "
                        "Naive datetimes (no timezone suffix) are interpreted as the server's "
                        "local timezone. To be safe, prefer relative offsets (+1h) or include "
                        "a timezone in ISO 8601 format (e.g. 2026-03-21T09:00:00-05:00). "
                        "Conventions: 'nightly' = 2-4 AM local, 'morning' = 7-9 AM local. "
                        "For recurring tasks at a fixed local time, use an absolute ISO 8601 "
                        "timestamp with timezone offset as the anchor."
                    ),
                },
                "recurrence": {
                    "type": "string",
                    "description": (
                        "Repeat interval: +30m, +1h, +1d, +1w. "
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
                "max_run_seconds": {
                    "type": "integer",
                    "description": (
                        "Maximum time in seconds this task is allowed to run before being "
                        "terminated. Overrides channel and global defaults. "
                        "Default: inherit from channel setting or global (1200s / 20min)."
                    ),
                },
            },
            "required": ["prompt"],
        },
    },
}


async def _resolve_bot_channel(bot_id: str, db) -> tuple[uuid.UUID | None, str | None, uuid.UUID | None, str, dict]:
    """Find the primary channel for a bot. Returns (channel_id, client_id, session_id, dispatch_type, dispatch_config)."""
    from app.db.models import Channel
    stmt = (
        select(Channel)
        .where(Channel.bot_id == bot_id)
        .order_by(Channel.name.asc())
        .limit(1)
    )
    channel = (await db.execute(stmt)).scalar_one_or_none()
    if not channel:
        return None, None, None, "none", {}
    dispatch_type = channel.integration or "none"
    dispatch_config = dict(channel.dispatch_config or {})
    return channel.id, channel.client_id, channel.active_session_id, dispatch_type, dispatch_config


@register(_SCHEDULE_TASK_SCHEMA)
async def schedule_task(
    prompt: str,
    title: str | None = None,
    workspace_file_path: str | None = None,
    scheduled_at: str | None = None,
    bot_id: str | None = None,
    reply_in_thread: bool = False,
    recurrence: str | None = None,
    trigger_rag_loop: bool = False,
    max_run_seconds: int | None = None,
) -> str:
    # Rate limit: cap task creation per agent loop iteration
    count = task_creation_count.get(0)
    if count >= _MAX_TASK_CREATIONS_PER_REQUEST:
        return json.dumps({"error": f"Task creation limit reached for this request (max {_MAX_TASK_CREATIONS_PER_REQUEST})."})
    task_creation_count.set(count + 1)

    scheduled = _parse_scheduled_at(scheduled_at)

    if recurrence:
        from app.agent.tasks import validate_recurrence
        try:
            validate_recurrence(recurrence)
        except ValueError as e:
            return json.dumps({"error": str(e)})

    cross_bot = False
    if bot_id:
        from app.agent.bots import resolve_bot_id, list_bots
        resolved = resolve_bot_id(bot_id)
        if resolved is None:
            available = ", ".join(b.id for b in list_bots())
            return json.dumps({"error": f"Unknown bot {bot_id!r}. Available: {available}"})
        bot_id = resolved.id
        if bot_id != (current_bot_id.get() or "default"):
            cross_bot = True

    effective_bot_id = bot_id or current_bot_id.get() or "default"

    callback_cfg = {"trigger_rag_loop": True} if trigger_rag_loop else None

    # Resolve workspace_id from bot config when workspace_file_path is provided
    ws_file_path = workspace_file_path
    ws_id = None
    ws_msg = ""
    if ws_file_path:
        from app.agent.bots import get_bot
        bot_cfg = get_bot(effective_bot_id)
        if bot_cfg and bot_cfg.shared_workspace_id:
            ws_id = bot_cfg.shared_workspace_id
            ws_msg = f" Using workspace file '{ws_file_path}'."
        else:
            return json.dumps({"error": f"Bot '{effective_bot_id}' has no shared workspace. Cannot use workspace_file_path."})

    async with async_session() as db:
        # Resolve channel/dispatch context
        if cross_bot:
            # Cross-bot: resolve the target bot's primary channel
            ch_id, client_id, session_id, dispatch_type, dispatch_config = await _resolve_bot_channel(effective_bot_id, db)
            if not ch_id:
                return json.dumps({"error": f"Bot '{effective_bot_id}' has no channel. Create a channel for it first."})
        else:
            # Same bot: use current context, with fallback to bot's primary channel
            ch_id = current_channel_id.get()
            client_id = current_client_id.get()
            session_id = current_session_id.get()
            dispatch_type = current_dispatch_type.get() or "none"
            dispatch_config = dict(current_dispatch_config.get() or {})

            if not ch_id:
                # No channel in context (e.g. ephemeral delegation) — resolve from bot's channels
                ch_id, client_id, session_id, dispatch_type, dispatch_config = await _resolve_bot_channel(effective_bot_id, db)

        if dispatch_type == "slack":
            dispatch_config["reply_in_thread"] = reply_in_thread

        # If recurrence is set, create as an active schedule template
        initial_status = "active" if recurrence else "pending"
        task = Task(
            bot_id=effective_bot_id,
            client_id=client_id,
            session_id=session_id,
            channel_id=ch_id,
            prompt=prompt,
            title=title or None,
            scheduled_at=scheduled,
            status=initial_status,
            task_type="scheduled",
            dispatch_type=dispatch_type,
            dispatch_config=dispatch_config,
            callback_config=callback_cfg,
            recurrence=recurrence or None,
            workspace_file_path=ws_file_path,
            workspace_id=ws_id,
            max_run_seconds=max_run_seconds,
            created_at=datetime.now(timezone.utc),
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)

    recur_suffix = f" Repeats every {recurrence}." if recurrence else ""
    bot_suffix = f" (bot={effective_bot_id})" if cross_bot else ""
    if scheduled:
        from zoneinfo import ZoneInfo
        from app.config import settings
        local_dt = scheduled.astimezone(ZoneInfo(settings.TIMEZONE))
        when_local = local_dt.strftime("%Y-%m-%d %H:%M %Z")
        when_utc = scheduled.strftime("%H:%M UTC")
        ws_info = f" Using workspace file '{ws_file_path}'." if ws_file_path else ""
        return f"Task {task.id} scheduled for {when_local} ({when_utc}).{bot_suffix}{recur_suffix}{ws_info}"
    ws_info = f" Using workspace file '{ws_file_path}'." if ws_file_path else ""
    return f"Task {task.id} queued (runs immediately).{bot_suffix}{recur_suffix}{ws_info}"


@register({
    "type": "function",
    "function": {
        "name": "list_tasks",
        "description": (
            "List tasks for the current channel (or another bot's channel). "
            "By default only shows pending/running/active tasks, excluding internal tasks."
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
                "bot_id": {
                    "type": "string",
                    "description": (
                        "List tasks for a different bot (by bot ID). "
                        "Requires that the current bot has the target bot in its delegate_bots list. "
                        "Omit to list tasks for the current channel."
                    ),
                },
                "include_completed": {
                    "type": "boolean",
                    "description": (
                        "When true, include completed/failed/cancelled tasks in the listing. "
                        "Default false (only pending, running, and active tasks)."
                    ),
                },
                "include_internal": {
                    "type": "boolean",
                    "description": (
                        "When true, include internal tasks (callbacks, concrete schedule runs) "
                        "that are normally hidden. Default false."
                    ),
                },
            },
            "required": [],
        },
    },
})
async def list_tasks(task_id: str | None = None, bot_id: str | None = None, include_completed: bool = False, include_internal: bool = False) -> str:
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
        _wfp = getattr(task, "workspace_file_path", None)
        if isinstance(_wfp, str) and _wfp:
            data["workspace_file_path"] = _wfp
        if task.result:
            data["result"] = task.result
        if task.error:
            data["error"] = task.error
        return json.dumps(data)

    # List mode — cross-bot or current channel
    async with async_session() as db:
        from sqlalchemy import and_ as _and

        if bot_id:
            # Cross-bot: check delegation access
            from app.agent.bots import get_bot as _get_bot, resolve_bot_id
            resolved = resolve_bot_id(bot_id)
            if not resolved:
                return json.dumps({"error": f"Unknown bot '{bot_id}'."})
            caller_bot = _get_bot(current_bot_id.get() or "default")
            if caller_bot and resolved.id not in caller_bot.delegate_bots:
                return json.dumps({"error": f"No access to bot '{resolved.id}'. Add it to your delegate_bots list."})
            # Query by bot_id across all channels
            conditions = [Task.bot_id == resolved.id]
        else:
            # Scope by current bot to see tasks across all its channels
            effective_bot = current_bot_id.get() or "default"
            conditions = [Task.bot_id == effective_bot]
        if not include_completed:
            conditions.append(Task.status.in_(["pending", "running", "active"]))
        # Hide child tasks (callbacks, concrete schedule runs) by default
        if not include_internal:
            conditions.append(Task.parent_task_id.is_(None))
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

        # Prompt source badge
        tpl_badge = ""
        _wfp = getattr(t, "workspace_file_path", None)
        if isinstance(_wfp, str) and _wfp:
            tpl_badge = f" file={_wfp}"
        elif t.prompt_template_id:
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
            "Update a pending or active task: schedule time, prompt, workspace file, recurrence, or bot. "
            "Omit any field to leave it unchanged."
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
                "workspace_file_path": {
                    "type": "string",
                    "description": (
                        "Path to a workspace file to use as the prompt. Pass null to unlink. "
                        "Omit to leave unchanged."
                    ),
                },
                "recurrence": {
                    "type": "string",
                    "description": (
                        "New repeat interval (+30m, +1h, +1d, +1w). Pass null to make one-shot. "
                        "Omit to leave unchanged."
                    ),
                },
                "bot_id": {
                    "type": "string",
                    "description": "Change the bot that will run this task. Omit to leave unchanged.",
                },
                "max_run_seconds": {
                    "type": "integer",
                    "description": "Max run time in seconds. Pass null to clear (inherit from channel/global). Omit to leave unchanged.",
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
    workspace_file_path: str | None | object = _UNSET,
    recurrence: str | None | object = _UNSET,
    bot_id: str | object = _UNSET,
    reply_in_thread: bool | object = _UNSET,
    trigger_rag_loop: bool | object = _UNSET,
    max_run_seconds: int | None | object = _UNSET,
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

        if workspace_file_path is not _UNSET:
            if workspace_file_path is None:
                task.workspace_file_path = None
                task.workspace_id = None
                changes.append("workspace file unlinked")
            else:
                from app.agent.bots import get_bot
                bot_cfg = get_bot(task.bot_id)
                if bot_cfg and bot_cfg.shared_workspace_id:
                    task.workspace_file_path = workspace_file_path
                    task.workspace_id = bot_cfg.shared_workspace_id
                    changes.append(f"workspace file → '{workspace_file_path}'")
                else:
                    return json.dumps({"error": f"Bot '{task.bot_id}' has no shared workspace."})

        if recurrence is not _UNSET:
            if recurrence:
                from app.agent.tasks import validate_recurrence
                try:
                    validate_recurrence(recurrence)
                except ValueError as e:
                    return json.dumps({"error": str(e)})
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

        if max_run_seconds is not _UNSET:
            task.max_run_seconds = max_run_seconds
            changes.append(f"max_run_seconds → {max_run_seconds}")

        if not changes:
            return json.dumps({"error": "Provide at least one field to change."})

        await db.commit()

    return f"Task {task_id} updated ({'; '.join(changes)})."


# ---------------------------------------------------------------------------
# get_task_result — check output of a delegation / exec task
# ---------------------------------------------------------------------------
@register({
    "type": "function",
    "function": {
        "name": "get_task_result",
        "description": (
            "Retrieve the result or current status of a task by ID. "
            "Useful for checking the output of delegation or exec tasks "
            "after they complete."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task UUID to look up.",
                },
            },
            "required": ["task_id"],
        },
    },
})
async def get_task_result(task_id: str) -> str:
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
            "task_type": task.task_type,
            "bot_id": task.bot_id,
        }
        if task.title:
            data["title"] = task.title
        if task.result:
            data["result"] = task.result
        if task.error:
            data["error"] = task.error
        if task.run_at:
            data["run_at"] = task.run_at.isoformat()
        if task.completed_at:
            data["completed_at"] = task.completed_at.isoformat()
        if task.run_count:
            data["run_count"] = task.run_count

        # Include child tasks count if any
        child_count = (await db.execute(
            select(func.count()).select_from(Task).where(Task.parent_task_id == tid)
        )).scalar_one()
        if child_count:
            data["child_task_count"] = child_count

    return json.dumps(data)
