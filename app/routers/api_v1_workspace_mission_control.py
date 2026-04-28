"""Workspace Mission Control API."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_scopes
from app.domain.errors import NotFoundError, ValidationError
from app.services.workspace_attention import actor_label
from app.services.workspace_mission_ai import (
    accept_mission_draft,
    dismiss_mission_draft,
    generate_mission_control_drafts,
    serialize_draft,
    update_mission_draft,
)
from app.services.workspace_mission_control import build_mission_control


router = APIRouter(prefix="/workspace/mission-control", tags=["workspace-mission-control"])


class MissionControlAiRequest(BaseModel):
    instruction: str | None = None


class MissionDraftUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    directive: str | None = Field(default=None, min_length=1)
    rationale: str | None = None
    scope: str | None = None
    bot_id: str | None = None
    target_channel_id: uuid.UUID | None = None
    interval_kind: str | None = None
    recurrence: str | None = None
    model_override: str | None = None
    model_provider_id_override: str | None = None
    harness_effort: str | None = None


@router.get("")
async def get_mission_control(
    include_completed: bool = False,
    limit: int = Query(100, ge=1, le=250),
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    return await build_mission_control(
        db,
        auth=auth,
        include_completed=include_completed,
        limit=limit,
    )


@router.post("/ai/refresh")
async def post_mission_control_ai_refresh(
    body: MissionControlAiRequest | None = None,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await generate_mission_control_drafts(
            db,
            auth=auth,
            actor=actor_label(auth) or "user",
            user_instruction=body.instruction if body else None,
        )
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/ai/ask")
async def post_mission_control_ai_ask(
    body: MissionControlAiRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    if not (body.instruction or "").strip():
        raise HTTPException(400, "instruction is required.")
    try:
        return await generate_mission_control_drafts(
            db,
            auth=auth,
            actor=actor_label(auth) or "user",
            user_instruction=body.instruction,
        )
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e


@router.patch("/drafts/{draft_id}")
async def patch_mission_draft(
    draft_id: uuid.UUID,
    body: MissionDraftUpdateRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        draft = await update_mission_draft(
            db,
            draft_id,
            auth=auth,
            title=body.title,
            directive=body.directive,
            rationale=body.rationale,
            scope=body.scope,
            bot_id=body.bot_id,
            target_channel_id=body.target_channel_id,
            interval_kind=body.interval_kind,
            recurrence=body.recurrence,
            model_override=body.model_override,
            model_provider_id_override=body.model_provider_id_override,
            harness_effort=body.harness_effort,
        )
        return {"draft": await serialize_draft(db, draft)}
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/drafts/{draft_id}/dismiss")
async def post_mission_draft_dismiss(
    draft_id: uuid.UUID,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        draft = await dismiss_mission_draft(db, draft_id, auth=auth)
        return {"draft": await serialize_draft(db, draft)}
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/drafts/{draft_id}/accept")
async def post_mission_draft_accept(
    draft_id: uuid.UUID,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await accept_mission_draft(
            db,
            draft_id,
            auth=auth,
            actor=actor_label(auth) or "user",
        )
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e
