"""Task CRUD endpoints: /tasks."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes as sa_attributes

from app.agent.bots import get_bot
from app.db.models import Channel, Session, Task
from app.dependencies import get_db, verify_auth_or_user
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
    correlation_id: Optional[str] = None
    delegation_session_id: Optional[uuid.UUID] = None
    # Surfaced from execution_config/callback_config for convenience
    model_override: Optional[str] = None
    model_provider_id_override: Optional[str] = None
    trigger_rag_loop: bool = False
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
        if not self.trigger_rag_loop:
            self.trigger_rag_loop = cb.get("trigger_rag_loop", False)
        return self


class TaskCreateIn(BaseModel):
    prompt: str
    bot_id: str
    title: Optional[str] = None
    channel_id: Optional[uuid.UUID] = None
    prompt_template_id: Optional[uuid.UUID] = None
    scheduled_at: Optional[str] = None
    recurrence: Optional[str] = None
    task_type: str = "scheduled"
    trigger_rag_loop: bool = False
    model_override: Optional[str] = None
    model_provider_id_override: Optional[str] = None


class TaskUpdateIn(BaseModel):
    prompt: Optional[str] = None
    bot_id: Optional[str] = None
    title: Optional[str] = None
    prompt_template_id: Optional[uuid.UUID] = None
    status: Optional[str] = None
    scheduled_at: Optional[str] = None
    recurrence: Optional[str] = None
    task_type: Optional[str] = None
    trigger_rag_loop: Optional[bool] = None
    model_override: Optional[str] = None
    model_provider_id_override: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/tasks")
async def admin_list_tasks(
    status: Optional[str] = None,
    bot_id: Optional[str] = None,
    channel_id: Optional[uuid.UUID] = None,
    task_type: Optional[str] = None,
    after: Optional[str] = None,
    before: Optional[str] = None,
    include_children: bool = False,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """List tasks with optional filters. `after`/`before` are ISO datetime strings filtering on scheduled_at or created_at.

    Returns both concrete tasks (filtered by date range) and active schedule templates
    (always returned, not filtered by date range — the frontend expands them into virtual entries).
    By default, child tasks (callbacks with parent_task_id set) are hidden. Use include_children=true to show them.
    """
    # Concrete tasks query (excludes active schedule templates)
    stmt = select(Task).where(Task.status != "active").order_by(Task.scheduled_at.asc().nullslast(), Task.created_at.asc())
    count_stmt = select(func.count()).select_from(Task).where(Task.status != "active")

    # By default, hide child tasks (callbacks/concrete schedule runs with parent_task_id)
    if not include_children:
        stmt = stmt.where(Task.parent_task_id.is_(None))
        count_stmt = count_stmt.where(Task.parent_task_id.is_(None))

    # Schedule templates query (always returned)
    sched_stmt = select(Task).where(Task.status == "active", Task.recurrence.isnot(None))

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


@router.get("/tasks/{task_id}", response_model=TaskDetailOut)
async def admin_get_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Get a single task with all fields."""
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    out = TaskDetailOut.model_validate(task)
    corr_map = await _heartbeat_correlation_ids(db, [task])
    cid = corr_map.get(task.id)
    if cid:
        out.correlation_id = str(cid)
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
    _auth=Depends(verify_auth_or_user),
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
    _auth=Depends(verify_auth_or_user),
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
    if cb_extras:
        callback_config = cb_extras
    if ec_extras:
        execution_config = ec_extras

    # If recurrence is set, create as an active schedule template
    initial_status = "active" if body.recurrence else "pending"

    task = Task(
        bot_id=body.bot_id,
        prompt=body.prompt,
        title=body.title,
        prompt_template_id=body.prompt_template_id,
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
    _auth=Depends(verify_auth_or_user),
):
    """Update task fields. Only provided fields are changed."""
    from app.tools.local.tasks import _parse_scheduled_at

    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    updates = body.model_dump(exclude_unset=True)

    for field in ("prompt", "prompt_template_id", "bot_id", "status", "task_type", "title"):
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

    ec_fields = {"model_override", "model_provider_id_override"}
    if ec_fields & updates.keys():
        ec = dict(task.execution_config or {})
        if "model_override" in updates:
            ec["model_override"] = updates["model_override"] or None
        if "model_provider_id_override" in updates:
            ec["model_provider_id_override"] = updates["model_provider_id_override"] or None
        task.execution_config = ec
        sa_attributes.flag_modified(task, "execution_config")

    await db.commit()
    await db.refresh(task)
    return TaskDetailOut.model_validate(task)


@router.delete("/tasks/{task_id}", status_code=204)
async def admin_delete_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Delete a task."""
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    await db.delete(task)
    await db.commit()
