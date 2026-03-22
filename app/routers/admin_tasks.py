"""Admin routes for the task scheduling system."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from app.agent.bots import list_bots
from app.db.engine import async_session
from app.db.models import Skill as SkillRow, Task, ToolEmbedding
from app.routers.admin_template_filters import install_admin_template_filters

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
install_admin_template_filters(templates.env)


def _ago(dt: datetime | None) -> str | None:
    """Short relative time for list cells; None means caller should show only fmt_dt (too far past/future)."""
    if dt is None:
        return None
    now = datetime.now(timezone.utc)
    d = dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    delta_secs = int((now - d).total_seconds())
    future = delta_secs < 0
    secs = abs(delta_secs)

    if future:
        if secs < 60:
            return "in <1 min"
        if secs < 3600:
            m = max(1, secs // 60)
            return f"in {m} min" if m != 1 else "in 1 min"
        if secs < 86400:
            h = secs // 3600
            return f"in {h} h" if h != 1 else "in 1 h"
        if secs < 86400 * 14:
            days = max(1, (secs + 86399) // 86400)
            return f"in {days} d" if days != 1 else "in 1 day"
        return None

    if secs < 45:
        return "just now"
    if secs < 3600:
        m = secs // 60
        return f"{m} min ago" if m != 1 else "1 min ago"
    if secs < 86400:
        h = secs // 3600
        return f"{h} h ago" if h != 1 else "1 h ago"
    if secs < 86400 * 7:
        days = secs // 86400
        return f"{days} d ago" if days != 1 else "1 day ago"
    if secs < 86400 * 90:
        wk = secs // 604800
        return f"{wk} wk ago" if wk != 1 else "1 wk ago"
    return None


templates.env.filters["ago"] = _ago  # type: ignore[attr-defined]


@router.get("/tasks", response_class=HTMLResponse)
async def admin_tasks(
    request: Request,
    status: Optional[str] = None,
    bot_id: Optional[str] = None,
    dispatch_type: Optional[str] = None,
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
        if dispatch_type:
            stmt = stmt.where(Task.dispatch_type == dispatch_type)
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
            "dispatch_type_filter": dispatch_type or "",
            "page": page,
            "page_size": page_size,
            "total": total,
        },
    )


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
async def admin_task_detail(request: Request, task_id: uuid.UUID):
    from app.services.providers import get_available_models_grouped

    async with async_session() as db:
        task = await db.get(Task, task_id)
        if not task:
            return HTMLResponse("<div class='text-red-400 p-4'>Task not found.</div>", status_code=404)
        all_skills = list((await db.execute(select(SkillRow).order_by(SkillRow.name))).scalars().all())
        tool_names = list((await db.execute(
            select(ToolEmbedding.tool_name).distinct().order_by(ToolEmbedding.tool_name)
        )).scalars().all())

    from app.tools.packs import get_tool_packs
    packs = get_tool_packs()
    bots = list_bots()
    completions = (
        [{"value": f"skill:{s.id}", "label": f"skill:{s.id} — {s.name}"} for s in all_skills]
        + [{"value": f"tool:{t}", "label": f"tool:{t}"} for t in tool_names]
        + [
            {"value": f"tool-pack:{k}", "label": f"tool-pack:{k} — {len(v)} tools"}
            for k, v in sorted(packs.items())
        ]
    )
    model_groups = await get_available_models_grouped()

    return templates.TemplateResponse(
        "admin/task_detail.html",
        {
            "request": request,
            "task": task,
            "completions_json": json.dumps(completions),
            "bots": bots,
            "model_groups": model_groups,
        },
    )


@router.post("/tasks/{task_id}/edit", response_class=HTMLResponse)
async def admin_task_edit(
    task_id: uuid.UUID,
    prompt: str = Form(...),
    scheduled_at: str = Form(""),
    recurrence: str = Form(""),
    status: str = Form(...),
    bot_id: str = Form(...),
    reply_in_thread: str = Form(""),  # checkbox: "on" when checked, "" when not
    trigger_rag_loop: str = Form(""),  # checkbox: "on" when checked, "" when not
    model_override: str = Form(""),
    model_provider_id_override: str = Form(""),
):
    async with async_session() as db:
        task = await db.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        task.prompt = prompt.strip()
        task.recurrence = recurrence.strip() or None
        task.status = status
        task.bot_id = bot_id.strip()
        cb = {**(task.callback_config or {}), "trigger_rag_loop": trigger_rag_loop == "on"}
        mo = model_override.strip()
        mpo = model_provider_id_override.strip()
        if mo:
            cb["model_override"] = mo
            cb["model_provider_id_override"] = mpo or None
        else:
            cb.pop("model_override", None)
            cb.pop("model_provider_id_override", None)
        task.callback_config = cb

        # Update reply_in_thread in dispatch_config for Slack tasks
        if task.dispatch_type == "slack" and task.dispatch_config is not None:
            cfg = dict(task.dispatch_config)
            cfg["reply_in_thread"] = reply_in_thread == "on"
            task.dispatch_config = cfg

        # Parse scheduled_at
        sa_str = scheduled_at.strip()
        if not sa_str:
            task.scheduled_at = None
        else:
            try:
                from app.tools.local.tasks import _parse_scheduled_at
                task.scheduled_at = _parse_scheduled_at(sa_str)
            except ValueError:
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
