"""Memory endpoints: DELETE /memories/{id}."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Memory
from app.dependencies import get_db, verify_auth_or_user

router = APIRouter()


@router.delete("/memories/{memory_id}")
async def admin_delete_memory(
    memory_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    row = await db.get(Memory, memory_id)
    if not row:
        raise HTTPException(status_code=404, detail="Memory not found")
    await db.delete(row)
    await db.commit()
    return {"ok": True}
