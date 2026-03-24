"""Tools listing: /tools, /tools/{tool_id}."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ToolEmbedding
from app.dependencies import get_db, verify_auth

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ToolOut(BaseModel):
    id: str
    tool_key: str
    tool_name: str
    server_name: Optional[str] = None
    source_dir: Optional[str] = None
    source_integration: Optional[str] = None
    source_file: Optional[str] = None
    description: Optional[str] = None
    parameters: Optional[dict] = None
    schema_: Optional[dict] = None
    indexed_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/tools", response_model=list[ToolOut])
async def admin_list_tools(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    """List all indexed tools."""
    rows = (await db.execute(
        select(ToolEmbedding)
        .order_by(ToolEmbedding.server_name.nullsfirst(), ToolEmbedding.tool_name)
    )).scalars().all()

    return [_to_out(r) for r in rows]


@router.get("/tools/{tool_id}", response_model=ToolOut)
async def admin_get_tool(
    tool_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    """Get a single tool by ID (UUID) or tool_key."""
    # Try UUID first
    row = None
    try:
        uid = UUID(tool_id)
        row = await db.get(ToolEmbedding, uid)
    except ValueError:
        pass

    # Fall back to tool_key lookup
    if not row:
        row = (await db.execute(
            select(ToolEmbedding).where(ToolEmbedding.tool_key == tool_id)
        )).scalar_one_or_none()

    # Fall back to tool_name lookup
    if not row:
        row = (await db.execute(
            select(ToolEmbedding).where(ToolEmbedding.tool_name == tool_id)
        )).scalar_one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail="Tool not found")
    return _to_out(row)


def _to_out(row: ToolEmbedding) -> ToolOut:
    schema = row.schema_ or {}
    fn = schema.get("function", {})
    return ToolOut(
        id=str(row.id),
        tool_key=row.tool_key,
        tool_name=row.tool_name,
        server_name=row.server_name,
        source_dir=row.source_dir,
        source_integration=row.source_integration,
        source_file=row.source_file,
        description=fn.get("description"),
        parameters=fn.get("parameters"),
        schema_=schema,
        indexed_at=row.indexed_at,
    )
