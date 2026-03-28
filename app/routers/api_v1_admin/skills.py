"""Skills CRUD + file-sync: /skills, /file-sync."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, SharedWorkspace, Skill as SkillRow
from app.dependencies import get_db, verify_auth_or_user

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
    # Workspace skill fields (only set when source_type == "workspace")
    workspace_id: Optional[str] = None
    workspace_name: Optional[str] = None
    mode: Optional[str] = None
    bot_id: Optional[str] = None

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
    _auth: str = Depends(verify_auth_or_user),
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

    result = [
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

    # Include workspace skills from documents table
    ws_skill_rows = (await db.execute(
        select(
            Document.metadata_["skill_id"].as_string().label("skill_id"),
            Document.metadata_["skill_name"].as_string().label("skill_name"),
            Document.metadata_["workspace_id"].as_string().label("workspace_id"),
            Document.metadata_["mode"].as_string().label("mode"),
            Document.metadata_["bot_id"].as_string().label("bot_id"),
            Document.metadata_["source_path"].as_string().label("source_path"),
            func.count().label("chunk_count"),
        )
        .where(Document.source.like("workspace_skill:%"))
        .group_by("skill_id", "skill_name", "workspace_id", "mode", "bot_id", "source_path")
        .order_by("skill_name")
    )).all()

    if ws_skill_rows:
        # Batch-fetch workspace names
        ws_id_strs = list({r.workspace_id for r in ws_skill_rows if r.workspace_id})
        ws_names: dict[str, str] = {}
        if ws_id_strs:
            import uuid as _uuid
            ws_uuids = []
            for s in ws_id_strs:
                try:
                    ws_uuids.append(_uuid.UUID(s))
                except ValueError:
                    pass
            if ws_uuids:
                ws_rows = (await db.execute(
                    select(SharedWorkspace.id, SharedWorkspace.name)
                    .where(SharedWorkspace.id.in_(ws_uuids))
                )).all()
                ws_names = {str(r.id): r.name for r in ws_rows}

        now = datetime.now(timezone.utc)
        for r in ws_skill_rows:
            result.append(SkillOut(
                id=r.skill_id,
                name=r.skill_name or r.skill_id,
                source_type="workspace",
                source_path=r.source_path,
                chunk_count=r.chunk_count,
                created_at=now,
                updated_at=now,
                workspace_id=r.workspace_id,
                workspace_name=ws_names.get(r.workspace_id, r.workspace_id),
                mode=r.mode,
                bot_id=r.bot_id,
            ))

    return result


@router.get("/skills/{skill_id}", response_model=SkillOut)
async def admin_get_skill(
    skill_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
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
    _auth: str = Depends(verify_auth_or_user),
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
    _auth: str = Depends(verify_auth_or_user),
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
    _auth: str = Depends(verify_auth_or_user),
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
    _auth: str = Depends(verify_auth_or_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger a full file sync for skills, knowledge, and workspace skills."""
    from app.services.file_sync import sync_all_files
    result = await sync_all_files()

    # Also re-embed workspace skills (with orphan cleanup)
    ws_stats: list[dict] = []
    from app.db.models import SharedWorkspace as SW
    ws_rows = (await db.execute(
        select(SW).where(SW.workspace_skills_enabled == True)  # noqa: E712
    )).scalars().all()
    if ws_rows:
        from app.services.workspace_skills import embed_workspace_skills
        for ws in ws_rows:
            try:
                stats = await embed_workspace_skills(str(ws.id))
                ws_stats.append({"workspace": ws.name, **stats})
            except Exception:
                ws_stats.append({"workspace": ws.name, "error": True})

    return {"ok": True, **result, "workspace_skills": ws_stats}
