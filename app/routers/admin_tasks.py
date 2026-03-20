"""Admin routes for the task scheduling system."""
from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from app.agent.bots import list_bots
from app.db.engine import async_session
from app.db.models import Task

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M")


templates.env.filters["fmt_dt"] = _fmt_dt  # type: ignore[attr-defined]


@router.get("/tasks", response_class=HTMLResponse)
async def admin_tasks(
    request: Request,
    status: Optional[str] = None,
    bot_id: Optional[str] = None,
    page: int = 1,
):
    page_size = 50
    offset = (page - 1) * page_size

    async with async_session() as db:
        stmt = select(Task).order_by(Task.created_at.desc())
        if status:
            stmt = stmt.where(Task.status == status)
        if bot_id:
            stmt = stmt.where(Task.bot_id == bot_id)
        total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        tasks = (await db.execute(stmt.offset(offset).limit(page_size))).scalars().all()

        bot_ids = (await db.execute(select(Task.bot_id).distinct())).scalars().all()

    bots = list_bots()
    return templates.TemplateResponse(
        "admin/tasks.html",
        {
            "request": request,
            "tasks": tasks,
            "bots": bots,
            "bot_ids": sorted(filter(None, bot_ids)),
            "status_filter": status or "",
            "bot_filter": bot_id or "",
            "page": page,
            "page_size": page_size,
            "total": total,
        },
    )


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
async def admin_task_detail(request: Request, task_id: uuid.UUID):
    async with async_session() as db:
        task = await db.get(Task, task_id)
    if not task:
        return HTMLResponse("<div class='text-red-400 p-4'>Task not found.</div>", status_code=404)
    return templates.TemplateResponse(
        "admin/task_detail.html",
        {"request": request, "task": task},
    )


@router.post("/tasks/{task_id}/edit", response_class=HTMLResponse)
async def admin_task_edit(
    task_id: uuid.UUID,
    prompt: str = Form(...),
    scheduled_at: str = Form(""),
    recurrence: str = Form(""),
    status: str = Form(...),
):
    async with async_session() as db:
        task = await db.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        task.prompt = prompt.strip()
        task.recurrence = recurrence.strip() or None
        task.status = status

        # Parse scheduled_at
        sa_str = scheduled_at.strip()
        if not sa_str:
            task.scheduled_at = None
        else:
            try:
                from app.tools.local.tasks import _parse_scheduled_at
                task.scheduled_at = _parse_scheduled_at(sa_str)
            except ValueError:
                # Try raw ISO parse as fallback
                try:
                    task.scheduled_at = datetime.fromisoformat(sa_str)
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"Invalid scheduled_at: {sa_str}")

        await db.commit()

    return RedirectResponse(f"/admin/tasks/{task_id}", status_code=303)


@router.delete("/tasks/{task_id}", response_class=HTMLResponse)
async def admin_task_delete(task_id: uuid.UUID):
    async with async_session() as db:
        task = await db.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        await db.delete(task)
        await db.commit()
    return HTMLResponse("", status_code=200)
