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
    get_channel_bot_spatial_policy,
    list_nodes,
    pin_widget_to_canvas,
    serialize_node,
    update_channel_bot_spatial_policy,
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


class PinPresetToCanvasRequest(BaseModel):
    """Pin a `widget_presets[*]` entry directly onto the workspace canvas.

    Server runs the preset's preview pipeline (resolves config + binding-derived
    tool args, executes the tool once, applies the matching tool_widget) so the
    canvas pin lands with a fully-seeded envelope. Subsequent refreshes flow
    through the tool_widget's own `state_poll`.
    """
    preset_id: str
    config: dict | None = None
    source_bot_id: str | None = None
    source_channel_id: uuid.UUID | None = None
    display_label: str | None = None
    world_x: float | None = None
    world_y: float | None = None
    world_w: float | None = None
    world_h: float | None = None


class SpatialBotPolicyRequest(BaseModel):
    enabled: bool | None = None
    allow_movement: bool | None = None
    step_world_units: int | None = None
    max_move_steps_per_turn: int | None = None
    minimum_clearance_steps: int | None = None
    awareness_radius_steps: int | None = None
    nearest_neighbor_floor: int | None = None
    allow_moving_spatial_objects: bool | None = None
    allow_spatial_widget_management: bool | None = None
    tug_radius_steps: int | None = None
    max_tug_steps_per_turn: int | None = None
    allow_nearby_inspect: bool | None = None
    movement_trace_ttl_minutes: int | None = None


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


@router.get("/channels/{channel_id}/bots/{bot_id}/policy")
async def get_spatial_bot_policy(
    channel_id: uuid.UUID,
    bot_id: str,
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        policy = await get_channel_bot_spatial_policy(db, channel_id, bot_id)
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    return {"bot_id": bot_id, "channel_id": str(channel_id), "policy": policy}


@router.patch("/channels/{channel_id}/bots/{bot_id}/policy")
async def patch_spatial_bot_policy(
    channel_id: uuid.UUID,
    bot_id: str,
    body: SpatialBotPolicyRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        policy = await update_channel_bot_spatial_policy(
            db,
            channel_id,
            bot_id,
            body.model_dump(exclude_unset=True),
        )
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    return {"bot_id": bot_id, "channel_id": str(channel_id), "policy": policy}


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


@router.post("/preset-pins", status_code=201)
async def pin_preset(
    body: PinPresetToCanvasRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    """Pin a `widget_presets[*]` entry onto the workspace canvas.

    Mirrors the dashboard preset pin endpoint but routes through
    `pin_widget_to_canvas`, so the result lands in `workspace_spatial_nodes`
    at the requested world coords. The seeded envelope, resolved config, and
    runtime tool_args all come from `preview_widget_preset` — same path the
    dashboard pin uses, no divergence.
    """
    from app.services.widget_presets import (
        get_widget_preset,
        preview_envelope_to_dict,
        preview_widget_preset,
    )

    try:
        preview, resolved_config, tool_args = await preview_widget_preset(
            db,
            preset_id=body.preset_id,
            config=body.config,
            source_bot_id=body.source_bot_id,
            source_channel_id=str(body.source_channel_id) if body.source_channel_id else None,
        )
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e

    if not preview.ok or preview.envelope is None:
        raise HTTPException(400, f"Preset '{body.preset_id}' preview failed")

    preset = get_widget_preset(body.preset_id)
    tool_name = preset.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name.strip():
        raise HTTPException(400, f"Preset '{body.preset_id}' missing tool_name")

    envelope = preview_envelope_to_dict(preview.envelope) or {}
    envelope["source_instantiation_kind"] = "preset"
    envelope["source_preset_id"] = body.preset_id

    widget_origin: dict = {
        "definition_kind": "tool_widget",
        "instantiation_kind": "preset",
        "tool_name": tool_name,
        "preset_id": body.preset_id,
    }
    tool_family = preset.get("tool_family")
    if isinstance(tool_family, str) and tool_family.strip():
        widget_origin["tool_family"] = tool_family.strip()
    template_id = envelope.get("template_id")
    if isinstance(template_id, str) and template_id.strip():
        widget_origin["template_id"] = template_id.strip()

    try:
        pin, node = await pin_widget_to_canvas(
            db,
            source_kind="channel" if body.source_channel_id else "adhoc",
            tool_name=tool_name,
            envelope=envelope,
            source_channel_id=body.source_channel_id,
            source_bot_id=body.source_bot_id,
            tool_args=tool_args,
            widget_config=resolved_config,
            widget_origin=widget_origin,
            display_label=body.display_label or preset.get("name"),
            world_x=body.world_x,
            world_y=body.world_y,
            world_w=body.world_w if body.world_w is not None else 220.0,
            world_h=body.world_h if body.world_h is not None else 140.0,
        )
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e
    return {"pin": serialize_pin(pin), "node": serialize_node(node)}
