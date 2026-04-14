"""Skills CRUD + file-sync: /skills, /file-sync."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete, func, select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BotSkillEnrollment, Document, Skill as SkillRow, ToolCall, TraceEvent
from app.dependencies import get_db, require_scopes

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SkillOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    triggers: list[str] = []
    content: str = ""
    source_type: str = "manual"
    source_path: Optional[str] = None
    chunk_count: int = 0
    created_at: datetime
    updated_at: datetime
    last_surfaced_at: Optional[datetime] = None
    surface_count: int = 0
    total_auto_injects: int = 0
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
    source_type: str | None = None,
    bot_id: str | None = None,
    sort: str = "name",
    days: int = Query(default=0, ge=0, le=90, description="Time window in days (0 = all-time)"),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("skills:read")),
):
    """List all skills with chunk counts.

    Optional filters:
    - source_type: filter by source type (e.g. "tool", "file", "manual")
    - bot_id: filter to bot-authored skills (bots/{bot_id}/%)
    - sort: "name" (default) or "recent" (updated_at DESC)
    """
    q = select(SkillRow)
    if source_type:
        q = q.where(SkillRow.source_type == source_type)
    if bot_id:
        q = q.where(SkillRow.id.like(f"bots/{bot_id}/%"))
    if sort == "recent":
        q = q.order_by(SkillRow.updated_at.desc())
    else:
        q = q.order_by(SkillRow.name)
    skills = (await db.execute(q)).scalars().all()

    chunk_rows = (await db.execute(
        select(Document.source, func.count())
        .where(Document.source.like("skill:%"))
        .group_by(Document.source)
    )).all()
    chunk_map = {row[0]: row[1] for row in chunk_rows}

    # Aggregate auto-inject + surfacing counts (time-windowed or all-time)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days) if days > 0 else None

    if cutoff:
        # Time-windowed: per-skill surfacings from ToolCall
        _surf_rows = (await db.execute(
            select(
                ToolCall.arguments["skill_id"].astext.label("skill_id"),
                func.count().label("n"),
            )
            .where(ToolCall.tool_name == "get_skill", ToolCall.created_at >= cutoff)
            .group_by(ToolCall.arguments["skill_id"].astext)
        )).all()
        surf_map = {r.skill_id: int(r.n) for r in _surf_rows}

        # Time-windowed: per-skill auto-injects from TraceEvent (unnest array)
        _ai_rows = (await db.execute(sa_text(
            "SELECT je.value::text AS skill_id, COUNT(*) AS n "
            "FROM trace_events, jsonb_array_elements_text(data->'auto_injected') je "
            "WHERE event_type = 'skill_index' AND created_at >= :cutoff "
            "AND jsonb_array_length(data->'auto_injected') > 0 "
            "GROUP BY je.value"
        ).bindparams(cutoff=cutoff))).all()
        ai_map = {r.skill_id.strip('"'): int(r.n) for r in _ai_rows}
    else:
        # All-time: use the DB counters (cheaper)
        surf_map = {}  # will use Skill.surface_count directly
        _ai_agg = (await db.execute(
            select(
                BotSkillEnrollment.skill_id,
                func.coalesce(func.sum(BotSkillEnrollment.auto_inject_count), 0).label("total_ai"),
            )
            .group_by(BotSkillEnrollment.skill_id)
        )).all()
        ai_map = {row.skill_id: int(row.total_ai) for row in _ai_agg}

    def _extract_bot_id(skill_id: str, st: str) -> str | None:
        if st == "tool" and skill_id.startswith("bots/"):
            parts = skill_id.split("/", 3)
            return parts[1] if len(parts) >= 3 else None
        return None

    result = [
        SkillOut(
            id=s.id,
            name=s.name,
            description=s.description,
            category=s.category,
            triggers=s.triggers or [],
            content=s.content or "",
            source_type=s.source_type,
            source_path=s.source_path,
            chunk_count=chunk_map.get(f"skill:{s.id}", 0),
            created_at=s.created_at,
            updated_at=s.updated_at,
            last_surfaced_at=s.last_surfaced_at,
            surface_count=surf_map.get(s.id, 0) if cutoff else s.surface_count,
            total_auto_injects=ai_map.get(s.id, 0),
            bot_id=_extract_bot_id(s.id, s.source_type),
        )
        for s in skills
    ]

    return result


@router.get("/skills/{skill_id:path}", response_model=SkillOut)
async def admin_get_skill(
    skill_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("skills:read")),
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
        description=row.description, category=row.category,
        triggers=row.triggers or [],
        source_type=row.source_type, source_path=row.source_path,
        chunk_count=chunk_count,
        created_at=row.created_at, updated_at=row.updated_at,
        last_surfaced_at=row.last_surfaced_at,
        surface_count=row.surface_count,
    )


@router.post("/skills", response_model=SkillOut, status_code=201)
async def admin_create_skill(
    body: SkillCreateIn,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("skills:write")),
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


@router.put("/skills/{skill_id:path}", response_model=SkillOut)
async def admin_update_skill(
    skill_id: str,
    body: SkillUpdateIn,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("skills:write")),
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


@router.delete("/skills/{skill_id:path}")
async def admin_delete_skill(
    skill_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("skills:write")),
):
    row = await db.get(SkillRow, skill_id)
    if not row:
        raise HTTPException(status_code=404, detail="Skill not found")
    if row.source_type in ("file", "integration"):
        raise HTTPException(status_code=403, detail="Cannot delete a file-managed skill")
    await db.delete(row)
    await db.execute(sa_delete(Document).where(Document.source == f"skill:{skill_id}"))
    from app.agent.skills import cascade_skill_deletion
    cascade_stats = await cascade_skill_deletion(skill_id, db)
    await db.commit()
    return {"ok": True, **cascade_stats}


@router.post("/file-sync")
async def admin_file_sync(
    _auth: str = Depends(require_scopes("skills:write")),
    db: AsyncSession = Depends(get_db),
):
    """Trigger a full file sync for skills and knowledge."""
    from app.services.file_sync import sync_all_files
    result = await sync_all_files()
    return {"ok": True, **result}
