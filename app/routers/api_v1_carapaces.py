"""Bot-facing carapace API — /api/v1/carapaces.

Non-admin endpoints for bots to manage carapaces programmatically.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Carapace as CarapaceRow
from app.dependencies import get_db, require_scopes
from app.routers._carapace_schemas import (
    CarapaceCreateIn,
    CarapaceOut,
    CarapaceUpdateIn,
    try_reload,
)

router = APIRouter(prefix="/carapaces", tags=["Carapaces"])


async def _try_reindex(carapace_id: str) -> None:
    """Best-effort reindex of a single capability embedding."""
    try:
        from app.agent.capability_rag import reindex_capability
        await reindex_capability(carapace_id)
    except Exception:
        pass


@router.get("", response_model=list[CarapaceOut])
async def list_carapaces(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("carapaces:read")),
):
    rows = (await db.execute(
        select(CarapaceRow).order_by(CarapaceRow.name)
    )).scalars().all()
    return [CarapaceOut.model_validate(r) for r in rows]


@router.get("/{carapace_id}", response_model=CarapaceOut)
async def get_carapace(
    carapace_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("carapaces:read")),
):
    row = await db.get(CarapaceRow, carapace_id)
    if not row:
        raise HTTPException(status_code=404, detail="Carapace not found")
    return CarapaceOut.model_validate(row)


@router.post("", response_model=CarapaceOut, status_code=201)
async def create_carapace(
    body: CarapaceCreateIn,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("carapaces:write")),
):
    cid = body.id.strip().lower().replace(" ", "-")
    if not cid or not body.name.strip():
        raise HTTPException(status_code=422, detail="id and name are required")

    existing = await db.get(CarapaceRow, cid)
    if existing:
        raise HTTPException(status_code=409, detail=f"Carapace '{cid}' already exists")

    now = datetime.now(timezone.utc)
    row = CarapaceRow(
        id=cid,
        name=body.name.strip(),
        description=body.description,
        local_tools=body.local_tools,
        mcp_tools=body.mcp_tools,
        pinned_tools=body.pinned_tools,
        system_prompt_fragment=body.system_prompt_fragment,
        includes=body.includes,
        tags=body.tags,
        source_type="manual",
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    await try_reload()
    await _try_reindex(cid)

    return CarapaceOut.model_validate(row)


@router.put("/{carapace_id}", response_model=CarapaceOut)
async def update_carapace(
    carapace_id: str,
    body: CarapaceUpdateIn,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("carapaces:write")),
):
    row = await db.get(CarapaceRow, carapace_id)
    if not row:
        raise HTTPException(status_code=404, detail="Carapace not found")
    if row.source_type in ("file", "integration"):
        raise HTTPException(status_code=403, detail="Cannot edit a file-managed carapace")

    if body.name is not None:
        row.name = body.name.strip()
    if body.description is not None:
        row.description = body.description
    if body.local_tools is not None:
        row.local_tools = body.local_tools
    if body.mcp_tools is not None:
        row.mcp_tools = body.mcp_tools
    if body.pinned_tools is not None:
        row.pinned_tools = body.pinned_tools
    if body.system_prompt_fragment is not None:
        row.system_prompt_fragment = body.system_prompt_fragment
    if body.includes is not None:
        row.includes = body.includes
    if body.tags is not None:
        row.tags = body.tags
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)

    await try_reload()
    await _try_reindex(carapace_id)

    return CarapaceOut.model_validate(row)


@router.delete("/{carapace_id}")
async def delete_carapace(
    carapace_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("carapaces:write")),
):
    row = await db.get(CarapaceRow, carapace_id)
    if not row:
        raise HTTPException(status_code=404, detail="Carapace not found")
    if row.source_type in ("file", "integration"):
        raise HTTPException(status_code=403, detail="Cannot delete a file-managed carapace")
    await db.delete(row)
    await db.commit()

    await try_reload()
    await _try_reindex(carapace_id)

    return {"ok": True}
