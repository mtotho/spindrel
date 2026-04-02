import uuid
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Task
from app.dependencies import get_db, require_scopes

router = APIRouter(prefix="/tasks", tags=["Tasks"])


class TaskOut(BaseModel):
    id: uuid.UUID
    status: str
    bot_id: str
    prompt: str
    result: Optional[str] = None
    error: Optional[str] = None
    dispatch_type: str
    scheduled_at: Optional[datetime] = None
    run_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, t: Task) -> "TaskOut":
        return cls(
            id=t.id,
            status=t.status,
            bot_id=t.bot_id,
            prompt=t.prompt,
            result=t.result,
            error=t.error,
            dispatch_type=t.dispatch_type,
            scheduled_at=t.scheduled_at,
            run_at=t.run_at,
            completed_at=t.completed_at,
        )


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("tasks:read")),
):
    """Poll a task's status and result."""
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskOut.from_orm(task)
