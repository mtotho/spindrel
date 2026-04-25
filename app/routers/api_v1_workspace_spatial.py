"""Workspace Spatial Canvas API.

Endpoints for the workspace-scope infinite plane. Single source of truth
for tile world positions is ``workspace_spatial_nodes``. Channel rows
auto-populate on first read (``GET /workspace/spatial/nodes`` is also a
"seed if missing" call). World widget pins are created atomically via the
service layer — frontend never calls pin-create + node-create separately.

Reserved dashboard slug ``workspace:spatial`` hosts world widget pins so
the existing widget host plumbing (envelope, iframe auth, contract
snapshots) is reused. The slug is excluded from every dashboard-listing
surface.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_scopes
from app.domain.errors import NotFoundError, ValidationError
from app.services.dashboard_pins import serialize_pin
from app.services.workspace_spatial import (
    delete_node,
    list_nodes,
    pin_widget_to_canvas,
    serialize_node,
    update_node_position,
)
from app.services.upcoming_activity import list_upcoming_activity


router = APIRouter(prefix="/workspace/spatial", tags=["workspace-spatial"])


class UpdateNodePositionRequest(BaseModel):
    world_x: float | None = None
    world_y: float | None = None
    world_w: float | None = None
    world_h: float | None = None
    z_index: int | None = None


class PinWidgetToCanvasRequest(BaseModel):
    source_kind: str = Field(..., description="'channel' or 'adhoc'")
    tool_name: str
    envelope: dict
    source_channel_id: uuid.UUID | None = None
    source_bot_id: str | None = None
    tool_args: dict | None = None
    widget_config: dict | None = None
    widget_origin: dict | None = None
    display_label: str | None = None
    world_x: float | None = None
    world_y: float | None = None
    world_w: float | None = None
    world_h: float | None = None


@router.get("/nodes")
async def get_nodes(
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    """List all spatial nodes; auto-seeds channel rows for any channel
    that doesn't yet have a position. Widget nodes embed their pin payload
    inline (envelope, contract/presentation snapshots, source bot) so the
    client renders without a second roundtrip. Idempotent."""
    pairs = await list_nodes(db)
    return {"nodes": [serialize_node(n, pin) for n, pin in pairs]}


@router.get("/upcoming-activity")
async def get_upcoming_activity(
    limit: int = 50,
    type: str | None = None,
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    """List scheduled work visible to the workspace canvas.

    This is the canvas-facing seam for scheduled activity. It intentionally
    omits admin-only memory-hygiene rows and channel-less tasks; the admin task
    surface continues to use ``/api/v1/admin/upcoming-activity`` for the full
    operational view.
    """
    items = await list_upcoming_activity(
        db,
        limit=max(1, min(limit, 1000)),
        type_filter=type,
        auth=auth,
        include_memory_hygiene=False,
        include_channelless_tasks=False,
    )
    return {"items": items}


@router.patch("/nodes/{node_id}")
async def patch_node(
    node_id: uuid.UUID,
    body: UpdateNodePositionRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        node = await update_node_position(
            db,
            node_id,
            world_x=body.world_x,
            world_y=body.world_y,
            world_w=body.world_w,
            world_h=body.world_h,
            z_index=body.z_index,
        )
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e
    return {"node": serialize_node(node)}


@router.delete("/nodes/{node_id}", status_code=204)
async def remove_node(
    node_id: uuid.UUID,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        await delete_node(db, node_id)
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    return None


@router.post("/widget-pins", status_code=201)
async def pin_widget(
    body: PinWidgetToCanvasRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    """Atomically pin a widget to the workspace canvas.

    Creates a ``widget_dashboard_pins`` row on the reserved
    ``workspace:spatial`` dashboard AND its matching
    ``workspace_spatial_nodes`` row in one transaction.
    """
    try:
        pin, node = await pin_widget_to_canvas(
            db,
            source_kind=body.source_kind,
            tool_name=body.tool_name,
            envelope=body.envelope,
            source_channel_id=body.source_channel_id,
            source_bot_id=body.source_bot_id,
            tool_args=body.tool_args,
            widget_config=body.widget_config,
            widget_origin=body.widget_origin,
            display_label=body.display_label,
            world_x=body.world_x,
            world_y=body.world_y,
            world_w=body.world_w if body.world_w is not None else 220.0,
            world_h=body.world_h if body.world_h is not None else 140.0,
        )
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e
    return {"pin": serialize_pin(pin), "node": serialize_node(node)}
