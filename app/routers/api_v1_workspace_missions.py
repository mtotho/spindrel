"""Workspace Missions API."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_scopes
from app.domain.errors import NotFoundError, ValidationError
from app.services.workspace_attention import actor_label
from app.services.workspace_missions import (
    DEFAULT_MISSION_RECURRENCE,
    assign_mission_bot,
    create_mission,
    get_mission,
    list_missions,
    run_mission_now,
    serialize_mission,
    set_mission_status,
)


router = APIRouter(prefix="/workspace/missions", tags=["workspace-missions"])


class MissionCreateRequest(BaseModel):
    title: str = Field(min_length=1)
    directive: str = Field(min_length=1)
    scope: str = "workspace"
    channel_id: uuid.UUID | None = None
    bot_id: str | None = None
    play_key: str | None = None
    interval_kind: str = "preset"
    recurrence: str | None = DEFAULT_MISSION_RECURRENCE
    model_override: str | None = None
    model_provider_id_override: str | None = None
    fallback_models: list[dict] | None = None
    harness_effort: str | None = None
    history_mode: str | None = "recent"
    history_recent_count: int | None = 8


class MissionStatusRequest(BaseModel):
    status: str


class MissionAssignRequest(BaseModel):
    bot_id: str = Field(min_length=1)
    target_channel_id: uuid.UUID | None = None


@router.get("")
async def get_missions(
    include_completed: bool = False,
    limit: int = Query(100, ge=1, le=250),
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    return {"missions": await list_missions(db, auth=auth, include_completed=include_completed, limit=limit)}


@router.post("", status_code=201)
async def post_mission(
    body: MissionCreateRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        mission = await create_mission(
            db,
            auth=auth,
            actor=actor_label(auth) or "user",
            title=body.title,
            directive=body.directive,
            scope=body.scope,
            channel_id=body.channel_id,
            bot_id=body.bot_id,
            play_key=body.play_key,
            interval_kind=body.interval_kind,
            recurrence=body.recurrence,
            model_override=body.model_override,
            model_provider_id_override=body.model_provider_id_override,
            fallback_models=body.fallback_models,
            harness_effort=body.harness_effort,
            history_mode=body.history_mode,
            history_recent_count=body.history_recent_count,
        )
        return {"mission": await serialize_mission(db, mission, include_updates=20)}
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/{mission_id}")
async def get_one_mission(
    mission_id: uuid.UUID,
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        mission = await get_mission(db, mission_id, auth=auth)
        return {"mission": await serialize_mission(db, mission, include_updates=50)}
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/{mission_id}/status")
async def post_mission_status(
    mission_id: uuid.UUID,
    body: MissionStatusRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        mission = await set_mission_status(db, mission_id, auth=auth, status=body.status)
        return {"mission": await serialize_mission(db, mission, include_updates=20)}
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/{mission_id}/run-now")
async def post_mission_run_now(
    mission_id: uuid.UUID,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        mission = await run_mission_now(db, mission_id, auth=auth)
        return {"mission": await serialize_mission(db, mission, include_updates=20)}
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/{mission_id}/assign")
async def post_mission_assign(
    mission_id: uuid.UUID,
    body: MissionAssignRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        mission = await assign_mission_bot(
            db,
            mission_id,
            auth=auth,
            bot_id=body.bot_id,
            target_channel_id=body.target_channel_id,
        )
        return {"mission": await serialize_mission(db, mission, include_updates=20)}
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e
