"""Task CRUD endpoints: /tasks."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy import and_, func, or_, select

# Task types allowed to be created/updated via the admin API.
# Internal types like 'exec', 'claude_code', 'delegation' are only
# created programmatically by the system (task worker, delegation service, etc.).
ALLOWED_TASK_TYPES = {"scheduled", "agent"}
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes as sa_attributes

from app.agent.bots import get_bot
from app.db.models import Channel, Session, Task
from app.dependencies import get_db, require_scopes
from ._helpers import _heartbeat_correlation_ids

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TaskDetailOut(BaseModel):
    id: uuid.UUID
    status: str
    bot_id: str
    prompt: str
    title: Optional[str] = None
    prompt_template_id: Optional[uuid.UUID] = None
    workspace_file_path: Optional[str] = None
    workspace_id: Optional[uuid.UUID] = None
    result: Optional[str] = None
    error: Optional[str] = None
    dispatch_type: str = "none"
    task_type: str = "agent"
    recurrence: Optional[str] = None
    client_id: Optional[str] = None
    session_id: Optional[uuid.UUID] = None
    channel_id: Optional[uuid.UUID] = None
    parent_task_id: Optional[uuid.UUID] = None
    dispatch_config: Optional[dict] = None
    callback_config: Optional[dict] = None
    execution_config: Optional[dict] = None
    correlation_id: Optional[uuid.UUID] = None
    delegation_session_id: Optional[uuid.UUID] = None
    trigger_config: Optional[dict] = None
    # Surfaced from execution_config/callback_config for convenience
    model_override: Optional[str] = None
    model_provider_id_override: Optional[str] = None
    fallback_models: Optional[list[dict]] = None
    trigger_rag_loop: bool = False
    workflow_id: Optional[str] = None
    workflow_session_mode: Optional[str] = None
    max_run_seconds: Optional[int] = None
    retry_count: int = 0
    run_count: int = 0
    created_at: datetime
    scheduled_at: Optional[datetime] = None
    run_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def _surface_callback_fields(self):
        # Surface model overrides from execution_config (new) or callback_config (legacy)
        ec = self.execution_config or {}
        cb = self.callback_config or {}
        if self.model_override is None:
            self.model_override = ec.get("model_override") or cb.get("model_override") or None
        if self.model_provider_id_override is None:
            self.model_provider_id_override = ec.get("model_provider_id_override") or cb.get("model_provider_id_override") or None
        if self.fallback_models is None:
            self.fallback_models = ec.get("fallback_models") or cb.get("fallback_models") or None
        if not self.trigger_rag_loop:
            self.trigger_rag_loop = cb.get("trigger_rag_loop", False)
        return self


def _validate_recurrence(v: str | None) -> str | None:
    if v is not None:
        from app.agent.tasks import validate_recurrence
        validate_recurrence(v)
    return v


class TaskCreateIn(BaseModel):
    prompt: str = ""
    bot_id: str
    title: Optional[str] = None
    channel_id: Optional[uuid.UUID] = None
    prompt_template_id: Optional[uuid.UUID] = None
    workspace_file_path: Optional[str] = None
    workspace_id: Optional[uuid.UUID] = None
    scheduled_at: Optional[str] = None
    recurrence: Optional[str] = None
    task_type: str = "scheduled"
    trigger_rag_loop: bool = False
    model_override: Optional[str] = None
    model_provider_id_override: Optional[str] = None
    fallback_models: Optional[list[dict]] = None
    max_run_seconds: Optional[int] = None
    workflow_id: Optional[str] = None
    workflow_session_mode: Optional[str] = None
    trigger_config: Optional[dict] = None
    skills: Optional[list[str]] = None
    tools: Optional[list[str]] = None

    _check_recurrence = field_validator("recurrence")(_validate_recurrence)

    @field_validator("task_type")
    @classmethod
    def _validate_task_type(cls, v: str) -> str:
        if v not in ALLOWED_TASK_TYPES:
            raise ValueError(f"task_type must be one of {sorted(ALLOWED_TASK_TYPES)}, got '{v}'")
        return v

    @model_validator(mode="after")
    def _require_prompt_or_workflow(self):
        has_prompt = bool(self.prompt.strip()) or self.prompt_template_id or self.workspace_file_path
        if not has_prompt and not self.workflow_id:
            raise ValueError("Either prompt (or prompt_template_id/workspace_file_path) or workflow_id is required")
        return self


class TaskUpdateIn(BaseModel):
    prompt: Optional[str] = None
    bot_id: Optional[str] = None
    title: Optional[str] = None
    prompt_template_id: Optional[uuid.UUID] = None
    workspace_file_path: Optional[str] = None
    workspace_id: Optional[str] = None
    status: Optional[str] = None
    scheduled_at: Optional[str] = None
    recurrence: Optional[str] = None
    task_type: Optional[str] = None
    trigger_rag_loop: Optional[bool] = None
    model_override: Optional[str] = None
    model_provider_id_override: Optional[str] = None
    fallback_models: Optional[list[dict]] = None
    max_run_seconds: Optional[int] = None
    workflow_id: Optional[str] = None
    workflow_session_mode: Optional[str] = None
    trigger_config: Optional[dict] = None
    skills: Optional[list[str]] = None
    tools: Optional[list[str]] = None

    _check_recurrence = field_validator("recurrence")(_validate_recurrence)

    @field_validator("task_type")
    @classmethod
    def _validate_task_type(cls, v: str | None) -> str | None:
        if v is not None and v not in ALLOWED_TASK_TYPES:
            raise ValueError(f"task_type must be one of {sorted(ALLOWED_TASK_TYPES)}, got '{v}'")
        return v


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/tasks")
async def admin_list_tasks(
    status: Optional[str] = None,
    bot_id: Optional[str] = None,
    channel_id: Optional[uuid.UUID] = None,
    task_type: Optional[str] = None,
    workflow_run_id: Optional[str] = None,
    after: Optional[str] = None,
    before: Optional[str] = None,
    include_children: bool = False,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("tasks:read")),
):
    """List tasks with optional filters. `after`/`before` are ISO datetime strings filtering on scheduled_at or created_at.

    Returns both concrete tasks (filtered by date range) and active schedule templates
    (always returned, not filtered by date range — the frontend expands them into virtual entries).
    By default, child tasks (callbacks with parent_task_id set) are hidden. Use include_children=true to show them.
    """
    # Schedule templates include both active and cancelled/disabled (so disabled
    # schedules don't vanish from the UI).
    is_schedule_template = and_(Task.recurrence.isnot(None), Task.status.in_(["active", "cancelled"]))

    # Concrete tasks query (excludes schedule templates — both active and disabled)
    stmt = select(Task).where(~is_schedule_template).order_by(Task.scheduled_at.asc().nullslast(), Task.created_at.asc())
    count_stmt = select(func.count()).select_from(Task).where(~is_schedule_template)

    # By default, hide child tasks (callbacks/concrete schedule runs with parent_task_id)
    # workflow_run_id filter overrides this to include children.
    if workflow_run_id:
        include_children = True
    if not include_children:
        stmt = stmt.where(Task.parent_task_id.is_(None))
        count_stmt = count_stmt.where(Task.parent_task_id.is_(None))

    # Schedule templates query (always returned — both active and disabled)
    sched_stmt = select(Task).where(is_schedule_template)

    # workflow_run_id filter: match tasks linked to a specific workflow run
    if workflow_run_id:
        wf_filter = Task.callback_config["workflow_run_id"].as_string() == workflow_run_id
        stmt = stmt.where(wf_filter)
        count_stmt = count_stmt.where(wf_filter)
        sched_stmt = sched_stmt.where(wf_filter)

    if status and status != "active":
        stmt = stmt.where(Task.status == status)
        count_stmt = count_stmt.where(Task.status == status)
    if bot_id:
        stmt = stmt.where(Task.bot_id == bot_id)
        count_stmt = count_stmt.where(Task.bot_id == bot_id)
        sched_stmt = sched_stmt.where(Task.bot_id == bot_id)
    if channel_id:
        stmt = stmt.where(Task.channel_id == channel_id)
        count_stmt = count_stmt.where(Task.channel_id == channel_id)
        sched_stmt = sched_stmt.where(Task.channel_id == channel_id)
    if task_type:
        stmt = stmt.where(Task.task_type == task_type)
        count_stmt = count_stmt.where(Task.task_type == task_type)
        sched_stmt = sched_stmt.where(Task.task_type == task_type)
    if after:
        from datetime import datetime as dt
        after_dt = dt.fromisoformat(after)
        time_col = func.coalesce(Task.scheduled_at, Task.created_at)
        stmt = stmt.where(time_col >= after_dt)
        count_stmt = count_stmt.where(time_col >= after_dt)
    if before:
        from datetime import datetime as dt
        before_dt = dt.fromisoformat(before)
        time_col = func.coalesce(Task.scheduled_at, Task.created_at)
        stmt = stmt.where(time_col < before_dt)
        count_stmt = count_stmt.where(time_col < before_dt)

    total = (await db.execute(count_stmt)).scalar_one()
    tasks = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()
    schedules = (await db.execute(sched_stmt)).scalars().all()

    # Look up correlation_ids for tasks that have run
    corr_map = await _heartbeat_correlation_ids(db, list(tasks))

    def _task_dict(t: Task) -> dict:
        ec = t.execution_config or {}
        cb = t.callback_config or {}
        cid = corr_map.get(t.id)
        return {
            "id": str(t.id),
            "status": t.status,
            "bot_id": t.bot_id,
            "prompt": t.prompt,
            "title": t.title,
            "prompt_template_id": str(t.prompt_template_id) if t.prompt_template_id else None,
            "workspace_file_path": t.workspace_file_path,
            "workspace_id": str(t.workspace_id) if t.workspace_id else None,
            "result": t.result[:500] if t.result else None,
            "error": t.error,
            "dispatch_type": t.dispatch_type,
            "task_type": t.task_type,
            "recurrence": t.recurrence,
            "run_count": t.run_count,
            "channel_id": str(t.channel_id) if t.channel_id else None,
            "parent_task_id": str(t.parent_task_id) if t.parent_task_id else None,
            "correlation_id": str(cid) if cid else None,
            "model_override": ec.get("model_override") or cb.get("model_override"),
            "model_provider_id_override": ec.get("model_provider_id_override") or cb.get("model_provider_id_override"),
            "trigger_rag_loop": cb.get("trigger_rag_loop", False),
            "workflow_run_id": cb.get("workflow_run_id"),
            "workflow_step_index": cb.get("workflow_step_index"),
            "workflow_id": t.workflow_id,
            "workflow_session_mode": t.workflow_session_mode,
            "max_run_seconds": t.max_run_seconds,
            "trigger_config": t.trigger_config,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "scheduled_at": t.scheduled_at.isoformat() if t.scheduled_at else None,
            "run_at": t.run_at.isoformat() if t.run_at else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        }

    return {
        "tasks": [_task_dict(t) for t in tasks],
        "schedules": [_task_dict(s) for s in schedules],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/tasks/trigger-events")
async def admin_list_trigger_events(
    _auth=Depends(require_scopes("tasks:read")),
):
    """List available trigger event sources and their events.

    Aggregates from:
    - Internal EVENT_REGISTRY (system webhook events)
    - Installed integration manifests (binding.config_fields where key == 'event_filter')
    """
    from app.services.webhooks import EVENT_REGISTRY
    from integrations import discover_binding_metadata

    sources: list[dict] = []

    # Internal system events
    system_events = [
        {"type": k, "label": k.replace("_", " ").title(), "description": v}
        for k, v in EVENT_REGISTRY.items()
    ]
    if system_events:
        sources.append({
            "source": "internal",
            "label": "System Events",
            "events": system_events,
        })

    # Integration events from binding metadata
    bindings = discover_binding_metadata()
    for integration_id, binding in bindings.items():
        config_fields = binding.get("config_fields", [])
        for field in config_fields:
            if field.get("key") != "event_filter":
                continue
            options = field.get("options", [])
            if not options:
                continue
            events = [
                {"type": opt["value"], "label": opt.get("label", opt["value"])}
                for opt in options
                if isinstance(opt, dict) and "value" in opt
            ]
            if events:
                sources.append({
                    "source": integration_id,
                    "label": binding.get("display_name_placeholder", integration_id.title()),
                    "events": events,
                })

    return {"sources": sources}


@router.get("/tasks/{task_id}", response_model=TaskDetailOut)
async def admin_get_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("tasks:read")),
):
    """Get a single task with all fields."""
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    out = TaskDetailOut.model_validate(task)
    corr_map = await _heartbeat_correlation_ids(db, [task])
    cid = corr_map.get(task.id)
    if cid:
        out.correlation_id = cid
    # Look up delegation child session if this task created one
    if task.task_type == "delegation":
        del_session = (await db.execute(
            select(Session.id).where(Session.source_task_id == task.id).limit(1)
        )).scalar_one_or_none()
        if del_session:
            out.delegation_session_id = del_session
    return out


@router.get("/tasks/{task_id}/children")
async def admin_list_task_children(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("tasks:read")),
):
    """List child tasks (callbacks, concrete schedule runs) of a parent task."""
    parent = await db.get(Task, task_id)
    if not parent:
        raise HTTPException(status_code=404, detail="Task not found")
    stmt = (
        select(Task)
        .where(Task.parent_task_id == task_id)
        .order_by(Task.created_at.asc())
    )
    children = (await db.execute(stmt)).scalars().all()
    return [TaskDetailOut.model_validate(c) for c in children]


@router.post("/tasks", response_model=TaskDetailOut, status_code=201)
async def admin_create_task(
    body: TaskCreateIn,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("tasks:write")),
):
    """Create a new task. If channel_id is provided, resolve dispatch info from the channel."""
    from app.tools.local.tasks import _parse_scheduled_at

    try:
        scheduled = _parse_scheduled_at(body.scheduled_at)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    dispatch_type = "none"
    dispatch_config = None
    client_id = None
    session_id = None
    channel_id = None

    if body.channel_id:
        channel = await db.get(Channel, body.channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")
        channel_id = channel.id
        client_id = channel.client_id
        session_id = channel.active_session_id
        if channel.integration and channel.dispatch_config:
            dispatch_type = channel.integration
            dispatch_config = dict(channel.dispatch_config)

    callback_config = None
    execution_config = None
    cb_extras: dict = {}
    ec_extras: dict = {}
    if body.trigger_rag_loop:
        cb_extras["trigger_rag_loop"] = True
    if body.model_override:
        ec_extras["model_override"] = body.model_override
    if body.model_provider_id_override:
        ec_extras["model_provider_id_override"] = body.model_provider_id_override
    if body.fallback_models:
        ec_extras["fallback_models"] = body.fallback_models
    if body.skills:
        ec_extras["skills"] = body.skills
    if body.tools:
        ec_extras["tools"] = body.tools
    if cb_extras:
        callback_config = cb_extras
    if ec_extras:
        execution_config = ec_extras

    # Active status for schedule templates and event-triggered tasks (they're templates)
    trigger_type = (body.trigger_config or {}).get("type")
    initial_status = "active" if (body.recurrence or trigger_type == "event") else "pending"

    # Use placeholder prompt when workflow_id is set and prompt is empty
    effective_prompt = body.prompt or ("[Workflow trigger]" if body.workflow_id else "")

    task = Task(
        bot_id=body.bot_id,
        prompt=effective_prompt,
        title=body.title,
        prompt_template_id=body.prompt_template_id,
        workspace_file_path=body.workspace_file_path,
        workspace_id=body.workspace_id,
        status=initial_status,
        task_type=body.task_type,
        scheduled_at=scheduled,
        recurrence=body.recurrence,
        dispatch_type=dispatch_type,
        dispatch_config=dispatch_config,
        callback_config=callback_config,
        execution_config=execution_config,
        client_id=client_id,
        session_id=session_id,
        channel_id=channel_id,
        max_run_seconds=body.max_run_seconds,
        workflow_id=body.workflow_id,
        workflow_session_mode=body.workflow_session_mode,
        trigger_config=body.trigger_config,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return TaskDetailOut.model_validate(task)


@router.api_route("/tasks/{task_id}", methods=["PUT", "PATCH"], response_model=TaskDetailOut)
async def admin_update_task(
    task_id: uuid.UUID,
    body: TaskUpdateIn,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("tasks:write")),
):
    """Update task fields. Only provided fields are changed."""
    from app.tools.local.tasks import _parse_scheduled_at

    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    updates = body.model_dump(exclude_unset=True)

    for field in ("prompt", "prompt_template_id", "workspace_file_path", "workspace_id", "bot_id", "status", "task_type", "title", "max_run_seconds", "workflow_id", "workflow_session_mode", "trigger_config"):
        if field in updates:
            setattr(task, field, updates[field])
    if "recurrence" in updates:
        task.recurrence = updates["recurrence"] or None

    if "scheduled_at" in updates:
        try:
            task.scheduled_at = _parse_scheduled_at(updates["scheduled_at"])
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    # trigger_rag_loop goes in callback_config; model overrides go in execution_config
    if "trigger_rag_loop" in updates:
        cb = dict(task.callback_config or {})
        cb["trigger_rag_loop"] = updates["trigger_rag_loop"]
        task.callback_config = cb
        sa_attributes.flag_modified(task, "callback_config")

    ec_fields = {"model_override", "model_provider_id_override", "fallback_models", "skills", "tools"}
    if ec_fields & updates.keys():
        ec = dict(task.execution_config or {})
        if "model_override" in updates:
            ec["model_override"] = updates["model_override"] or None
        if "model_provider_id_override" in updates:
            ec["model_provider_id_override"] = updates["model_provider_id_override"] or None
        if "fallback_models" in updates:
            ec["fallback_models"] = updates["fallback_models"] or None
        if "skills" in updates:
            ec["skills"] = updates["skills"] or None
        if "tools" in updates:
            ec["tools"] = updates["tools"] or None
        task.execution_config = ec
        sa_attributes.flag_modified(task, "execution_config")

    await db.commit()
    await db.refresh(task)
    return TaskDetailOut.model_validate(task)


@router.get("/cron-jobs")
async def admin_list_cron_jobs(
    workspace_id: Optional[str] = None,
    _auth=Depends(require_scopes("tasks:read")),
):
    """Discover cron jobs across workspace containers and host OS."""
    from app.services.cron_discovery import discover_crons
    from dataclasses import asdict

    result = await discover_crons(workspace_id=workspace_id)
    return {
        "cron_jobs": [asdict(e) for e in result.cron_jobs],
        "errors": result.errors,
    }


@router.delete("/tasks/{task_id}", status_code=204)
async def admin_delete_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("tasks:write")),
):
    """Delete a task."""
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    await db.delete(task)
    await db.commit()
