"""Task CRUD endpoints: /tasks."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import get_bot
from app.db.models import Channel, Task
from app.dependencies import get_db, verify_auth_or_user

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TaskDetailOut(BaseModel):
    id: uuid.UUID
    status: str
    bot_id: str
    prompt: str
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
    retry_count: int = 0
    created_at: datetime
    scheduled_at: Optional[datetime] = None
    run_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TaskCreateIn(BaseModel):
    prompt: str
    bot_id: str
    channel_id: Optional[uuid.UUID] = None
    scheduled_at: Optional[str] = None
    recurrence: Optional[str] = None
    task_type: str = "scheduled"
    trigger_rag_loop: bool = False
    model_override: Optional[str] = None
    model_provider_id_override: Optional[str] = None


class TaskUpdateIn(BaseModel):
    prompt: Optional[str] = None
    bot_id: Optional[str] = None
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
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """List tasks with optional filters. `after`/`before` are ISO datetime strings filtering on scheduled_at or created_at."""
    stmt = select(Task).order_by(Task.scheduled_at.asc().nullslast(), Task.created_at.asc())
    count_stmt = select(func.count()).select_from(Task)

    if status:
        stmt = stmt.where(Task.status == status)
        count_stmt = count_stmt.where(Task.status == status)
    if bot_id:
        stmt = stmt.where(Task.bot_id == bot_id)
        count_stmt = count_stmt.where(Task.bot_id == bot_id)
    if channel_id:
        stmt = stmt.where(Task.channel_id == channel_id)
        count_stmt = count_stmt.where(Task.channel_id == channel_id)
    if task_type:
        stmt = stmt.where(Task.task_type == task_type)
        count_stmt = count_stmt.where(Task.task_type == task_type)
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

    return {
        "tasks": [
            {
                "id": str(t.id),
                "status": t.status,
                "bot_id": t.bot_id,
                "prompt": t.prompt,
                "result": t.result[:500] if t.result else None,
                "error": t.error,
                "dispatch_type": t.dispatch_type,
                "task_type": t.task_type,
                "recurrence": t.recurrence,
                "channel_id": str(t.channel_id) if t.channel_id else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "scheduled_at": t.scheduled_at.isoformat() if t.scheduled_at else None,
                "run_at": t.run_at.isoformat() if t.run_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            }
            for t in tasks
        ],
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
    return TaskDetailOut.model_validate(task)


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
    extras: dict = {}
    if body.trigger_rag_loop:
        extras["trigger_rag_loop"] = True
    if body.model_override:
        extras["model_override"] = body.model_override
    if body.model_provider_id_override:
        extras["model_provider_id_override"] = body.model_provider_id_override
    if extras:
        callback_config = extras

    task = Task(
        bot_id=body.bot_id,
        prompt=body.prompt,
        status="pending",
        task_type=body.task_type,
        scheduled_at=scheduled,
        recurrence=body.recurrence,
        dispatch_type=dispatch_type,
        dispatch_config=dispatch_config,
        callback_config=callback_config,
        client_id=client_id,
        session_id=session_id,
        channel_id=channel_id,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return TaskDetailOut.model_validate(task)


@router.put("/tasks/{task_id}", response_model=TaskDetailOut)
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

    if body.prompt is not None:
        task.prompt = body.prompt
    if body.bot_id is not None:
        task.bot_id = body.bot_id
    if body.status is not None:
        task.status = body.status
    if body.task_type is not None:
        task.task_type = body.task_type
    if body.recurrence is not None:
        task.recurrence = body.recurrence or None

    if body.scheduled_at is not None:
        try:
            task.scheduled_at = _parse_scheduled_at(body.scheduled_at)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    if body.trigger_rag_loop is not None or body.model_override is not None or body.model_provider_id_override is not None:
        cb = dict(task.callback_config or {})
        if body.trigger_rag_loop is not None:
            cb["trigger_rag_loop"] = body.trigger_rag_loop
        if body.model_override is not None:
            cb["model_override"] = body.model_override or None
        if body.model_provider_id_override is not None:
            cb["model_provider_id_override"] = body.model_provider_id_override or None
        task.callback_config = cb

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
