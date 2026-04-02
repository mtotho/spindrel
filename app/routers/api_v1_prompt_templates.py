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
from app.dependencies import get_db, require_scopes

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
    content: str = ""
    category: Optional[str] = None
    tags: list[str] = []
    workspace_id: Optional[UUID] = None
    source_type: str = "manual"  # "manual" | "workspace_file"
    source_path: Optional[str] = None


class PromptTemplateUpdateIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    workspace_id: Optional[UUID] = None
    source_type: Optional[str] = None
    source_path: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[PromptTemplateOut])
async def list_prompt_templates(
    workspace_id: Optional[UUID] = None,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("settings:read")),
):
    """List prompt templates. Supports workspace_id, category, and tag filters."""
    stmt = select(PromptTemplate).order_by(PromptTemplate.category, PromptTemplate.name)
    if workspace_id is not None:
        stmt = stmt.where(
            (PromptTemplate.workspace_id == workspace_id)
            | (PromptTemplate.workspace_id.is_(None))
        )
    if category is not None:
        stmt = stmt.where(PromptTemplate.category == category)
    if tag is not None:
        stmt = stmt.where(PromptTemplate.tags.contains([tag]))
    rows = (await db.execute(stmt)).scalars().all()
    return rows


@router.get("/{template_id}", response_model=PromptTemplateOut)
async def get_prompt_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("settings:read")),
):
    row = await db.get(PromptTemplate, template_id)
    if not row:
        raise HTTPException(status_code=404, detail="Prompt template not found")
    return row


@router.post("", response_model=PromptTemplateOut, status_code=201)
async def create_prompt_template(
    body: PromptTemplateCreateIn,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("settings:write")),
):
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="name is required")

    content = body.content
    source_type = body.source_type or "manual"

    if source_type == "workspace_file":
        if not body.workspace_id:
            raise HTTPException(status_code=422, detail="workspace_id required for workspace_file source")
        if not body.source_path:
            raise HTTPException(status_code=422, detail="source_path required for workspace_file source")
        # Read initial content from workspace file
        try:
            from app.services.shared_workspace import shared_workspace_service
            result = shared_workspace_service.read_file(str(body.workspace_id), body.source_path)
            content = result["content"]
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Cannot read workspace file: {exc}")
    elif not content.strip():
        raise HTTPException(status_code=422, detail="content is required for manual templates")

    now = datetime.now(timezone.utc)
    row = PromptTemplate(
        name=body.name.strip(),
        description=body.description,
        content=content,
        category=body.category,
        tags=body.tags or [],
        workspace_id=body.workspace_id,
        source_type=source_type,
        source_path=body.source_path,
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
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
    _auth=Depends(require_scopes("settings:write")),
):
    row = await db.get(PromptTemplate, template_id)
    if not row:
        raise HTTPException(status_code=404, detail="Prompt template not found")
    if row.source_type == "file":
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
    if body.source_type is not None:
        row.source_type = body.source_type
    if body.source_path is not None:
        row.source_path = body.source_path

    # If switching to workspace_file, validate and cache content
    if row.source_type == "workspace_file" and row.workspace_id and row.source_path:
        if body.source_type is not None or body.source_path is not None:
            try:
                from app.services.shared_workspace import shared_workspace_service
                result = shared_workspace_service.read_file(str(row.workspace_id), row.source_path)
                row.content = result["content"]
                row.content_hash = hashlib.sha256(row.content.encode()).hexdigest()
            except Exception as exc:
                raise HTTPException(status_code=422, detail=f"Cannot read workspace file: {exc}")

    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{template_id}")
async def delete_prompt_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("settings:write")),
):
    row = await db.get(PromptTemplate, template_id)
    if not row:
        raise HTTPException(status_code=404, detail="Prompt template not found")
    if row.source_type in ("file",):
        raise HTTPException(status_code=403, detail="Cannot delete a file-managed template")
    await db.delete(row)
    await db.commit()
    return {"ok": True}
