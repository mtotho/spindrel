"""API v1 — Projects."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Project, SharedWorkspace
from app.dependencies import get_db, require_scopes
from app.services.projects import (
    normalize_project_path,
    normalize_project_slug,
    project_directory_from_project,
    project_directory_payload,
)

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    slug: str
    description: Optional[str] = None
    root_path: str
    prompt: Optional[str] = None
    prompt_file_path: Optional[str] = None
    metadata_: dict = {}
    resolved: dict | None = None
    attached_channel_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectWrite(BaseModel):
    workspace_id: uuid.UUID | None = None
    name: str | None = None
    slug: str | None = None
    description: str | None = None
    root_path: str | None = None
    prompt: str | None = None
    prompt_file_path: str | None = None
    metadata_: dict | None = None


class ProjectChannelOut(BaseModel):
    id: uuid.UUID
    name: str
    bot_id: str

    model_config = {"from_attributes": True}


async def _default_workspace_id(db: AsyncSession) -> uuid.UUID:
    row = (await db.execute(select(SharedWorkspace.id).order_by(SharedWorkspace.created_at).limit(1))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=422, detail="No shared workspace exists")
    return row


async def _project_out(db: AsyncSession, project: Project) -> ProjectOut:
    out = ProjectOut.model_validate(project)
    out.resolved = project_directory_payload(project_directory_from_project(project))
    out.attached_channel_count = int((await db.execute(
        select(func.count()).select_from(Channel).where(Channel.project_id == project.id)
    )).scalar_one() or 0)
    return out


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    projects = (await db.execute(select(Project).order_by(Project.name))).scalars().all()
    return [await _project_out(db, project) for project in projects]


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    body: ProjectWrite,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    if not body.name:
        raise HTTPException(status_code=422, detail="name is required")
    workspace_id = body.workspace_id or await _default_workspace_id(db)
    if await db.get(SharedWorkspace, workspace_id) is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    root_path = normalize_project_path(body.root_path)
    if not root_path:
        raise HTTPException(status_code=422, detail="root_path is required")
    project = Project(
        workspace_id=workspace_id,
        name=body.name.strip(),
        slug=normalize_project_slug(body.slug, fallback=body.name),
        description=body.description,
        root_path=root_path,
        prompt=body.prompt,
        prompt_file_path=normalize_project_path(body.prompt_file_path),
        metadata_=body.metadata_ or {},
    )
    db.add(project)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"project already exists or is invalid: {exc}") from exc
    await db.refresh(project)
    return await _project_out(db, project)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return await _project_out(db, project)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID,
    body: ProjectWrite,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    fields = body.model_fields_set
    if "name" in fields and body.name is not None:
        project.name = body.name.strip()
    if "slug" in fields and body.slug is not None:
        project.slug = normalize_project_slug(body.slug, fallback=project.name)
    if "description" in fields:
        project.description = body.description
    if "root_path" in fields and body.root_path is not None:
        root_path = normalize_project_path(body.root_path)
        if not root_path:
            raise HTTPException(status_code=422, detail="root_path is required")
        project.root_path = root_path
    if "prompt" in fields:
        project.prompt = body.prompt
    if "prompt_file_path" in fields:
        project.prompt_file_path = normalize_project_path(body.prompt_file_path)
    if "metadata_" in fields:
        project.metadata_ = body.metadata_ or {}
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"project update failed: {exc}") from exc
    await db.refresh(project)
    return await _project_out(db, project)


@router.get("/{project_id}/channels", response_model=list[ProjectChannelOut])
async def get_project_channels(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    if await db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    return (await db.execute(
        select(Channel).where(Channel.project_id == project_id).order_by(Channel.name)
    )).scalars().all()
