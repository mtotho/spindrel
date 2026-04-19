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
            "CREATE a NEW task or pipeline definition. Use this ONLY for work that does not already exist. "
            "To RE-RUN an existing task or pipeline, call `run_task` with its task_id instead — "
            "do NOT create a duplicate here. Call `list_tasks` first to check whether a matching "
            "definition already exists. "
            "Defaults to the current bot in the current channel. To schedule work for a DIFFERENT bot, "
            "pass bot_id — the task will run in that bot's primary channel automatically. "
            "The result is dispatched back to the target channel/thread. "
            "For multi-step pipelines, pass steps instead of prompt — each step can be exec (shell), "
            "tool (direct call), or agent (LLM). See the Pipeline Authoring skill for the full step schema."
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
                    "description": (
                        "The full prompt/instruction to run when the task executes. "
                        "Required for single-prompt tasks. For pipeline tasks (when steps "
                        "is provided), this is optional — a placeholder is auto-generated."
                    ),
                },
                "steps": {
                    "type": "string",
                    "description": (
                        "JSON array of pipeline step definitions. Each step needs at minimum "
                        "id and type ('exec', 'tool', 'agent', 'user_prompt', or 'foreach'). "
                        "'user_prompt' pauses the pipeline for human approval (response shapes: "
                        "'binary' or 'multi_item'; resolved via POST /tasks/{id}/steps/{i}/resolve). "
                        "'foreach' iterates a list from a prior step ('over: {{steps.X.result.items}}') "
                        "running 'do' sub-steps per item — sub-step type 'tool' only in v1. "
                        "Providing steps creates "
                        "a pipeline task that executes steps sequentially. "
                        "Example: '[{\"id\":\"search\",\"type\":\"tool\",\"tool_name\":\"web_search\","
                        "\"tool_args\":{\"query\":\"latest news\"}},{\"id\":\"analyze\",\"type\":\"agent\","
                        "\"prompt\":\"Summarize the search results.\"}]'"
                    ),
                },
                "execution_config": {
                    "type": "string",
                    "description": (
                        "JSON object with execution overrides. Valid keys: "
                        "model_override (string), tools (list of tool names), "
                        "skills (list of skill IDs). Applied to agent steps."
                    ),
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
                "trigger_config": {
                    "type": "string",
                    "description": (
                        "JSON object configuring event-based triggers. "
                        "When set, the task runs in response to events instead of (or in addition to) a schedule. "
                        "Example: '{\"type\":\"event\",\"event_source\":\"github\",\"event_type\":\"push\"}'. "
                        "The task status will be set to 'active' when trigger_config is provided."
                    ),
                },
            },
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


@register(
    _SCHEDULE_TASK_SCHEMA,
    safety_tier="control_plane",
    requires_bot_context=True,
    requires_channel_context=True,
)
async def schedule_task(
    prompt: str = "",
    title: str | None = None,
    steps: str | None = None,
    execution_config: str | None = None,
    workspace_file_path: str | None = None,
    scheduled_at: str | None = None,
    bot_id: str | None = None,
    reply_in_thread: bool = False,
    recurrence: str | None = None,
    trigger_rag_loop: bool = False,
    max_run_seconds: int | None = None,
    trigger_config: str | None = None,
) -> str:
    # Rate limit: cap task creation per agent loop iteration
    count = task_creation_count.get(0)
    if count >= _MAX_TASK_CREATIONS_PER_REQUEST:
        return json.dumps({"error": f"Task creation limit reached for this request (max {_MAX_TASK_CREATIONS_PER_REQUEST})."}, ensure_ascii=False)
    task_creation_count.set(count + 1)

    # Parse pipeline steps
    parsed_steps = None
    if steps:
        try:
            parsed_steps = json.loads(steps)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON in steps parameter."}, ensure_ascii=False)
        if not isinstance(parsed_steps, list) or not parsed_steps:
            return json.dumps({"error": "steps must be a non-empty JSON array."}, ensure_ascii=False)

    # Parse execution config
    parsed_ec = None
    if execution_config:
        try:
            parsed_ec = json.loads(execution_config)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON in execution_config parameter."}, ensure_ascii=False)

    # Parse trigger config
    parsed_tc = None
    if trigger_config:
        try:
            parsed_tc = json.loads(trigger_config)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON in trigger_config parameter."}, ensure_ascii=False)

    # Must have at least one of prompt, steps, or workspace_file_path
    if not prompt and not parsed_steps and not workspace_file_path:
        return json.dumps({"error": "Provide at least one of: prompt, steps, or workspace_file_path."}, ensure_ascii=False)

    # Determine task type and effective prompt
    effective_task_type = "scheduled"
    effective_prompt = prompt
    if parsed_steps:
        effective_task_type = "pipeline"
        if not effective_prompt:
            effective_prompt = f"[Pipeline: {len(parsed_steps)} steps]"

    scheduled = _parse_scheduled_at(scheduled_at)

    if recurrence:
        from app.agent.tasks import validate_recurrence
        try:
            validate_recurrence(recurrence)
        except ValueError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    cross_bot = False
    if bot_id:
        from app.agent.bots import resolve_bot_id, list_bots
        resolved = resolve_bot_id(bot_id)
        if resolved is None:
            available = ", ".join(b.id for b in list_bots())
            return json.dumps({"error": f"Unknown bot {bot_id!r}. Available: {available}"}, ensure_ascii=False)
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
            return json.dumps({"error": f"Bot '{effective_bot_id}' has no shared workspace. Cannot use workspace_file_path."}, ensure_ascii=False)

    async with async_session() as db:
        # Resolve channel/dispatch context
        if cross_bot:
            # Cross-bot: resolve the target bot's primary channel
            ch_id, client_id, session_id, dispatch_type, dispatch_config = await _resolve_bot_channel(effective_bot_id, db)
            if not ch_id:
                return json.dumps({"error": f"Bot '{effective_bot_id}' has no channel. Create a channel for it first."}, ensure_ascii=False)
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

        # Active status for schedule templates and event-triggered tasks
        trigger_type = (parsed_tc or {}).get("type")
        initial_status = "active" if (recurrence or trigger_type == "event") else "pending"
        task = Task(
            bot_id=effective_bot_id,
            client_id=client_id,
            session_id=session_id,
            channel_id=ch_id,
            prompt=effective_prompt,
            title=title or None,
            scheduled_at=scheduled,
            status=initial_status,
            task_type=effective_task_type,
            steps=parsed_steps,
            execution_config=parsed_ec,
            trigger_config=parsed_tc,
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

    result_data: dict = {
        "id": str(task.id),
        "status": initial_status,
        "task_type": effective_task_type,
        "bot_id": effective_bot_id,
        "title": title or None,
        "recurrence": recurrence or None,
    }
    if scheduled:
        from zoneinfo import ZoneInfo
        from app.config import settings
        local_dt = scheduled.astimezone(ZoneInfo(settings.TIMEZONE))
        result_data["scheduled_at"] = local_dt.strftime("%Y-%m-%d %H:%M %Z")
    if ws_file_path:
        result_data["workspace_file_path"] = ws_file_path
    if parsed_steps:
        result_data["step_count"] = len(parsed_steps)
    if cross_bot:
        result_data["cross_bot"] = True
    return json.dumps(result_data, ensure_ascii=False)


@register({
    "type": "function",
    "function": {
        "name": "list_tasks",
        "description": (
            "List task definitions, get detailed info on a specific task, "
            "or view run history of a task definition. "
            "Shows all bots' tasks by default. Pass bot_id to filter by a specific bot. "
            "Only shows pending/running/active tasks unless include_completed is set."
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
                        "Filter tasks by bot ID. "
                        "Omit to see tasks for all bots."
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
                "parent_task_id": {
                    "type": "string",
                    "description": (
                        "List run history (child tasks) of a task definition. "
                        "Pass the definition's task UUID to see its concrete runs. "
                        "When set, completed runs are included automatically."
                    ),
                },
            },
            "required": [],
        },
    },
})
async def list_tasks(task_id: str | None = None, bot_id: str | None = None, include_completed: bool = False, include_internal: bool = False, parent_task_id: str | None = None) -> str:
    # Detail mode: single task lookup
    if task_id:
        try:
            tid = uuid.UUID(task_id)
        except ValueError:
            return json.dumps({"error": f"Invalid task_id: {task_id}"}, ensure_ascii=False)

        async with async_session() as db:
            task = await db.get(Task, tid)
            if not task:
                return json.dumps({"error": f"Task {task_id} not found."}, ensure_ascii=False)

            # Fetch template name if linked
            tpl_name = None
            if task.prompt_template_id:
                tpl = await db.get(PromptTemplate, task.prompt_template_id)
                if tpl:
                    tpl_name = tpl.name

        data: dict = {
            "id": str(task.id),
            "status": task.status,
            "task_type": task.task_type,
            "bot_id": task.bot_id,
            "title": task.title,
            "prompt": task.prompt,
            "scheduled_at": task.scheduled_at.isoformat() if task.scheduled_at else None,
            "run_at": task.run_at.isoformat() if task.run_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "dispatch_type": task.dispatch_type,
            "recurrence": task.recurrence,
            "run_count": task.run_count,
        }
        if task.parent_task_id:
            data["parent_task_id"] = str(task.parent_task_id)
        if tpl_name:
            data["prompt_template"] = tpl_name
        _wfp = getattr(task, "workspace_file_path", None)
        if isinstance(_wfp, str) and _wfp:
            data["workspace_file_path"] = _wfp
        if task.result:
            data["result"] = task.result
        if task.error:
            data["error"] = task.error
        if task.steps:
            data["steps"] = task.steps
            data["step_count"] = len(task.steps)
        if task.step_states:
            data["step_states"] = task.step_states
        if task.execution_config:
            data["execution_config"] = task.execution_config
        if task.trigger_config:
            data["trigger_config"] = task.trigger_config
        if task.max_run_seconds:
            data["max_run_seconds"] = task.max_run_seconds
        return json.dumps(data, ensure_ascii=False)

    # Run history mode — list children of a task definition
    if parent_task_id:
        try:
            pid = uuid.UUID(parent_task_id)
        except ValueError:
            return json.dumps({"error": f"Invalid parent_task_id: {parent_task_id}"}, ensure_ascii=False)

        async with async_session() as db:
            parent = await db.get(Task, pid)
            if not parent:
                return json.dumps({"error": f"Task {parent_task_id} not found."}, ensure_ascii=False)
            stmt = (
                select(Task)
                .where(Task.parent_task_id == pid)
                .order_by(Task.created_at.desc())
                .limit(20)
            )
            children = list((await db.execute(stmt)).scalars().all())

        if not children:
            return json.dumps({"runs": [], "message": "No runs found for this task definition."}, ensure_ascii=False)

        run_list = []
        for c in children:
            entry: dict = {
                "id": str(c.id),
                "status": c.status,
                "task_type": c.task_type,
            }
            if c.run_at:
                entry["run_at"] = c.run_at.isoformat()
            if c.completed_at:
                entry["completed_at"] = c.completed_at.isoformat()
            if c.created_at:
                entry["created_at"] = c.created_at.isoformat()
            if c.result:
                entry["result_preview"] = c.result[:80] + ("..." if len(c.result) > 80 else "")
            if c.error:
                entry["error"] = c.error
            if c.step_states:
                done = sum(1 for s in c.step_states if s.get("status") == "done")
                total = len(c.step_states)
                entry["steps_summary"] = f"{done}/{total} done"
            run_list.append(entry)

        return json.dumps({"runs": run_list, "count": len(run_list), "definition_id": parent_task_id}, ensure_ascii=False)

    # List mode — all tasks or filtered by bot
    async with async_session() as db:
        from sqlalchemy import and_ as _and

        conditions: list = []
        if bot_id:
            # Filter by specific bot
            from app.agent.bots import resolve_bot_id
            resolved = resolve_bot_id(bot_id)
            if not resolved:
                return json.dumps({"error": f"Unknown bot '{bot_id}'."}, ensure_ascii=False)
            conditions.append(Task.bot_id == resolved.id)
        if not include_completed:
            conditions.append(Task.status.in_(["pending", "running", "active"]))
        # Hide child tasks (callbacks, concrete schedule runs) by default
        if not include_internal:
            conditions.append(Task.parent_task_id.is_(None))
            # Exclude system-internal task types
            _internal_types = ("delegation", "callback", "memory_hygiene", "skill_review", "claude_code")
            conditions.append(Task.task_type.notin_(_internal_types))
        stmt = select(Task).order_by(Task.created_at.desc()).limit(20)
        if conditions:
            stmt = stmt.where(_and(*conditions))
        tasks = list((await db.execute(stmt)).scalars().all())

        if not tasks:
            msg = "No tasks found." if include_completed else "No pending/running/active tasks. Use include_completed=true to see completed/failed tasks."
            return json.dumps({"tasks": [], "message": msg}, ensure_ascii=False)

        # Batch-fetch template names
        tpl_ids = {t.prompt_template_id for t in tasks if t.prompt_template_id}
        tpl_names: dict[uuid.UUID, str] = {}
        if tpl_ids:
            tpl_rows = (await db.execute(
                select(PromptTemplate.id, PromptTemplate.name)
                .where(PromptTemplate.id.in_(tpl_ids))
            )).all()
            tpl_names = {row.id: row.name for row in tpl_rows}

    task_list = []
    for t in tasks:
        entry: dict = {
            "id": str(t.id),
            "status": t.status,
            "task_type": t.task_type,
            "bot_id": t.bot_id,
            "title": t.title,
        }
        if t.scheduled_at:
            entry["scheduled_at"] = t.scheduled_at.strftime("%Y-%m-%d %H:%M UTC")
        if t.recurrence:
            entry["recurrence"] = t.recurrence
        if t.run_count:
            entry["run_count"] = t.run_count
        # Prompt source
        _wfp = getattr(t, "workspace_file_path", None)
        if isinstance(_wfp, str) and _wfp:
            entry["source"] = _wfp
        elif t.prompt_template_id:
            entry["source"] = tpl_names.get(t.prompt_template_id, "template")
        # Title fallback to prompt preview
        if not t.title and t.prompt:
            preview = t.prompt[:60].replace("\n", " ")
            if len(t.prompt) > 60:
                preview += "..."
            entry["title"] = preview
        if t.result:
            entry["result_preview"] = t.result[:80] + ("..." if len(t.result) > 80 else "")
        task_list.append(entry)

    return json.dumps({"tasks": task_list, "count": len(task_list)}, ensure_ascii=False)


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
}, safety_tier="control_plane")
async def cancel_task(task_id: str) -> str:
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        return json.dumps({"error": f"Invalid task_id: {task_id}"}, ensure_ascii=False)

    async with async_session() as db:
        task = await db.get(Task, tid)
        if not task:
            return json.dumps({"error": f"Task {task_id} not found."}, ensure_ascii=False)
        if task.status not in ("pending", "active"):
            return json.dumps({"error": f"Task is {task.status}, can only cancel pending or active tasks."}, ensure_ascii=False)
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
            "Update a pending or active task definition: schedule, prompt, pipeline steps, "
            "execution config, event triggers, recurrence, or bot. "
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
                "steps": {
                    "type": "string",
                    "description": (
                        "Updated pipeline step definitions as a JSON array. "
                        "Pass null to clear steps (converts back to agent task). "
                        "Omit to leave unchanged."
                    ),
                },
                "execution_config": {
                    "type": "string",
                    "description": (
                        "Execution overrides as JSON object. Valid keys: "
                        "model_override (string), tools (list of tool names), "
                        "skills (list of skill IDs). Merged with existing config. "
                        "Pass null to clear. Omit to leave unchanged."
                    ),
                },
                "trigger_config": {
                    "type": "string",
                    "description": (
                        "Event trigger configuration as JSON object. "
                        "Example: '{\"type\":\"event\",\"event_source\":\"github\","
                        "\"event_type\":\"push\"}'. "
                        "Pass null to clear. Omit to leave unchanged."
                    ),
                },
            },
            "required": ["task_id"],
        },
    },
}, safety_tier="control_plane")
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
    steps: str | None | object = _UNSET,
    execution_config: str | None | object = _UNSET,
    trigger_config: str | None | object = _UNSET,
) -> str:
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        return json.dumps({"error": f"Invalid task_id: {task_id}"}, ensure_ascii=False)

    async with async_session() as db:
        task = await db.get(Task, tid)
        if not task:
            return json.dumps({"error": f"Task {task_id} not found."}, ensure_ascii=False)
        if task.status not in ("pending", "active"):
            return json.dumps({"error": f"Task is {task.status}, can only update pending or active tasks."}, ensure_ascii=False)

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
                    return json.dumps({"error": f"Bot '{task.bot_id}' has no shared workspace."}, ensure_ascii=False)

        if recurrence is not _UNSET:
            if recurrence:
                from app.agent.tasks import validate_recurrence
                try:
                    validate_recurrence(recurrence)
                except ValueError as e:
                    return json.dumps({"error": str(e)}, ensure_ascii=False)
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
                return json.dumps({"error": f"Unknown bot {bot_id!r}. Available: {available}"}, ensure_ascii=False)
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

        if steps is not _UNSET:
            from sqlalchemy.orm import attributes as sa_attributes
            if steps is None:
                task.steps = None
                sa_attributes.flag_modified(task, "steps")
                if task.task_type == "pipeline":
                    task.task_type = "scheduled"
                changes.append("steps cleared (task_type → scheduled)")
            else:
                try:
                    parsed_steps = json.loads(steps)
                except json.JSONDecodeError:
                    return json.dumps({"error": "Invalid JSON in steps parameter."}, ensure_ascii=False)
                if not isinstance(parsed_steps, list) or not parsed_steps:
                    return json.dumps({"error": "steps must be a non-empty JSON array."}, ensure_ascii=False)
                task.steps = parsed_steps
                sa_attributes.flag_modified(task, "steps")
                task.task_type = "pipeline"
                changes.append(f"steps updated ({len(parsed_steps)} steps, task_type → pipeline)")

        if execution_config is not _UNSET:
            from sqlalchemy.orm import attributes as sa_attributes
            if execution_config is None:
                task.execution_config = None
                sa_attributes.flag_modified(task, "execution_config")
                changes.append("execution_config cleared")
            else:
                try:
                    parsed_ec = json.loads(execution_config)
                except json.JSONDecodeError:
                    return json.dumps({"error": "Invalid JSON in execution_config parameter."}, ensure_ascii=False)
                ec = dict(task.execution_config or {})
                ec.update(parsed_ec)
                task.execution_config = ec
                sa_attributes.flag_modified(task, "execution_config")
                changes.append(f"execution_config updated ({', '.join(parsed_ec.keys())})")

        if trigger_config is not _UNSET:
            from sqlalchemy.orm import attributes as sa_attributes
            if trigger_config is None:
                task.trigger_config = None
                changes.append("trigger_config cleared")
            else:
                try:
                    parsed_tc = json.loads(trigger_config)
                except json.JSONDecodeError:
                    return json.dumps({"error": "Invalid JSON in trigger_config parameter."}, ensure_ascii=False)
                task.trigger_config = parsed_tc
                if parsed_tc.get("type") == "event" and task.status == "pending":
                    task.status = "active"
                    changes.append("trigger_config set (status → active)")
                else:
                    changes.append("trigger_config updated")

        if not changes:
            return json.dumps({"error": "Provide at least one field to change."}, ensure_ascii=False)

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
        return json.dumps({"error": f"Invalid task_id: {task_id}"}, ensure_ascii=False)

    async with async_session() as db:
        task = await db.get(Task, tid)
        if not task:
            return json.dumps({"error": f"Task {task_id} not found."}, ensure_ascii=False)

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
        if task.parent_task_id:
            data["parent_task_id"] = str(task.parent_task_id)
        if task.step_states:
            data["step_states"] = task.step_states
        if task.steps:
            data["step_count"] = len(task.steps)

        # Include child tasks count if any
        child_count = (await db.execute(
            select(func.count()).select_from(Task).where(Task.parent_task_id == tid)
        )).scalar_one()
        if child_count:
            data["child_task_count"] = child_count

    return json.dumps(data, ensure_ascii=False)


# ---------------------------------------------------------------------------
# run_task — manually trigger a task definition
# ---------------------------------------------------------------------------
@register({
    "type": "function",
    "function": {
        "name": "run_task",
        "description": (
            "RE-RUN or trigger an existing task / pipeline / schedule by its id. "
            "Use this when the user says 'run that pipeline again', 'trigger the job', "
            "'re-run yesterday's task', or similar. Spawns a concrete child run from the "
            "definition and schedules it immediately; does NOT duplicate the definition. "
            "Works on active schedule templates, pipeline definitions, and event-triggered tasks. "
            "If you don't know the task_id, call `list_tasks` first to find it. "
            "Returns the new run's id and status. Use `list_tasks` with parent_task_id to view run history."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task definition UUID to trigger.",
                },
            },
            "required": ["task_id"],
        },
    },
}, safety_tier="control_plane")
async def run_task(task_id: str) -> str:
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        return json.dumps({"error": f"Invalid task_id: {task_id}"}, ensure_ascii=False)

    from app.services.task_ops import spawn_child_run

    async with async_session() as db:
        try:
            child = await spawn_child_run(tid, db)
        except ValueError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        await db.commit()
        await db.refresh(child)

    result_data: dict = {
        "id": str(child.id),
        "parent_task_id": task_id,
        "status": "pending",
        "task_type": child.task_type,
        "bot_id": child.bot_id,
    }
    if child.title:
        result_data["title"] = child.title
    if child.steps:
        result_data["step_count"] = len(child.steps)
    return json.dumps(result_data, ensure_ascii=False)
