"""Prompt Templates CRUD: /api/v1/prompt-templates."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PromptTemplate
from app.dependencies import get_db, verify_auth_or_user

router = APIRouter(prefix="/prompt-templates", tags=["Prompt Templates"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PromptTemplateOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    content: str
    category: Optional[str] = None
    tags: list[str] = []
    workspace_id: Optional[UUID] = None
    source_type: str = "manual"
    source_path: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PromptTemplateCreateIn(BaseModel):
    name: str
    description: Optional[str] = None
    content: str
    category: Optional[str] = None
    tags: list[str] = []
    workspace_id: Optional[UUID] = None


class PromptTemplateUpdateIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    workspace_id: Optional[UUID] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[PromptTemplateOut])
async def list_prompt_templates(
    workspace_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """List prompt templates. If workspace_id provided, returns global + workspace-scoped."""
    stmt = select(PromptTemplate).order_by(PromptTemplate.category, PromptTemplate.name)
    if workspace_id is not None:
        stmt = stmt.where(
            (PromptTemplate.workspace_id == workspace_id)
            | (PromptTemplate.workspace_id.is_(None))
        )
    rows = (await db.execute(stmt)).scalars().all()
    return rows


@router.get("/{template_id}", response_model=PromptTemplateOut)
async def get_prompt_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    row = await db.get(PromptTemplate, template_id)
    if not row:
        raise HTTPException(status_code=404, detail="Prompt template not found")
    return row


@router.post("", response_model=PromptTemplateOut, status_code=201)
async def create_prompt_template(
    body: PromptTemplateCreateIn,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    if not body.name.strip() or not body.content.strip():
        raise HTTPException(status_code=422, detail="name and content are required")
    now = datetime.now(timezone.utc)
    row = PromptTemplate(
        name=body.name.strip(),
        description=body.description,
        content=body.content,
        category=body.category,
        tags=body.tags or [],
        workspace_id=body.workspace_id,
        source_type="manual",
        content_hash=hashlib.sha256(body.content.encode()).hexdigest(),
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.put("/{template_id}", response_model=PromptTemplateOut)
async def update_prompt_template(
    template_id: UUID,
    body: PromptTemplateUpdateIn,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    row = await db.get(PromptTemplate, template_id)
    if not row:
        raise HTTPException(status_code=404, detail="Prompt template not found")
    if row.source_type in ("file",):
        raise HTTPException(status_code=403, detail="Cannot edit a file-managed template")

    if body.name is not None:
        row.name = body.name.strip()
    if body.description is not None:
        row.description = body.description
    if body.content is not None:
        row.content = body.content
        row.content_hash = hashlib.sha256(body.content.encode()).hexdigest()
    if body.category is not None:
        row.category = body.category
    if body.tags is not None:
        row.tags = body.tags
    if body.workspace_id is not None:
        row.workspace_id = body.workspace_id
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{template_id}")
async def delete_prompt_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    row = await db.get(PromptTemplate, template_id)
    if not row:
        raise HTTPException(status_code=404, detail="Prompt template not found")
    if row.source_type in ("file",):
        raise HTTPException(status_code=403, detail="Cannot delete a file-managed template")
    await db.delete(row)
    await db.commit()
    return {"ok": True}
