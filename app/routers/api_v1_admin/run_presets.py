"""Run preset endpoints for admin/product surfaces."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.dependencies import require_scopes
from app.services.run_presets import (
    get_run_preset,
    list_run_presets,
    serialize_run_preset,
)

router = APIRouter(prefix="/run-presets")


class RunPresetTaskDefaultsOut(BaseModel):
    title: str
    prompt: str
    scheduled_at: str | None = None
    recurrence: str | None = None
    task_type: str
    trigger_config: dict[str, Any]
    skills: list[str]
    tools: list[str]
    post_final_to_channel: bool
    history_mode: str
    history_recent_count: int
    skip_tool_approval: bool
    session_target: dict[str, Any] | None = None
    project_instance: dict[str, Any] | None = None
    allow_issue_reporting: bool | None = None
    harness_effort: str | None = None
    max_run_seconds: int | None = None


class RunPresetHeartbeatDefaultsOut(BaseModel):
    append_spatial_prompt: bool
    append_spatial_map_overview: bool
    include_pinned_widgets: bool
    execution_config: dict[str, Any]
    spatial_policy: dict[str, Any]


class RunPresetOut(BaseModel):
    id: str
    title: str
    description: str
    surface: str
    task_defaults: RunPresetTaskDefaultsOut | None = None
    heartbeat_defaults: RunPresetHeartbeatDefaultsOut | None = None


class RunPresetListOut(BaseModel):
    presets: list[RunPresetOut]


@router.get("", response_model=RunPresetListOut)
async def list_presets(
    surface: str | None = Query(default=None),
    _auth=Depends(require_scopes("tasks:read")),
):
    presets = [serialize_run_preset(preset) for preset in list_run_presets(surface)]
    return {"presets": presets}


@router.get("/{preset_id}", response_model=RunPresetOut)
async def get_preset(
    preset_id: str,
    _auth=Depends(require_scopes("tasks:read")),
):
    preset = get_run_preset(preset_id)
    if preset is None:
        raise HTTPException(status_code=404, detail="Run preset not found")
    return serialize_run_preset(preset)
