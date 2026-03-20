"""Admin skills CRUD routes."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select

from app.agent.skills import re_embed_skill
from app.db.engine import async_session
from app.db.models import Document, Skill as SkillRow

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.get("/skills", response_class=HTMLResponse)
async def admin_skills(request: Request):
    async with async_session() as db:
        skills = (await db.execute(select(SkillRow).order_by(SkillRow.name))).scalars().all()
        # Get chunk counts per skill
        chunk_counts: dict[str, int] = {}
        for skill in skills:
            count = (await db.execute(
                select(func.count()).select_from(Document)
                .where(Document.source == f"skill:{skill.id}")
            )).scalar_one()
            chunk_counts[skill.id] = count
    return templates.TemplateResponse("admin/skills.html", {
        "request": request,
        "skills": skills,
        "chunk_counts": chunk_counts,
    })


@router.get("/skills/new", response_class=HTMLResponse)
async def admin_skill_new(request: Request):
    return templates.TemplateResponse("admin/skill_edit.html", {
        "request": request,
        "skill": None,
    })


@router.post("/skills", response_class=HTMLResponse)
async def admin_skill_create(
    request: Request,
    id: str = Form(...),
    name: str = Form(...),
    content: str = Form(""),
):
    skill_id = id.strip().lower().replace(" ", "_")
    if not skill_id or not name.strip():
        return HTMLResponse("<div class='text-red-400 p-4'>id and name are required.</div>", status_code=422)

    content_hash = hashlib.sha256(content.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    row = SkillRow(
        id=skill_id,
        name=name.strip(),
        content=content,
        content_hash=content_hash,
        created_at=now,
        updated_at=now,
    )

    async with async_session() as db:
        db.add(row)
        try:
            await db.commit()
        except Exception as exc:
            return HTMLResponse(f"<div class='text-red-400 p-4'>Error: {exc}</div>", status_code=400)

    if content.strip():
        await re_embed_skill(skill_id)

    return RedirectResponse("/admin/skills", status_code=303)


@router.get("/skills/{skill_id}/edit", response_class=HTMLResponse)
async def admin_skill_edit(request: Request, skill_id: str):
    async with async_session() as db:
        row = await db.get(SkillRow, skill_id)
        if not row:
            raise HTTPException(status_code=404, detail="Skill not found")
    return templates.TemplateResponse("admin/skill_edit.html", {
        "request": request,
        "skill": row,
    })


@router.post("/skills/{skill_id}", response_class=HTMLResponse)
async def admin_skill_update(
    request: Request,
    skill_id: str,
    name: str = Form(...),
    content: str = Form(""),
):
    content_hash = hashlib.sha256(content.encode()).hexdigest()

    async with async_session() as db:
        row = await db.get(SkillRow, skill_id)
        if not row:
            raise HTTPException(status_code=404, detail="Skill not found")
        row.name = name.strip()
        row.content = content
        row.content_hash = content_hash
        row.updated_at = datetime.now(timezone.utc)
        await db.commit()

    await re_embed_skill(skill_id)
    return RedirectResponse("/admin/skills", status_code=303)


@router.delete("/skills/{skill_id}", response_class=HTMLResponse)
async def admin_skill_delete(skill_id: str):
    async with async_session() as db:
        row = await db.get(SkillRow, skill_id)
        if not row:
            raise HTTPException(status_code=404, detail="Skill not found")
        await db.delete(row)
        await db.execute(delete(Document).where(Document.source == f"skill:{skill_id}"))
        await db.commit()
    return HTMLResponse("", status_code=200)
