"""API endpoints for /api/v1/todos."""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import get_bot
from app.db.models import Todo
from app.dependencies import get_db, verify_auth

router = APIRouter(prefix="/todos", tags=["Todos"])


class TodoOut(BaseModel):
    id: uuid.UUID
    bot_id: str
    channel_id: uuid.UUID
    content: str
    status: str
    priority: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TodoCreate(BaseModel):
    bot_id: str
    channel_id: uuid.UUID
    content: str
    priority: int = 0


class TodoPatch(BaseModel):
    content: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[int] = None


@router.get("", response_model=list[TodoOut])
async def list_todos(
    bot_id: str = Query(...),
    channel_id: uuid.UUID = Query(...),
    status: str = Query("pending"),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    stmt = (
        select(Todo)
        .where(Todo.bot_id == bot_id, Todo.channel_id == channel_id)
        .order_by(Todo.priority.desc(), Todo.created_at.asc())
    )
    if status != "all":
        stmt = stmt.where(Todo.status == status)
    rows = (await db.execute(stmt)).scalars().all()
    return [TodoOut.model_validate(r) for r in rows]


@router.post("", response_model=TodoOut, status_code=201)
async def create_todo(
    body: TodoCreate,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    # Validate bot exists
    try:
        get_bot(body.bot_id)
    except HTTPException:
        raise HTTPException(status_code=400, detail=f"Unknown bot: {body.bot_id}")

    todo = Todo(
        id=uuid.uuid4(),
        bot_id=body.bot_id,
        channel_id=body.channel_id,
        content=body.content,
        status="pending",
        priority=body.priority,
    )
    db.add(todo)
    await db.commit()
    await db.refresh(todo)
    return TodoOut.model_validate(todo)


@router.patch("/{todo_id}", response_model=TodoOut)
async def patch_todo(
    todo_id: uuid.UUID,
    body: TodoPatch,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    todo = await db.get(Todo, todo_id)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    if body.content is not None:
        todo.content = body.content
    if body.status is not None:
        todo.status = body.status
    if body.priority is not None:
        todo.priority = body.priority
    from datetime import datetime, timezone
    todo.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(todo)
    return TodoOut.model_validate(todo)


@router.delete("/{todo_id}", status_code=204)
async def delete_todo(
    todo_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    todo = await db.get(Todo, todo_id)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    await db.delete(todo)
    await db.commit()
