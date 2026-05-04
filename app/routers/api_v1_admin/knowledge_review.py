"""Admin review queue for pending user Knowledge Documents."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SharedWorkspace
from app.dependencies import get_db, require_scopes
from app.services.knowledge_capture import delete_user_knowledge_index_entry, reindex_user_knowledge_workspace
from app.services.knowledge_documents import (
    delete_document,
    list_documents,
    read_document,
    set_document_status,
    user_knowledge_surface,
    write_document,
)
from app.services.shared_workspace import shared_workspace_service

router = APIRouter(prefix="/knowledge/review", tags=["Admin Knowledge Review"])


class KnowledgeReviewWriteIn(BaseModel):
    content: str
    base_hash: str | None = None


async def _default_workspace(db: AsyncSession) -> SharedWorkspace:
    workspace = (await db.execute(select(SharedWorkspace).order_by(SharedWorkspace.created_at.asc()).limit(1))).scalar_one_or_none()
    if workspace is None:
        raise HTTPException(status_code=404, detail="Shared workspace not found")
    return workspace


@router.get("")
async def list_pending_knowledge_review(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
) -> dict[str, Any]:
    workspace = await _default_workspace(db)
    root = shared_workspace_service.ensure_host_dirs(str(workspace.id))
    users_root = Path(root) / "users"
    groups: list[dict[str, Any]] = []
    if users_root.is_dir():
        for user_dir in sorted(p for p in users_root.iterdir() if p.is_dir()):
            surface = user_knowledge_surface(workspace_root=root, user_id=user_dir.name)
            pending = list_documents(surface, status="pending_review")
            if pending:
                groups.append({"user_id": user_dir.name, "documents": pending})
    return {"workspace_id": str(workspace.id), "groups": groups}


@router.get("/{user_id}/{slug}")
async def read_pending_knowledge_document(
    user_id: str,
    slug: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
) -> dict[str, Any]:
    workspace = await _default_workspace(db)
    root = shared_workspace_service.ensure_host_dirs(str(workspace.id))
    return read_document(user_knowledge_surface(workspace_root=root, user_id=user_id), slug)


@router.put("/{user_id}/{slug}")
async def write_pending_knowledge_document(
    user_id: str,
    slug: str,
    data: KnowledgeReviewWriteIn = Body(...),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
) -> dict[str, Any]:
    workspace = await _default_workspace(db)
    workspace_id = str(workspace.id)
    await db.rollback()
    root = shared_workspace_service.ensure_host_dirs(workspace_id)
    doc = write_document(
        user_knowledge_surface(workspace_root=root, user_id=user_id),
        slug,
        data.content,
        data.base_hash,
    )
    await reindex_user_knowledge_workspace(workspace_id=workspace_id, user_id=user_id)
    return doc


@router.post("/{user_id}/{slug}/accept")
async def accept_pending_knowledge_document(
    user_id: str,
    slug: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
) -> dict[str, Any]:
    workspace = await _default_workspace(db)
    workspace_id = str(workspace.id)
    await db.rollback()
    root = shared_workspace_service.ensure_host_dirs(workspace_id)
    doc = set_document_status(user_knowledge_surface(workspace_root=root, user_id=user_id), slug, "accepted")
    await reindex_user_knowledge_workspace(workspace_id=workspace_id, user_id=user_id)
    return doc


@router.post("/{user_id}/{slug}/reject")
async def reject_pending_knowledge_document(
    user_id: str,
    slug: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
) -> dict[str, Any]:
    workspace = await _default_workspace(db)
    workspace_id = str(workspace.id)
    await db.rollback()
    root = shared_workspace_service.ensure_host_dirs(workspace_id)
    doc = delete_document(user_knowledge_surface(workspace_root=root, user_id=user_id), slug)
    await delete_user_knowledge_index_entry(workspace_id=workspace_id, user_id=user_id, slug=slug)
    return {"deleted": True, "document": doc}
