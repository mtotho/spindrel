"""Skills CRUD + file-sync: /skills, /file-sync."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, Skill as SkillRow
from app.dependencies import get_db, verify_auth

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SkillOut(BaseModel):
    id: str
    name: str
    content: str = ""
    source_type: str = "manual"
    source_path: Optional[str] = None
    chunk_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SkillCreateIn(BaseModel):
    id: str
    name: str
    content: str = ""


class SkillUpdateIn(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/skills", response_model=list[SkillOut])
async def admin_list_skills(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    """List all skills with chunk counts."""
    skills = (await db.execute(
        select(SkillRow).order_by(SkillRow.name)
    )).scalars().all()

    chunk_rows = (await db.execute(
        select(Document.source, func.count())
        .where(Document.source.like("skill:%"))
        .group_by(Document.source)
    )).all()
    chunk_map = {row[0]: row[1] for row in chunk_rows}

    return [
        SkillOut(
            id=s.id,
            name=s.name,
            content=s.content or "",
            source_type=s.source_type,
            source_path=s.source_path,
            chunk_count=chunk_map.get(f"skill:{s.id}", 0),
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in skills
    ]


@router.get("/skills/{skill_id}", response_model=SkillOut)
async def admin_get_skill(
    skill_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    row = await db.get(SkillRow, skill_id)
    if not row:
        raise HTTPException(status_code=404, detail="Skill not found")
    chunk_count = (await db.execute(
        select(func.count()).select_from(Document)
        .where(Document.source == f"skill:{skill_id}")
    )).scalar_one()
    return SkillOut(
        id=row.id, name=row.name, content=row.content or "",
        source_type=row.source_type, source_path=row.source_path,
        chunk_count=chunk_count,
        created_at=row.created_at, updated_at=row.updated_at,
    )


@router.post("/skills", response_model=SkillOut, status_code=201)
async def admin_create_skill(
    body: SkillCreateIn,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    skill_id = body.id.strip().lower().replace(" ", "_")
    if not skill_id or not body.name.strip():
        raise HTTPException(status_code=422, detail="id and name are required")

    existing = await db.get(SkillRow, skill_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Skill '{skill_id}' already exists")

    content_hash = hashlib.sha256(body.content.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    row = SkillRow(
        id=skill_id, name=body.name.strip(), content=body.content,
        content_hash=content_hash, created_at=now, updated_at=now,
    )
    db.add(row)
    await db.commit()

    if body.content.strip():
        from app.agent.skills import re_embed_skill
        await re_embed_skill(skill_id)

    return SkillOut(
        id=row.id, name=row.name, content=row.content or "",
        source_type=row.source_type, source_path=row.source_path,
        chunk_count=0, created_at=row.created_at, updated_at=row.updated_at,
    )


@router.put("/skills/{skill_id}", response_model=SkillOut)
async def admin_update_skill(
    skill_id: str,
    body: SkillUpdateIn,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    row = await db.get(SkillRow, skill_id)
    if not row:
        raise HTTPException(status_code=404, detail="Skill not found")
    if row.source_type in ("file", "integration"):
        raise HTTPException(status_code=403, detail="Cannot edit a file-managed skill")

    if body.name is not None:
        row.name = body.name.strip()
    if body.content is not None:
        row.content = body.content
        row.content_hash = hashlib.sha256(body.content.encode()).hexdigest()
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()

    from app.agent.skills import re_embed_skill
    await re_embed_skill(skill_id)

    chunk_count = (await db.execute(
        select(func.count()).select_from(Document)
        .where(Document.source == f"skill:{skill_id}")
    )).scalar_one()
    return SkillOut(
        id=row.id, name=row.name, content=row.content or "",
        source_type=row.source_type, source_path=row.source_path,
        chunk_count=chunk_count,
        created_at=row.created_at, updated_at=row.updated_at,
    )


@router.delete("/skills/{skill_id}")
async def admin_delete_skill(
    skill_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    row = await db.get(SkillRow, skill_id)
    if not row:
        raise HTTPException(status_code=404, detail="Skill not found")
    if row.source_type in ("file", "integration"):
        raise HTTPException(status_code=403, detail="Cannot delete a file-managed skill")
    await db.delete(row)
    await db.execute(sa_delete(Document).where(Document.source == f"skill:{skill_id}"))
    await db.commit()
    return {"ok": True}


@router.post("/file-sync")
async def admin_file_sync(
    _auth: str = Depends(verify_auth),
):
    """Trigger a full file sync for skills and knowledge."""
    from app.services.file_sync import sync_all_files
    counts = await sync_all_files()
    return {"ok": True, **counts}
